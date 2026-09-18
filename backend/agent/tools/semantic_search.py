"""Format retrieved KB chunks for the chat prompt."""

from __future__ import annotations

from datetime import datetime

from rag.retrieve import RetrievedChunk


def journal_entry_date_label(created_at: str | None) -> str | None:
    """Calendar day of the parent journal entry, if parseable."""
    if not created_at:
        return None
    text = str(created_at).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


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
        if chunk.category == "journal":
            dated = journal_entry_date_label(chunk.created_at)
            if dated:
                header = f"{header} · {dated}"
        body = chunk.content.strip()
        if len(body) > max_chars:
            body = body[: max_chars - 3].rstrip() + "..."
        parts.append(f"[{index}] {header}\n{body}")
    return "\n\n".join(parts)
