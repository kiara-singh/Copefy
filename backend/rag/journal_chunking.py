"""Structure-Aware Journal Chunker.

Splits journal entries at natural paragraph and sentence boundaries while preserving
coherent thoughts, sentence integrity, and original entry order.
"""

from __future__ import annotations

import re

# Practical safeguards for chunk target length
TARGET_MAX_CHARS = 450
MIN_CHUNK_CHARS = 40


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using standard punctuation delimiters."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def chunk_journal_entry(content: str) -> list[str]:
    """Chunk a journal entry using natural paragraph and sentence boundaries.

    Rules:
    - Short entries (< TARGET_MAX_CHARS) remain a single chunk.
    - Paragraph boundaries (\\n\\n or \\n) are preferred.
    - Unusually long paragraphs are divided at sentence boundaries.
    - Sentences are never split mid-sentence.
    - Chunk order is preserved.
    """
    text = content.strip()
    if not text:
        return []

    # Short entries remain a single chunk
    if len(text) <= TARGET_MAX_CHARS:
        return [text]

    # Split into paragraphs by blank lines or newlines
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current_accum: list[str] = []
    current_length = 0

    for para in paragraphs:
        # If a single paragraph is unusually long, split it by sentence boundaries
        if len(para) > TARGET_MAX_CHARS:
            # Flush any accumulated paragraph content first
            if current_accum:
                chunks.append("\n\n".join(current_accum))
                current_accum = []
                current_length = 0

            sentences = _split_into_sentences(para)
            sent_accum: list[str] = []
            sent_len = 0
            for sent in sentences:
                if sent_len + len(sent) + 1 > TARGET_MAX_CHARS and sent_accum:
                    chunks.append(" ".join(sent_accum))
                    sent_accum = [sent]
                    sent_len = len(sent)
                else:
                    sent_accum.append(sent)
                    sent_len += len(sent) + 1
            if sent_accum:
                chunks.append(" ".join(sent_accum))

        else:
            # If adding this paragraph exceeds target max, flush accumulated content
            if current_length + len(para) + 2 > TARGET_MAX_CHARS and current_accum:
                chunks.append("\n\n".join(current_accum))
                current_accum = [para]
                current_length = len(para)
            else:
                current_accum.append(para)
                current_length += len(para) + 2

    if current_accum:
        chunks.append("\n\n".join(current_accum))

    # Final pass: merge tiny residual trailing chunks if needed
    merged_chunks: list[str] = []
    for chunk in chunks:
        if merged_chunks and len(chunk) < MIN_CHUNK_CHARS and len(merged_chunks[-1]) + len(chunk) + 2 <= TARGET_MAX_CHARS * 1.5:
            merged_chunks[-1] = merged_chunks[-1] + "\n\n" + chunk
        else:
            merged_chunks.append(chunk)

    return merged_chunks or [text]
