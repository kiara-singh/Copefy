"""Web search — scaffold."""

from __future__ import annotations


async def web_search(query: str) -> dict:
    return {
        "status": "unavailable",
        "message": "Web search is not available yet.",
        "query": query,
    }
