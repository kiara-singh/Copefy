"""Print Postgres database and table sizes. Optional: --vacuum to reclaim dead space."""
import argparse
import asyncio

from config import settings
from rag.store import KnowledgeStore


async def main(vacuum: bool) -> None:
    store = KnowledgeStore(settings.database_url)
    await store.connect()
    try:
        if vacuum:
            print("Running VACUUM ANALYZE kb_chunks ...")
            await store.pool.execute("VACUUM ANALYZE kb_chunks")
            print("Running VACUUM ANALYZE kb_documents ...")
            await store.pool.execute("VACUUM ANALYZE kb_documents")
            print("Done.")

        row = await store.pool.fetchrow(
            """
            SELECT
                pg_size_pretty(pg_database_size(current_database())) AS db_size,
                pg_database_size(current_database()) AS db_bytes
            """
        )
        print("database:", dict(row))
        tables = await store.pool.fetch(
            """
            SELECT relname AS table_name,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total
            FROM pg_catalog.pg_statio_user_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 10
            """
        )
        for r in tables:
            print(f"  {r['table_name']}: {r['total']}")
        active = await store.pool.fetchval(
            "SELECT COUNT(*)::int FROM kb_documents WHERE status = 'active'"
        )
        chunks = await store.pool.fetchval("SELECT COUNT(*)::int FROM kb_chunks")
        print(f"active_docs={active} chunks={chunks}")
        indexes = await store.pool.fetch(
            """
            SELECT indexname,
                   pg_size_pretty(pg_relation_size(quote_ident(schemaname) || '.' || quote_ident(indexname))) AS size
            FROM pg_indexes
            WHERE tablename = 'kb_chunks'
            ORDER BY pg_relation_size(quote_ident(schemaname) || '.' || quote_ident(indexname)) DESC
            """
        )
        print("kb_chunks indexes:")
        for r in indexes:
            print(f"  {r['indexname']}: {r['size']}")
    finally:
        await store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vacuum", action="store_true", help="Run VACUUM ANALYZE first")
    args = parser.parse_args()
    asyncio.run(main(args.vacuum))
