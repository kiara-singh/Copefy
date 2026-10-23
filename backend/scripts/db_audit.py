"""Audit all public tables for size and row counts."""
import asyncio

from config import settings
from rag.store import KnowledgeStore


async def main() -> None:
    store = KnowledgeStore(settings.database_url)
    await store.connect()
    try:
        row = await store.pool.fetchrow(
            "SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size"
        )
        print("database:", row["db_size"])

        tables = await store.pool.fetch(
            """
            SELECT c.relname AS table_name,
                   pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
                   pg_total_relation_size(c.oid) AS bytes,
                   COALESCE(s.n_live_tup, 0)::bigint AS live_rows,
                   COALESCE(s.n_dead_tup, 0)::bigint AS dead_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC
            """
        )
        print("\n=== public tables ===")
        for r in tables:
            print(
                f"{r['table_name']:28} {r['total']:>10}  "
                f"live={r['live_rows']} dead={r['dead_rows']}"
            )

        kb = await store.pool.fetch(
            """
            SELECT status, COUNT(*)::int AS n
            FROM kb_documents
            GROUP BY status
            ORDER BY n DESC
            """
        )
        print("\n=== kb_documents by status ===")
        for r in kb:
            print(f"  {r['status']}: {r['n']}")

        orphans = await store.pool.fetch(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        print("\n=== all public table names ===")
        print(", ".join(r["tablename"] for r in orphans))
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
