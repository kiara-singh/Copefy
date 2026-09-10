"""Offline tests for the retrieval judge helpers."""

from __future__ import annotations

from eval.judge import (
    LAYER3_MISS_IDS,
    JudgeScore,
    EMPTY_SCORE,
    build_judge_prompt,
    parse_judge_payload,
    pairwise_mmr_vs_baseline,
    stratify_sample,
    summarize_scores,
)


class _Chunk:
    def __init__(self, content: str, title: str = "t", category: str = "anxiety") -> None:
        self.content = content
        self.title = title
        self.category = category


def test_parse_clamps_out_of_range_and_computes_overall():
    score = parse_judge_payload(
        {
            "useful": 9,
            "on_topic": 0,
            "grounded": "4",
            "non_redundant": 2,
            "rationale": "ok",
        }
    )
    assert score.useful == 5
    assert score.on_topic == 1
    assert score.grounded == 4
    assert score.non_redundant == 2
    assert score.overall == 3.0


def test_parse_defaults_bad_values():
    score = parse_judge_payload({"useful": "nope"})
    assert 1 <= score.useful <= 5
    assert score.rationale == ""


def test_empty_score_is_ones():
    assert EMPTY_SCORE.overall == 1.0
    assert EMPTY_SCORE.useful == 1


def test_prompt_is_blind_to_strategy_and_includes_query():
    prompt = build_judge_prompt(
        "I can't sleep",
        [_Chunk("breathing exercise", title="sleep", category="anxiety")],
        corpus="clinical",
    )
    assert "I can't sleep" in prompt
    assert "mmr" not in prompt.lower()
    assert "baseline" not in prompt.lower()
    assert "clinical knowledge base" in prompt.lower()


def test_pairwise_mmr_vs_baseline():
    mmr_better = JudgeScore(useful=5, on_topic=5, grounded=5, non_redundant=5)
    baseline = JudgeScore(useful=3, on_topic=3, grounded=3, non_redundant=3)
    tie = JudgeScore(useful=4, on_topic=4, grounded=4, non_redundant=4)
    pair = pairwise_mmr_vs_baseline(
        {
            "a": {"mmr": mmr_better, "baseline": baseline},
            "b": {"mmr": tie, "baseline": tie},
            "c": {"mmr": baseline, "baseline": mmr_better},
        }
    )
    assert pair == {"mmr_wins": 1, "baseline_wins": 1, "ties": 1, "n": 3}


def test_stratify_always_includes_known_misses():
    misses = [
        {
            "id": case_id,
            "expected_categories": ["anxiety"],
            "type": "symptom_sharing",
        }
        for case_id in sorted(LAYER3_MISS_IDS)
    ]
    extras = [
        {
            "id": f"extra_{i}",
            "expected_categories": ["adhd" if i % 2 else "depression"],
            "type": "coping_request" if i % 3 else "symptom_sharing",
        }
        for i in range(40)
    ]
    sampled = stratify_sample(misses + extras, n=20, seed="copefy-judge")
    sampled_ids = {case["id"] for case in sampled}
    assert LAYER3_MISS_IDS <= sampled_ids
    assert len(sampled) == 20


def test_summarize_scores_averages():
    scores = [
        JudgeScore(useful=5, on_topic=5, grounded=5, non_redundant=5),
        JudgeScore(useful=3, on_topic=3, grounded=3, non_redundant=3),
    ]
    summary = summarize_scores("mmr", scores, empty_retrieves=1)
    assert summary.strategy == "mmr"
    assert summary.cases == 2
    assert summary.empty_retrieves == 1
    assert summary.avg_overall == 4.0


def test_journal_eval_yaml_is_not_a_layer1_case_file():
    from eval.load_golden import load_golden_cases, load_journal_eval_cases

    golden_ids = {case["id"] for case in load_golden_cases()}
    journal_cases = load_journal_eval_cases()
    assert journal_cases
    assert all("query" in case for case in journal_cases)
    assert {case["id"] for case in journal_cases}.isdisjoint(golden_ids)
    kinds = {case.get("kind") for case in journal_cases}
    assert "callback" in kinds
    assert "negative" in kinds
    assert "mood_trap" in kinds
    assert any(case.get("expect_empty") for case in journal_cases)
    assert len(journal_cases) == 30
    from collections import Counter

    kinds = Counter(case.get("kind") for case in journal_cases)
    assert kinds["callback"] == 15
    assert kinds["paraphrase"] == 6
    assert kinds["negative"] == 5
    assert kinds["mood_trap"] == 4
