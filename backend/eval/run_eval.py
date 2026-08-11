"""Evaluate retrieval quality on golden cases labeled expected_path: search_database."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from eval.load_golden import load_golden_cases
from eval.run_strategy_compare import retrieval_positive_cases
from rag.retrieve import _detect_categories, retrieve_with_strategy


def _category_recall(expected: list[str], retrieved_categories: list[str | None]) -> float:
    if not expected:
        return 1.0
    normalized = {cat for cat in retrieved_categories if cat}
    hits = sum(1 for cat in expected if cat in normalized)
    return hits / len(expected)


async def _run(path: Path | None, limit: int | None) -> int:
    if path is not None:
        import yaml

        with path.open(encoding="utf-8") as handle:
            questions = yaml.safe_load(handle) or []
    else:
        questions = retrieval_positive_cases(load_golden_cases())
    if limit:
        questions = questions[:limit]
    if not questions:
        print("No retrieval-positive questions found.")
        return 1

    category_scores: list[float] = []
    empty_count = 0

    print(f"{'id':<28} {'chunks':<8} {'cats@5':<8} detected")
    print("-" * 70)

    for item in questions:
        history = item.get("history", [])
        _, chunks = await retrieve_with_strategy(item["query"], history=history)
        categories = [chunk.category for chunk in chunks[:5]]
        recall = _category_recall(item.get("expected_categories", []), categories)
        if chunks:
            category_scores.append(recall)
        else:
            empty_count += 1

        detected = _detect_categories(item["query"])
        print(
            f"{item['id']:<28} "
            f"{len(chunks):<8} "
            f"{recall:<8.2f} "
            f"{detected}"
        )

    n = len(questions)
    print("-" * 70)
    print(f"Retrieval cases: {n}")
    print(f"Empty retrieves: {empty_count}")
    if category_scores:
        avg = sum(category_scores) / len(category_scores)
        print(f"Average category recall@5: {avg:.2f}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate KB retrieval on retrieval-positive golden cases")
    parser.add_argument(
        "--questions",
        type=Path,
        default=None,
        help="Optional single YAML file (default: eval/golden/*.yaml)",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    limit = args.limit or None
    raise SystemExit(asyncio.run(_run(args.questions, limit)))


if __name__ == "__main__":
    main()
