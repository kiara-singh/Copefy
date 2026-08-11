"""pgvector search against the medical knowledge base."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db import get_pool


@dataclass(frozen=True)
class KBChunkHit:
    id: str
    document_id: str
    content: str
    metadata: dict[str, Any]
    similarity: float
    title: str | None
    source_url: str | None
    category: str | None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


async def search_kb_chunks(
    query_embedding: list[float],
    *,
    match_count: int = 20,
    filter_category: str | None = None,
) -> list[KBChunkHit]:
    """Run match_kb_chunks and enrich results with document metadata."""
    pool = await get_pool()
    literal = _vector_literal(query_embedding)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, document_id, content, metadata, similarity
            FROM match_kb_chunks($1::vector, $2, $3)
            """,
            literal,
            match_count,
            filter_category,
        )

        if not rows:
            return []

        doc_ids = list({str(row["document_id"]) for row in rows})
        doc_rows = await conn.fetch(
            """
            SELECT id, title, source_url, category
            FROM kb_documents
            WHERE id = ANY($1::uuid[])
            """,
            doc_ids,
        )

    docs = {str(row["id"]): row for row in doc_rows}
    hits: list[KBChunkHit] = []

    for row in rows:
        doc = docs.get(str(row["document_id"]))
        metadata = row["metadata"] or {}
        if isinstance(metadata, str):
            metadata = {}

        hits.append(
            KBChunkHit(
                id=str(row["id"]),
                document_id=str(row["document_id"]),
                content=row["content"],
                metadata=dict(metadata),
                similarity=float(row["similarity"]),
                title=doc["title"] if doc else None,
                source_url=doc["source_url"] if doc else None,
                category=doc["category"] if doc else None,
            )
        )

    return hits
