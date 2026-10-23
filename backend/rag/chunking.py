"""Markdown-aware chunking for RAG ingest."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    token_estimate: int


def _estimate_tokens(text: str) -> int:
    # Rough heuristic: ~4 characters per token for English prose.
    return max(1, len(text) // 4)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    buckets: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        if len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            buckets.append(current)
            current = sentence
    if current:
        buckets.append(current)
    return buckets


def chunk_markdown(
    markdown: str,
    *,
    category: str,
    title: str,
    max_chars: int = 800,
    overlap: int = 120,
    min_chars: int = 200,
    max_chunks: int = 40,
    max_source_chars: int = 24_000,
) -> list[TextChunk]:
    """
    Split markdown into overlapping chunks.

    Prefers heading boundaries, then paragraphs, then sentences.
    Each chunk is prefixed with category + title for embedding context.

    Caps protect the free-tier embed quota from mega-pages (e.g. site hubs).
    """
    text = markdown.strip()
    if not text:
        return []

    if max_source_chars > 0 and len(text) > max_source_chars:
        text = text[:max_source_chars].rsplit("\n", 1)[0].strip()

    # Split on markdown headings while keeping the heading with following body.
    sections = re.split(r"(?=^#{1,6}\s+)", text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]
    if not sections:
        sections = [text]

    raw_pieces: list[str] = []
    for section in sections:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
        if not paragraphs:
            continue
        buffer = ""
        for paragraph in paragraphs:
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= max_chars:
                buffer = candidate
                continue
            if buffer:
                raw_pieces.extend(_split_long(buffer, max_chars))
            raw_pieces.extend(_split_long(paragraph, max_chars))
            buffer = ""
        if buffer:
            raw_pieces.extend(_split_long(buffer, max_chars))

    # Apply character overlap between consecutive pieces.
    overlapped: list[str] = []
    for piece in raw_pieces:
        if overlapped and overlap > 0:
            prev = overlapped[-1]
            prefix = prev[-overlap:] if len(prev) > overlap else prev
            merged = f"{prefix}\n{piece}".strip()
            overlapped.append(merged if len(merged) <= max_chars + overlap else piece)
        else:
            overlapped.append(piece)

    prefix = f"[{category}] {title}\n".strip()
    chunks: list[TextChunk] = []
    for index, piece in enumerate(overlapped):
        body = piece.strip()
        if len(body) < min_chars:
            continue
        content = f"{prefix}\n{body}".strip()
        chunks.append(
            TextChunk(
                index=index,
                content=content,
                token_estimate=_estimate_tokens(content),
            )
        )

    # Re-index after filtering short chunks, then hard-cap chunk count.
    if max_chunks > 0:
        chunks = chunks[:max_chunks]
    return [
        TextChunk(index=i, content=c.content, token_estimate=c.token_estimate)
        for i, c in enumerate(chunks)
    ]
