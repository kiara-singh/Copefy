"""Re-embed existing journal_entries into journal_chunks with real Gemini vectors.

Use this when stored embeddings are placeholders (all [0.01, ...]), which makes
production journal search return the same memories for every query.

    python -m scripts.reingest_journal_embeddings
    python -m scripts.reingest_journal_embeddings --user-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio

from eval.journal_retrieve import JOURNAL_EVAL_USER_ID, load_journal_entries
from rag.journal_ingestion import ingest_journal_entry


async def reingest(user_id: str) -> int:
    entries = await load_journal_entries(user_id=user_id, dedupe=False)
    if not entries:
        raise SystemExit(f"No journal_entries for user {user_id}")
    print(f"Re-ingesting {len(entries)} entries for {user_id} (no diary text logged)")
    for index, entry in enumerate(entries, start=1):
        chunks = await ingest_journal_entry(entry.id, user_id, entry.content)
        print(f"  {index}/{len(entries)} {entry.id} chunks={len(chunks)} chars={entry.char_len}")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-embed journal_entries into journal_chunks")
    parser.add_argument("--user-id", default=JOURNAL_EVAL_USER_ID)
    args = parser.parse_args()
    asyncio.run(reingest(args.user_id))


if __name__ == "__main__":
    main()
