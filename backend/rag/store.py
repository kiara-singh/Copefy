"""asyncpg persistence for kb_documents and kb_chunks."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from urllib.parse import urlparse

import asyncpg

from rag import ANXIETY_SUBTYPES
from rag.chunking import TextChunk

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


@dataclass
class UpsertOutcome:
    document_id: str
    changed: bool
    chunk_count: int
    skipped: bool


class KnowledgeStore:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required for RAG storage")
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        # Same TLS contract as db.get_pool. asyncpg wants ssl=, not a DSN sslmode.
        self._pool = await asyncpg.create_pool(
            dsn=self.database_url,
            min_size=1,
            max_size=4,
            command_timeout=60,
            ssl="require",
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("KnowledgeStore is not connected")
        return self._pool

    async def get_existing_hash(self, source_url: str) -> str | None:
        row = await self.pool.fetchrow(
            "SELECT content_hash FROM kb_documents WHERE source_url = $1",
            source_url,
        )
        return None if row is None else str(row["content_hash"])

    async def get_active_source_urls(self) -> set[str]:
        """Return source_urls already stored as active (skip re-crawl by default)."""
        rows = await self.pool.fetch(
            "SELECT source_url FROM kb_documents WHERE status = 'active'"
        )
        return {str(r["source_url"]) for r in rows}

    async def upsert_document_with_chunks(
        self,
        *,
        source_url: str,
        source_type: str,
        title: str,
        category: str,
        categories: Sequence[str] | None = None,
        anxiety_subtype: str | None = None,
        markdown: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
        extra_metadata: dict[str, Any] | None = None,
    ) -> UpsertOutcome:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")

        digest = content_hash(markdown)
        domain = urlparse(source_url).netloc.lower()
        now = datetime.now(timezone.utc)
        label_categories = tuple(dict.fromkeys(categories or (category,)))

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    """
                    SELECT id, content_hash
                    FROM kb_documents
                    WHERE source_url = $1
                    """,
                    source_url,
                )

                if not chunks and not embeddings and existing:
                    await self._upsert_document_categories(
                        conn, existing["id"], category, label_categories
                    )
                    if anxiety_subtype is not None:
                        await conn.execute(
                            """
                            UPDATE kb_documents
                            SET anxiety_subtype = $2
                            WHERE id = $1 AND category = 'anxiety'
                            """,
                            existing["id"],
                            anxiety_subtype,
                        )
                    return UpsertOutcome(
                        document_id=str(existing["id"]),
                        changed=False,
                        chunk_count=0,
                        skipped=True,
                    )

                if not chunks:
                    raise ValueError("cannot upsert empty document without embeddings")

                if existing and existing["content_hash"] == digest:
                    # Estimate-only caches markdown as status='skipped' with the
                    # same content_hash. That must NOT skip when we finally have
                    # embeddings to write — otherwise paid embeds are thrown away.
                    row = await conn.fetchrow(
                        """
                        SELECT status,
                               (SELECT COUNT(*)::int FROM kb_chunks c WHERE c.document_id = d.id) AS chunk_n
                        FROM kb_documents d
                        WHERE d.id = $1
                        """,
                        existing["id"],
                    )
                    if (
                        row is not None
                        and row["status"] == "active"
                        and int(row["chunk_n"] or 0) > 0
                    ):
                        await self._upsert_document_categories(
                            conn, existing["id"], category, label_categories
                        )
                        return UpsertOutcome(
                            document_id=str(existing["id"]),
                            changed=False,
                            chunk_count=0,
                            skipped=True,
                        )
                    # Fall through: upgrade skipped/error cache rows (or active
                    # rows missing chunks) by writing embeddings below.

                if existing:
                    document_id = existing["id"]
                    await conn.execute(
                        """
                        UPDATE kb_documents
                        SET source_type = $2,
                            title = $3,
                            category = $4,
                            domain = $5,
                            content_hash = $6,
                            raw_markdown = $7,
                            anxiety_subtype = $9,
                            status = 'active',
                            crawled_at = $8,
                            updated_at = $8
                        WHERE id = $1
                        """,
                        document_id,
                        source_type,
                        title,
                        category,
                        domain,
                        digest,
                        markdown,
                        now,
                        anxiety_subtype,
                    )
                    await conn.execute(
                        "DELETE FROM kb_chunks WHERE document_id = $1",
                        document_id,
                    )
                else:
                    document_id = await conn.fetchval(
                        """
                        INSERT INTO kb_documents (
                            source_url, source_type, title, category, domain,
                            content_hash, raw_markdown, anxiety_subtype, status,
                            crawled_at, updated_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active', $9, $9)
                        RETURNING id
                        """,
                        source_url,
                        source_type,
                        title,
                        category,
                        domain,
                        digest,
                        markdown,
                        anxiety_subtype,
                        now,
                    )

                base_meta = {
                    "source_url": source_url,
                    "title": title,
                    "category": category,
                    "source_type": source_type,
                    **({"anxiety_subtype": anxiety_subtype} if anxiety_subtype else {}),
                    **(extra_metadata or {}),
                }

                for chunk, vector in zip(chunks, embeddings, strict=True):
                    metadata = {
                        **base_meta,
                        "chunk_index": chunk.index,
                    }
                    await conn.execute(
                        """
                        INSERT INTO kb_chunks (
                            document_id, chunk_index, content, token_estimate,
                            embedding, metadata
                        )
                        VALUES (
                            $1, $2, $3, $4, $5::vector, $6::jsonb
                        )
                        """,
                        document_id,
                        chunk.index,
                        chunk.content,
                        chunk.token_estimate,
                        _vector_literal(vector),
                        json.dumps(metadata),
                    )

                await self._upsert_document_categories(conn, document_id, category, label_categories)

                return UpsertOutcome(
                    document_id=str(document_id),
                    changed=True,
                    chunk_count=len(chunks),
                    skipped=False,
                )

    async def mark_error(
        self,
        source_url: str,
        category: str,
        source_type: str,
        error: str,
        *,
        title: str = "",
        markdown: str | None = None,
    ) -> None:
        """
        Mark a source as error without destroying useful crawled text.

        Transient failures (rate limits) should pass markdown so a later re-run
        can re-embed without re-crawling from a poisoned ERROR blob.
        """
        now = datetime.now(timezone.utc)
        domain = urlparse(source_url).netloc.lower()
        preserved = (markdown or "").strip()
        # Use a unique hash so the next successful crawl/embed is never treated
        # as "unchanged" against a previous error marker.
        digest = content_hash(preserved) if preserved else content_hash(f"error:{error}")
        body = preserved if preserved else f"ERROR: {error}"
        await self.pool.execute(
            """
            INSERT INTO kb_documents (
                source_url, source_type, title, category, domain,
                content_hash, raw_markdown, status, crawled_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'error', $8, $8)
            ON CONFLICT (source_url) DO UPDATE
            SET status = 'error',
                title = COALESCE(NULLIF(EXCLUDED.title, ''), kb_documents.title),
                updated_at = EXCLUDED.updated_at,
                raw_markdown = CASE
                    WHEN length(EXCLUDED.raw_markdown) > 0
                         AND EXCLUDED.raw_markdown NOT LIKE 'ERROR:%'
                    THEN EXCLUDED.raw_markdown
                    ELSE kb_documents.raw_markdown
                END,
                content_hash = EXCLUDED.content_hash
            """,
            source_url,
            source_type,
            title,
            category,
            domain,
            digest,
            body,
            now,
        )

    async def save_crawl_cache(
        self,
        *,
        source_url: str,
        source_type: str,
        title: str,
        category: str,
        markdown: str,
    ) -> None:
        """
        Persist crawled markdown as a status='skipped' row with no chunks.

        Used by --estimate-only so the later paid run can re-chunk from the DB
        instead of re-crawling. Never downgrades an active document.
        """
        now = datetime.now(timezone.utc)
        domain = urlparse(source_url).netloc.lower()
        await self.pool.execute(
            """
            INSERT INTO kb_documents (
                source_url, source_type, title, category, domain,
                content_hash, raw_markdown, status, crawled_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'skipped', $8, $8)
            ON CONFLICT (source_url) DO UPDATE
            SET title = COALESCE(NULLIF(EXCLUDED.title, ''), kb_documents.title),
                raw_markdown = EXCLUDED.raw_markdown,
                content_hash = EXCLUDED.content_hash,
                crawled_at = EXCLUDED.crawled_at,
                updated_at = EXCLUDED.updated_at,
                status = CASE
                    WHEN kb_documents.status = 'active' THEN 'active'
                    ELSE 'skipped'
                END
            """,
            source_url,
            source_type,
            title,
            category,
            domain,
            content_hash(markdown),
            markdown,
            now,
        )

    async def get_reusable_markdown(self, source_url: str) -> tuple[str, str] | None:
        """
        Return (title, markdown) cached by a previous estimate/error pass.

        Only non-active rows with real crawled text qualify; active documents
        are handled by the already-active skip in ingest.
        """
        row = await self.pool.fetchrow(
            """
            SELECT title, raw_markdown
            FROM kb_documents
            WHERE source_url = $1
              AND status IN ('skipped', 'error')
              AND raw_markdown IS NOT NULL
              AND raw_markdown NOT LIKE 'ERROR:%'
              AND length(raw_markdown) >= 200
            """,
            source_url,
        )
        if row is None:
            return None
        return str(row["title"] or ""), str(row["raw_markdown"])

    async def delete_error_rows(self) -> int:
        """Remove failed rows so the next ingest can recreate them cleanly."""
        result = await self.pool.execute(
            "DELETE FROM kb_documents WHERE status = 'error'"
        )
        # asyncpg returns strings like 'DELETE 3'
        try:
            return int(str(result).split()[-1])
        except (TypeError, ValueError, IndexError):
            return 0

    async def _upsert_document_categories(
        self,
        conn: asyncpg.Connection,
        document_id: object,
        primary: str,
        categories: Sequence[str],
    ) -> None:
        for cat in categories:
            await conn.execute(
                """
                INSERT INTO kb_document_categories (document_id, category, confidence, is_primary)
                VALUES ($1, $2, 1.0, $3)
                ON CONFLICT (document_id, category) DO UPDATE
                SET is_primary = EXCLUDED.is_primary
                """,
                document_id,
                cat,
                cat == primary,
            )

    async def count_active_labels_by_category(self) -> dict[str, int]:
        """Count active documents per category label (multi-label)."""
        rows = await self.pool.fetch(
            """
            SELECT dc.category, COUNT(DISTINCT d.id)::int AS n
            FROM kb_documents d
            JOIN kb_document_categories dc ON dc.document_id = d.id
            WHERE d.status = 'active'
            GROUP BY dc.category
            """
        )
        if rows:
            return {str(r["category"]): int(r["n"]) for r in rows}
        # Fallback before migration is applied.
        rows = await self.pool.fetch(
            """
            SELECT category, COUNT(*)::int AS n
            FROM kb_documents
            WHERE status = 'active'
            GROUP BY category
            """
        )
        return {str(r["category"]): int(r["n"]) for r in rows}

    async def count_active_anxiety_subtypes(self) -> dict[str, int]:
        rows = await self.pool.fetch(
            """
            SELECT anxiety_subtype, COUNT(*)::int AS n
            FROM kb_documents
            WHERE status = 'active'
              AND category = 'anxiety'
              AND anxiety_subtype IS NOT NULL
            GROUP BY anxiety_subtype
            """
        )
        out = {st: 0 for st in ANXIETY_SUBTYPES}
        for row in rows:
            out[str(row["anxiety_subtype"])] = int(row["n"])
        return out

    async def ensure_multilabel_schema(self) -> None:
        """Create junction table + multilabel match helper if not applied manually."""
        await self.pool.execute(
            """
            ALTER TABLE kb_documents
            ADD COLUMN IF NOT EXISTS anxiety_subtype TEXT
            """
        )
        await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_document_categories (
                document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                category TEXT NOT NULL CHECK (
                    category IN (
                        'adhd', 'depression', 'anxiety', 'ocd', 'ptsd'
                    )
                ),
                confidence REAL NOT NULL DEFAULT 1.0,
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (document_id, category)
            )
            """
        )
        await self.pool.execute(
            """
            CREATE INDEX IF NOT EXISTS kb_document_categories_category_idx
            ON kb_document_categories (category)
            """
        )
        await self.pool.execute(
            """
            INSERT INTO kb_document_categories (document_id, category, confidence, is_primary)
            SELECT id, category, 1.0, TRUE
            FROM kb_documents
            WHERE status = 'active'
            ON CONFLICT (document_id, category) DO NOTHING
            """
        )
        await self.pool.execute(
            """
            CREATE OR REPLACE FUNCTION match_kb_chunks(
                query_embedding vector(768),
                match_count INT DEFAULT 8,
                filter_category TEXT DEFAULT NULL
            )
            RETURNS TABLE (
                id UUID,
                document_id UUID,
                content TEXT,
                metadata JSONB,
                similarity FLOAT
            )
            LANGUAGE sql
            STABLE
            AS $$
                SELECT
                    c.id,
                    c.document_id,
                    c.content,
                    c.metadata,
                    1 - (c.embedding <=> query_embedding) AS similarity
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE d.status = 'active'
                  AND (
                      filter_category IS NULL
                      OR EXISTS (
                          SELECT 1 FROM kb_document_categories dc
                          WHERE dc.document_id = d.id AND dc.category = filter_category
                      )
                      OR (
                          NOT EXISTS (
                              SELECT 1 FROM kb_document_categories dc2
                              WHERE dc2.document_id = d.id
                          )
                          AND d.category = filter_category
                      )
                  )
                ORDER BY c.embedding <=> query_embedding
                LIMIT match_count;
            $$
            """
        )
