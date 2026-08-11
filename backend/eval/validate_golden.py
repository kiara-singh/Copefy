"""Validate golden eval suite: schema, duplicates, minimum size, label balance."""

from __future__ import annotations

import argparse
from collections import Counter

from eval.load_golden import load_golden_cases

REQUIRED_FIELDS = ("id", "query", "type", "expected_path")

PATHS = (
    "crisis",
    "direct_answer",
    "search_database",
    "web_search",
    "structured_query",
    "document_extraction",
)

CORPORA = ("clinical", "journal", "both")

MIN_CASES = 500

# Paths we can meaningfully score today. Journal-only corpus cases are not
# authored yet, so no minimum is enforced for expected_corpus.
MIN_PER_PATH = {
    "crisis": 40,
    "direct_answer": 50,
    "search_database": 150,
    "web_search": 20,
    "structured_query": 15,
    "document_extraction": 15,
}

# Negative cases matter as much as positive ones: without them a path can score
# perfect recall purely by over-firing.
MIN_TRAPS_BY_TAG = {
    "web_trap": 30,
    "crisis_trap": 25,
    "tool_trap": 12,
}


def validate_cases(cases: list[dict], *, min_cases: int = MIN_CASES) -> list[str]:
    errors: list[str] = []
    ids: list[str] = []

    for idx, case in enumerate(cases):
        label = case.get("id", f"#{idx}")

        for field in REQUIRED_FIELDS:
            if field not in case:
                errors.append(f"Case {label} missing field {field!r}")

        path = case.get("expected_path")
        if path is not None and path not in PATHS:
            errors.append(f"Case {label}: unknown expected_path {path!r}")

        corpus = case.get("expected_corpus")
        if corpus is not None:
            if corpus not in CORPORA:
                errors.append(f"Case {label}: unknown expected_corpus {corpus!r}")
            if path != "search_database":
                errors.append(
                    f"Case {label}: expected_corpus set but expected_path is {path!r}"
                )
        elif path == "search_database":
            errors.append(f"Case {label}: search_database case needs expected_corpus")

        if case.get("expected_categories") and path != "search_database":
            errors.append(
                f"Case {label}: expected_categories only apply to search_database cases"
            )

        for field in ("expected_categories", "history", "tags"):
            if field in case and not isinstance(case[field], list):
                errors.append(f"Case {label}: {field} must be a list")

        if "id" in case:
            ids.append(case["id"])

    dupes = [item for item, count in Counter(ids).items() if count > 1]
    if dupes:
        errors.append(f"Duplicate IDs: {', '.join(sorted(dupes))}")

    # Same query under different history is a distinct case, so key on both.
    seen_queries = Counter(
        (
            case.get("query", "").strip().lower(),
            tuple(entry.get("content", "") for entry in case.get("history", [])),
        )
        for case in cases
    )
    dupe_queries = [query for (query, _), count in seen_queries.items() if query and count > 1]
    if dupe_queries:
        errors.append(f"Duplicate queries: {len(dupe_queries)} (e.g. {dupe_queries[0]!r})")

    if len(cases) < min_cases:
        errors.append(f"Only {len(cases)} cases; need at least {min_cases}")

    by_path = Counter(case.get("expected_path") for case in cases)
    for path, minimum in MIN_PER_PATH.items():
        if by_path.get(path, 0) < minimum:
            errors.append(
                f"Only {by_path.get(path, 0)} {path} cases; need at least {minimum}"
            )

    for tag, minimum in MIN_TRAPS_BY_TAG.items():
        found = sum(1 for case in cases if tag in case.get("tags", []))
        if found < minimum:
            errors.append(f"Only {found} {tag} cases; need at least {minimum}")

    return errors


def print_balance_report(cases: list[dict]) -> None:
    by_type = Counter(case.get("type", "unknown") for case in cases)
    by_path = Counter(case.get("expected_path", "unknown") for case in cases)
    by_tag = Counter(tag for case in cases for tag in case.get("tags", []))

    print("\nLabel balance:")
    print(f"  Total cases: {len(cases)}")

    print("\nBy expected_path:")
    for path, count in by_path.most_common():
        print(f"  {path:<24} {count}")

    print("\nBy type:")
    for case_type, count in sorted(by_type.items()):
        print(f"  {case_type:<24} {count}")

    if by_tag:
        print("\nBy tag:")
        for tag, count in by_tag.most_common():
            print(f"  {tag:<24} {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate golden eval suite")
    parser.add_argument("--min-cases", type=int, default=MIN_CASES)
    args = parser.parse_args()

    cases = load_golden_cases()
    errors = validate_cases(cases, min_cases=args.min_cases)

    if errors:
        print("Validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        raise SystemExit(1)

    print(f"Validation OK — {len(cases)} cases")
    print_balance_report(cases)


if __name__ == "__main__":
    main()
