"""Compare retrieval strategies on retrieval-positive golden cases only."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eval.load_golden import load_golden_cases
from rag.embed import clear_embed_cache
from rag.strategies import get_strategy, strategy_names


def retrieval_positive_cases(cases: list[dict]) -> list[dict]:
    """Cases the router is expected to send to the clinical KB."""
    return [case for case in cases if case.get("expected_path") == "search_database"]


@dataclass
class CaseResult:
    case_id: str
    case_type: str
    category_recall: float
    top1_similarity: float | None
    chunk_count: int
    categories: list[str | None] = field(default_factory=list)


@dataclass
class StrategySummary:
    strategy: str
    retrieval_cases: int
    avg_category_recall: float
    avg_top1_similarity: float | None
    empty_retrieves: int
    avg_latency_ms: float
    by_type: dict[str, dict[str, float]] = field(default_factory=dict)


def _category_recall(expected: list[str], retrieved_categories: list[str | None]) -> float:
    if not expected:
        return 1.0
    normalized = {cat for cat in retrieved_categories if cat}
    hits = sum(1 for cat in expected if cat in normalized)
    return hits / len(expected)


async def _eval_case(strategy, case: dict) -> tuple[CaseResult, float]:
    history = case.get("history", [])
    started = time.perf_counter()

    result = await strategy.retrieve(case["query"], history=history)
    elapsed_ms = (time.perf_counter() - started) * 1000

    chunks = result.chunks
    categories = [chunk.category for chunk in chunks[:5]]
    top1 = chunks[0].similarity if chunks else None

    case_result = CaseResult(
        case_id=case["id"],
        case_type=case.get("type", "unknown"),
        category_recall=_category_recall(case.get("expected_categories", []), categories)
        if chunks
        else 0.0,
        top1_similarity=top1,
        chunk_count=len(chunks),
        categories=categories,
    )
    return case_result, elapsed_ms


def _summarize(strategy_name: str, results: list[CaseResult], latencies: list[float]) -> StrategySummary:
    recall_scores = [r.category_recall for r in results if r.chunk_count > 0]
    sims = [r.top1_similarity for r in results if r.top1_similarity is not None]
    empty_ret = sum(1 for r in results if r.chunk_count == 0)

    by_type: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_type[r.case_type].append(r)

    type_stats: dict[str, dict[str, float]] = {}
    for case_type, typed in by_type.items():
        recalls = [r.category_recall for r in typed if r.chunk_count > 0]
        type_stats[case_type] = {
            "avg_category_recall": (sum(recalls) / len(recalls)) if recalls else 0.0,
            "count": float(len(typed)),
        }

    return StrategySummary(
        strategy=strategy_name,
        retrieval_cases=len(results),
        avg_category_recall=(sum(recall_scores) / len(recall_scores)) if recall_scores else 0.0,
        avg_top1_similarity=(sum(sims) / len(sims)) if sims else None,
        empty_retrieves=empty_ret,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
        by_type=type_stats,
    )


def _print_summary_table(summaries: list[StrategySummary]) -> None:
    headers = [
        "strategy",
        "cases",
        "cat_recall",
        "top1_sim",
        "empty_ret",
        "avg_ms",
    ]
    rows = []
    for s in summaries:
        rows.append(
            [
                s.strategy,
                str(s.retrieval_cases),
                f"{s.avg_category_recall:.2f}",
                f"{s.avg_top1_similarity:.3f}" if s.avg_top1_similarity is not None else "n/a",
                str(s.empty_retrieves),
                f"{s.avg_latency_ms:.0f}",
            ]
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _print_retrieval_failures(strategy_name: str, results: list[CaseResult], limit: int = 15) -> None:
    failures = [r for r in results if r.chunk_count == 0 or r.category_recall < 0.5]
    if not failures:
        print(f"\n{strategy_name}: no retrieval failures (recall < 0.5 or empty)")
        return
    print(f"\n{strategy_name}: {len(failures)} retrieval issues (showing up to {limit})")
    for r in failures[:limit]:
        print(
            f"  {r.case_id:<32} chunks={r.chunk_count} "
            f"recall={r.category_recall:.2f} cats={r.categories[:3]}"
        )


async def _run_compare(
    strategies: list[str],
    cases: list[dict],
) -> dict[str, dict]:
    strategy_objs = {name: get_strategy(name) for name in strategies}
    results_by_strategy: dict[str, list[CaseResult]] = {name: [] for name in strategies}
    latencies_by_strategy: dict[str, list[float]] = {name: [] for name in strategies}
    total = len(cases)

    for idx, case in enumerate(cases, start=1):
        print(f"  case {idx}/{total}: {case['id']}")
        for name in strategies:
            case_result, elapsed = await _eval_case(strategy_objs[name], case)
            results_by_strategy[name].append(case_result)
            latencies_by_strategy[name].append(elapsed)

    all_results: dict[str, dict] = {}
    for name in strategies:
        results = results_by_strategy[name]
        latencies = latencies_by_strategy[name]
        summary = _summarize(name, results, latencies)
        all_results[name] = {
            "summary": asdict(summary),
            "cases": [asdict(r) for r in results],
        }
        _print_retrieval_failures(name, results)

    return all_results


def _export_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote JSON results to {path}")


def _export_csv(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for strategy_name, data in payload["strategies"].items():
        for case in data["cases"]:
            rows.append(
                {
                    "strategy": strategy_name,
                    **case,
                    "categories": "|".join(c or "" for c in case.get("categories", [])),
                }
            )

    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote CSV results to {path}")


async def _main_async(args: argparse.Namespace) -> int:
    cases = retrieval_positive_cases(load_golden_cases())
    if args.limit:
        cases = cases[: args.limit]

    if not cases:
        print("No retrieval cases found. Run: python -m eval.generate_golden")
        return 1

    strategies = args.strategies or strategy_names()
    print(f"=== Strategy compare ({len(cases)} cases × {len(strategies)} strategies) ===")
    print(
        f"  Embeds: ~{len(cases)} unique queries (cached; free tier ~100/min, "
        f"expect ~{max(1, int(len(cases) * 0.7 / 60) + 1)} min)"
    )

    clear_embed_cache()
    results = await _run_compare(strategies, cases)

    summaries = [StrategySummary(**data["summary"]) for data in results.values()]
    print("\n=== Strategy comparison summary ===")
    _print_summary_table(summaries)

    print("\n=== By case type (avg category recall) ===")
    for name, data in results.items():
        print(f"\n{name}:")
        for case_type, stats in sorted(data["summary"]["by_type"].items()):
            print(
                f"  {case_type:<28} {stats['avg_category_recall']:.2f}  (n={int(stats['count'])})"
            )

    payload = {
        "retrieval_case_count": len(cases),
        "strategies": results,
    }

    if args.output:
        _export_json(args.output, payload)
    if args.csv:
        _export_csv(args.csv, payload)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare retrieval strategies on search_database cases"
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        help="Strategy names (default: all registered strategies)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit retrieval cases for smoke tests")
    parser.add_argument("--output", type=Path, help="Write full JSON results")
    parser.add_argument("--csv", type=Path, help="Write per-case CSV")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
