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


def test_expect_empty_recall():
    chunk = type("C", (), {"content": "organic chemistry exam"})()
    empty_case = {"expect_empty": True}
    assert journal_label_recall(empty_case, [], [], []) == 1.0
    assert journal_label_recall(empty_case, ["exam"], [chunk], []) == 0.0


def test_expect_empty_ignores_clinical_mixins():
    from eval.journal_retrieve import snippets_for_journal_recall

    clinical = type("C", (), {"content": "anxiety psychoeducation", "category": "anxiety"})()
    journal = type(
        "J",
        (),
        {"content": "homemade cookies", "category": "journal", "document_id": "abc"},
    )()
    empty_case = {"expect_empty": True}
    assert snippets_for_journal_recall([clinical]) == []
    assert journal_label_recall(empty_case, [], [clinical], []) == 1.0
    assert journal_label_recall(empty_case, ["abc"], [clinical, journal], []) == 0.0
    labeled = {"expected_contains": ["homemade cookies"]}
    assert journal_label_recall(labeled, ["abc"], [clinical, journal], []) == 1.0
    assert journal_label_recall(labeled, [], [clinical], []) == 0.0


def test_content_hash_is_stable():
    from eval.journal_retrieve import _content_hash

    assert _content_hash("hello") == _content_hash("hello")
    assert _content_hash("hello") != _content_hash("hello ")


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


def _chunk(content: str, document_id: str = "", category: str = "journal"):
    return type("C", (), {"content": content, "document_id": document_id, "category": category, "id": document_id})()


def test_hit_at_k_and_mrr_on_fake_ranks():
    from eval.journal_retrieve import hit_at_k, reciprocal_rank

    assert hit_at_k(1, 1) == 1.0
    assert hit_at_k(2, 1) == 0.0
    assert hit_at_k(2, 3) == 1.0
    assert hit_at_k(None, 3) == 0.0
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(2) == 0.5
    assert reciprocal_rank(3) == 1.0 / 3
    assert reciprocal_rank(None) == 0.0


def test_gold_rank_uses_ranked_id_list():
    from eval.journal_retrieve import gold_rank, ranked_case_metrics

    gold = _chunk("lost my student ID in my jacket pocket", "gold")
    other = _chunk("ate lunch in the dining hall", "other")
    case = {
        "kind": "callback",
        "expected_contains": ["jacket pocket"],
        "expected_entry_ids": ["gold"],
    }
    assert gold_rank(case, [gold, other]) == 1
    assert gold_rank(case, [other, gold]) == 2
    assert gold_rank(case, [other]) is None
    ranked = ranked_case_metrics(case, [other, gold])
    assert ranked["hit_at_1"] == 0.0
    assert ranked["hit_at_3"] == 1.0
    assert ranked["reciprocal_rank"] == 0.5


def test_gold_rank_skips_negatives_and_mood_traps():
    from eval.journal_retrieve import gold_rank, ranked_case_metrics, summarize_ranked_metrics

    junk = _chunk("homemade cookies", "x")
    negative = {"kind": "negative", "expect_empty": True}
    mood = {"kind": "mood_trap"}
    assert gold_rank(negative, [junk]) is None
    assert gold_rank(mood, [junk]) is None
    neg_row = {"case_id": "n", **ranked_case_metrics(negative, [junk])}
    mood_row = {"case_id": "m", **ranked_case_metrics(mood, [])}
    hit_row = {
        "case_id": "c",
        **ranked_case_metrics(
            {"kind": "callback", "expected_contains": ["jacket pocket"]},
            [_chunk("jacket pocket", "gold")],
        ),
    }
    paraphrase = {
        "case_id": "p",
        **ranked_case_metrics(
            {"kind": "paraphrase", "expected_contains": ["freeze"]},
            [_chunk("I freeze during exams", "p1"), _chunk("other", "p2")],
        ),
    }
    summary = summarize_ranked_metrics([hit_row, paraphrase, neg_row, mood_row])
    assert summary["memory_quality"]["n"] == 2
    assert summary["memory_quality"]["hit_at_1"] == 1.0
    assert summary["memory_quality"]["mrr"] == 1.0
    assert summary["negatives"]["empty_retrieves"] == 0
    assert summary["negatives"]["n"] == 1
    assert summary["mood_traps"]["n"] == 1
    assert summary["by_kind"]["mood_trap"]["n"] == 1
    assert "hit_at_1" not in summary["by_kind"]["mood_trap"]


def test_headline_hit_k_excludes_negatives():
    from eval.journal_retrieve import ranked_case_metrics, summarize_ranked_metrics

    miss = ranked_case_metrics(
        {"kind": "callback", "expected_contains": ["Victorian"]},
        [_chunk("organic chemistry", "wrong")],
    )
    empty_neg = ranked_case_metrics({"kind": "negative", "expect_empty": True}, [])
    summary = summarize_ranked_metrics(
        [{"case_id": "miss", **miss}, {"case_id": "neg", **empty_neg}]
    )
    assert summary["memory_quality"]["hit_at_3"] == 0.0
    assert summary["negatives"]["empty_rate"] == 1.0
