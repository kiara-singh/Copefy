"""Tests for Layer 3 scoring helpers."""

from __future__ import annotations

from eval.retrieval_scoring import (
    StrategySummary,
    apply_split,
    category_recall,
    gate_failures,
    is_labeled,
    pick_winner,
    retrieval_positive_cases,
    score_case,
)


class _Chunk:
    def __init__(self, category: str | None, similarity: float = 0.8) -> None:
        self.category = category
        self.similarity = similarity


def test_empty_expected_categories_is_unlabeled_not_perfect():
    case = {
        "id": "x",
        "type": "symptom_sharing",
        "expected_path": "search_database",
        "expected_categories": [],
    }
    assert not is_labeled(case)
    scored = score_case(case, [_Chunk("anxiety")])
    assert scored.category_recall is None


def test_empty_retrieve_on_labeled_case_is_zero_recall():
    case = {
        "id": "y",
        "type": "symptom_sharing",
        "expected_categories": ["anxiety"],
    }
    scored = score_case(case, [])
    assert scored.labeled
    assert scored.category_recall == 0.0


def test_category_recall_partial():
    assert category_recall(["anxiety", "ocd"], ["anxiety", "adhd"]) == 0.5


def test_split_excludes_heldout():
    cases = [
        {"id": "a", "expected_path": "search_database", "tags": []},
        {"id": "b", "expected_path": "search_database", "tags": ["heldout"]},
        {"id": "c", "expected_path": "direct_answer", "tags": []},
    ]
    search = retrieval_positive_cases(cases)
    regression = apply_split(search, "regression")
    heldout = apply_split(search, "heldout")
    assert [c["id"] for c in regression] == ["a"]
    assert [c["id"] for c in heldout] == ["b"]


def test_pick_winner_recall_then_empty_then_latency():
    low_recall = StrategySummary(
        strategy="a",
        retrieval_cases=10,
        labeled_cases=10,
        unlabeled_cases=0,
        avg_category_recall=0.70,
        avg_top1_similarity=0.8,
        empty_retrieves=0,
        empty_labeled=0,
        avg_latency_ms=10,
    )
    high_recall_slow = StrategySummary(
        strategy="b",
        retrieval_cases=10,
        labeled_cases=10,
        unlabeled_cases=0,
        avg_category_recall=0.90,
        avg_top1_similarity=0.8,
        empty_retrieves=0,
        empty_labeled=0,
        avg_latency_ms=200,
    )
    assert pick_winner([low_recall, high_recall_slow]).strategy == "b"


def test_gate_fails_when_best_is_mostly_empty():
    summary = StrategySummary(
        strategy="baseline",
        retrieval_cases=10,
        labeled_cases=10,
        unlabeled_cases=0,
        avg_category_recall=0.5,
        avg_top1_similarity=0.7,
        empty_retrieves=8,
        empty_labeled=8,
        avg_latency_ms=50,
    )
    assert gate_failures([summary])
