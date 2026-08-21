"""Semantic search over the medical knowledge base."""

from __future__ import annotations

from rag.retrieve import RetrievedChunk, retrieve_with_strategy


async def semantic_search_kb(
    user_message: str,
    *,
    history: list[dict[str, str]] | None = None,
) -> dict:
    plan, chunks = await retrieve_with_strategy(user_message, history=history)
    return {
        "status": "ok",
        "retrieved": bool(chunks),
        "reason": plan.reason,
        "categories": list(plan.categories),
        "chunks": [
            {
                "content": chunk.content,
                "source_url": chunk.source_url,
                "title": chunk.title,
                "category": chunk.category,
                "similarity": round(chunk.similarity, 4),
            }
            for chunk in chunks
        ],
    }


def format_chunks_for_prompt(chunks: list[RetrievedChunk], *, max_chunks: int = 3, max_chars: int = 400) -> str:
    if not chunks:
        return "No reference material retrieved."

    parts: list[str] = []
    for index, chunk in enumerate(chunks[:max_chunks], start=1):
        header = chunk.title or chunk.category or "Reference"
        body = chunk.content.strip()
        if len(body) > max_chars:
            body = body[: max_chars - 3].rstrip() + "..."
        parts.append(f"[{index}] {header}\n{body}")
    return "\n\n".join(parts)
