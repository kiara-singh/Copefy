"""Persistent synthetic fixtures using production journal chunking/embedding/storage."""
import hashlib
import json
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import yaml

ROOT=Path(__file__).parent
NAMESPACE='copefy-baseline-v1'
STATE_PATH=ROOT/'results'/'baseline-state'/'fixture-fingerprints.json'

@lru_cache(maxsize=1)
def definitions():
    return yaml.safe_load((ROOT/'fixtures/synthetic.yaml').read_text(encoding='utf-8'))

def fingerprint(content, model):
    from rag import journal_chunking
    payload={'content':content,'model':model,'dimensions':768,
             'chunker_sha256':hashlib.sha256(Path(journal_chunking.__file__).read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()

def entry_id(alias, slug):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,f'{NAMESPACE}/{alias}/{slug}'))

def fixture_state():
    """Local persistent provenance; the deployed journal table has no tags column."""
    from config import settings
    project=hashlib.sha256(settings.supabase_url.encode()).hexdigest()
    if STATE_PATH.exists():
        state=json.loads(STATE_PATH.read_text(encoding='utf-8'))
        if state.get('namespace')!=NAMESPACE or state.get('project')!=project:
            raise RuntimeError('Fixture provenance belongs to another project/namespace')
        return state
    return {'namespace':NAMESPACE,'project':project,'entries':{}}

def save_fixture_state(state):
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    temp=STATE_PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(state,indent=2),encoding='utf-8')
    temp.replace(STATE_PATH)

def selected_journals(identifiers=None):
    all_entries=definitions()['journals']
    if identifiers is None: return all_entries
    requested=set(identifiers)
    if not requested or requested-{f['id'] for f in all_entries}:
        raise ValueError('Unknown or empty fixture selection')
    return [f for f in all_entries if f['id'] in requested]

def valid_chunks(rows, content, user_id):
    from rag.journal_chunking import chunk_journal_entry
    expected=chunk_journal_entry(content.strip())
    return len(rows)==len(expected) and all(
        r['chunk_index']==i and r['content']==text and str(r['user_id'])==str(user_id)
        and r['dimensions']==768 and r['norm']>0
        for i,(r,text) in enumerate(zip(rows,expected)))

async def users(conn, create=False, allow_missing=False):
    from db import get_supabase
    result={}
    for alias in definitions()['users']:
        email=f'{NAMESPACE}-{alias}@example.com'
        row=await conn.fetchrow('SELECT id, raw_app_meta_data FROM auth.users WHERE email=$1',email)
        if not row and create:
            # Admin creation does not send email. Password is random and never stored/logged.
            import asyncio,secrets
            await asyncio.to_thread(get_supabase().auth.admin.create_user,{
                'email':email,'password':secrets.token_urlsafe(40),'email_confirm':True,
                'app_metadata':{'eval_namespace':NAMESPACE},'user_metadata':{'synthetic_eval':True}})
            row=await conn.fetchrow('SELECT id, raw_app_meta_data FROM auth.users WHERE email=$1',email)
        if not row:
            if allow_missing: continue
            raise RuntimeError(f'Synthetic user {alias} is not seeded')
        metadata=row['raw_app_meta_data']
        if isinstance(metadata,str): metadata=json.loads(metadata)
        if metadata.get('eval_namespace')!=NAMESPACE:
            raise RuntimeError('Account marker mismatch; refusing to reuse or mutate account')
        result[alias]=str(row['id'])
    return result

async def inspect_kb(conn):
    # Existing production names only. No invented clinical tables or DDL.
    async with conn.transaction(readonly=True):
        docs=await conn.fetchval("SELECT to_regclass('public.kb_documents') IS NOT NULL")
        funcs=await conn.fetch("SELECT oid::regprocedure::text AS signature FROM pg_proc WHERE proname='match_kb_chunks' AND pg_function_is_visible(oid)")
        available=bool(docs and funcs)
        probe_error=None
        if available:
            try:
                async with conn.transaction():
                    await conn.fetch('SELECT id, title, source_url, category FROM kb_documents LIMIT 1')
                    await conn.fetch('SELECT id, document_id, content, metadata, similarity FROM match_kb_chunks($1::vector, $2, $3)', '['+','.join(['0.01']*768)+']',1,None)
            except Exception as exc:
                available=False; probe_error=type(exc).__name__
        return {'available':available,'kb_documents':docs,'rpc_signatures':[r['signature'] for r in funcs],
                'probe':'read_only_non_Gemini_vector','probe_error':probe_error}

async def chunk_rows(conn,jid):
    return await conn.fetch('SELECT id, user_id, chunk_index, content, vector_dims(embedding) AS dimensions, vector_norm(embedding) AS norm FROM journal_chunks WHERE journal_entry_id=$1::uuid ORDER BY chunk_index',jid)

async def seed(identifiers=None):
    from config import settings
    from db import get_pool
    from rag.journal_ingestion import ingest_journal_entry_asyncpg
    chosen=selected_journals(identifiers)
    state=fixture_state()
    pool=await get_pool(); results=[]
    async with pool.acquire() as conn:
        # Serializes seed/reset across processes without an eval schema.
        await conn.execute("SELECT pg_advisory_lock(hashtext($1))",NAMESPACE)
        try:
            ids=await users(conn,create=True)
            for alias,uid in ids.items():
                await conn.execute('UPDATE profiles SET preferred_name=$1 WHERE id=$2::uuid',f'SYNTHETIC EVAL {NAMESPACE} {alias}',uid)
            for fixture in chosen:
                uid=ids[fixture['user']]; jid=entry_id(fixture['user'],fixture['id'])
                content=fixture['content']; stamp=fingerprint(content,settings.gemini_embed_model)
                fixture_time=datetime.fromisoformat(fixture['created_at'])
                async with conn.transaction():
                    existing=await conn.fetchrow('SELECT user_id, content, created_at FROM journal_entries WHERE id=$1::uuid',jid)
                    if existing and str(existing['user_id'])!=uid:
                        raise RuntimeError('Journal ownership marker mismatch')
                    if existing and jid not in state['entries']:
                        raise RuntimeError('Persisted journal lacks local embedding provenance; reset explicitly')
                    rows=await chunk_rows(conn,jid) if existing else []
                    unchanged=bool(existing and state['entries'].get(jid)==stamp and existing['content']==content and valid_chunks(rows,content,uid))
                    if not unchanged:
                        await conn.execute('INSERT INTO journal_entries(id,user_id,content,created_at) VALUES($1::uuid,$2::uuid,$3,$4) ON CONFLICT(id) DO UPDATE SET content=EXCLUDED.content,created_at=EXCLUDED.created_at',jid,uid,content,fixture_time)
                        # Same ingestion function as /journal: chunker -> Gemini -> journal_chunks.
                        # Transaction additionally prevents partial fixture replacement on failure.
                        await ingest_journal_entry_asyncpg(conn,jid,uid,content)
                        rows=await chunk_rows(conn,jid)
                        if not valid_chunks(rows,content,uid): raise RuntimeError('Persisted chunk verification failed')
                    elif existing['created_at']!=fixture_time:
                        await conn.execute('UPDATE journal_entries SET created_at=$1 WHERE id=$2::uuid',fixture_time,jid)
                if not unchanged:
                    state['entries'][jid]=stamp
                    save_fixture_state(state)
                results.append({'fixture':fixture['id'],'user':fixture['user'],'journal_entry_id':jid,
                                'status':'unchanged' if unchanged else 'embedded','chunk_ids':[str(r['id']) for r in rows]})
            return {'users':ids,'journals':results,'clinical_kb':await inspect_kb(conn)}
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtext($1))',NAMESPACE)

async def verify(identifiers=None):
    from config import settings
    from db import get_pool
    chosen=selected_journals(identifiers)
    state=fixture_state()
    pool=await get_pool()
    async with pool.acquire() as conn:
        ids=await users(conn)
        for f in chosen:
            jid=entry_id(f['user'],f['id'])
            row=await conn.fetchrow('SELECT content,user_id,created_at FROM journal_entries WHERE id=$1::uuid',jid)
            stamp=fingerprint(f['content'],settings.gemini_embed_model)
            if not row or str(row['user_id'])!=ids[f['user']] or row['content']!=f['content'] or row['created_at']!=datetime.fromisoformat(f['created_at']) or state['entries'].get(jid)!=stamp or not valid_chunks(await chunk_rows(conn,jid),f['content'],ids[f['user']]):
                raise RuntimeError(f'Fixture missing/stale/corrupt: {f["id"]}; seed first')
        return ids,await inspect_kb(conn)

async def reset(confirm):
    if confirm!=NAMESPACE: raise ValueError('Reset requires exact namespace confirmation')
    from db import get_pool,get_supabase
    import asyncio
    pool=await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('SELECT pg_advisory_lock(hashtext($1))',NAMESPACE)
        try:
            ids=await users(conn,allow_missing=True)
            # Only the two exact emails with trusted app_metadata markers, never arbitrary IDs.
            for uid in ids.values():
                await asyncio.to_thread(get_supabase().auth.admin.delete_user,uid)
            STATE_PATH.unlink(missing_ok=True)
            return {'deleted_synthetic_users':list(ids),'namespace':NAMESPACE}
        finally:
            await conn.execute('SELECT pg_advisory_unlock(hashtext($1))',NAMESPACE)
