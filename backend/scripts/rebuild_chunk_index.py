"""Drop failed REINDEX leftover and rebuild HNSW index on kb_chunks.

Usage (from backend/, venv active):

    python -m scripts.rebuild_chunk_index --drop-orphan-only
    python -m scripts.rebuild_chunk_index --rebuild
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import asyncpg

from config import settings
from rag.store import KnowledgeStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rebuild_chunk_index")

ORPHAN_INDEX = "kb_chunks_embedding_hnsw_idx_ccnew"
MAIN_INDEX = "kb_chunks_embedding_hnsw_idx"


async def _connect_no_timeout() -> asyncpg.Connection:
    dsn = settings.database_url
    if dsn and "sslmode=" not in dsn.lower() and "localhost" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return await asyncpg.connect(dsn=dsn, command_timeout=3600)


async def drop_orphan() -> None:
    conn = await _connect_no_timeout()
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_indexes WHERE indexname = $1", ORPHAN_INDEX
        )
        if not exists:
            logger.info("No orphan index %s — nothing to drop.", ORPHAN_INDEX)
            return
        logger.info("Dropping orphan index %s ...", ORPHAN_INDEX)
        await conn.execute(f'DROP INDEX IF EXISTS "{ORPHAN_INDEX}"')
        logger.info("Dropped %s.", ORPHAN_INDEX)
    finally:
        await conn.close()


async def rebuild_index() -> None:
    conn = await _connect_no_timeout()
    try:
        logger.info("Dropping main HNSW index %s ...", MAIN_INDEX)
        await conn.execute(f'DROP INDEX IF EXISTS "{MAIN_INDEX}"')
        logger.info("Creating HNSW index (may take several minutes) ...")
        await conn.execute(
            f"""
            CREATE INDEX "{MAIN_INDEX}"
            ON kb_chunks
            USING hnsw (embedding vector_cosine_ops)
            """
        )
        logger.info("Index rebuild complete.")
        logger.info("Running VACUUM ANALYZE kb_chunks ...")
        await conn.execute("VACUUM ANALYZE kb_chunks")
        logger.info("Done.")
    finally:
        await conn.close()


async def main(drop_orphan_only: bool, rebuild: bool) -> None:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL missing")
    if drop_orphan_only:
        await drop_orphan()
        return
    if rebuild:
        await drop_orphan()
        await rebuild_index()
        store = KnowledgeStore(settings.database_url)
        await store.connect()
        try:
            row = await store.pool.fetchrow(
                "SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size"
            )
            logger.info("database size now: %s", row["db_size"])
        finally:
            await store.close()
        return
    raise SystemExit("Pass --drop-orphan-only or --rebuild")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop-orphan-only", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.drop_orphan_only, args.rebuild))
