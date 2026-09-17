"""Eval-only paid client, cumulative ledger, and request-boundary accounting."""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import threading
from unittest.mock import patch

# Standard text prices, USD / million tokens. Verified 2026-09-17:
# https://ai.google.dev/gemini-api/docs/pricing
RATES={'gemini-embedding-2':(.20,0), 'gemini-2.5-flash':(.30,2.50),
       'gemini-3.5-flash-lite':(.30,2.50),'gemini-3.6-flash':(.75,3.75)}
JUDGE_MODEL='gemini-3.5-flash-lite'
STATE=Path(__file__).parent/'results'/'baseline-state'

class BudgetExceeded(RuntimeError): pass

class Ledger:
    """One persistent Phase 1 ledger; reserve before sending, including failed calls."""
    def __init__(self, path, cap=1.0):
        if not 0<cap<=1: raise ValueError('Phase 1 cap must be in (0,1]')
        self.path=Path(path); self.cap=cap; self.lock=threading.Lock()
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'schema_version':1,'calls':[]}

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data,indent=2),encoding='utf-8'); temp.replace(self.path)

    def reserve(self,kind,model,contents,config):
        if model not in RATES: raise BudgetExceeded('Unpriced model blocked before request: '+model)
        if not isinstance(contents,str): raise BudgetExceeded('Only text requests have approved cost accounting')
        cfg=config.model_dump(exclude_none=True) if hasattr(config,'model_dump') else (config or {})
        if cfg.get('tools') or cfg.get('cached_content') or cfg.get('candidate_count',1)!=1:
            raise BudgetExceeded('Unbudgeted tools/cache/multiple candidates blocked')
        # UTF-8 bytes plus structural allowance is deliberately conservative for text.
        input_bound=len(contents.encode())+len(json.dumps(cfg,default=str).encode())+1024
        output_bound=0 if kind=='embedding' else int(cfg.get('max_output_tokens') or 65536)+32768
        a,b=RATES[model]; reservation=(input_bound*a+output_bound*b)/1e6
        with self.lock:
            spent=sum(c['charged_or_reserved_usd'] for c in self.data['calls'])
            if spent+reservation>self.cap: raise BudgetExceeded('Phase 1 cumulative budget would be exceeded')
            item={'kind':kind,'model':model,'status':'reserved','reserved_usd':reservation,
                  'charged_or_reserved_usd':reservation,'input_bound':input_bound,'output_bound':output_bound}
            self.data['calls'].append(item); self.save()
            return item

    def finish(self,item,response):
        usage=getattr(response,'usage_metadata',None)
        usage=usage.model_dump(exclude_none=True) if hasattr(usage,'model_dump') else None
        with self.lock:
            item['status']='completed'; item['usage']=usage
            if usage and 'prompt_token_count' in usage:
                inp=usage.get('prompt_token_count') or 0
                out=(usage.get('candidates_token_count') or 0)+(usage.get('thoughts_token_count') or 0)
                a,b=RATES[item['model']]
                item['estimated_usage_usd']=(inp*a+out*b)/1e6
                item['charged_or_reserved_usd']=item['estimated_usage_usd']
            self.save()

    def summary(self):
        from collections import Counter
        return {'cap_usd':self.cap,'call_counts':dict(Counter(c['kind'] for c in self.data['calls'])),
                'estimated_or_reserved_usd':sum(c['charged_or_reserved_usd'] for c in self.data['calls']),
                'note':'API usage estimates, not billing reconciliation. Failed/unknown calls retain their reservation.'}

def eval_key():
    from dotenv import dotenv_values
    return os.environ.get('EVAL_GEMINI_API_KEY') or dotenv_values(Path(__file__).parents[1]/'.env').get('EVAL_GEMINI_API_KEY')

@contextmanager
def paid_runtime(cap=1.0):
    key=eval_key()
    if not key: raise ValueError('Set EVAL_GEMINI_API_KEY locally; no fallback to application keys')
    STATE.mkdir(parents=True,exist_ok=True)
    lock_path=STATE/'paid.lock'
    # Exclusive across processes. A crash leaves a lock requiring explicit inspection/removal.
    fd=os.open(lock_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        os.close(fd)
        from google import genai
        from google.genai import types,models
        from config import settings
        from agent import orchestrator
        from rag import embed
        ledger=Ledger(STATE/'phase1-ledger.json',cap)
        client=genai.Client(api_key=key,http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
        generate=models.Models.generate_content; embedding=models.Models.embed_content
        def call(original,kind,instance,**kwargs):
            item=ledger.reserve(kind,kwargs['model'],kwargs['contents'],kwargs.get('config'))
            try:
                response=original(instance,**kwargs)
            except BaseException:
                with ledger.lock:
                    item['status']='failed_or_unknown'; ledger.save()
                raise
            ledger.finish(item,response)
            return response
        with ExitStack() as stack:
            stack.enter_context(patch.object(settings,'gemini_api_key',key))
            stack.enter_context(patch.object(settings,'agent_router_api_key',key))
            stack.enter_context(patch.object(settings,'gemini_ingest_api_key',key))
            for env,attr in [('EVAL_GEMINI_CHAT_MODEL','gemini_chat_model'),('EVAL_GEMINI_EMBED_MODEL','gemini_embed_model')]:
                if os.environ.get(env): stack.enter_context(patch.object(settings,attr,os.environ[env]))
            if settings.agent_router!='rule': raise ValueError('Baseline currently supports the configured rule router only')
            stack.enter_context(patch.object(orchestrator,'_client',return_value=client))
            stack.enter_context(patch.object(embed,'_client',return_value=client))
            stack.enter_context(patch.object(models.Models,'generate_content',lambda self,**kw:call(generate,'judge' if getattr(self,'_baseline_judge',False) else 'generation',self,**kw)))
            stack.enter_context(patch.object(models.Models,'embed_content',lambda self,**kw:call(embedding,'embedding',self,**kw)))
            embed.clear_embed_cache()
            try: yield ledger,client
            finally: embed.clear_embed_cache()
        client.close()
    finally:
        lock_path.unlink(missing_ok=True)
