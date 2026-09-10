"""LLM-as-judge bake-off for clinical KB and live journal search.

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
    JOURNAL_EVAL_USER_ID,
    JOURNAL_STRATEGY_SPECS,
    PROD_JOURNAL_STRATEGIES,
    count_journal_chunks,
    describe_entries,
    embed_journal_entries,
    journal_embedding_distinct_count,
    journal_label_recall,
    load_journal_entries,
    retrieve_journal,
    retrieve_production_journal,
    snippets_for_journal_recall,
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


def _journal_score(
    case: dict,
    chunks: list,
    journal_chunks: list,
    *,
    skip_judge: bool,
    history: list[dict[str, str]],
    corpus: str,
) -> JudgeScore:
    if case.get("expect_empty"):
        if not journal_chunks:
            return JudgeScore(
                useful=5,
                on_topic=5,
                grounded=5,
                non_redundant=5,
                rationale="correct empty journal retrieve",
            )
        return JudgeScore(
            useful=1,
            on_topic=1,
            grounded=1,
            non_redundant=1,
            rationale="retrieved a journal when the query has no matching entry",
        )
    if skip_judge:
        return JudgeScore(
            useful=0,
            on_topic=0,
            grounded=0,
            non_redundant=0,
            rationale="judge skipped",
        )
    return score_retrieval(case["query"], chunks, history=history, corpus=corpus)


async def _judge_journal(
    strategies: list[str],
    cases: list[dict],
    *,
    list_only: bool = False,
    user_id: str | None = None,
    skip_judge: bool = False,
    source: str = "production",
) -> tuple[dict[str, dict], dict[str, dict[str, JudgeScore]], list[dict], dict]:
    resolved_user = user_id or JOURNAL_EVAL_USER_ID
    print("Loading journal_entries …")
    entries = await load_journal_entries(user_id=resolved_user)
    meta = describe_entries(entries)
    chunk_count = await count_journal_chunks(resolved_user)
    print(
        f"  user={resolved_user}  entries={len(entries)}  journal_chunks={chunk_count}"
    )
    if list_only:
        for item in meta:
            print(
                f"    {item['id']}  chars={item['char_len']}  created={item['created_at']}"
            )
        return {}, {}, meta, {"user_id": resolved_user, "chunk_count": chunk_count}
    if not entries:
        raise RuntimeError(f"No journal_entries for user {resolved_user}")
    if not cases:
        raise RuntimeError("journal_eval.yaml has no cases")
    if source == "production" and chunk_count == 0:
        raise RuntimeError(
            f"No journal_chunks for user {resolved_user}. "
            "Ingest journals into journal_chunks before scoring production search."
        )
    if source == "production":
        distinct = await journal_embedding_distinct_count(resolved_user)
        print(f"  distinct embeddings={distinct}")
        if chunk_count > 1 and distinct <= 1:
            raise RuntimeError(
                "journal_chunks embeddings are identical (placeholder [0.01] vectors). "
                "Re-run from backend/: python scripts/reingest_journal_embeddings.py "
                f"--user-id {resolved_user}"
            )

    if source == "inmemory":
        print("Embedding journal entries (in-process, not written back) …")
        await embed_journal_entries(entries)
    else:
        print("Using production search_journal_chunks (stored embeddings, MMR).")

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
        print(f"  case {idx}/{total}: {case['id']}", flush=True)
        scores_by_case[case["id"]] = {}
        history = case.get("history") or []
        for name in strategies:
            started = time.perf_counter()
            if source == "production":
                chunks, entry_ids = await retrieve_production_journal(
                    resolved_user,
                    case["query"],
                    strategy_name=name,
                    history=history,
                )
            else:
                retrieved, entry_ids = await retrieve_journal(
                    case["query"],
                    entries,
                    strategy_name=name,
                    history=history,
                )
                chunks = retrieved.chunks
            elapsed_ms = (time.perf_counter() - started) * 1000
            journal_chunks = snippets_for_journal_recall(chunks)
            if not journal_chunks:
                results[name]["empty_retrieves"] += 1
            judge_corpus = "both" if name == "both" else "journal"
            if skip_judge or case.get("expect_empty"):
                score = _journal_score(
                    case,
                    chunks,
                    journal_chunks,
                    skip_judge=skip_judge,
                    history=history,
                    corpus=judge_corpus,
                )
            else:
                score = await asyncio.to_thread(
                    _journal_score,
                    case,
                    chunks,
                    journal_chunks,
                    skip_judge=False,
                    history=history,
                    corpus=judge_corpus,
                )
            recall = journal_label_recall(case, entry_ids, chunks, entries)
            scores_by_case[case["id"]][name] = score
            results[name]["scores"].append(score)
            results[name]["entry_recalls"].append(recall)
            results[name]["cases"].append(
                {
                    "case_id": case["id"],
                    "chunk_count": len(chunks),
                    "journal_chunk_count": len(journal_chunks),
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
    return results, scores_by_case, meta, {
        "user_id": resolved_user,
        "chunk_count": chunk_count,
        "source": source,
    }


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
    if args.corpus == "journal":
        if args.source == "production":
            strategies = args.strategies or ["journal_mmr"]
            unknown = [name for name in strategies if name not in PROD_JOURNAL_STRATEGIES]
            if unknown:
                raise SystemExit(
                    f"Unknown production journal strategy {unknown}. "
                    f"Use: {', '.join(PROD_JOURNAL_STRATEGIES)}"
                )
        else:
            strategies = args.strategies or list(JOURNAL_STRATEGY_SPECS)
        cases = load_journal_eval_cases()
        if args.limit:
            cases = cases[: args.limit]
        print(
            f"=== Journal judge ({len(cases)} queries × {len(strategies)} strategies, "
            f"source={args.source}) ==="
        )
        results, scores_by_case, meta, info = await _judge_journal(
            strategies,
            cases,
            list_only=args.list_journal,
            user_id=args.user_id or JOURNAL_EVAL_USER_ID,
            skip_judge=args.skip_judge,
            source=args.source,
        )
        if args.list_journal:
            payload = {
                "user_id": info["user_id"],
                "chunk_count": info["chunk_count"],
                "entries": meta,
            }
            if args.output:
                _export_json(args.output, payload)
            return 0
        _print_summaries(results, journal=True)
        pair = pairwise_mmr_vs_baseline(scores_by_case)
        if "mmr" in results and "baseline" in results:
            _print_pairwise(pair)
        payload = {
            "corpus": "journal",
            "source": info["source"],
            "user_id": info["user_id"],
            "entry_count": len(meta),
            "chunk_count": info["chunk_count"],
            "case_count": len(cases),
            "skip_judge": args.skip_judge,
            "strategies": results,
            "note": (
                "Production journal search (search_journal_chunks). "
                "Gold is expected_contains on journal snippets. "
                "Do not retune clinical RAG_STRATEGY from this."
                if info["source"] == "production"
                else "In-memory journal eval. Measure only. Do not retune RAG_STRATEGY."
            ),
        }
        if args.output:
            _export_json(args.output, payload)
        return 0

    strategies = args.strategies or strategy_names()
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
        help="clinical KB (default) or live journal search",
    )
    parser.add_argument(
        "--source",
        choices=("production", "inmemory"),
        default="production",
        help="journal: production search_journal_chunks (default) or in-memory bake-off",
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
        help="Strategy names. Journal production default: journal_mmr. "
        "Also: both (journal + clinical, same as chat). "
        "In-memory: baseline threshold_0.65 mmr wide_then_narrow.",
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
        "--skip-judge",
        action="store_true",
        help="Score journal entry recall only; skip LLM-as-judge API calls",
    )
    parser.add_argument(
        "--list-journal",
        action="store_true",
        help="Print journal entry ids/dates/lengths and exit (no embeds, no judge)",
    )
    parser.add_argument(
        "--user-id",
        default=JOURNAL_EVAL_USER_ID,
        help="Journal user UUID (default: live seed corpus in journal_eval.yaml)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
