"""Helpers for listing chat sessions and deriving sidebar titles."""

from __future__ import annotations

TITLE_MAX = 48
NEW_CHAT_TITLE = "New chat"


def title_from_first_message(content: str | None) -> str:
    if not content or not str(content).strip():
        return NEW_CHAT_TITLE
    text = " ".join(str(content).split())
    if len(text) <= TITLE_MAX:
        return text
    return text[: TITLE_MAX - 1].rstrip() + "…"


def summarize_sessions(
    sessions: list[dict],
    messages: list[dict],
) -> list[dict]:
    """Build list payloads: title from first user message, last_activity from latest row."""
    by_session: dict[str, list[dict]] = {}
    for row in messages:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            continue
        by_session.setdefault(session_id, []).append(row)

    summaries: list[dict] = []
    for session in sessions:
        session_id = str(session["id"])
        rows = by_session.get(session_id, [])
        first_user = next(
            (row.get("content") for row in rows if row.get("role") == "user"),
            None,
        )
        last_activity = None
        if rows:
            last_activity = rows[-1].get("created_at")
        elif session.get("started_at"):
            last_activity = session.get("started_at")
        summaries.append(
            {
                "session_id": session_id,
                "title": title_from_first_message(first_user),
                "last_activity": last_activity,
                "message_count": len(rows),
            }
        )
    return summaries
