"""Offline checks for clinical KB classification and embedding shape."""

from rag import CATEGORIES
from rag.chunking import chunk_markdown
from rag.classify import classify_content
from rag.embed import EMBED_DIMENSIONS
from rag.search import _vector_literal as search_literal
from rag.store import _vector_literal as store_literal


def test_seeded_depression_page_does_not_keep_anxiety_subtype():
    """A depression seed stays depression and does not store an anxiety subtype."""
    result = classify_content(
        url="https://www.nimh.nih.gov/health/topics/anxiety-disorders",
        title="Panic disorder and phobias",
        body="Panic attacks, phobias, and constant worry are the focus of this page.",
        seed_category="depression",
    )
    assert result is not None
    assert result.primary == "depression"
    assert result.anxiety_subtype is None
    assert all(cat in CATEGORIES for cat in result.categories)


def test_anxiety_seed_keeps_a_valid_subtype():
    result = classify_content(
        url="https://www.nimh.nih.gov/health/topics/anxiety-disorders",
        title="Anxiety disorders",
        body="Worry, panic attacks, and avoidance.",
        seed_category="gad",
    )
    assert result is not None
    assert result.primary == "anxiety"
    assert result.anxiety_subtype == "gad"


def test_chunks_and_vector_literals_match_retrieval():
    chunks = chunk_markdown(
        "Anxiety is persistent worry.\n\nBreathing exercises can help in the moment.",
        category="anxiety",
        title="Worry",
        max_chars=200,
        overlap=20,
        min_chars=20,
        max_chunks=4,
    )
    assert chunks
    assert all(chunk.content.startswith("[anxiety]") for chunk in chunks)
    vector = [0.125, -0.5, 1.0 / 3]
    assert search_literal(vector) == store_literal(vector)
    assert EMBED_DIMENSIONS == 768
