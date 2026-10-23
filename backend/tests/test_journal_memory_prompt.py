"""Deterministic tests for journal query, entry dates, and memory prompt."""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from agent.orchestrator import _build_user_prompt, run_agent
from agent.persona import UserPersona, build_system_instruction
from agent.prompts import JOURNAL_MEMORY_PROMPT
from agent.routers import get_router
from agent.tools.semantic_search import format_chunks_for_prompt, journal_entry_date_label
from rag.journal_retrieve import search_journal_chunks
from rag.retrieve import RetrievedChunk


def test_journal_search_sql_uses_entry_created_at_not_chunk_timestamp():
    source = inspect.getsource(search_journal_chunks)
    assert "JOIN journal_entries je ON je.id = jc.journal_entry_id" in source
    assert "je.created_at AS entry_created_at" in source
    assert "mmr_rerank_hits" in source
    assert "apply_min_similarity" in source
    assert "WHERE jc.user_id = $2::uuid" in source
    assert "FROM journal_chunks\n            WHERE user_id" not in source


def test_journal_entry_date_label():
    assert journal_entry_date_label("2026-06-20T12:00:00+00:00") == "2026-06-20"
    assert journal_entry_date_label(None) is None
    assert journal_entry_date_label("not-a-date") is None


def test_format_chunks_includes_journal_entry_date_only():
    journal = RetrievedChunk(
        content="My new mentor is Helen.",
        source_url=None,
        title="Personal Journal",
        category="journal",
        similarity=0.8,
        document_id="entry-1",
        created_at="2026-06-20T12:00:00+00:00",
    )
    clinical = RetrievedChunk(
        content="Generic anxiety psychoeducation.",
        source_url="https://example.test",
        title="KB",
        category="anxiety",
        similarity=0.8,
        document_id="kb-1",
        created_at="2026-06-20T12:00:00+00:00",
    )
    rendered = format_chunks_for_prompt([journal, clinical])
    assert "Personal Journal · 2026-06-20" in rendered
    assert "KB · 2026-06-20" not in rendered


def test_journal_memory_rule_only_when_flagged():
    plain = build_system_instruction(UserPersona())
    with_memory = build_system_instruction(UserPersona(), journal_memories=True)
    assert JOURNAL_MEMORY_PROMPT not in plain
    assert JOURNAL_MEMORY_PROMPT in with_memory


@pytest.mark.asyncio
async def test_journal_route_search_query_is_current_message_only():
    router = get_router("rule")
    current = (
        "I need to ask the person mentoring me now for feedback without apologizing "
        "for needing help. Can you help me draft the opening, using their name?"
    )
    decision = await router.decide(
        current,
        history=[
            {
                "role": "user",
                "content": (
                    "I need feedback at work and I am already rehearsing an apology "
                    "for asking. I do not want the first sentence to be me shrinking."
                ),
            },
            {"role": "assistant", "content": "What would you want the first sentence to be?"},
            {"role": "user", "content": "Every time I replay it I lose the details and then I freeze."},
        ],
    )
    assert decision.corpus == "journal"
    assert decision.search_query == current
    assert "shrinking" not in decision.search_query
    assert "freeze" not in decision.search_query


@pytest.mark.asyncio
async def test_run_agent_embeds_current_message_and_dates_journals():
    current = (
        "I need to ask the person mentoring me now for feedback without apologizing "
        "for needing help. Can you help me draft the opening, using their name?"
    )
    seen: dict[str, str] = {}

    async def fake_search(user_id, query, top_k=3):
        seen["query"] = query
        return [
            RetrievedChunk(
                content="Rosa retired. My new mentor is Helen.",
                source_url=None,
                title="Personal Journal",
                category="journal",
                similarity=0.7,
                document_id="entry-after",
                created_at="2026-06-20T12:00:00+00:00",
            )
        ]

    def fake_generate(prompt, system_instruction):
        seen["prompt"] = prompt
        seen["system"] = system_instruction
        return "Here is a draft.", "gemini-3.5-flash-lite"

    history = [
        {
            "role": "user",
            "content": "I need feedback at work and I am already rehearsing an apology for asking.",
        },
        {"role": "assistant", "content": "What would help?"},
    ]
    with (
        patch("agent.orchestrator.search_journal_chunks", side_effect=fake_search),
        patch("agent.orchestrator._generate_reply", side_effect=fake_generate),
    ):
        result = await run_agent(
            current,
            user_id="00000000-0000-0000-0000-000000000001",
            history=history,
        )

    assert seen["query"] == current
    assert "shrinking" not in seen["query"]
    assert "Personal Journal · 2026-06-20" in seen["prompt"]
    assert "<retrieved_journal>" in seen["prompt"]
    assert "untrusted reference data" in seen["prompt"]
    assert JOURNAL_MEMORY_PROMPT in seen["system"]
    assert result.sources[0]["created_at"] == "2026-06-20T12:00:00+00:00"


def test_user_prompt_journal_block_is_dated():
    chunk = RetrievedChunk(
        content="Dev chose nursing school instead.",
        source_url=None,
        title="Personal Journal",
        category="journal",
        similarity=0.9,
        created_at="2026-07-02T12:00:00+00:00",
    )
    prompt, _ = _build_user_prompt("help me ask about the program", [], [chunk], None, None)
    assert "User's past journal entries" in prompt
    assert "2026-07-02" in prompt
    assert "<retrieved_journal>" in prompt
    assert "untrusted reference data" in prompt
    assert prompt.index("<retrieved_journal>") < prompt.index("Dev chose nursing")
    assert prompt.index("Dev chose nursing") < prompt.index("</retrieved_journal>")


def _journal_row(user_id: str, similarity: float, content: str, suffix: str) -> dict:
    from datetime import datetime, timezone

    return {
        "id": f"00000000-0000-0000-0000-00000000000{suffix}",
        "journal_entry_id": f"11111111-1111-1111-1111-11111111111{suffix}",
        "user_id": user_id,
        "chunk_index": 0,
        "content": content,
        "similarity": similarity,
        "entry_created_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
    }


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _FakeConn:
    def __init__(self, rows_by_user: dict[str, list[dict]]):
        self.rows_by_user = rows_by_user
        self.seen_user_ids: list[str] = []

    async def fetch(self, sql, _literal, user_id, _limit):
        uid = str(user_id)
        self.seen_user_ids.append(uid)
        assert "WHERE jc.user_id = $2::uuid" in sql
        return list(self.rows_by_user.get(uid, []))


async def _search_with_rows(rows_by_user: dict[str, list[dict]], user_id: str, query: str = "current ask"):
    conn = _FakeConn(rows_by_user)
    pool = _FakePool(conn)

    async def fake_get_pool():
        return pool

    with (
        patch("rag.journal_retrieve.embed_query", return_value=[0.01] * 768),
        patch("db.get_pool", fake_get_pool),
    ):
        chunks = await search_journal_chunks(user_id, query, top_k=3)
    return chunks, conn


@pytest.mark.asyncio
async def test_journal_gate_keeps_chunks_at_or_above_threshold():
    user = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    chunks, _ = await _search_with_rows(
        {
            user: [
                _journal_row(user, 0.81, "strong current memory", "1"),
                _journal_row(user, 0.70, "borderline current memory", "2"),
            ]
        },
        user,
    )
    assert [round(chunk.similarity, 2) for chunk in chunks] == [0.81, 0.70]


@pytest.mark.asyncio
async def test_journal_gate_removes_low_score_chunks():
    user = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    chunks, _ = await _search_with_rows(
        {
            user: [
                _journal_row(user, 0.81, "keep me", "1"),
                _journal_row(user, 0.69, "drop me", "2"),
            ]
        },
        user,
    )
    assert len(chunks) == 1
    assert chunks[0].content == "keep me"


@pytest.mark.asyncio
async def test_journal_gate_allows_zero_chunks():
    user = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    chunks, _ = await _search_with_rows(
        {user: [_journal_row(user, 0.65, "nearest junk", "1")]},
        user,
    )
    assert chunks == []


@pytest.mark.asyncio
async def test_journal_gate_does_not_return_another_users_rows():
    owner = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    other = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    chunks, conn = await _search_with_rows(
        {
            owner: [_journal_row(owner, 0.82, "mine", "1")],
            other: [_journal_row(other, 0.99, "not mine", "9")],
        },
        owner,
    )
    assert conn.seen_user_ids == [owner]
    assert [chunk.content for chunk in chunks] == ["mine"]
    empty, conn_other = await _search_with_rows(
        {
            owner: [_journal_row(owner, 0.82, "mine", "1")],
            other: [_journal_row(other, 0.99, "not mine", "9")],
        },
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
    )
    assert empty == []
    assert "cccccccc-cccc-cccc-cccc-cccccccccccc" in conn_other.seen_user_ids

