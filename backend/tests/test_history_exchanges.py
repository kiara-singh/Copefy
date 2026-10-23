"""Generation history is limited by user/assistant exchanges, not raw messages."""

from agent.orchestrator import (
    _build_user_prompt,
    _format_history,
    _group_exchanges,
    _recent_exchange_messages,
)
from agent.prompts import RECENT_FACT_REUSE_PROMPT
from config import settings


def _pair(user: str, assistant: str = "ok") -> list[dict[str, str]]:
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def test_recent_exchanges_preserve_order_and_pair_boundaries():
    history = []
    for i in range(5):
        history.extend(_pair(f"u{i}", f"a{i}"))

    recent = _recent_exchange_messages(history, exchange_limit=2)
    assert [m["content"] for m in recent] == ["u3", "a3", "u4", "a4"]
    assert len(_group_exchanges(recent)) == 2


def test_six_exchanges_still_drop_long_state_update():
    """11-turn state_* fixtures: update at turn 4, 10 prior exchanges on final turn."""
    history = []
    for text in (
        "nervous",
        "test",
        "Tuesday",
        "Friday now",
        "sneak back",
        "father",
        "tell him",
        "coat",
        "check first",
        "next step",
    ):
        history.extend(_pair(text))

    at_six = " ".join(m["content"] for m in _recent_exchange_messages(history, 6))
    at_eight = " ".join(m["content"] for m in _recent_exchange_messages(history, 8))
    assert "Friday" not in at_six
    assert "Friday" in at_eight


def test_default_exchange_limit_keeps_long_state_update():
    history = []
    for text in (
        "nervous",
        "test",
        "Tuesday",
        "It is Friday now.",
        "sneak back",
        "father",
        "tell him",
        "coat",
        "check first",
        "next step",
    ):
        history.extend(_pair(text))

    formatted = _format_history(history)
    assert "Friday" in formatted
    assert settings.chat_history_exchanges >= 7


def test_current_user_message_stays_separate():
    history = _pair("I am trying for ten this week.")
    prompt, _ = _build_user_prompt(
        "use the bedtime I switched to",
        history,
        [],
        None,
        None,
    )
    assert prompt.index("Recent conversation:") < prompt.index(
        "USER: use the bedtime I switched to"
    )
    assert RECENT_FACT_REUSE_PROMPT in prompt
    # History block should not duplicate the current user line.
    history_block = prompt.split("USER: use the bedtime I switched to")[0]
    assert "use the bedtime I switched to" not in history_block


def test_no_fact_reuse_instruction_without_history():
    prompt, _ = _build_user_prompt("hello", [], [], None, None)
    assert RECENT_FACT_REUSE_PROMPT not in prompt
