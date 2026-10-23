"""Gemini embedding client for Copefy RAG ingest."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Sequence

from google import genai
from google.genai import types
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tqdm import tqdm

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when the embedding API fails after retries."""


def _is_rate_limited(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "429" in text or "resource_exhausted" in text or "too many requests" in text:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status == 429


def _should_retry(exc: BaseException) -> bool:
    if _is_rate_limited(exc):
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in ("timeout", "temporarily", "unavailable", "503", "500")
    )


class GeminiEmbedder:
    """
    Embedder using gemini-embedding-2 at a fixed output dimensionality.

    Embeds one text per request. Passing a Python list to embed_content for
    gemini-embedding-2 often returns a single combined embedding, which broke
    ingest with "got 1 for N texts". One-at-a-time is also gentler on free tier.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-embedding-2",
        dimensions: int = 768,
        batch_size: int = 8,
        max_concurrency: int = 1,
        inter_batch_delay_seconds: float = 2.0,
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for embeddings")
        self.model = model
        self.dimensions = dimensions
        # batch_size kept for logging progress only; requests are 1 text each.
        self.batch_size = max(1, batch_size)
        self.inter_batch_delay_seconds = max(0.0, inter_batch_delay_seconds)
        # Global cap on in-flight embed requests across all documents.
        # Free tier should stay at 1; paid tier can raise EMBED_CONCURRENCY.
        self.max_concurrency = max(1, max_concurrency)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._client = genai.Client(api_key=api_key)

    def _embed_one_sync(self, text: str) -> list[float]:
        # Same request shape as rag.embed.embed_query (gemini-embedding-2, 768 dims).
        # Query-time clinical search uses that call, so document vectors stay in
        # the space match_kb_chunks compares with cosine distance.
        response = self._client.models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )
        vectors = self._vectors_from_response(response, expected=1)
        return vectors[0]

    def _vectors_from_response(self, response: object, *, expected: int) -> list[list[float]]:
        embeddings = getattr(response, "embeddings", None)
        if not embeddings:
            single = getattr(response, "embedding", None)
            embeddings = [single] if single is not None else None
        if not embeddings:
            raise EmbeddingError("Embedding API returned no embeddings")

        vectors: list[list[float]] = []
        for item in embeddings:
            values = list(getattr(item, "values", None) or [])
            if len(values) != self.dimensions:
                raise EmbeddingError(
                    f"Expected {self.dimensions}-d embedding, got {len(values)}"
                )
            vectors.append(values)
        if len(vectors) != expected:
            raise EmbeddingError(
                f"Embedding count mismatch: got {len(vectors)} for {expected} texts"
            )
        return vectors

    @retry(
        retry=retry_if_exception(_should_retry),
        wait=wait_exponential_jitter(initial=8, max=180),
        stop=stop_after_attempt(12),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _embed_one(self, text: str) -> list[float]:
        async with self._semaphore:
            if self.max_concurrency == 1:
                await asyncio.sleep(random.uniform(0.15, 0.4))
            else:
                await asyncio.sleep(random.uniform(0.02, 0.1))
            return await asyncio.to_thread(self._embed_one_sync, text)

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed many texts. Parallelizes up to max_concurrency when > 1."""
        if not texts:
            return []

        total = len(texts)
        show_bar = total > 5
        progress = (
            tqdm(
                total=total,
                desc="Embed",
                unit="chunk",
                leave=False,
                dynamic_ncols=True,
            )
            if show_bar
            else None
        )

        async def _one(index: int, text: str) -> tuple[int, list[float]]:
            try:
                vector = await self._embed_one(text)
            except Exception as exc:  # noqa: BLE001
                if _is_rate_limited(exc):
                    logger.error(
                        "Still rate-limited after retries at chunk %s/%s. "
                        "Wait a few minutes and re-run with --clear-errors.",
                        index + 1,
                        total,
                    )
                logger.error("Embedding failed at chunk %s/%s: %s", index + 1, total, exc)
                raise EmbeddingError(str(exc)) from exc
            if progress is not None:
                progress.update(1)
            elif (index + 1) % self.batch_size == 0 or index + 1 == total:
                logger.info("Embedded %s/%s texts", index + 1, total)
            if self.inter_batch_delay_seconds:
                await asyncio.sleep(self.inter_batch_delay_seconds)
            return index, vector

        try:
            if self.max_concurrency == 1:
                ordered: list[list[float]] = []
                for index, text in enumerate(texts):
                    _, vector = await _one(index, text)
                    ordered.append(vector)
                return ordered

            results = await asyncio.gather(
                *(_one(index, text) for index, text in enumerate(texts))
            )
            results_sorted = sorted(results, key=lambda item: item[0])
            return [vector for _, vector in results_sorted]
        finally:
            if progress is not None:
                progress.close()
