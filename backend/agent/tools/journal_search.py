"""Journal entry search — scaffold for v2."""

from __future__ import annotations


async def search_journal_entries(user_id: str, query: str, top_k: int = 5) -> dict:
    return {
        "status": "unavailable",
        "message": "Journal search is not available yet.",
        "user_id": user_id,
        "query": query,
        "top_k": top_k,
        "entries": [],
    }
