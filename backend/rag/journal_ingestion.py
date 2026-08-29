"""Journal Entry Ingestion Pipeline.

Processes journal entries into structure-aware chunks, generates 768-dim Gemini
embeddings, and idempotently stores retrieval units in journal_chunks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rag.embed import embed_query
from rag.journal_chunking import chunk_journal_entry
from rag.search import _vector_literal

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """Raised when journal entry ingestion fails."""


async def ensure_journal_chunks_table(conn: Any) -> None:
    """Ensure vector extension, journal_chunks table, and indexes exist in PostgreSQL."""
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            journal_entry_id UUID NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            chunk_index INT NOT NULL,
            content TEXT NOT NULL,
            embedding vector(768) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_journal_chunks_user_id ON journal_chunks(user_id);
        CREATE INDEX IF NOT EXISTS idx_journal_chunks_entry_id ON journal_chunks(journal_entry_id);
        """
    )


async def ingest_journal_entry_asyncpg(
    conn: Any,
    journal_entry_id: str,
    user_id: str,
    content: str,
) -> list[dict[str, Any]]:
    """Ingest a journal entry into journal_chunks via an asyncpg connection.

    Idempotent: deletes prior chunks for journal_entry_id before inserting new ones.
    """
    await ensure_journal_chunks_table(conn)

    cleaned_content = content.strip()
    if not cleaned_content:
        # Delete existing chunks if content is empty
        await conn.execute(
            "DELETE FROM journal_chunks WHERE journal_entry_id = $1::uuid",
            journal_entry_id,
        )
        return []

    # 1. Structure-aware chunking
    chunk_texts = chunk_journal_entry(cleaned_content)
    if not chunk_texts:
        return []

    # 2. Generate 768-dim embeddings using shared embed_query
    embeddings: list[list[float]] = []
    for text in chunk_texts:
        try:
            vec = await asyncio.to_thread(embed_query, text)
            embeddings.append(vec)
        except Exception as err:
            raise IngestionError(
                f"Failed to generate embedding for journal_entry_id {journal_entry_id}: {err}"
            ) from err

    # 3. Delete prior chunks for idempotency
    await conn.execute(
        "DELETE FROM journal_chunks WHERE journal_entry_id = $1::uuid",
        journal_entry_id,
    )

    # 4. Insert new chunks
    inserted: list[dict[str, Any]] = []
    for idx, (text, vec) in enumerate(zip(chunk_texts, embeddings)):
        literal = _vector_literal(vec)
        row = await conn.fetchrow(
            """
            INSERT INTO journal_chunks (journal_entry_id, user_id, chunk_index, content, embedding)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::vector)
            RETURNING id, journal_entry_id, user_id, chunk_index, content, created_at
            """,
            journal_entry_id,
            user_id,
            idx,
            text,
            literal,
        )
        if not row:
            raise IngestionError(
                f"Database insert returned no row for chunk_index {idx} of entry {journal_entry_id}"
            )
        inserted.append(dict(row))

    logger.info(
        "Ingested journal entry %s for user %s into %d chunks",
        journal_entry_id,
        user_id,
        len(inserted),
    )
    return inserted


async def ingest_journal_entry(
    journal_entry_id: str,
    user_id: str,
    content: str,
) -> list[dict[str, Any]]:
    """Ingest a journal entry into journal_chunks using the shared asyncpg pool."""
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await ingest_journal_entry_asyncpg(
            conn, journal_entry_id, user_id, content
        )
