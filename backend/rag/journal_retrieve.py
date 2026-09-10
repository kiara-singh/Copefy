"""User-isolated vector retrieval over journal_chunks.

Strictly filters by authenticated user_id in the database query and applies MMR
reranking consistent with Layer 3 clinical KB retrieval.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rag.embed import embed_query
from rag.retrieve import RetrievedChunk
from rag.search import KBChunkHit, _vector_literal
from rag.strategies.pipeline import mmr_rerank_hits


async def search_journal_chunks(
    user_id: str,
    query: str,
    *,
    match_count: int = 15,
    top_k: int = 5,
    mmr_lambda: float = 0.7,
) -> list[RetrievedChunk]:
    """Execute vector search over journal_chunks filtered strictly by user_id.

    Reuses MMR reranking to balance relevance and diversity.
    """
    cleaned_query = query.strip()
    if not cleaned_query or not user_id:
        return []

    # 1. Embed query string using shared embed_query (768-dim)
    query_embedding = await asyncio.to_thread(embed_query, cleaned_query)
    literal = _vector_literal(query_embedding)

    # 2. Execute pgvector search with STRICT DB-level user_id filtering
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, journal_entry_id, user_id, chunk_index, content,
                   1 - (embedding <=> $1::vector) AS similarity, created_at
            FROM journal_chunks
            WHERE user_id = $2::uuid
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            literal,
            user_id,
            match_count,
        )

    if not rows:
        return []

    # 3. Map to KBChunkHit structure for MMR reranking compatibility
    hits: list[KBChunkHit] = [
        KBChunkHit(
            id=str(row["id"]),
            document_id=str(row["journal_entry_id"]),
            content=row["content"],
            metadata={"chunk_index": row["chunk_index"], "user_id": str(row["user_id"])},
            similarity=float(row["similarity"]),
            title="Personal Journal",
            source_url=None,
            category="journal",
        )
        for row in rows
    ]

    # 4. Apply standard Layer 3 MMR reranking
    reranked = mmr_rerank_hits(hits, top_k=top_k, lambda_mult=mmr_lambda)

    # 5. Convert to RetrievedChunk instances tagged as 'journal'
    return [
        RetrievedChunk(
            content=hit.content,
            source_url=hit.source_url,
            title=hit.title,
            category="journal",
            similarity=hit.similarity,
            document_id=hit.document_id,
        )
        for hit in reranked
    ]
