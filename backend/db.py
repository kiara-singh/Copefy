"""Database / vector store access.

For now this only wires up a Supabase client placeholder. The pgvector
connection used for RAG embeddings will be added here later, likely via the
`database_url` setting and an async Postgres driver (e.g. asyncpg / SQLAlchemy)
with the `vector` extension enabled in Supabase.
"""

from functools import lru_cache

from supabase import Client, create_client

from config import settings


@lru_cache
def get_supabase() -> Client | None:
    """Return a cached Supabase client, or None if not configured yet."""
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_key)


# TODO: pgvector connection for RAG.
# Example (to implement later):
#   import asyncpg
#   pool = await asyncpg.create_pool(settings.database_url)
#   # ensure `create extension if not exists vector;` is run on the DB
#   # then store/query embeddings against a table with a `vector` column.
