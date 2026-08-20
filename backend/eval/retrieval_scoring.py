"""Shared Layer 3 scoring: category recall, empty rate, winner pick.

Unlabeled search cases (empty expected_categories) must never count as
perfect recall. Empty retrieves on labeled cases count as 0.0 recall.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


def retrieval_positive_cases(cases: list[dict]) -> list[dict]:
    """Cases the router is expected to send to the clinical KB."""
    return [case for case in cases if case.get("expected_path") == "search_database"]


def apply_tag_filters(
    cases: list[dict],
    *,
    tag: str | None = None,
    exclude_tag: str | None = None,
) -> list[dict]:
    if tag:
        cases = [case for case in cases if tag in case.get("tags", [])]
    if exclude_tag:
        cases = [case for case in cases if exclude_tag not in case.get("tags", [])]
    return cases


def apply_split(cases: list[dict], split: str) -> list[dict]:
    """regression = exclude heldout; heldout = only that tag; all = no tag filter."""
    if split == "regression":
        return apply_tag_filters(cases, exclude_tag="heldout")
    if split == "heldout":
        return apply_tag_filters(cases, tag="heldout")
    if split == "all":
        return cases
    raise ValueError(f"Unknown split {split!r}")


def is_labeled(case: dict) -> bool:
    return bool(case.get("expected_categories"))


def category_recall(expected: list[str], retrieved_categories: list[str | None]) -> float:
    if not expected:
        return float("nan")
    normalized = {cat for cat in retrieved_categories if cat}
    hits = sum(1 for cat in expected if cat in normalized)
    return hits / len(expected)


@dataclass
class CaseResult:
    case_id: str
    case_type: str
    labeled: bool
    category_recall: float | None
    top1_similarity: float | None
    chunk_count: int
    categories: list[str | None] = field(default_factory=list)


@dataclass
class StrategySummary:
    strategy: str
    retrieval_cases: int
    labeled_cases: int
    unlabeled_cases: int
    avg_category_recall: float | None
    avg_top1_similarity: float | None
    empty_retrieves: int
    empty_labeled: int
    avg_latency_ms: float
    by_type: dict[str, dict[str, float]] = field(default_factory=dict)


def score_case(
    case: dict,
    chunks: list,
    *,
    recall_at: int = 5,
) -> CaseResult:
    labeled = is_labeled(case)
    categories = [chunk.category for chunk in chunks[:recall_at]]
    top1 = chunks[0].similarity if chunks else None
    expected = case.get("expected_categories") or []

    if not labeled:
        recall: float | None = None
    elif not chunks:
        recall = 0.0
    else:
        recall = category_recall(expected, categories)

    return CaseResult(
        case_id=case["id"],
        case_type=case.get("type", "unknown"),
        labeled=labeled,
        category_recall=recall,
        top1_similarity=top1,
        chunk_count=len(chunks),
        categories=categories,
    )


def summarize(
    strategy_name: str,
    results: list[CaseResult],
    latencies: list[float],
) -> StrategySummary:
    labeled = [r for r in results if r.labeled]
    unlabeled = [r for r in results if not r.labeled]
    recalls = [r.category_recall for r in labeled if r.category_recall is not None]
    sims = [r.top1_similarity for r in results if r.top1_similarity is not None]
    empty_ret = sum(1 for r in results if r.chunk_count == 0)
    empty_labeled = sum(1 for r in labeled if r.chunk_count == 0)

    by_type: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        by_type[result.case_type].append(result)

    type_stats: dict[str, dict[str, float]] = {}
    for case_type, typed in by_type.items():
        typed_labeled = [r for r in typed if r.labeled and r.category_recall is not None]
        type_stats[case_type] = {
            "avg_category_recall": (
                (sum(r.category_recall or 0.0 for r in typed_labeled) / len(typed_labeled))
                if typed_labeled
                else 0.0
            ),
            "count": float(len(typed)),
            "labeled": float(len(typed_labeled)),
        }

    return StrategySummary(
        strategy=strategy_name,
        retrieval_cases=len(results),
        labeled_cases=len(labeled),
        unlabeled_cases=len(unlabeled),
        avg_category_recall=(sum(recalls) / len(recalls)) if recalls else None,
        avg_top1_similarity=(sum(sims) / len(sims)) if sims else None,
        empty_retrieves=empty_ret,
        empty_labeled=empty_labeled,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
        by_type=type_stats,
    )


def pick_winner(summaries: list[StrategySummary]) -> StrategySummary:
    """Highest labeled recall, then fewer labeled empties, then faster."""

    def sort_key(summary: StrategySummary) -> tuple:
        recall = summary.avg_category_recall
        recall_rank = -recall if recall is not None else 0.0
        return (recall_rank, summary.empty_labeled, summary.avg_latency_ms)

    return sorted(summaries, key=sort_key)[0]


# Regression gate: even the best strategy emptying this often means the KB/eval
# path is broken, not that one strategy lost.
MAX_EMPTY_LABELED_RATE = 0.25


def gate_failures(summaries: list[StrategySummary]) -> list[str]:
    if not summaries:
        return ["no strategy summaries"]
    labeled = summaries[0].labeled_cases
    if labeled == 0:
        return ["no labeled search_database cases in this split"]
    best = pick_winner(summaries)
    empty_rate = best.empty_labeled / labeled
    if empty_rate > MAX_EMPTY_LABELED_RATE:
        return [
            f"{best.strategy} empty on {best.empty_labeled}/{labeled} labeled cases "
            f"({empty_rate:.0%} > {MAX_EMPTY_LABELED_RATE:.0%} cap)"
        ]
    return []
