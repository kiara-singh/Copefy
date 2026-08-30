"""Resolve the authenticated user from a Supabase JWT."""

from __future__ import annotations

import logging

from db import get_supabase

logger = logging.getLogger(__name__)


def resolve_user_id(
    authorization: str | None,
    *,
    fallback_user_id: str | None = None,
) -> str | None:
    """Return the user id from a Bearer token.

    When a token is present but invalid, returns None (never silently falls back).
    When no token is sent, returns fallback_user_id for local scripts only.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return fallback_user_id

    token = authorization[7:].strip()
    if not token:
        return fallback_user_id

    client = get_supabase()
    if client is None:
        logger.warning("supabase not configured; cannot verify auth token")
        return None

    try:
        response = client.auth.get_user(token)
        if response and response.user:
            return str(response.user.id)
    except Exception:
        logger.warning("failed to verify auth token", exc_info=True)

    return None
