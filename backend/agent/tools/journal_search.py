"""Journal entry vector search tool wrapper."""

from __future__ import annotations

from rag.journal_retrieve import search_journal_chunks


async def search_journal_entries(user_id: str, query: str, top_k: int = 5) -> dict:
    chunks = await search_journal_chunks(user_id, query, top_k=top_k)
    return {
        "status": "ok",
        "retrieved": bool(chunks),
        "user_id": user_id,
        "query": query,
        "chunks": [
            {
                "content": chunk.content,
                "similarity": round(chunk.similarity, 4),
                "category": chunk.category,
            }
            for chunk in chunks
        ],
    }
