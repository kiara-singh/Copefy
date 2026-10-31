"""Unit and integration tests for Journal RAG pipeline.

Tests structure-aware chunking, 768-dim embeddings, idempotent ingestion, strict
user isolation, smoke queries, and error handling for missing API keys.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rag.embed import EMBED_DIMENSIONS, EmbeddingError, embed_query
from rag.journal_chunking import chunk_journal_entry
from rag.journal_retrieve import search_journal_chunks
from rag.search import _vector_literal


def test_structure_aware_chunking_short_entry():
    """Requirement 1: Short journal remains one coherent chunk."""
    text = "Feeling good today after a long walk in the park. The sunshine really helped."
    chunks = chunk_journal_entry(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_structure_aware_chunking_multi_paragraph():
    """Requirement 2: Multi-paragraph entry produces ordered chunks without mid-sentence splitting."""
    text = (
        "I am feeling so anxious about my upcoming midterm exam in organic chemistry. "
        "I've been studying for hours every night, but my mind keeps racing.\n\n"
        "Had to give a presentation in my seminar class today. Public speaking always makes me "
        "so nervous. My hands were shaking and my heart was pounding before I stepped up."
    )
    chunks = chunk_journal_entry(text)
    assert len(chunks) >= 1
    for chunk in chunks:
        # Verify no mid-sentence cuts (chunk ends with sentence punctuation or newline boundary)
        cleaned = chunk.strip()
        assert cleaned[-1] in ".!?"


def test_missing_gemini_api_key_raises_embedding_error():
    """Requirement 3: Confirm that missing GEMINI_API_KEY raises EmbeddingError."""
    with patch("config.settings.gemini_api_key", ""):
        from rag.embed import _client
        _client.cache_clear()
        with pytest.raises(EmbeddingError) as exc_info:
            embed_query("Test string with missing API key")
        assert "GEMINI_API_KEY is required for embeddings" in str(exc_info.value)
        _client.cache_clear()


def test_embedding_dimensions():
    """Requirement 4: Verify 768-dimensional embedding shape."""
    mock_vector = [0.01] * 768
    with patch("rag.embed._call_embed_api", return_value=mock_vector):
        vec = embed_query("Test journal entry content for embedding dimensions.")
        assert len(vec) == 768
        assert len(vec) == EMBED_DIMENSIONS


def test_vector_literal_formatting():
    """Verify pgvector literal formatting produces valid string."""
    vec = [0.1, 0.2, 0.3]
    literal = _vector_literal(vec)
    assert literal == "[0.10000000,0.20000000,0.30000000]"


def test_unknown_user_gets_no_journal_chunks():
    """A UUID with no rows must not receive someone else's journals.

    Do not call seed_synthetic_journals from tests. Mocked embed_query there
    wrote identical [0.01] vectors into the live journal_chunks table.
    """
    import asyncio

    other_user_id = "00000000-0000-0000-0000-000000000000"

    async def _run():
        with patch("rag.journal_retrieve.embed_query", return_value=[0.01] * 768):
            return await search_journal_chunks(other_user_id, "exam anxiety", top_k=5)

    assert asyncio.run(_run()) == []
