"""VACUUM FULL kb_chunks to compact heap after large deletes."""
import asyncio

import asyncpg

from config import settings
from rag.store import KnowledgeStore


async def main() -> None:
    dsn = settings.database_url
    if dsn and "sslmode=" not in dsn.lower() and "localhost" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    conn = await asyncpg.connect(dsn=dsn, command_timeout=3600)
    try:
        print("VACUUM FULL kb_chunks (may take several minutes)...")
        await conn.execute("VACUUM FULL kb_chunks")
        print("VACUUM ANALYZE kb_documents...")
        await conn.execute("VACUUM ANALYZE kb_documents")
    finally:
        await conn.close()

    store = KnowledgeStore(settings.database_url)
    await store.connect()
    try:
        row = await store.pool.fetchrow(
            "SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size"
        )
        print("database size now:", row["db_size"])
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
