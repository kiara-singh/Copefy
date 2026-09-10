"""Tests for chat history titles."""

from chat_history import NEW_CHAT_TITLE, summarize_sessions, title_from_first_message


def test_title_truncates_long_first_message():
    long = "a" * 80
    title = title_from_first_message(long)
    assert title.endswith("…")
    assert len(title) == 48


def test_empty_title_is_new_chat():
    assert title_from_first_message(None) == NEW_CHAT_TITLE
    assert title_from_first_message("   ") == NEW_CHAT_TITLE


def test_summarize_uses_first_user_message():
    sessions = [{"id": "s1", "started_at": "2026-09-01T00:00:00Z"}]
    messages = [
        {"session_id": "s1", "role": "assistant", "content": "Hi", "created_at": "1"},
        {"session_id": "s1", "role": "user", "content": "I am stressed", "created_at": "2"},
        {"session_id": "s1", "role": "assistant", "content": "Tell me more", "created_at": "3"},
    ]
    rows = summarize_sessions(sessions, messages)
    assert rows[0]["title"] == "I am stressed"
    assert rows[0]["message_count"] == 3
    assert rows[0]["last_activity"] == "3"
