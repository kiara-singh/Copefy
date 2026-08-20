"""Shared vector search pipeline for all strategies."""

from __future__ import annotations

import asyncio

from rag.retrieve import (
    RetrievalPlan,
    RetrievedChunk,
    _rerank_hits,
    build_retrieval_plan,
)
from rag.search import KBChunkHit
from rag.strategies.base import StrategyConfig


async def _collect_hits(
    embedding: list[float],
    plan: RetrievalPlan,
    match_count: int,
) -> list[KBChunkHit]:
    from rag.search import search_kb_chunks

    all_hits: list[KBChunkHit] = []
    seen_ids: set[str] = set()

    categories_to_search = list(plan.categories) if plan.categories else [None]
    for category in categories_to_search:
        hits = await search_kb_chunks(
            embedding,
            match_count=match_count,
            filter_category=category,
        )
        for hit in hits:
            if hit.id not in seen_ids:
                seen_ids.add(hit.id)
                all_hits.append(hit)

    if len(all_hits) < 5:
        for hit in await search_kb_chunks(
            embedding,
            match_count=match_count,
            filter_category=None,
        ):
            if hit.id not in seen_ids:
                seen_ids.add(hit.id)
                all_hits.append(hit)

    return all_hits


def _tokenize(text: str) -> set[str]:
    import re

    return {token for token in re.findall(r"[a-z0-9']+", text.lower()) if len(token) > 2}


def _jaccard(a: KBChunkHit, b: KBChunkHit) -> float:
    ta, tb = _tokenize(a.content), _tokenize(b.content)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def mmr_rerank_hits(
    hits: list[KBChunkHit],
    top_k: int,
    *,
    lambda_mult: float = 0.7,
) -> list[KBChunkHit]:
    """Diversity rerank using relevance + token Jaccard against selected chunks."""
    if not hits:
        return []

    remaining = sorted(hits, key=lambda h: h.similarity, reverse=True)
    selected: list[KBChunkHit] = []

    while remaining and len(selected) < top_k:
        best_idx = 0
        best_score = float("-inf")
        for idx, hit in enumerate(remaining):
            relevance = hit.similarity
            if selected:
                diversity = max(_jaccard(hit, chosen) for chosen in selected)
                score = lambda_mult * relevance - (1 - lambda_mult) * diversity
            else:
                score = relevance
            if score > best_score:
                best_score = score
                best_idx = idx
        selected.append(remaining.pop(best_idx))

    return selected


def apply_min_similarity(
    hits: list[KBChunkHit],
    min_similarity: float | None,
) -> list[KBChunkHit]:
    """Drop hits below a similarity cutoff. None means keep everything."""
    if min_similarity is None:
        return hits
    return [hit for hit in hits if hit.similarity >= min_similarity]


def hits_to_chunks(hits: list[KBChunkHit], inject_k: int) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            content=hit.content,
            source_url=hit.source_url,
            title=hit.title,
            category=hit.category,
            similarity=hit.similarity,
        )
        for hit in hits[:inject_k]
    ]


async def run_strategy_pipeline(
    user_message: str,
    *,
    history: list[dict[str, str]] | None,
    config: StrategyConfig,
    rerank_mode: str = "heuristic",
    plan: RetrievalPlan | None = None,
) -> tuple[RetrievalPlan, list[RetrievedChunk], dict]:
    # The router already decided to search; it passes the plan it built. Callers
    # without a router (the Layer 3 eval scripts) get one built here.
    from rag.embed import embed_query

    plan = plan or build_retrieval_plan(user_message, history)

    embedding = await asyncio.to_thread(embed_query, plan.search_query)
    all_hits = await _collect_hits(embedding, plan, config.match_count)

    if rerank_mode == "mmr":
        ranked = mmr_rerank_hits(all_hits, config.top_k, lambda_mult=config.mmr_lambda)
    else:
        ranked = _rerank_hits(plan.search_query, all_hits, config.top_k)

    ranked = apply_min_similarity(ranked, config.min_similarity)

    chunks = hits_to_chunks(ranked, config.inject_k)
    meta = {
        "match_count": config.match_count,
        "top_k": config.top_k,
        "rerank_mode": rerank_mode,
        "candidates": len(all_hits),
    }
    return plan, chunks, meta
