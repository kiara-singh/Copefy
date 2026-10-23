"""One-shot DB migration: 8 categories -> 5 + anxiety_subtype.

Usage (from backend/, venv active):

    python -m rag.migrate_categories --dry-run
    python -m rag.migrate_categories --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config import settings
from rag.store import KnowledgeStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("rag.migrate_categories")

_SQL_PATH = Path(__file__).resolve().parents[2] / "database" / "migrate_categories_5.sql"


def _sql_statements(sql: str) -> list[str]:
    parts: list[str] = []
    for chunk in sql.split(";"):
        statement = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if statement and statement.upper() not in {"BEGIN", "COMMIT"}:
            parts.append(statement)
    return parts


async def run_migration(*, confirm: bool) -> int:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is missing. Set it in backend/.env")
    if not _SQL_PATH.is_file():
        raise SystemExit(f"Migration SQL not found: {_SQL_PATH}")

    sql = _SQL_PATH.read_text(encoding="utf-8")
    if not confirm:
        logger.info("Dry run. Would execute %s (%s bytes).", _SQL_PATH.name, len(sql))
        logger.info("Re-run with --confirm to apply.")
        return 0

    store = KnowledgeStore(settings.database_url)
    await store.connect()
    try:
        async with store.pool.acquire() as conn:
            async with conn.transaction():
                for statement in _sql_statements(sql):
                    await conn.execute(statement)
        await store.ensure_multilabel_schema()
        logger.info("Migration applied successfully.")
        return 0
    finally:
        await store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate KB to 5 categories + anxiety_subtype")
    parser.add_argument("--confirm", action="store_true", help="Apply migration")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    args = parser.parse_args(argv)
    if args.confirm and args.dry_run:
        raise SystemExit("Use either --dry-run or --confirm")
    if not args.confirm:
        args.dry_run = True
    return asyncio.run(run_migration(confirm=args.confirm))


if __name__ == "__main__":
    sys.exit(main())
