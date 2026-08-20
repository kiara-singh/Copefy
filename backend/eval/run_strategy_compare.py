"""Compare retrieval strategies on search_database golden cases.

Default split is regression (excludes heldout). Held-out is measure-only:

    python -m eval.run_strategy_compare
    python -m eval.run_strategy_compare --split heldout --no-gate
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from dataclasses import asdict
from pathlib import Path

from eval.load_golden import load_golden_cases
from eval.retrieval_scoring import (
    CaseResult,
    StrategySummary,
    apply_split,
    apply_tag_filters,
    gate_failures,
    pick_winner,
    retrieval_positive_cases,
    score_case,
    summarize,
)
from rag.embed import clear_embed_cache
from rag.strategies import get_strategy, strategy_names


async def _eval_case(strategy, case: dict) -> tuple[CaseResult, float]:
    history = case.get("history", [])
    started = time.perf_counter()
    result = await strategy.retrieve(case["query"], history=history)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return score_case(case, result.chunks), elapsed_ms


def _print_summary_table(summaries: list[StrategySummary]) -> None:
    headers = [
        "strategy",
        "labeled",
        "unlabeled",
        "cat_recall",
        "top1_sim",
        "empty_lab",
        "empty_all",
        "avg_ms",
    ]
    rows = []
    for summary in summaries:
        recall = (
            f"{summary.avg_category_recall:.2f}"
            if summary.avg_category_recall is not None
            else "n/a"
        )
        sim = (
            f"{summary.avg_top1_similarity:.3f}"
            if summary.avg_top1_similarity is not None
            else "n/a"
        )
        rows.append(
            [
                summary.strategy,
                str(summary.labeled_cases),
                str(summary.unlabeled_cases),
                recall,
                sim,
                str(summary.empty_labeled),
                str(summary.empty_retrieves),
                f"{summary.avg_latency_ms:.0f}",
            ]
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _print_retrieval_failures(strategy_name: str, results: list[CaseResult], limit: int = 15) -> None:
    failures = [
        r
        for r in results
        if r.labeled and (r.chunk_count == 0 or (r.category_recall or 0.0) < 0.5)
    ]
    if not failures:
        print(f"\n{strategy_name}: no labeled retrieval failures (recall < 0.5 or empty)")
        return
    print(f"\n{strategy_name}: {len(failures)} labeled retrieval issues (showing up to {limit})")
    for result in failures[:limit]:
        print(
            f"  {result.case_id:<32} chunks={result.chunk_count} "
            f"recall={result.category_recall:.2f} cats={result.categories[:3]}"
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
        summary = summarize(name, results, latencies)
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


def _select_cases(args: argparse.Namespace) -> list[dict]:
    cases = retrieval_positive_cases(load_golden_cases())
    cases = apply_split(cases, args.split)
    cases = apply_tag_filters(cases, tag=args.tag, exclude_tag=args.exclude_tag)
    if args.limit:
        cases = cases[: args.limit]
    return cases


async def _main_async(args: argparse.Namespace) -> int:
    cases = _select_cases(args)
    unlabeled = sum(1 for case in cases if not case.get("expected_categories"))
    labeled = len(cases) - unlabeled

    if not cases:
        print("No retrieval cases found for this split.")
        return 1

    strategies = args.strategies or strategy_names()
    print(
        f"=== Strategy compare ({args.split}: {len(cases)} search cases, "
        f"{labeled} labeled, {unlabeled} unlabeled × {len(strategies)} strategies) ==="
    )
    print(
        f"  Embeds: ~{len(cases)} unique queries (cached across strategies; "
        f"free tier ~100/min, expect ~{max(1, int(len(cases) * 0.7 / 60) + 1)} min)"
    )

    clear_embed_cache()
    results = await _run_compare(strategies, cases)

    summaries = [StrategySummary(**data["summary"]) for data in results.values()]
    print("\n=== Strategy comparison summary ===")
    _print_summary_table(summaries)

    print("\n=== By case type (avg category recall on labeled rows) ===")
    for name, data in results.items():
        print(f"\n{name}:")
        for case_type, stats in sorted(data["summary"]["by_type"].items()):
            print(
                f"  {case_type:<28} {stats['avg_category_recall']:.2f}  "
                f"(n={int(stats['count'])}, labeled={int(stats['labeled'])})"
            )

    winner = pick_winner(summaries)
    print("\n=== Recommended winner (regression rule) ===")
    print(
        f"  {winner.strategy}  "
        f"recall={winner.avg_category_recall if winner.avg_category_recall is not None else 'n/a'}  "
        f"empty_labeled={winner.empty_labeled}  "
        f"avg_ms={winner.avg_latency_ms:.0f}"
    )
    print("  Tie-break: highest labeled category recall, then fewer empties, then lower latency.")
    if args.split != "regression":
        print("  Note: do not change RAG_STRATEGY from a held-out or all-split run.")

    payload = {
        "split": args.split,
        "retrieval_case_count": len(cases),
        "labeled_case_count": labeled,
        "unlabeled_case_count": unlabeled,
        "recommended_winner": winner.strategy,
        "strategies": results,
    }

    if args.output:
        _export_json(args.output, payload)
    if args.csv:
        _export_csv(args.csv, payload)

    if args.no_gate or args.split == "heldout":
        return 0

    failures = gate_failures(summaries)
    if failures:
        print("\nGate FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare retrieval strategies on search_database cases"
    )
    parser.add_argument(
        "--split",
        choices=("regression", "heldout", "all"),
        default="regression",
        help="regression excludes heldout (default); heldout is measure-only",
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        help="Strategy names (default: all registered strategies)",
    )
    parser.add_argument("--tag", default=None, help="Only score cases with this tag")
    parser.add_argument(
        "--exclude-tag",
        default=None,
        help="Skip cases with this tag (applied after --split)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit retrieval cases for smoke tests")
    parser.add_argument("--output", type=Path, help="Write full JSON results")
    parser.add_argument("--csv", type=Path, help="Write per-case CSV")
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Do not fail on empty-retrieve cap (held-out is always ungated)",
    )
    args = parser.parse_args()

    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
