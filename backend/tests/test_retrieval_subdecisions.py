"""Offline Layer 3 sub-decision tests — no Gemini, no database."""

from __future__ import annotations

from rag.retrieve import (
    CLINICAL_EXPANSIONS,
    _detect_categories,
    _rerank_hits,
    build_retrieval_plan,
)
from rag.search import KBChunkHit
from rag.strategies.pipeline import apply_min_similarity, mmr_rerank_hits


def _hit(
    *,
    hit_id: str,
    document_id: str,
    content: str,
    similarity: float,
    category: str | None = "anxiety",
) -> KBChunkHit:
    return KBChunkHit(
        id=hit_id,
        document_id=document_id,
        content=content,
        metadata={},
        similarity=similarity,
        title=hit_id,
        source_url=None,
        category=category,
    )


def test_detect_anxiety_from_worry():
    assert _detect_categories("I can't stop worrying about everything")[0] == "anxiety"


def test_detect_adhd_from_focus():
    cats = _detect_categories("I keep losing focus at work and forgetting what people just told me")
    assert "adhd" in cats


def test_detect_empty_on_chitchat():
    assert _detect_categories("Hi, how are you?") == []


def test_query_expansion_adds_clinical_terms():
    plan = build_retrieval_plan("I can't stop worrying about everything")
    assert "anxiety" in plan.categories
    for token in CLINICAL_EXPANSIONS["anxiety"].split():
        assert token in plan.search_query


def test_heuristic_rerank_keeps_one_chunk_per_document():
    hits = [
        _hit(hit_id="a1", document_id="doc-a", content="worry coping", similarity=0.9),
        _hit(hit_id="a2", document_id="doc-a", content="worry extra", similarity=0.89),
        _hit(hit_id="b1", document_id="doc-b", content="unrelated text", similarity=0.88),
    ]
    ranked = _rerank_hits("worry", hits, top_k=5)
    assert [hit.document_id for hit in ranked] == ["doc-a", "doc-b"]


def test_heuristic_rerank_boosts_coping_language():
    weak_coping = _hit(
        hit_id="c1",
        document_id="doc-c",
        content="A coping strategy that can be helpful",
        similarity=0.70,
    )
    strong_generic = _hit(
        hit_id="d1",
        document_id="doc-d",
        content="Diagnostic criteria listed in a table",
        similarity=0.72,
    )
    ranked = _rerank_hits("help", [strong_generic, weak_coping], top_k=2)
    assert ranked[0].id == "c1"


def test_mmr_prefers_diverse_second_chunk():
    query_like = _hit(
        hit_id="m1",
        document_id="doc-1",
        content="panic attacks racing heart night worry",
        similarity=0.95,
    )
    near_duplicate = _hit(
        hit_id="m2",
        document_id="doc-2",
        content="panic attacks racing heart night worry again",
        similarity=0.94,
    )
    diverse = _hit(
        hit_id="m3",
        document_id="doc-3",
        content="grounding breath count five things you can see",
        similarity=0.80,
    )
    ranked = mmr_rerank_hits([query_like, near_duplicate, diverse], top_k=2, lambda_mult=0.5)
    assert ranked[0].id == "m1"
    assert ranked[1].id == "m3"


def test_similarity_threshold_drops_weak_hits():
    hits = [
        _hit(hit_id="s1", document_id="d1", content="strong", similarity=0.80),
        _hit(hit_id="s2", document_id="d2", content="weak", similarity=0.40),
    ]
    kept = apply_min_similarity(hits, 0.65)
    assert [hit.id for hit in kept] == ["s1"]


def test_similarity_threshold_none_keeps_all():
    hits = [
        _hit(hit_id="s1", document_id="d1", content="strong", similarity=0.80),
        _hit(hit_id="s2", document_id="d2", content="weak", similarity=0.40),
    ]
    assert apply_min_similarity(hits, None) == hits
