"""Eval-only journal ranking bake-off. Does not change production retrieval."""
from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from eval.baseline import cases as load_conversations
from eval.baseline_fixtures import definitions, entry_id, users
from eval.query_embed_cache import cached_embed_query
from rag.retrieve import recent_user_context
from rag.search import KBChunkHit, _vector_literal
from rag.strategies.pipeline import apply_min_similarity, mmr_rerank_hits
from config import settings

# Recency may break near-ties; it cannot overcome a similarity gap larger than this.
RECENCY_WEIGHT = 0.05
MATCH_COUNT = 15
TOP_K = 3
OUT = Path(__file__).resolve().parent / "results" / "test-scratch" / "journal-ranking-compare.json"


def _parse_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def recency_rerank(hits: list[KBChunkHit], top_k: int, *, recency_weight: float = RECENCY_WEIGHT) -> list[KBChunkHit]:
    """Similarity first; pool-normalized entry date is a bounded additive bonus."""
    if not hits:
        return []
    stamps = [_parse_time((hit.metadata or {}).get("entry_created_at")) for hit in hits]
    valid = [stamp for stamp in stamps if stamp is not None]
    if len(valid) < 2:
        return sorted(hits, key=lambda hit: hit.similarity, reverse=True)[:top_k]
    oldest, newest = min(valid), max(valid)
    span = (newest - oldest).total_seconds()
    scored: list[tuple[float, KBChunkHit]] = []
    for hit, stamp in zip(hits, stamps):
        recency = 0.0 if stamp is None or span <= 0 else (stamp - oldest).total_seconds() / span
        scored.append((hit.similarity + recency_weight * recency, hit))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [hit for _, hit in scored[:top_k]]


def _query_pair(turns: list[str]) -> tuple[str, str]:
    message = turns[-1].strip()
    history = [{"role": "user", "content": text} for text in turns[:-1]]
    three_turn = recent_user_context(history, message)
    return three_turn, message


def _hit_from_row(row) -> KBChunkHit:
    created = row["entry_created_at"]
    return KBChunkHit(
        id=str(row["id"]),
        document_id=str(row["journal_entry_id"]),
        content=row["content"],
        metadata={
            "chunk_index": row["chunk_index"],
            "user_id": str(row["user_id"]),
            "entry_created_at": created.isoformat() if created is not None else None,
        },
        similarity=float(row["similarity"]),
        title="Personal Journal",
        source_url=None,
        category="journal",
    )


async def fetch_pool(conn, user_id: str, embedding: list[float]) -> list[KBChunkHit]:
    rows = await conn.fetch(
        """
        SELECT jc.id, jc.journal_entry_id, jc.user_id, jc.chunk_index, jc.content,
               1 - (jc.embedding <=> $1::vector) AS similarity,
               je.created_at AS entry_created_at
        FROM journal_chunks jc
        JOIN journal_entries je ON je.id = jc.journal_entry_id
        WHERE jc.user_id = $2::uuid
        ORDER BY jc.embedding <=> $1::vector
        LIMIT $3
        """,
        _vector_literal(embedding),
        user_id,
        MATCH_COUNT,
    )
    return [_hit_from_row(row) for row in rows]


def _preview(hit: KBChunkHit) -> dict:
    return {
        "document_id": hit.document_id,
        "similarity": round(hit.similarity, 4),
        "entry_created_at": (hit.metadata or {}).get("entry_created_at"),
        "preview": (hit.content or "")[:140],
    }


def _gold_rank(hits: list[KBChunkHit], match) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if match(hit):
            return index
    return None


async def main() -> None:
    from db import get_pool

    journals = {item["id"]: item for item in definitions()["journals"]}
    fixture_by_uuid = {entry_id(item["user"], item["id"]): item["id"] for item in journals.values()}

    def label(document_id: str) -> str:
        return fixture_by_uuid.get(document_id, document_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        ids = await users(conn)

    tasks: list[dict] = []
    for case in load_conversations():
        if "journal_retrieval" in case.get("tags", []):
            slice_name = "updated_fact"
        elif case.get("expect_empty"):
            slice_name = "synthetic_negative"
        else:
            continue
        three, current = _query_pair(case["turns"])
        expected = list(case.get("expected_entries") or [])
        stale = [name.replace("_after", "_before") for name in expected if name.endswith("_after")]
        canaries = [
            check["value"]
            for check in case.get("checks", [])
            if str(check.get("kind", "")).startswith("forbid")
        ]
        tasks.append(
            {
                "id": case["id"],
                "slice": slice_name,
                "user_id": ids[case["user"]],
                "three_turn": three,
                "current": current,
                "expected_fixtures": expected,
                "stale_fixtures": stale,
                "canaries": canaries,
                "expected_ids": [entry_id(case["user"], name) for name in expected],
                "kind": "contains_id",
            }
        )

    unique_queries: dict[tuple[str, str], list[float]] = {}
    for task in tasks:
        for text in (task["three_turn"], task["current"]):
            unique_queries.setdefault((task["user_id"], text), [])

    print(f"Cases={len(tasks)} unique_query_embeds={len(unique_queries)}", flush=True)
    hits = 0
    for index, key in enumerate(unique_queries, start=1):
        print(f"embed {index}/{len(unique_queries)}", flush=True)
        unique_queries[key] = await asyncio.to_thread(cached_embed_query, key[1])
        hits += 1
    print(f"Query embeddings finished ({hits}); repeats load from eval/cache/query_embeddings.json", flush=True)

    strategies = (
        ("three_turn_mmr", "three_turn", "mmr"),
        ("current_mmr", "current", "mmr"),
        ("current_recency", "current", "recency"),
    )

    async with pool.acquire() as conn:
        pools: dict[tuple[str, str], list[KBChunkHit]] = {}
        for user_id, text in unique_queries:
            pools[(user_id, text)] = await fetch_pool(conn, user_id, unique_queries[(user_id, text)])

    def apply(strategy_name: str, strategy_rerank: str, hits: list[KBChunkHit]) -> list[KBChunkHit]:
        if strategy_rerank == "mmr":
            ranked = mmr_rerank_hits(hits, top_k=TOP_K, lambda_mult=0.7)
            if strategy_name == "current_mmr":
                ranked = apply_min_similarity(ranked, settings.journal_min_similarity)
            return ranked
        return recency_rerank(hits, TOP_K)

    def matches_gold(task: dict, hit: KBChunkHit) -> bool:
        if task.get("expect_empty"):
            return False
        if hit.document_id in set(task["expected_ids"]):
            return True
        if label(hit.document_id) in set(task["expected_fixtures"]):
            return True
        content = (hit.content or "").lower()
        return any(needle.lower() in content for needle in task.get("needles") or [])

    rows = []
    summary = {name: defaultdict(Counter) for name, _, _ in strategies}
    for task in tasks:
        record = {"id": task["id"], "slice": task["slice"], "strategies": {}}
        for name, query_key, rerank in strategies:
            hits = apply(name, rerank, pools[(task["user_id"], task[query_key])])
            labels = [label(hit.document_id) for hit in hits]
            rank = _gold_rank(hits, lambda hit, task=task: matches_gold(task, hit))
            stale_hit = any(item in task["stale_fixtures"] for item in labels)
            canary_hit = any(
                canary.lower() in (hit.content or "").lower()
                for hit in hits
                for canary in task["canaries"]
            )
            empty_ok = task["slice"] in {"synthetic_negative", "eval_negative"}
            stats = summary[name][task["slice"]]
            stats["n"] += 1
            if empty_ok:
                stats["always_returns_k"] += int(bool(hits))
                stats["canary_or_gold_in_top3"] += int(bool(rank) or canary_hit)
            else:
                stats["hit_at_1"] += int(rank == 1)
                stats["hit_at_3"] += int(rank is not None and rank <= 3)
                stats["stale_in_top3"] += int(stale_hit)
            record["strategies"][name] = {
                "gold_rank": rank,
                "stale_in_top3": stale_hit,
                "canary_in_top3": canary_hit,
                "top3": [{**_preview(hit), "fixture": label(hit.document_id)} for hit in hits],
            }
        rows.append(record)

    compact = {}
    for name, slice_counts in summary.items():
        compact[name] = {}
        for slice_name, counts in slice_counts.items():
            n = counts["n"] or 1
            if slice_name in {"synthetic_negative", "eval_negative"}:
                compact[name][slice_name] = {
                    "n": counts["n"],
                    "nonempty_top3": counts["always_returns_k"],
                    "canary_or_labeled_gold_in_top3": counts["canary_or_gold_in_top3"],
                }
            else:
                compact[name][slice_name] = {
                    "n": counts["n"],
                    "hit_at_1": round(counts["hit_at_1"] / n, 3),
                    "hit_at_3": round(counts["hit_at_3"] / n, 3),
                    "hit_at_1_n": counts["hit_at_1"],
                    "hit_at_3_n": counts["hit_at_3"],
                    "stale_in_top3": counts["stale_in_top3"],
                }

    regressions = []
    baseline = "three_turn_mmr"
    for row in rows:
        base = row["strategies"][baseline]
        for name in ("current_mmr", "current_recency"):
            other = row["strategies"][name]
            base_hit = base["gold_rank"] is not None and base["gold_rank"] <= 3
            other_hit = other["gold_rank"] is not None and other["gold_rank"] <= 3
            if row["slice"] in {"synthetic_negative", "eval_negative"}:
                if (not base["canary_in_top3"]) and other["canary_in_top3"]:
                    regressions.append({"id": row["id"], "slice": row["slice"], "strategy": name, "kind": "canary_appeared"})
                continue
            if base_hit and not other_hit:
                regressions.append({"id": row["id"], "slice": row["slice"], "strategy": name, "kind": "lost_hit_at_3"})
            if (not base["stale_in_top3"]) and other["stale_in_top3"]:
                regressions.append({"id": row["id"], "slice": row["slice"], "strategy": name, "kind": "new_stale"})

    payload = {
        "recency_weight": RECENCY_WEIGHT,
        "match_count": MATCH_COUNT,
        "top_k": TOP_K,
        "embedding_calls": len(unique_queries),
        "summary": compact,
        "regressions_vs_three_turn_mmr": regressions,
        "cases": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"summary": compact, "regressions": regressions, "out": str(OUT)}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
