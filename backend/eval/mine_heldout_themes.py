"""One-pass theme dump of held-out search→direct misses. Read-only analysis."""

from __future__ import annotations

import asyncio
import re
from collections import Counter

from agent.routers import get_router
from eval.load_golden import load_golden_cases

THEME_PATTERNS = {
    "grief_loss": r"\b(?:lost|loss|died|death|passed away|grief|mourning)\b",
    "loneliness": r"\b(?:lonely|alone|isolat|no friends|abandoned)\b",
    "anger": r"\b(?:angry|anger|rage|furious|resent)\b",
    "substance": r"\b(?:drink|drinking|alcohol|marijuana|weed|drug|smoking)\b",
    "how_handle": r"\bhow (?:can|do) i (?:handle|deal|cope|get)\b",
    "relationship": r"\b(?:boyfriend|girlfriend|husband|wife|partner|marriage|divorce)\b",
    "childhood": r"\b(?:childhood|grew up|parents?|abusive|foster)\b",
    "self_esteem": r"\b(?:ugly|worthless|hate myself|not good enough)\b",
    "sleep": r"\b(?:sleep|insomnia|nightmares?|tired)\b",
    "fear_therapy": r"\b(?:afraid|scared).{0,40}\b(?:doctor|therap|diagnos|medicat|antidepress)\b",
}


async def main() -> None:
    cases = [
        c
        for c in load_golden_cases()
        if "heldout" in c.get("tags", []) and c.get("expected_path") == "search_database"
    ]
    router = get_router("rule")
    themes: Counter[str] = Counter()
    samples: list[str] = []

    for case in cases:
        decision = await router.decide(case["query"], history=case.get("history") or [])
        if decision.path.value != "direct_answer":
            continue
        text = case["query"].lower()
        hit = False
        for name, pattern in THEME_PATTERNS.items():
            if re.search(pattern, text):
                themes[name] += 1
                hit = True
        if not hit:
            themes["other"] += 1
        if len(samples) < 12:
            samples.append(re.sub(r"\s+", " ", case["query"])[:140])

    print(f"search->direct misses: {sum(themes.values())}")
    print("themes:")
    for name, count in themes.most_common():
        print(f"  {name:<16} {count}")
    print("samples:")
    for sample in samples:
        print(f"  - {sample}")


if __name__ == "__main__":
    asyncio.run(main())
