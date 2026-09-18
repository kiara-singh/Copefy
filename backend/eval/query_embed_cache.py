"""Disk cache for eval/diagnostic query embeddings.

Reuse the same question vector across bake-offs. Do not use this on the live
chat path — user messages should not be written to disk from production.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config import settings
from rag.embed import EMBED_DIMENSIONS, embed_query

CACHE_PATH = Path(__file__).resolve().parent / "cache" / "query_embeddings.json"


def cache_key(text: str, *, model: str | None = None, dimensions: int = EMBED_DIMENSIONS) -> str:
    payload = {
        "text": text,
        "model": model or settings.gemini_embed_model,
        "dimensions": dimensions,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_cache(path: Path = CACHE_PATH) -> dict:
    if not path.exists():
        return {"schema_version": 1, "vectors": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "vectors": {}}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "vectors": {}}
    payload.setdefault("vectors", {})
    return payload


def save_cache(payload: dict, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    temp.replace(path)


def cached_embed_query(text: str, *, path: Path = CACHE_PATH) -> list[float]:
    """Return a 768-d query embedding, calling Gemini only on a cache miss."""
    cleaned = text.strip()
    key = cache_key(cleaned)
    payload = load_cache(path)
    vectors = payload["vectors"]
    hit = vectors.get(key)
    if isinstance(hit, list) and len(hit) == EMBED_DIMENSIONS:
        return [float(value) for value in hit]
    vector = embed_query(cleaned)
    vectors[key] = vector
    save_cache(payload, path)
    return vector
