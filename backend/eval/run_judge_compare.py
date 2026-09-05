"""LLM-as-judge bake-off for clinical KB and in-memory journal retrieval.

Measure only — do not retune RAG_STRATEGY from this sample.

    python -m eval.run_judge_compare --sample 50
    python -m eval.run_judge_compare --corpus journal
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path

from eval.judge import (
    JudgeScore,
    pairwise_mmr_vs_baseline,
    score_retrieval,
    stratify_sample,
    summarize_scores,
    summary_asdict,
)
from eval.journal_retrieve import (
    describe_entries,
    embed_journal_entries,
    journal_label_recall,
    load_journal_entries,
    retrieve_journal,
)
from eval.load_golden import load_golden_cases, load_journal_eval_cases
from eval.retrieval_scoring import apply_split, apply_tag_filters, is_labeled, retrieval_positive_cases
from rag.embed import clear_embed_cache
from rag.strategies import get_strategy, strategy_names


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)] if rows else [len(h) for h in headers]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _export_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote JSON results to {path}")


def _select_clinical_cases(args: argparse.Namespace) -> list[dict]:
    cases = [
        case
        for case in retrieval_positive_cases(load_golden_cases())
        if is_labeled(case)
    ]
    cases = apply_split(cases, args.split)
    cases = apply_tag_filters(cases, tag=args.tag, exclude_tag=args.exclude_tag)
    cases = stratify_sample(cases, args.sample, seed=args.seed)
    if args.limit:
        cases = cases[: args.limit]
    return cases


async def _judge_clinical(
    strategies: list[str],
    cases: list[dict],
) -> tuple[dict[str, dict], dict[str, dict[str, JudgeScore]]]:
    strategy_objs = {name: get_strategy(name) for name in strategies}
    scores_by_case: dict[str, dict[str, JudgeScore]] = {}
    results: dict[str, dict] = {
        name: {"cases": [], "empty_retrieves": 0, "scores": []} for name in strategies
    }
    total = len(cases)

    for idx, case in enumerate(cases, start=1):
        print(f"  case {idx}/{total}: {case['id']}")
        scores_by_case[case["id"]] = {}
        history = case.get("history") or []
        for name in strategies:
            started = time.perf_counter()
            retrieved = await strategy_objs[name].retrieve(case["query"], history=history)
            elapsed_ms = (time.perf_counter() - started) * 1000
            chunks = retrieved.chunks
            if not chunks:
                results[name]["empty_retrieves"] += 1
            score = await asyncio.to_thread(
                score_retrieval,
                case["query"],
                chunks,
                history=history,
                corpus="clinical",
            )
            scores_by_case[case["id"]][name] = score
            results[name]["scores"].append(score)
            results[name]["cases"].append(
                {
                    "case_id": case["id"],
                    "chunk_count": len(chunks),
                    "latency_ms": elapsed_ms,
                    "judge": asdict(score),
                    "categories": [chunk.category for chunk in chunks[:3]],
                }
            )

    for name in strategies:
        summary = summarize_scores(
            name,
            results[name]["scores"],
            empty_retrieves=results[name]["empty_retrieves"],
        )
        results[name]["summary"] = summary_asdict(summary)
        del results[name]["scores"]
    return results, scores_by_case


async def _judge_journal(
    strategies: list[str],
    cases: list[dict],
    *,
    list_only: bool = False,
    user_id: str | None = None,
) -> tuple[dict[str, dict], dict[str, dict[str, JudgeScore]], list[dict]]:
    print("Loading journal_entries …")
    entries = await load_journal_entries(user_id=user_id)
    meta = describe_entries(entries)
    print(f"  {len(entries)} entries:")
    for item in meta:
        print(f"    {item['id']}  chars={item['char_len']}  created={item['created_at']}")
    if list_only:
        return {}, {}, meta
    if not entries:
        raise RuntimeError("No journal entries found")
    if not cases:
        raise RuntimeError("journal_eval.yaml has no cases")

    print("Embedding journal entries (in-process, not written back) …")
    await embed_journal_entries(entries)

    scores_by_case: dict[str, dict[str, JudgeScore]] = {}
    results: dict[str, dict] = {
        name: {
            "cases": [],
            "empty_retrieves": 0,
            "scores": [],
            "entry_recalls": [],
        }
        for name in strategies
    }
    total = len(cases)

    for idx, case in enumerate(cases, start=1):
        print(f"  case {idx}/{total}: {case['id']}")
        scores_by_case[case["id"]] = {}
        history = case.get("history") or []
        for name in strategies:
            started = time.perf_counter()
            retrieved, entry_ids = await retrieve_journal(
                case["query"],
                entries,
                strategy_name=name,
                history=history,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            chunks = retrieved.chunks
            if not chunks:
                results[name]["empty_retrieves"] += 1
            score = await asyncio.to_thread(
                score_retrieval,
                case["query"],
                chunks,
                history=history,
                corpus="journal",
            )
            recall = journal_label_recall(case, entry_ids, chunks, entries)
            scores_by_case[case["id"]][name] = score
            results[name]["scores"].append(score)
            results[name]["entry_recalls"].append(recall)
            results[name]["cases"].append(
                {
                    "case_id": case["id"],
                    "chunk_count": len(chunks),
                    "latency_ms": elapsed_ms,
                    "entry_ids": entry_ids,
                    "entry_recall": None if recall != recall else recall,
                    "judge": asdict(score),
                }
            )

    for name in strategies:
        summary = summarize_scores(
            name,
            results[name]["scores"],
            empty_retrieves=results[name]["empty_retrieves"],
            entry_recalls=results[name]["entry_recalls"],
        )
        results[name]["summary"] = summary_asdict(summary)
        del results[name]["scores"]
        del results[name]["entry_recalls"]
    return results, scores_by_case, meta


def _print_summaries(results: dict[str, dict], *, journal: bool) -> None:
    headers = [
        "strategy",
        "n",
        "overall",
        "useful",
        "on_topic",
        "grounded",
        "non_redun",
        "empty",
    ]
    if journal:
        headers.append("entry_rec")
    rows: list[list[str]] = []
    for name, data in results.items():
        summary = data["summary"]
        row = [
            name,
            str(summary["cases"]),
            f"{summary['avg_overall']:.2f}",
            f"{summary['avg_useful']:.2f}",
            f"{summary['avg_on_topic']:.2f}",
            f"{summary['avg_grounded']:.2f}",
            f"{summary['avg_non_redundant']:.2f}",
            str(summary["empty_retrieves"]),
        ]
        if journal:
            recall = summary.get("avg_entry_recall")
            row.append("n/a" if recall is None else f"{recall:.2f}")
        rows.append(row)
    print("\n=== Judge summary (measure only — do not retune RAG_STRATEGY) ===")
    _print_table(rows, headers)


def _print_pairwise(pair: dict[str, int]) -> None:
    print("\n=== Pairwise MMR vs baseline (overall score per case) ===")
    if pair["n"] == 0:
        print("  (need both mmr and baseline in --strategies)")
        return
    print(
        f"  mmr_wins={pair['mmr_wins']}  baseline_wins={pair['baseline_wins']}  "
        f"ties={pair['ties']}  n={pair['n']}"
    )


async def _main_async(args: argparse.Namespace) -> int:
    strategies = args.strategies or strategy_names()
    if args.corpus == "journal":
        cases = load_journal_eval_cases()
        if args.limit:
            cases = cases[: args.limit]
        print(
            f"=== Journal judge ({len(cases)} queries × {len(strategies)} strategies) ==="
        )
        results, scores_by_case, meta = await _judge_journal(
            strategies, cases, list_only=args.list_journal, user_id=args.user_id
        )
        if args.list_journal:
            payload = {"user_id": args.user_id, "entries": meta}
            if args.output:
                _export_json(args.output, payload)
            return 0
        _print_summaries(results, journal=True)
        pair = pairwise_mmr_vs_baseline(scores_by_case)
        _print_pairwise(pair)
        payload = {
            "corpus": "journal",
            "user_id": args.user_id,
            "entry_count": len(meta),
            "entries": meta,
            "case_count": len(cases),
            "pairwise_mmr_vs_baseline": pair,
            "strategies": results,
            "note": "In-memory journal eval. Tiny corpus: wide-then-narrow ≈ baseline. Measure only.",
        }
        if args.output:
            _export_json(args.output, payload)
        return 0

    cases = _select_clinical_cases(args)
    if not cases:
        print("No labeled clinical search cases for this split/sample.")
        return 1
    print(
        f"=== Clinical judge ({args.split}: {len(cases)} labeled cases "
        f"× {len(strategies)} strategies) ==="
    )
    print(
        f"  ~{len(cases)} embeds (cached across strategies) + "
        f"~{len(cases) * len(strategies)} judge calls. "
        "Uses AGENT_ROUTER_API_KEY when set."
    )
    clear_embed_cache()
    results, scores_by_case = await _judge_clinical(strategies, cases)
    _print_summaries(results, journal=False)
    pair = pairwise_mmr_vs_baseline(scores_by_case)
    _print_pairwise(pair)
    payload = {
        "corpus": "clinical",
        "split": args.split,
        "sample": args.sample,
        "seed": args.seed,
        "case_count": len(cases),
        "case_ids": [case["id"] for case in cases],
        "pairwise_mmr_vs_baseline": pair,
        "strategies": results,
        "note": "Measure only. Do not change RAG_STRATEGY from this sample.",
    }
    if args.output:
        _export_json(args.output, payload)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-as-judge comparison of retrieval strategies"
    )
    parser.add_argument(
        "--corpus",
        choices=("clinical", "journal"),
        default="clinical",
        help="clinical KB (default) or in-memory journal entries",
    )
    parser.add_argument(
        "--split",
        choices=("regression", "heldout", "all"),
        default="regression",
        help="clinical split (ignored for --corpus journal)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=50,
        help="Stratified labeled sample size (clinical). 0 = all cases in split",
    )
    parser.add_argument("--seed", default="copefy-judge", help="Sample RNG seed")
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
    parser.add_argument("--limit", type=int, default=0, help="Cap cases after sampling")
    parser.add_argument("--output", type=Path, help="Write full JSON results")
    parser.add_argument(
        "--list-journal",
        action="store_true",
        help="Print journal entry ids/dates/lengths and exit (no embeds, no judge)",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Journal user UUID (default: DEV_USER_ID, then fall back to the largest corpus)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
