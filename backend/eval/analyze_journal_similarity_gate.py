"""Offline threshold sweep on saved current-message MMR top-3 scores. No API."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

SRC = Path(__file__).resolve().parent / "results" / "test-scratch" / "journal-ranking-compare.json"
OUT = Path(__file__).resolve().parent / "results" / "test-scratch" / "journal-similarity-gate.json"


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * q
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    frac = index - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def summarize(name: str, values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": round(min(values), 4),
        "p10": round(pct(values, 0.10), 4),
        "p25": round(pct(values, 0.25), 4),
        "median": round(median(values), 4),
        "p75": round(pct(values, 0.75), 4),
        "p90": round(pct(values, 0.90), 4),
        "max": round(max(values), 4),
    }


def gold_sim(row: dict) -> float | None:
    result = row["strategies"]["current_mmr"]
    rank = result["gold_rank"]
    if not rank:
        return None
    return float(result["top3"][rank - 1]["similarity"])


def all_sims(row: dict) -> list[float]:
    return [float(item["similarity"]) for item in row["strategies"]["current_mmr"]["top3"]]


def main() -> None:
    payload = json.loads(SRC.read_text(encoding="utf-8"))
    positives = [row for row in payload["cases"] if row["slice"] == "updated_fact"]
    negatives = [row for row in payload["cases"] if row["slice"] == "synthetic_negative"]

    gold_hits = [sim for sim in (gold_sim(row) for row in positives) if sim is not None]
    gold_misses = [row["id"] for row in positives if gold_sim(row) is None]
    pos_top1 = [all_sims(row)[0] for row in positives if all_sims(row)]
    pos_injected = [sim for row in positives for sim in all_sims(row)]
    neg_top1 = [all_sims(row)[0] for row in negatives if all_sims(row)]
    neg_injected = [sim for row in negatives for sim in all_sims(row)]
    neg_max = [max(all_sims(row)) for row in negatives if all_sims(row)]

    sweep = []
    for tenths in range(50, 91):
        threshold = tenths / 100
        hit_kept = sum(1 for sim in gold_hits if sim >= threshold)
        hit_lost = len(gold_hits) - hit_kept
        # Hit@3 among all 45: misses stay misses; hits drop if gold < t.
        hit_at_3 = hit_kept
        empty_neg = sum(1 for sim in neg_max if sim < threshold)
        nonempty_neg = len(neg_max) - empty_neg
        sweep.append(
            {
                "threshold": threshold,
                "positive_hit_at_3": f"{hit_at_3}/{len(positives)}",
                "hit_at_3_rate": round(hit_at_3 / len(positives), 3),
                "gold_hits_dropped": hit_lost,
                "negative_empty": f"{empty_neg}/{len(negatives)}",
                "negative_empty_rate": round(empty_neg / len(negatives), 3),
                "negative_still_injects": nonempty_neg,
            }
        )

    overlap_low = max(neg_max) if neg_max else None
    overlap_high = min(gold_hits) if gold_hits else None

    report = {
        "source": str(SRC),
        "strategy": "current_mmr",
        "note": (
            "Gate modeled as drop injected MMR top-3 chunks with similarity < t. "
            "Hit@3 only falls when a currently retrieved gold chunk is below t. "
            "The four current misses stay misses. No new embeddings."
        ),
        "positives": {
            "n": len(positives),
            "gold_in_top3": len(gold_hits),
            "gold_missing_from_top3": gold_misses,
            "gold_chunk_similarity": summarize("gold", gold_hits),
            "top1_similarity": summarize("pos_top1", pos_top1),
            "all_injected_similarity": summarize("pos_all", pos_injected),
        },
        "negatives": {
            "n": len(negatives),
            "top1_similarity": summarize("neg_top1", neg_top1),
            "max_of_top3_similarity": summarize("neg_max", neg_max),
            "all_injected_similarity": summarize("neg_all", neg_injected),
        },
        "separation": {
            "min_retrieved_gold": overlap_high,
            "max_negative_top3_max": overlap_low,
            "gap_min_gold_minus_max_negative": None
            if overlap_high is None or overlap_low is None
            else round(overlap_high - overlap_low, 4),
        },
        "sweep": sweep,
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
