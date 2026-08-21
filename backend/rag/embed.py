"""Gemini query embeddings for KB retrieval."""

from __future__ import annotations

import re
import time
from functools import lru_cache

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from config import settings

EMBED_DIMENSIONS = 768
_MAX_RETRIES = 6
_MIN_EMBED_INTERVAL_S = 0.7  # ~85 req/min, under free-tier 100/min
_last_embed_at = 0.0


class EmbeddingError(RuntimeError):
    """Raised when the embedding API fails."""


@lru_cache
def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise EmbeddingError("GEMINI_API_KEY is required for embeddings")
    return genai.Client(api_key=settings.gemini_api_key)


def _rate_limit() -> None:
    global _last_embed_at
    now = time.monotonic()
    wait = _MIN_EMBED_INTERVAL_S - (now - _last_embed_at)
    if wait > 0:
        time.sleep(wait)
    _last_embed_at = time.monotonic()


def _retry_delay_seconds(error: ClientError, attempt: int) -> float:
    match = re.search(r"retry in ([\d.]+)s", str(error).lower())
    if match:
        return float(match.group(1)) + 1.0
    return min(90.0, 15.0 * (attempt + 1))


def _call_embed_api(cleaned: str) -> list[float]:
    client = _client()
    last_error: ClientError | None = None

    for attempt in range(_MAX_RETRIES):
        _rate_limit()
        try:
            response = client.models.embed_content(
                model=settings.gemini_embed_model,
                contents=cleaned,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMENSIONS),
            )
        except ClientError as exc:
            last_error = exc
            if exc.code == 429 and attempt < _MAX_RETRIES - 1:
                time.sleep(_retry_delay_seconds(exc, attempt))
                continue
            raise EmbeddingError(f"Embedding API error: {exc}") from exc

        if not response.embeddings:
            raise EmbeddingError("Embedding API returned no embeddings")

        values = response.embeddings[0].values
        if values is None:
            raise EmbeddingError("Embedding API returned null values")

        vector = list(values)
        if len(vector) != EMBED_DIMENSIONS:
            raise EmbeddingError(
                f"Expected {EMBED_DIMENSIONS}-d embedding, got {len(vector)}"
            )
        return vector

    if last_error is not None:
        raise EmbeddingError(f"Embedding API rate-limited after retries: {last_error}") from last_error
    raise EmbeddingError("Embedding API failed after retries")


@lru_cache(maxsize=1024)
def _embed_cached(cleaned: str) -> tuple[float, ...]:
    return tuple(_call_embed_api(cleaned))


def embed_query(text: str) -> list[float]:
    """Embed a single query string (768-dim, gemini-embedding-2). Cached per process."""
    cleaned = text.strip()
    if not cleaned:
        raise EmbeddingError("Cannot embed empty text")
    return list(_embed_cached(cleaned))


def clear_embed_cache() -> None:
    """Clear in-process embedding cache (useful between eval runs)."""
    _embed_cached.cache_clear()
