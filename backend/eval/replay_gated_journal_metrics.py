"""Replay saved current-message MMR top-3 with the 0.70 journal gate. No API."""
from __future__ import annotations

import json
from pathlib import Path

from config import settings

SRC = Path(__file__).resolve().parent / "results" / "test-scratch" / "journal-ranking-compare.json"
OUT = Path(__file__).resolve().parent / "results" / "test-scratch" / "journal-phase2-gated.json"


def main() -> None:
    cutoff = settings.journal_min_similarity
    payload = json.loads(SRC.read_text(encoding="utf-8"))
    rows = []
    pos_hit1 = pos_hit3 = pos_n = stale = 0
    neg_n = neg_empty = neg_canary = 0
    lost_hit3 = []
    still_nonempty_neg = []

    for row in payload["cases"]:
        result = row["strategies"]["current_mmr"]
        ungated = result["top3"]
        gated = [item for item in ungated if float(item["similarity"]) >= cutoff]
        gold_rank = result["gold_rank"]
        gold_kept = False
        if gold_rank:
            gold = ungated[gold_rank - 1]
            gold_kept = float(gold["similarity"]) >= cutoff
            if gold_kept:
                gold_rank = next(
                    index
                    for index, item in enumerate(gated, start=1)
                    if item["document_id"] == gold["document_id"]
                    and item["similarity"] == gold["similarity"]
                )
            else:
                gold_rank = None
        elif gated:
            gold_rank = None

        stale_hit = result["stale_in_top3"] and any(
            "before" in (item.get("fixture") or "") for item in gated
        )
        canary = bool(result["canary_in_top3"]) and bool(gated)

        if row["slice"] == "updated_fact":
            pos_n += 1
            pos_hit1 += int(gold_rank == 1)
            pos_hit3 += int(gold_rank is not None)
            stale += int(stale_hit)
            if result["gold_rank"] and gold_rank is None:
                lost_hit3.append(row["id"])
        elif row["slice"] == "synthetic_negative":
            neg_n += 1
            neg_empty += int(not gated)
            neg_canary += int(canary)
            if gated:
                still_nonempty_neg.append(row["id"])

        rows.append(
            {
                "id": row["id"],
                "slice": row["slice"],
                "ungated_n": len(ungated),
                "gated_n": len(gated),
                "gold_rank": gold_rank,
            }
        )

    summary = {
        "cutoff": cutoff,
        "updated_fact": {
            "n": pos_n,
            "hit_at_1": f"{pos_hit1}/{pos_n}",
            "hit_at_3": f"{pos_hit3}/{pos_n}",
            "stale_in_top3": stale,
            "hit_at_3_lost_to_gate": lost_hit3,
        },
        "synthetic_negative": {
            "n": neg_n,
            "empty": f"{neg_empty}/{neg_n}",
            "still_injects": f"{neg_n - neg_empty}/{neg_n}",
            "canary_in_top3": neg_canary,
            "nonempty_ids": still_nonempty_neg,
        },
    }
    OUT.write_text(json.dumps({"summary": summary, "cases": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
