from pathlib import Path

from eval.query_embed_cache import cache_key, cached_embed_query, load_cache
from rag.embed import EMBED_DIMENSIONS


def test_query_embed_cache_reuses_disk_vector(tmp_path: Path):
    path = tmp_path / "query_embeddings.json"
    fake = [0.01] * EMBED_DIMENSIONS
    calls = {"n": 0}

    def fake_embed(text: str) -> list[float]:
        calls["n"] += 1
        return fake

    import eval.query_embed_cache as cache_mod

    original = cache_mod.embed_query
    cache_mod.embed_query = fake_embed
    try:
        first = cached_embed_query("same question twice", path=path)
        second = cached_embed_query("same question twice", path=path)
    finally:
        cache_mod.embed_query = original

    assert first == fake
    assert second == fake
    assert calls["n"] == 1
    stored = load_cache(path)
    assert cache_key("same question twice") in stored["vectors"]
