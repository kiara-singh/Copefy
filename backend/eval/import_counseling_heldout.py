"""Build a held-out golden file from public counseling questions.

Source: HuggingFace Amod/mental_health_counseling_conversations
Labels are assigned by product intent (our six paths), NOT by running the
rule router. Do not retune patterns against this file — its job is to measure
generalization.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from pathlib import Path

import yaml
from datasets import load_dataset

OUT_PATH = Path(__file__).resolve().parent / "golden" / "heldout_counseling.yaml"

# Independent of agent/prompts.py — intentional. If these drift toward the
# router keywords, the held-out score stops meaning anything.
CRISIS_MARKERS = (
    r"\bsuicid",
    r"\bkill(?:ing)? myself\b",
    r"\bhurt(?:ing)? myself\b",
    r"\bself[-\s]?harm\b",
    r"\bwant to die\b",
    r"\bend my life\b",
    r"\bend it all\b",
    r"\bdon'?t want to (?:be here|live|be alive|exist)\b",
    r"\bshouldn'?t be here\b",
    r"\bbetter off without me\b",
    r"\bcut(?:ting)? myself\b",
    r"\boverdose\b",
    r"\bnot wake up\b",
)

SEARCH_MARKERS = (
    r"\banxi",
    r"\bpanic\b",
    r"\bworr",
    r"\bdepress",
    r"\bhopeless\b",
    r"\bworthless\b",
    r"\btrauma\b",
    r"\bptsd\b",
    r"\bflashback",
    r"\bocd\b",
    r"\bobsess",
    r"\bcompuls",
    r"\badhd\b",
    r"\bconcentrat",
    r"\bdistract",
    r"\binsomnia\b",
    r"\bcan'?t sleep\b",
    r"\bgrief\b",
    r"\bbipolar\b",
    r"\bschizophren",
    r"\beating disorder\b",
    r"\banorex",
    r"\bbulimi",
    r"\bself[-\s]?esteem\b",
    r"\bis it normal\b",
    r"\bhow (?:can|do) i\b",
    r"\bwhat (?:can|should) i do\b",
    r"\bcoping\b",
    r"\btherap",
    r"\bcounsel",
    r"\bmedicat",
    r"\bantidepress",
    r"\bstress",
    r"\boverwhelm",
    r"\blonely\b",
    r"\bisolat",
    r"\bangry all the time\b",
    r"\bmood swings\b",
    r"\bintrusive\b",
)

DIRECT_MARKERS = (
    r"^(?:hi|hello|hey)\b",
    r"\bthank(?:s| you)\b",
    r"\bjust needed to (?:vent|say)\b",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def bucket(text: str) -> str:
    n = _norm(text)
    if _matches(CRISIS_MARKERS, n):
        return "crisisish"
    if re.search(r"\b(?:anxiety|anxious|panic)\b", n):
        return "anxiety"
    if re.search(r"\b(?:depress|hopeless|worthless)\b", n):
        return "depression"
    if re.search(r"\b(?:trauma|ptsd|flashback|abuse)\b", n):
        return "trauma"
    if re.search(r"\b(?:ocd|obsess|compuls)\b", n):
        return "ocd"
    if re.search(r"\b(?:adhd|focus|distract)\b", n):
        return "adhd"
    if re.search(
        r"\b(?:relationship|boyfriend|girlfriend|husband|wife|partner|marriage)\b", n
    ):
        return "relationship"
    return "other"


def _user_is_at_risk(text: str) -> bool:
    """Crisis only when the writer themselves is at risk — not a third party."""
    n = _norm(text)

    # Someone else's suicide / attempt / ideation is grief or support, not crisis.
    third_party = re.search(
        r"\b(?:friend|roommate|boyfriend|girlfriend|husband|wife|partner|fiance|"
        r"fiancée|mom|dad|mother|father|parent|brother|sister|cousin|classmate|"
        r"birth mother|adopted)\b.{0,40}\b(?:suicid|kill(?:ed|ing)? (?:her|him|them)self|"
        r"self[-\s]?harm)",
        n,
    ) or re.search(
        r"\b(?:suicid|kill(?:ed|ing)? (?:her|him|them)self).{0,40}\b(?:friend|roommate|"
        r"boyfriend|girlfriend|husband|wife|partner|mom|dad|mother|father|parent)\b",
        n,
    )
    if third_party and not re.search(
        r"\b(?:i|i'm|i am|i've|i have)\b.{0,30}\b(?:suicid|kill myself|hurt myself|"
        r"self[-\s]?harm|want to die|shouldn'?t be here)",
        n,
    ):
        return False

    return _matches(CRISIS_MARKERS, n)


def label_path(text: str) -> tuple[str, str, list[str]]:
    """Return (expected_path, type, tags) from product intent."""
    n = _norm(text)

    if _user_is_at_risk(text):
        return "crisis", "crisis", ["heldout", "counseling_hf"]

    if _matches(DIRECT_MARKERS, n) and not _matches(SEARCH_MARKERS, n):
        return "direct_answer", "general", ["heldout", "counseling_hf"]

    if _matches(SEARCH_MARKERS, n):
        case_type = "symptom_sharing"
        if re.search(r"\bis it normal\b", n):
            case_type = "seeks_normalization"
        elif re.search(r"\b(?:how (?:can|do) i|what (?:can|should) i do|coping)\b", n):
            case_type = "coping_request"
        return "search_database", case_type, ["heldout", "counseling_hf"]

    # Relationship / life questions with no clinical ask → conversational.
    if re.search(
        r"\b(?:boyfriend|girlfriend|husband|wife|partner|marriage|divorce|cheating)\b",
        n,
    ):
        return "direct_answer", "general", ["heldout", "counseling_hf", "relationship"]

    # Default for long counseling-platform posts: they came to ask for help.
    if len(n.split()) >= 40:
        return "search_database", "symptom_sharing", ["heldout", "counseling_hf"]

    return "direct_answer", "general", ["heldout", "counseling_hf"]


def categories_for(text: str, path: str) -> list[str]:
    if path != "search_database":
        return []
    n = _norm(text)
    found: list[str] = []
    mapping = {
        "anxiety": (r"\banxi", r"\bpanic\b", r"\bworr"),
        "depression": (r"\bdepress", r"\bhopeless\b", r"\bworthless\b"),
        "ptsd": (r"\btrauma\b", r"\bptsd\b", r"\bflashback", r"\babuse\b"),
        "ocd": (r"\bocd\b", r"\bobsess", r"\bcompuls"),
        "adhd": (r"\badhd\b", r"\bdistract", r"\bconcentrat"),
    }
    for cat, pats in mapping.items():
        if any(re.search(p, n) for p in pats):
            found.append(cat)
    return found[:2]


def stable_id(text: str, idx: int) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"heldout_counsel_{idx:03d}_{digest}"


def sample_stratified(contexts: list[str], n: int, seed: str = "copefy-heldout") -> list[str]:
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for ctx in contexts:
        by_bucket[bucket(ctx)].append(ctx)

    # Deterministic shuffle inside each bucket.
    for key, items in by_bucket.items():
        items.sort(key=lambda t: hashlib.sha1(f"{seed}:{t}".encode()).hexdigest())

    # Take all crisis-ish, then fill quotas.
    quotas = {
        "crisisish": min(len(by_bucket["crisisish"]), 22),
        "anxiety": 35,
        "depression": 35,
        "trauma": 20,
        "ocd": min(len(by_bucket["ocd"]), 6),
        "adhd": min(len(by_bucket["adhd"]), 7),
        "relationship": 40,
        "other": 40,
    }
    picked: list[str] = []
    for key, quota in quotas.items():
        picked.extend(by_bucket[key][:quota])

    # Top up from leftovers if under target.
    if len(picked) < n:
        leftover = [c for c in contexts if c not in set(picked)]
        leftover.sort(key=lambda t: hashlib.sha1(f"{seed}:extra:{t}".encode()).hexdigest())
        picked.extend(leftover[: n - len(picked)])

    return picked[:n]


def build_cases(n: int) -> list[dict]:
    ds = load_dataset("Amod/mental_health_counseling_conversations", split="train")
    unique: dict[str, str] = {}
    for row in ds:
        key = _norm(row["Context"])
        unique.setdefault(key, row["Context"].strip())

    sampled = sample_stratified(list(unique.values()), n=n)
    cases: list[dict] = []
    for idx, text in enumerate(sampled, start=1):
        # Cap very long counseling essays — router input in chat is shorter.
        # Label the truncated text so the gold matches what we actually score.
        query = text if len(text) <= 700 else text[:700].rsplit(" ", 1)[0] + "…"
        path, case_type, tags = label_path(query)
        case: dict = {
            "id": stable_id(text, idx),
            "query": query,
            "type": case_type,
            "expected_path": path,
            "tags": tags,
            "source": "Amod/mental_health_counseling_conversations",
        }
        if path == "search_database":
            case["expected_corpus"] = "clinical"
            cats = categories_for(query, path)
            if cats:
                case["expected_categories"] = cats
        cases.append(case)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    cases = build_cases(args.n)
    args.out.write_text(
        "# Held-out counseling questions from HuggingFace "
        "Amod/mental_health_counseling_conversations.\n"
        "# Labeled by product intent. Do NOT tune the rule router against this file.\n"
        "# Score with: python -m eval.layer1_eval --router rule --tag heldout\n\n"
        + yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )

    from collections import Counter

    paths = Counter(c["expected_path"] for c in cases)
    print(f"Wrote {len(cases)} cases -> {args.out}")
    for path, count in paths.most_common():
        print(f"  {path:<22} {count}")


if __name__ == "__main__":
    main()
