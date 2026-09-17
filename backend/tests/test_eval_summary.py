"""Offline tests for the eval cover sheet and generation-eval case picker."""

from __future__ import annotations

from eval.run_generation_eval import (
    _is_retryable,
    _judge_model_chain,
    _row_incomplete,
    _select_cases,
    _summarize,
)
from eval.write_eval_summary import render_stats, render_summary


def test_summary_falls_back_without_json():
    text = render_summary()
    assert "Hit@3" in text
    assert "MRR" in text
    assert "DeepEval" in text
    assert "manager" not in text.lower()
    assert "stakeholder" not in text.lower()
    assert "journal_eval.yaml" in text
    assert "mean reciprocal rank" in text
    assert "Maximal Marginal Relevance" in text
    assert "1/rank" in text
    stats = render_stats()
    assert "Hit@3" in stats or "Journal JSON missing" in stats
    assert "manager" not in stats.lower()


def test_summary_uses_ranked_metrics_and_ceiling_caveat():
    journal = {
        "source": "production",
        "user_id": "u",
        "entry_count": 112,
        "case_count": 30,
        "strategies": {
            "journal_mmr": {
                "summary": {"avg_entry_recall": 0.9, "avg_overall": 4.7},
                "ranked_metrics": {
                    "memory_quality": {
                        "n": 21,
                        "hit_at_1": 0.81,
                        "hit_at_3": 1.0,
                        "mrr": 0.88,
                    },
                    "by_kind": {
                        "callback": {"n": 15, "hit_at_1": 0.8, "hit_at_3": 1.0, "mrr": 0.9},
                        "paraphrase": {"n": 6, "hit_at_1": 0.83, "hit_at_3": 1.0, "mrr": 0.85},
                    },
                    "negatives": {"n": 5, "empty_retrieves": 0, "empty_rate": 0.0},
                    "mood_traps": {"n": 4},
                },
            }
        },
    }
    deepeval = {
        "judge_model": "gemini-2.0-flash",
        "case_count": 2,
        "summary": {
            "faithfulness": 0.9,
            "faithfulness_n": 2,
            "answer_relevancy": 0.8,
            "answer_relevancy_n": 2,
            "no_diagnosis": 1.0,
            "no_diagnosis_n": 2,
        },
    }
    text = render_summary(journal=journal, deepeval=deepeval)
    assert "100%" in text
    assert "near-ceiling" in text
    assert "0/5 empty" in text
    assert "Faithfulness" in text
    assert "0.90" in text
    assert "near-ceiling" in text
    assert "quota-limited smoke test" not in text
    assert "Sample size 2" in text
    stats = render_stats(journal=journal, deepeval=deepeval)
    assert "100%" in stats
    assert "Faithfulness" in stats
    assert "hand-labeled" not in stats


def test_summary_complete_deepeval_explains_faithfulness_vs_negatives():
    journal = {
        "user_id": "u",
        "entry_count": 112,
        "case_count": 30,
        "strategies": {
            "journal_mmr": {
                "ranked_metrics": {
                    "memory_quality": {
                        "n": 21,
                        "hit_at_1": 0.76,
                        "hit_at_3": 0.90,
                        "mrr": 0.83,
                    },
                    "negatives": {"n": 5, "empty_retrieves": 0, "empty_rate": 0.0},
                    "mood_traps": {"n": 4},
                },
            }
        },
    }
    deepeval = {
        "judge_model": "gemini-3.5-flash-lite",
        "case_count": 26,
        "summary": {
            "faithfulness": 1.0,
            "faithfulness_n": 26,
            "answer_relevancy": 1.0,
            "answer_relevancy_n": 26,
            "no_diagnosis": 0.1,
            "no_diagnosis_n": 26,
        },
    }
    text = render_summary(journal=journal, deepeval=deepeval)
    assert "10 of 26" not in text
    assert "10–11" not in text
    assert "manager" not in text.lower()
    assert "journal_eval.yaml" in text
    assert "not an LLM judge" in text
    assert "mean reciprocal rank" in text
    assert "26/26 on this quiz" in text
    assert "make the numbers more realistic" in text
    assert "Faithfulness 1.00" in text
    stats = render_stats(journal=journal, deepeval=deepeval)
    assert "26" in stats
    assert "1.00" in stats
    assert "hand-labeled" not in stats
    assert "manager" not in stats.lower()


def test_generation_eval_skips_negatives_and_mood_traps():
    cases = _select_cases(clinical_n=2, limit=0)
    kinds = {case.get("kind") for case in cases if case.get("eval_corpus") == "journal"}
    assert "negative" not in kinds
    assert "mood_trap" not in kinds
    assert "callback" in kinds
    assert "paraphrase" in kinds
    clinical = [case for case in cases if case.get("eval_corpus") == "clinical"]
    assert len(clinical) == 2
    assert all(case.get("expected_path") != "crisis" for case in cases)


def test_generation_eval_limit_caps_total():
    cases = _select_cases(clinical_n=5, limit=3)
    assert len(cases) == 3


def test_deepeval_summary_skips_null_faithfulness():
    rows = [
        {
            "metrics": {
                "faithfulness": {"score": None, "skipped": True},
                "answer_relevancy": {"score": 1.0, "skipped": False},
                "no_diagnosis": {"score": 1.0, "skipped": False},
            }
        },
        {
            "metrics": {
                "faithfulness": {"score": 0.5, "skipped": False},
                "answer_relevancy": {"score": 0.5, "skipped": False},
                "no_diagnosis": {"score": 1.0, "skipped": False},
            }
        },
    ]
    summary = _summarize(rows)
    assert summary["faithfulness"] == 0.5
    assert summary["faithfulness_n"] == 1
    assert summary["answer_relevancy"] == 0.75
    assert summary["no_diagnosis"] == 1.0


def test_judge_fallback_chain_dedupes_and_skips_empty():
    chain = _judge_model_chain("gemini-3.5-flash-lite")
    assert chain[0] == "gemini-3.5-flash-lite"
    assert "gemini-2.5-flash" not in chain
    assert "gemini-3.6-flash" not in chain
    assert _is_retryable(RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert _is_retryable(RuntimeError("404 NOT_FOUND"))
    assert _is_retryable(TimeoutError("Deadline timeout"))
    assert not _is_retryable(RuntimeError("invalid JSON"))


def test_row_incomplete_detects_skipped_metrics():
    complete = {
        "case_id": "a",
        "metrics": {
            "faithfulness": {"score": 1.0, "skipped": False},
            "answer_relevancy": {"score": 1.0, "skipped": False},
            "no_diagnosis": {"score": 0.1, "skipped": False},
        },
    }
    skipped = {
        "case_id": "b",
        "metrics": {
            "faithfulness": {"score": None, "skipped": True, "reason": "429"},
            "answer_relevancy": {"score": 1.0, "skipped": False},
            "no_diagnosis": {"score": 0.1, "skipped": False},
        },
    }
    empty_ok = {
        "case_id": "c",
        "metrics": {
            "faithfulness": {
                "score": None,
                "skipped": True,
                "reason": "skipped: no retrieval_context",
            },
            "answer_relevancy": {"score": 1.0, "skipped": False},
            "no_diagnosis": {"score": 1.0, "skipped": False},
        },
    }
    assert _row_incomplete(complete) is False
    assert _row_incomplete(skipped) is True
    assert _row_incomplete(empty_ok) is False
