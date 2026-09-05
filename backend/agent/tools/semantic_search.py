"""Format retrieved KB chunks for the chat prompt."""

from __future__ import annotations

from rag.retrieve import RetrievedChunk


def format_chunks_for_prompt(
    chunks: list[RetrievedChunk],
    *,
    max_chunks: int = 3,
    max_chars: int = 400,
) -> str:
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
