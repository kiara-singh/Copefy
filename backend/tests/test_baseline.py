"""Offline checks of eval validity, persistence guards, accounting and instrumentation."""
import asyncio
import copy
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pathlib import Path
import uuid

from eval.baseline import cases, validate_suite, offline, selected_records, trace_retrieval
from eval.baseline_fixtures import fingerprint, valid_chunks, entry_id, definitions
from eval.baseline_runtime import Ledger, BudgetExceeded
from eval.baseline_scoring import grade, summarize, validate_judge, WEIGHTS, FAILURE_TYPES

@pytest.fixture(autouse=True)
def no_network():
    with offline(): yield

@pytest.fixture
def tmp_path():
    # pytest's 0700 temp directories are unreadable under this Windows sandbox.
    # Use a new ignored run artifact directory with normal workspace permissions.
    path=Path(__file__).parents[1]/'eval'/'results'/'test-scratch'/uuid.uuid4().hex
    path.mkdir(parents=True)
    return path

def test_suite_counts_and_no_state_journal_contamination():
    items=cases(); report=validate_suite(items)
    assert report['distinct_conversations']==206
    assert report['category_counts']['statefulness']==45
    assert report['category_counts']['journal_retrieval']==45
    assert report['category_counts']['negative']==28
    assert report['category_counts']['hallucination']==28
    assert report['category_counts']['crisis']==60
    assert report['category_counts']['scope']==28
    assert report['category_counts']['privacy']==18
    assert report['lengths']['long_8_15']==15
    assert all(c['user']=='beta' for c in items if 'statefulness' in c['tags'])
    journals={f['id']:f for f in definitions()['journals']}
    assert len(journals)==109
    for c in items:
        if 'journal_retrieval' in c['tags']:
            later=c['expected_entries'][0]
            earlier=later.replace('_after','_before')
            assert earlier in journals
            assert journals[earlier]['created_at']<journals[later]['created_at']
            assert journals[earlier]['content']!=journals[later]['content']

def test_zero_denominators_are_not_perfect_scores():
    s=summarize([])
    assert s['crisis_precision']['rate'] is None
    assert s['judge']['mean_weighted_score'] is None

def test_confusion_denominators_and_failure_direction():
    rows=[grade({'checks':[], 'expected_crisis':expected},'',actual) for expected,actual in
          [(True,'crisis'),(True,'direct_answer'),(False,'crisis'),(False,'direct_answer')]]
    rows.append(grade({'checks':[{'metric':'unsupported','kind':'forbid','value':'canary','failure_metric':True}]},'canary','direct_answer'))
    s=summarize(rows)
    assert s['crisis_confusion']=={'TP':1,'FP':1,'TN':1,'FN':1}
    assert s['crisis_recall']['denominator']==2
    assert s['metrics']['unsupported']['numerator']==1

def test_high_judge_score_cannot_hide_hard_failure():
    j=validate_judge({'scores':dict.fromkeys(WEIGHTS,5),'failure_types':dict.fromkeys(FAILURE_TYPES,False),'rationale':'privacy canary disclosed','hard_failures':['cross_user_privacy_leak']})
    assert j['weighted_score']==5
    assert j['safety_status']=='failed'
    assert summarize([{'judge':j}])['hard_failures']=={'cross_user_privacy_leak':1}

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-1,6,True,'5'])
def test_invalid_judge_score_rejected(bad):
    scores=dict.fromkeys(WEIGHTS,5); scores['safety']=bad
    with pytest.raises(ValueError): validate_judge({'scores':scores,'hard_failures':[],'rationale':'x'})

def test_unassessed_safety_is_never_reported_pass():
    r=grade({'checks':[],'review':['uncertainty']},'hello','direct_answer')
    assert r['safety_status']=='not_fully_assessed'
    r=grade({'checks':[],'expected_crisis':True,'acute_self':True},'Call emergency help now','direct_answer')
    assert not r['hard_failures']  # Route miss requires response inspection.
    assert r['assertions'][-1]['requires_response_review']

def test_budget_reserves_failed_calls_and_persists_across_runs(tmp_path):
    path=tmp_path/'ledger.json'; l=Ledger(path,cap=.1)
    item=l.reserve('generation','gemini-2.5-flash','hi',{'max_output_tokens':1024})
    assert item['charged_or_reserved_usd']>0
    with pytest.raises(BudgetExceeded): Ledger(path,cap=.1).reserve('generation','gemini-2.5-flash','hi',{'max_output_tokens':1024})
    assert len(json.loads(path.read_text())['calls'])==1

def test_budget_settles_thinking_tokens_and_blocks_unpriced_models(tmp_path):
    l=Ledger(tmp_path/'l.json'); item=l.reserve('generation','gemini-2.5-flash','hi',{'max_output_tokens':1024})
    response=SimpleNamespace(usage_metadata=SimpleNamespace(model_dump=lambda **kw:{'prompt_token_count':100,'candidates_token_count':10,'thoughts_token_count':20}))
    l.finish(item,response)
    assert item['estimated_usage_usd']==pytest.approx(.000105)
    with pytest.raises(BudgetExceeded): l.reserve('generation','gemini-flash-latest','hi',{})

def test_fingerprint_depends_on_model_content_and_chunker(monkeypatch,tmp_path):
    from rag import journal_chunking
    first=fingerprint('hello','model-a')
    assert first!=fingerprint('hello','model-b')
    assert first!=fingerprint('changed','model-a')
    fake=tmp_path/'chunker.py'; fake.write_text('new chunking')
    monkeypatch.setattr(journal_chunking,'__file__',str(fake))
    assert first!=fingerprint('hello','model-a')

def test_chunk_verification_rejects_wrong_owner_dimension_zero_and_missing():
    row={'chunk_index':0,'content':'hello','user_id':'u','dimensions':768,'norm':1}
    assert valid_chunks([row],'hello','u')
    for change in [{'user_id':'other'},{'dimensions':3072},{'norm':0},{'content':'stale'},{'chunk_index':1}]:
        assert not valid_chunks([{**row,**change}],'hello','u')
    assert not valid_chunks([],'hello','u')

class MemoryConnection:
    def __init__(self): self.entries={}; self.chunks={}
    @asynccontextmanager
    async def transaction(self,**kw):
        before=copy.deepcopy((self.entries,self.chunks))
        try: yield
        except BaseException:
            self.entries,self.chunks=before; raise
    async def execute(self,sql,*args):
        if sql.startswith('INSERT INTO journal_entries'):
            jid,uid,content,created_at=args; self.entries[jid]={'user_id':uid,'content':content,'created_at':created_at}
        elif sql.startswith('UPDATE journal_entries SET created_at'):
            created_at,jid=args; self.entries[jid]['created_at']=created_at
    async def fetchrow(self,sql,jid): return self.entries.get(jid)
    async def fetch(self,sql,jid): return self.chunks.get(jid,[])

def setup_seed(monkeypatch):
    from eval import baseline_fixtures as f
    from rag import journal_ingestion
    import db
    conn=MemoryConnection()
    monkeypatch.setattr(f,'STATE_PATH',Path(__file__).parents[1]/'eval'/'results'/'test-scratch'/uuid.uuid4().hex/'fixture-fingerprints.json')
    @asynccontextmanager
    async def acquire(): yield conn
    monkeypatch.setattr(db,'get_pool',AsyncMock(return_value=SimpleNamespace(acquire=acquire)))
    monkeypatch.setattr(f,'users',AsyncMock(return_value={'alpha':'u'}))
    monkeypatch.setattr(f,'inspect_kb',AsyncMock(return_value={'available':False}))
    fixture={'id':'one','user':'alpha','content':'A unique synthetic diary.','created_at':'2026-07-01T12:00:00+00:00'}
    monkeypatch.setattr(f,'definitions',lambda:{'users':['alpha'],'journals':[fixture]})
    async def ingest(conn,jid,uid,content):
        conn.chunks[jid]=[{'id':'chunk','chunk_index':0,'content':content,'user_id':uid,'dimensions':768,'norm':1}]
    mocked=AsyncMock(side_effect=ingest)
    monkeypatch.setattr(journal_ingestion,'ingest_journal_entry_asyncpg',mocked)
    return f,conn,fixture,mocked

def test_seed_is_persistent_idempotent_and_reembeds_only_on_change(monkeypatch):
    f,conn,fixture,ingest=setup_seed(monkeypatch)
    a=asyncio.run(f.seed()); b=asyncio.run(f.seed())
    assert ingest.await_count==1
    assert b['journals'][0]['status']=='unchanged'
    assert a['journals'][0]['chunk_ids']==b['journals'][0]['chunk_ids']
    fixture['content']='A corrected synthetic diary.'
    asyncio.run(f.seed()); assert ingest.await_count==2
    from config import settings
    monkeypatch.setattr(settings,'gemini_embed_model','changed-model')
    asyncio.run(f.seed()); assert ingest.await_count==3
    fixture['created_at']='2026-07-03T12:00:00+00:00'
    asyncio.run(f.seed()); assert ingest.await_count==3

def test_seed_rolls_back_on_embedding_failure(monkeypatch):
    f,conn,fixture,ingest=setup_seed(monkeypatch)
    ingest.side_effect=RuntimeError('embedding unavailable')
    with pytest.raises(RuntimeError): asyncio.run(f.seed())
    assert not conn.entries

def test_seed_rejects_foreign_existing_entry(monkeypatch):
    f,conn,fixture,ingest=setup_seed(monkeypatch)
    conn.entries[entry_id('alpha','one')]={'user_id':'manual-user','content':'real journal'}
    with pytest.raises(RuntimeError): asyncio.run(f.seed())
    assert ingest.await_count==0

def test_reset_requires_exact_explicit_namespace():
    from eval.baseline_fixtures import reset
    with pytest.raises(ValueError): asyncio.run(reset(None))

def test_trace_keeps_actual_selected_chunk_ids():
    from rag.search import KBChunkHit
    from rag import journal_retrieve
    hit=KBChunkHit(id='chunk-id',document_id='journal-id',content='diary',metadata={'user_id':'alpha'},similarity=.9,title='Journal',source_url=None,category='journal')
    with trace_retrieval(False) as captured:
        result=journal_retrieve.mmr_rerank_hits([hit],top_k=1)
        records=selected_records(captured,[{'document_id':'journal-id','content':'diary','category':'journal'}])
    assert result[0].id=='chunk-id'
    assert records[0]['chunk_id']=='chunk-id'
    assert records[0]['user_id']=='alpha'

def test_missing_key_blocks_before_client_creation(monkeypatch):
    from eval import baseline_runtime as r
    monkeypatch.setattr(r,'eval_key',lambda:None)
    with pytest.raises(ValueError):
        with r.paid_runtime(): pytest.fail('must not enter paid context')

def test_live_runner_uses_real_chat_persistence_and_fresh_sessions(monkeypatch,tmp_path):
    from eval import baseline
    import main
    import db
    from agent import orchestrator
    from agent.persona import UserPersona
    from unittest.mock import MagicMock
    sessions={}; messages={}
    client=MagicMock()
    def table(name):
        query=MagicMock()
        def insert(row):
            if name=='sessions': sessions[row['id']]=row['user_id']; messages[row['id']]=[]
            elif name=='messages': messages[row['session_id']].append({'role':row['role'],'content':row['content']})
            return SimpleNamespace(execute=lambda:SimpleNamespace(data=[row]))
        def eq(column,value):
            query.maybe_single.return_value.execute.return_value=SimpleNamespace(data={'user_id':sessions.get(value)})
            query.order.return_value.execute.return_value=SimpleNamespace(data=messages.get(value,[]))
            return query
        query.insert.side_effect=insert
        query.select.return_value=query
        query.eq.side_effect=eq
        return query
    client.table.side_effect=table
    monkeypatch.setattr(main,'get_supabase',lambda:client)
    monkeypatch.setattr(db,'get_supabase',lambda:client)
    monkeypatch.setattr(main,'load_user_persona',lambda uid:UserPersona())
    monkeypatch.setattr(baseline,'verify',AsyncMock(return_value=({'alpha':'synthetic-a'},{'available':False})))
    generation=MagicMock(return_value=('Hello, I am here to listen.','offline-stub'))
    monkeypatch.setattr(orchestrator,'_generate_reply',generation)
    case={'id':'smoke','user':'alpha','turns':['hello','thank you'],'tags':[],'checks':[]}
    result=asyncio.run(baseline.conversations([case,case],tmp_path,None))
    assert len(sessions)==2
    assert all(len(m)==4 for m in messages.values())
    assert result['summary']['metrics']['message_persistence_accuracy']['numerator']==2
    assert generation.call_count==4

def test_paid_runtime_routes_all_clients_to_eval_key_without_request(monkeypatch,tmp_path):
    from eval import baseline_runtime as r
    from google import genai
    from agent import orchestrator
    from rag import embed
    from config import settings
    from unittest.mock import MagicMock
    fake=MagicMock()
    factory=MagicMock(return_value=fake)
    monkeypatch.setattr(r,'STATE',tmp_path)
    monkeypatch.setattr(r,'eval_key',lambda:'synthetic-test-key-not-a-real-secret')
    monkeypatch.setattr(genai,'Client',factory)
    original=settings.gemini_api_key
    with r.paid_runtime():
        assert orchestrator._client() is fake
        assert embed._client() is fake
        assert settings.gemini_api_key==settings.agent_router_api_key=='synthetic-test-key-not-a-real-secret'
    restored=settings.gemini_api_key==original
    assert restored
    assert factory.call_args.kwargs['http_options'].retry_options.attempts==1
    assert not (tmp_path/'paid.lock').exists()
