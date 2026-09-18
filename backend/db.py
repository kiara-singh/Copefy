"""Database / vector store access."""

from __future__ import annotations

import asyncio
from functools import lru_cache

import asyncpg
from supabase import Client, create_client

from config import settings

_pool: asyncpg.Pool | None = None
_pool_lock: asyncio.Lock | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


@lru_cache
def get_supabase() -> Client | None:
    """Return a cached Supabase client, or None if not configured yet."""
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _pool_is_stale(loop: asyncio.AbstractEventLoop) -> bool:
    if _pool is None:
        return False
    if _pool_loop is not loop:
        return True
    return bool(_pool_loop is not None and _pool_loop.is_closed())


async def _discard_pool() -> None:
    """Drop the cached pool. Terminate so a closed event loop cannot hang close()."""
    global _pool, _pool_lock, _pool_loop
    pool = _pool
    _pool = None
    _pool_lock = None
    _pool_loop = None
    if pool is None:
        return
    try:
        pool.terminate()
    except Exception:
        pass


async def get_pool() -> asyncpg.Pool:
    """Return a shared asyncpg pool for pgvector queries."""
    global _pool, _pool_lock, _pool_loop

    loop = asyncio.get_running_loop()
    if _pool_is_stale(loop):
        await _discard_pool()

    if _pool is not None:
        return _pool

    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for KB retrieval")

    if _pool_lock is None:
        _pool_lock = asyncio.Lock()

    async with _pool_lock:
        if _pool_is_stale(loop):
            await _discard_pool()
        if _pool is None:
            _pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=1,
                max_size=5,
                command_timeout=60,
                ssl="require",
            )
            _pool_loop = loop
    return _pool


async def close_pool() -> None:
    """Close the asyncpg pool (for tests / shutdown)."""
    await _discard_pool()
