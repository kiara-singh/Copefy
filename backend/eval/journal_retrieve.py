"""In-memory journal retrieval for eval only.

Loads live journal_entries for DEV_USER_ID, embeds them with Gemini 768-d,
then applies the same four Layer 3 rerankers. Does not write embeddings back
and does not wire Layer 2 into the orchestrator.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

from rag.retrieve import RetrievalPlan, RetrievedChunk, _rerank_hits
from rag.search import KBChunkHit
from rag.strategies.base import StrategyConfig, StrategyResult
from rag.strategies.baseline import DEFAULT_CONFIG
from rag.strategies.mmr import MMR_CONFIG
from rag.strategies.pipeline import apply_min_similarity, hits_to_chunks, mmr_rerank_hits
from rag.strategies.threshold import THRESHOLD_CONFIG
from rag.strategies.wide_then_narrow import WIDE_CONFIG

DEV_USER_ID = "78b0cc86-0b60-4220-8127-4430b1f3cd9e"

JOURNAL_STRATEGY_SPECS: dict[str, tuple[StrategyConfig, str]] = {
    "baseline": (DEFAULT_CONFIG, "heuristic"),
    "threshold_0.65": (THRESHOLD_CONFIG, "heuristic"),
    "mmr": (MMR_CONFIG, "mmr"),
    "wide_then_narrow": (WIDE_CONFIG, "heuristic"),
}


@dataclass
class JournalEntry:
    id: str
    content: str
    created_at: str | None = None
    char_len: int = 0
    embedding: list[float] | None = None


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def _normalize_body(text: str) -> str:
    return " ".join(text.lower().split())


def entry_id_recall(expected: list[str], retrieved_ids: list[str]) -> float:
    if not expected:
        return float("nan")
    got = set(retrieved_ids)
    hits = sum(1 for entry_id in expected if entry_id in got)
    return hits / len(expected)


def contains_recall(needles: list[str], chunks: list) -> float:
    if not needles:
        return float("nan")
    texts = [(getattr(chunk, "content", "") or "").lower() for chunk in chunks]
    hits = sum(1 for needle in needles if any(needle.lower() in text for text in texts))
    return hits / len(needles)


def journal_label_recall(
    case: dict,
    retrieved_ids: list[str],
    chunks: list,
    entries: list[JournalEntry],
) -> float:
    """Prefer expected_contains (stable with duplicate rows). Else entry ids, expanded by identical text."""
    needles = [str(item) for item in (case.get("expected_contains") or [])]
    if needles:
        return contains_recall(needles, chunks)
    expected_ids = [str(item) for item in (case.get("expected_entry_ids") or [])]
    if not expected_ids:
        return float("nan")
    by_content: dict[str, set[str]] = {}
    content_of: dict[str, str] = {}
    for entry in entries:
        key = _normalize_body(entry.content)
        content_of[entry.id] = key
        by_content.setdefault(key, set()).add(entry.id)
    expanded: set[str] = set()
    for entry_id in expected_ids:
        key = content_of.get(entry_id)
        if key:
            expanded.update(by_content[key])
        expanded.add(entry_id)
    got = set(retrieved_ids)
    hits = sum(1 for entry_id in expected_ids if entry_id in got or (content_of.get(entry_id) and by_content[content_of[entry_id]] & got))
    return hits / len(expected_ids)


def _text_column(column_names: set[str]) -> str:
    if "content" in column_names:
        return "content"
    if "raw_text" in column_names:
        return "raw_text"
    raise RuntimeError("journal_entries has neither content nor raw_text")


async def load_journal_entries(
    *,
    user_id: str | None = None,
    dedupe: bool = True,
) -> list[JournalEntry]:
    """Fetch journal rows. Logs ids/dates/lengths only — not body text.

    If the requested user has no rows, fall back to the user with the most entries
    (the live seed set is not under DEV_USER_ID).
    """
    from db import get_pool

    pool = await get_pool()
    requested = user_id or DEV_USER_ID
    async with pool.acquire() as conn:
        columns = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'journal_entries'
            """
        )
        names = {str(row["column_name"]) for row in columns}
        if not names:
            raise RuntimeError("journal_entries table not found")
        text_col = _text_column(names)
        has_created = "created_at" in names
        created_select = "created_at" if has_created else "NULL AS created_at"
        order_by = "created_at, id" if has_created else "id"

        async def _fetch(uid: str | None) -> list:
            if uid:
                return await conn.fetch(
                    f"""
                    SELECT id::text AS id, user_id::text AS user_id,
                           {text_col} AS body, {created_select}
                    FROM journal_entries
                    WHERE user_id = $1::uuid
                    ORDER BY {order_by}
                    """,
                    uid,
                )
            return await conn.fetch(
                f"""
                SELECT id::text AS id, user_id::text AS user_id,
                       {text_col} AS body, {created_select}
                FROM journal_entries
                ORDER BY {order_by}
                """
            )

        rows = await _fetch(requested)
        if not rows:
            rows = await _fetch(None)

    entries: list[JournalEntry] = []
    for row in rows:
        body = (row["body"] or "").strip()
        if not body:
            continue
        created = row["created_at"]
        entries.append(
            JournalEntry(
                id=str(row["id"]),
                content=body,
                created_at=created.isoformat() if created is not None else None,
                char_len=len(body),
            )
        )

    if not entries:
        return []

    if user_id is None and entries:
        # If we fell back, keep a single user's corpus (the one with the most rows).
        from collections import Counter

        users = Counter(str(row["user_id"]) for row in rows if row.get("user_id"))
        if users:
            majority, _ = users.most_common(1)[0]
            id_to_user = {str(row["id"]): str(row["user_id"]) for row in rows}
            entries = [entry for entry in entries if id_to_user.get(entry.id) == majority]
            print(f"  journal user={majority} ({len(entries)} rows)")

    if dedupe:
        seen: set[str] = set()
        unique: list[JournalEntry] = []
        for entry in entries:
            key = _normalize_body(entry.content)
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        print(f"  deduped journal texts {len(entries)} -> {len(unique)}")
        entries = unique
    return entries


def describe_entries(entries: list[JournalEntry]) -> list[dict]:
    """Safe-to-print metadata (no diary text)."""
    return [
        {"id": entry.id, "created_at": entry.created_at, "char_len": entry.char_len}
        for entry in entries
    ]


async def embed_journal_entries(entries: list[JournalEntry]) -> list[JournalEntry]:
    from rag.embed import embed_query

    for entry in entries:
        entry.embedding = await asyncio.to_thread(embed_query, entry.content)
    return entries


def rank_journal_hits(
    query_embedding: list[float],
    entries: list[JournalEntry],
    match_count: int,
) -> list[KBChunkHit]:
    hits: list[KBChunkHit] = []
    for entry in entries:
        if not entry.embedding:
            continue
        similarity = cosine_similarity(query_embedding, entry.embedding)
        hits.append(
            KBChunkHit(
                id=entry.id,
                document_id=entry.id,
                content=entry.content,
                metadata={},
                similarity=similarity,
                title=entry.created_at,
                source_url=None,
                category=None,
            )
        )
    hits.sort(key=lambda hit: hit.similarity, reverse=True)
    return hits[: max(1, match_count)]


def rerank_journal_hits(
    query: str,
    hits: list[KBChunkHit],
    config: StrategyConfig,
    rerank_mode: str,
) -> list[KBChunkHit]:
    if rerank_mode == "mmr":
        ranked = mmr_rerank_hits(hits, config.top_k, lambda_mult=config.mmr_lambda)
    else:
        ranked = _rerank_hits(query, hits, config.top_k)
    return apply_min_similarity(ranked, config.min_similarity)


async def retrieve_journal(
    query: str,
    entries: list[JournalEntry],
    *,
    strategy_name: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[StrategyResult, list[str]]:
    if strategy_name not in JOURNAL_STRATEGY_SPECS:
        raise ValueError(f"Unknown journal strategy {strategy_name!r}")
    config, rerank_mode = JOURNAL_STRATEGY_SPECS[strategy_name]

    parts = []
    if history:
        parts.extend(
            entry.get("content", "")
            for entry in history
            if entry.get("role") == "user"
        )
    parts.append(query.strip())
    search_query = " ".join(part for part in parts if part)

    from rag.embed import embed_query

    embedding = await asyncio.to_thread(embed_query, search_query)
    match_count = min(config.match_count, max(len(entries), 1))
    hits = rank_journal_hits(embedding, entries, match_count)
    ranked = rerank_journal_hits(search_query, hits, config, rerank_mode)
    chunks: list[RetrievedChunk] = hits_to_chunks(ranked, config.inject_k)
    retrieved_ids = [hit.id for hit in ranked[: config.inject_k]]
    plan = RetrievalPlan(
        search_query=search_query,
        categories=(),
        reason="journal_eval",
    )
    result = StrategyResult(
        plan=plan,
        chunks=chunks,
        metadata={
            "match_count": match_count,
            "top_k": config.top_k,
            "rerank_mode": rerank_mode,
            "candidates": len(hits),
            "entry_ids": retrieved_ids,
        },
    )
    return result, retrieved_ids
