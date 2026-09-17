"""Journal retrieval helpers for eval.

Production path calls `search_journal_chunks` (same as chat). The in-memory
path embeds full `journal_entries` in-process for ranker bake-offs only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from rag.retrieve import RetrievalPlan, RetrievedChunk, _rerank_hits
from rag.search import KBChunkHit
from rag.strategies.base import StrategyConfig, StrategyResult
from rag.strategies.baseline import DEFAULT_CONFIG
from rag.strategies.mmr import MMR_CONFIG
from rag.strategies.pipeline import apply_min_similarity, hits_to_chunks, mmr_rerank_hits
from rag.strategies.threshold import THRESHOLD_CONFIG
from rag.strategies.wide_then_narrow import WIDE_CONFIG

DEV_USER_ID = "78b0cc86-0b60-4220-8127-4430b1f3cd9e"
# Live seed diary corpus used by journal_eval.yaml.
JOURNAL_EVAL_USER_ID = "938c6dc2-bab8-44d9-b732-8bbd308fd838"
EMBED_CACHE_PATH = Path(__file__).resolve().parent / "cache" / "journal_embeddings.json"
PROD_JOURNAL_STRATEGIES = ("journal_mmr", "both")

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


def snippets_for_journal_recall(chunks: list) -> list:
    """Gold labels apply to journal snippets only.

    Chat's `both` path mixes clinical KB with journals. Clinical hits must not
    count as a journal match, and they must not fail `expect_empty`.
    Untagged in-memory eval chunks are treated as journal.
    """
    journal = [chunk for chunk in chunks if getattr(chunk, "category", None) == "journal"]
    if journal:
        return journal
    if any(getattr(chunk, "category", None) not in (None, "journal") for chunk in chunks):
        return []
    return list(chunks)


def entry_ids_from_chunks(chunks: list) -> list[str]:
    ids: list[str] = []
    for chunk in snippets_for_journal_recall(chunks):
        document_id = getattr(chunk, "document_id", None)
        if document_id:
            ids.append(str(document_id))
    return ids


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
    scored = snippets_for_journal_recall(chunks)
    if case.get("expect_empty"):
        return 1.0 if not scored else 0.0
    needles = [str(item) for item in (case.get("expected_contains") or [])]
    if needles:
        return contains_recall(needles, scored)
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


RANKED_MEMORY_KINDS = frozenset({"callback", "paraphrase"})
NEGATIVE_KIND = "negative"
MOOD_TRAP_KIND = "mood_trap"


def is_ranked_memory_case(case: dict) -> bool:
    """Callback/paraphrase (or any row with a gold memory). Not negatives or mood traps."""
    kind = str(case.get("kind") or "")
    if kind in RANKED_MEMORY_KINDS:
        return True
    if case.get("expect_empty") or kind in {NEGATIVE_KIND, MOOD_TRAP_KIND}:
        return False
    needles = case.get("expected_contains") or []
    ids = case.get("expected_entry_ids") or []
    return bool(needles or ids)


def _snippet_matches_gold(chunk, case: dict, entries: list[JournalEntry]) -> bool:
    content = (getattr(chunk, "content", "") or "").lower()
    needles = [str(item).lower() for item in (case.get("expected_contains") or []) if str(item).strip()]
    if needles:
        return any(needle in content for needle in needles)
    expected_ids = [str(item) for item in (case.get("expected_entry_ids") or [])]
    if not expected_ids:
        return False
    doc_id = str(getattr(chunk, "document_id", "") or getattr(chunk, "id", "") or "")
    if doc_id in expected_ids:
        return True
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
    return doc_id in expanded


def gold_rank(
    case: dict,
    chunks: list,
    *,
    entries: list[JournalEntry] | None = None,
) -> int | None:
    """1-based rank of the first gold journal snippet, or None if missing / not labeled."""
    if not is_ranked_memory_case(case):
        return None
    scored = snippets_for_journal_recall(chunks)
    for index, chunk in enumerate(scored, start=1):
        if _snippet_matches_gold(chunk, case, entries or []):
            return index
    return None


def hit_at_k(rank: int | None, k: int) -> float:
    if rank is None:
        return 0.0
    return 1.0 if rank <= k else 0.0


def reciprocal_rank(rank: int | None) -> float:
    """1.0 at rank 1, 0.5 at rank 2, 0 if missing. Not production MMR."""
    if rank is None or rank < 1:
        return 0.0
    return 1.0 / rank


def ranked_case_metrics(
    case: dict,
    chunks: list,
    *,
    entries: list[JournalEntry] | None = None,
) -> dict:
    kind = str(case.get("kind") or "")
    if is_ranked_memory_case(case):
        rank = gold_rank(case, chunks, entries=entries)
        return {
            "kind": kind or "memory",
            "gold_rank": rank,
            "hit_at_1": hit_at_k(rank, 1),
            "hit_at_3": hit_at_k(rank, 3),
            "reciprocal_rank": reciprocal_rank(rank),
        }
    journal_chunks = snippets_for_journal_recall(chunks)
    empty = not journal_chunks
    return {
        "kind": kind or ("negative" if case.get("expect_empty") else "other"),
        "gold_rank": None,
        "hit_at_1": None,
        "hit_at_3": None,
        "reciprocal_rank": None,
        "empty_retrieve": empty,
    }


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def summarize_ranked_metrics(cases: list[dict]) -> dict:
    """Headline Hit@k/MRR on callbacks+paraphrases only. Negatives and mood traps are separate rows."""
    by_kind: dict[str, list[dict]] = {}
    for row in cases:
        kind = str(row.get("kind") or "other")
        by_kind.setdefault(kind, []).append(row)

    def _hit_block(rows: list[dict]) -> dict:
        ranked = [row for row in rows if row.get("hit_at_1") is not None]
        return {
            "n": len(ranked),
            "hit_at_1": _mean([float(row["hit_at_1"]) for row in ranked]),
            "hit_at_3": _mean([float(row["hit_at_3"]) for row in ranked]),
            "mrr": _mean([float(row["reciprocal_rank"]) for row in ranked]),
        }

    memory_rows = [
        row
        for row in cases
        if row.get("kind") in RANKED_MEMORY_KINDS or row.get("hit_at_1") is not None
    ]
    # Avoid double-counting mood/negatives that slipped in with hit fields.
    memory_rows = [row for row in memory_rows if row.get("hit_at_1") is not None]

    kind_summaries: dict[str, dict] = {}
    for kind, rows in sorted(by_kind.items()):
        if kind == MOOD_TRAP_KIND:
            kind_summaries[kind] = {"n": len(rows), "note": "no gold day; Hit@k skipped"}
        elif kind == NEGATIVE_KIND:
            empties = [row for row in rows if row.get("empty_retrieve")]
            kind_summaries[kind] = {
                "n": len(rows),
                "empty_retrieves": len(empties),
                "empty_rate": (len(empties) / len(rows)) if rows else None,
            }
        else:
            kind_summaries[kind] = _hit_block(rows)

    negatives = by_kind.get(NEGATIVE_KIND, [])
    empty_n = sum(1 for row in negatives if row.get("empty_retrieve"))
    return {
        "memory_quality": _hit_block(memory_rows),
        "by_kind": kind_summaries,
        "negatives": {
            "n": len(negatives),
            "empty_retrieves": empty_n,
            "empty_rate": (empty_n / len(negatives)) if negatives else None,
            "note": (
                "Router should often never search journals; this is empty-retrieve "
                "when journal search was forced."
            ),
        },
        "mood_traps": {
            "n": len(by_kind.get(MOOD_TRAP_KIND, [])),
            "note": "No gold memory; Hit@k skipped. Snippet judge only.",
        },
    }


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


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_embed_cache() -> dict:
    if not EMBED_CACHE_PATH.exists():
        return {"model": "", "entries": {}}
    try:
        payload = json.loads(EMBED_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"model": "", "entries": {}}
    if not isinstance(payload, dict):
        return {"model": "", "entries": {}}
    payload.setdefault("entries", {})
    return payload


def _save_embed_cache(payload: dict) -> None:
    EMBED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMBED_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")


async def embed_journal_entries(entries: list[JournalEntry]) -> list[JournalEntry]:
    from config import settings
    from rag.embed import embed_query

    cache = _load_embed_cache()
    cache_model = str(cache.get("model") or "")
    if cache_model and cache_model != settings.gemini_embed_model:
        cache = {"model": settings.gemini_embed_model, "entries": {}}
    cache["model"] = settings.gemini_embed_model
    stored: dict = cache.setdefault("entries", {})

    total = len(entries)
    hits = 0
    misses = 0
    dirty = False
    for index, entry in enumerate(entries, start=1):
        digest = _content_hash(entry.content)
        cached = stored.get(entry.id) or {}
        vector = cached.get("vector") if cached.get("sha256") == digest else None
        if isinstance(vector, list) and vector:
            entry.embedding = [float(value) for value in vector]
            hits += 1
        else:
            entry.embedding = await asyncio.to_thread(embed_query, entry.content)
            stored[entry.id] = {"sha256": digest, "vector": entry.embedding}
            misses += 1
            dirty = True
        if dirty and (misses % 10 == 0 or index == total):
            _save_embed_cache(cache)
            dirty = False
        if index % 10 == 0 or index == total:
            print(f"  embedded {index}/{total} (cache hits={hits} new={misses})", flush=True)
    if dirty:
        _save_embed_cache(cache)
    if hits:
        print(f"  journal embed cache: reused {hits}, computed {misses}", flush=True)
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


def _search_query(query: str, history: list[dict[str, str]] | None) -> str:
    parts = []
    if history:
        parts.extend(
            entry.get("content", "")
            for entry in history
            if entry.get("role") == "user"
        )
    parts.append(query.strip())
    return " ".join(part for part in parts if part)


async def count_journal_chunks(user_id: str) -> int:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*)::int AS n
            FROM journal_chunks
            WHERE user_id = $1::uuid
            """,
            user_id,
        )
    return int(row["n"] or 0) if row else 0


async def journal_embedding_distinct_count(user_id: str) -> int:
    """How many unique stored vectors this user has. 1 means placeholder/mock ingest."""
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(DISTINCT embedding::text)::int AS n
            FROM journal_chunks
            WHERE user_id = $1::uuid
            """,
            user_id,
        )
    return int(row["n"] or 0) if row else 0


async def retrieve_production_journal(
    user_id: str,
    query: str,
    *,
    strategy_name: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[list[RetrievedChunk], list[str]]:
    """Same retrieval chat uses: journal MMR, or journal + clinical KB."""
    from rag.journal_retrieve import search_journal_chunks
    from rag.retrieve import RetrievalPlan, retrieve_with_strategy

    if strategy_name not in PROD_JOURNAL_STRATEGIES:
        raise ValueError(
            f"Unknown production journal strategy {strategy_name!r}. "
            f"Use one of: {', '.join(PROD_JOURNAL_STRATEGIES)}"
        )

    search_query = _search_query(query, history)
    if strategy_name == "journal_mmr":
        chunks = await search_journal_chunks(user_id, search_query, top_k=3)
    else:
        plan = RetrievalPlan(
            search_query=search_query,
            categories=(),
            reason="journal_eval_both",
        )
        kb_task = retrieve_with_strategy(query, history=history or [], plan=plan)
        journal_task = search_journal_chunks(user_id, search_query, top_k=3)
        (_, kb_chunks, _), journal_chunks = await asyncio.gather(kb_task, journal_task)
        chunks = kb_chunks[:2] + journal_chunks[:2]
    return chunks, entry_ids_from_chunks(chunks)
