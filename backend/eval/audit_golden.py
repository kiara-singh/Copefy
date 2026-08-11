"""Quality audit of the golden suite — the things schema validation cannot catch.

validate_golden.py proves the labels are well-formed. This asks whether they are
any good: near-duplicates, trivially-easy cases, and lopsided sources of signal.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from eval.load_golden import GOLDEN_DIR, _load_yaml_list, case_files, load_golden_cases

# Words that give the path away on their own. A case built around one of these
# tests string matching, not judgement.
GIVEAWAY_TERMS = {
    "web_search": ("look up", "search online", "google", "find me", "can you find"),
    "structured_query": ("my average", "how many", "show me my", "my profile", "my streak"),
    "document_extraction": ("uploaded", "attached", "i sent", "i shared", "the pdf"),
    "crisis": ("kill", "suicide", "suicidal", "end my life", "want to die", "self-harm"),
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def source_breakdown(cases: list[dict]) -> None:
    print("=== Where the cases come from ===")
    for path in case_files():
        file_cases = _load_yaml_list(path)
        by_path = Counter(c.get("expected_path") for c in file_cases)
        spread = ", ".join(f"{p}:{n}" for p, n in by_path.most_common())
        print(f"  {path.name:<18} {len(file_cases):>4}  ({spread})")

    generated = sum(1 for c in cases if str(c.get("id", "")).startswith("gen_"))
    print(f"\n  Template-generated: {generated}/{len(cases)} "
          f"({generated / len(cases):.0%} of the suite)")


def near_duplicates(cases: list[dict], threshold: float = 0.8) -> None:
    """Cases that differ by a word or two still only test one thing."""
    print("\n=== Near-duplicate queries (Jaccard >= 0.8) ===")
    groups: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        groups[case.get("expected_path", "?")].append(case)

    total = 0
    for path, group in groups.items():
        pairs = 0
        example = None
        for i, a in enumerate(group):
            ta = _tokens(a["query"])
            for b in group[i + 1 :]:
                tb = _tokens(b["query"])
                union = ta | tb
                if not union:
                    continue
                if len(ta & tb) / len(union) >= threshold:
                    pairs += 1
                    if example is None:
                        example = (a["id"], b["id"])
        total += pairs
        if pairs:
            print(f"  {path:<22} {pairs:>4} pairs   e.g. {example[0]} ~ {example[1]}")
    if not total:
        print("  none")
    print(f"  total near-duplicate pairs: {total}")


def giveaway_cases(cases: list[dict]) -> None:
    """How many tool cases are solvable by spotting one phrase?"""
    print("\n=== Cases solvable by a single giveaway phrase ===")
    for path, terms in GIVEAWAY_TERMS.items():
        group = [c for c in cases if c.get("expected_path") == path]
        if not group:
            continue
        easy = [c for c in group if any(t in _norm(c["query"]) for t in terms)]
        hard = [c for c in group if c not in easy]
        print(f"  {path:<22} {len(easy):>3}/{len(group)} easy, {len(hard)} require judgement")
        for case in hard[:4]:
            print(f"      hard: {case['id']} — {case['query'][:64]}")


def length_profile(cases: list[dict]) -> None:
    print("\n=== Query length by path (words) ===")
    by_path: dict[str, list[int]] = defaultdict(list)
    for case in cases:
        by_path[case.get("expected_path", "?")].append(len(case["query"].split()))
    for path, lengths in sorted(by_path.items()):
        lengths.sort()
        median = lengths[len(lengths) // 2]
        print(f"  {path:<22} min {lengths[0]:>2}  median {median:>2}  max {lengths[-1]:>3}")


def history_coverage(cases: list[dict]) -> None:
    with_history = [c for c in cases if c.get("history")]
    print(f"\n=== Multi-turn coverage ===")
    print(f"  {len(with_history)}/{len(cases)} cases carry conversation history")
    by_path = Counter(c.get("expected_path") for c in with_history)
    for path, count in by_path.most_common():
        print(f"    {path:<22} {count}")


def main() -> None:
    cases = load_golden_cases()
    print(f"Auditing {len(cases)} cases\n")
    source_breakdown(cases)
    near_duplicates(cases)
    giveaway_cases(cases)
    length_profile(cases)
    history_coverage(cases)


if __name__ == "__main__":
    main()
