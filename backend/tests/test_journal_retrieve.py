"""Offline tests for in-memory journal ranking."""

from __future__ import annotations

from eval.journal_retrieve import (
    JournalEntry,
    contains_recall,
    cosine_similarity,
    entry_id_recall,
    journal_label_recall,
    rank_journal_hits,
    rerank_journal_hits,
)
from rag.strategies.baseline import DEFAULT_CONFIG
from rag.strategies.mmr import MMR_CONFIG


def test_cosine_identical_is_one():
    vector = [0.3, 0.4, 0.0]
    assert abs(cosine_similarity(vector, vector) - 1.0) < 1e-9


def test_cosine_orthogonal_is_zero():
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_rank_journal_hits_orders_by_cosine():
    query = [1.0, 0.0]
    close = JournalEntry(id="close", content="a", embedding=[0.9, 0.1])
    far = JournalEntry(id="far", content="b", embedding=[0.1, 0.9])
    hits = rank_journal_hits(query, [far, close], match_count=2)
    assert [hit.id for hit in hits] == ["close", "far"]
    assert hits[0].similarity > hits[1].similarity


def test_rank_caps_match_count():
    query = [1.0, 0.0]
    entries = [
        JournalEntry(id=str(i), content="x", embedding=[1.0, 0.0]) for i in range(5)
    ]
    hits = rank_journal_hits(query, entries, match_count=2)
    assert len(hits) == 2


def test_entry_id_recall():
    import math

    assert entry_id_recall(["a", "b"], ["b", "c"]) == 0.5
    assert math.isnan(entry_id_recall([], ["a"]))


def test_contains_and_label_recall():
    close = JournalEntry(id="exam", content="worried about my organic chemistry midterm")
    chunk = type("C", (), {"content": close.content})()
    assert contains_recall(["organic chemistry"], [chunk]) == 1.0
    case = {"expected_contains": ["organic chemistry"]}
    assert journal_label_recall(case, ["exam"], [chunk], [close]) == 1.0
    case_ids = {"expected_entry_ids": ["exam"]}
    assert journal_label_recall(case_ids, ["exam"], [chunk], [close]) == 1.0


def test_mmr_and_heuristic_rerank_on_fake_hits():
    query = "exam stress"
    close = JournalEntry(id="exam", content="worried about my exam tomorrow", embedding=[1.0, 0.0])
    other = JournalEntry(id="sleep", content="could not sleep at all", embedding=[0.2, 0.8])
    hits = rank_journal_hits([1.0, 0.0], [close, other], match_count=2)
    heuristic = rerank_journal_hits(query, hits, DEFAULT_CONFIG, "heuristic")
    mmr = rerank_journal_hits(query, hits, MMR_CONFIG, "mmr")
    assert heuristic
    assert mmr
    assert {hit.id for hit in heuristic} == {"exam", "sleep"}
    assert {hit.id for hit in mmr} == {"exam", "sleep"}
