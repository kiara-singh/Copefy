"""Load user profile preferences for generation."""

from __future__ import annotations

from agent.persona import UserPersona, normalize_style
from db import get_supabase


def load_user_persona(user_id: str) -> UserPersona:
    client = get_supabase()
    if client is None:
        return UserPersona()

    try:
        result = (
            client.table("profiles")
            .select("preferred_name, communication_style, wellness_goal, coaching_preferences")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        row = getattr(result, "data", None)
    except Exception:
        row = None

    if not row or not isinstance(row, dict):
        return UserPersona()

    return UserPersona(
        communication_style=normalize_style(row.get("communication_style")),
        preferred_name=row.get("preferred_name"),
        wellness_goal=row.get("wellness_goal"),
        coaching_preferences=row.get("coaching_preferences"),
    )
