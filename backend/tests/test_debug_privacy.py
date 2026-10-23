"""Public debug traces must not leak retrieved journal or clinical text."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agent.pipeline_trace import LayerStep, PipelineTrace
from agent.types import AgentResult, strip_retrieved_text
from main import app

client = TestClient(app)

TEST_USER_ID = "11111111-2222-3333-4444-555555555555"
SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "I hid the pills in the garage behind the winter coats."


def _result_with_secret() -> AgentResult:
    pipeline = PipelineTrace()
    pipeline.layers.append(
        LayerStep(
            layer=3,
            name="retrieval",
            decision="journal_mmr",
            details={
                "sources": [
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "entry-1",
                        "category": "journal",
                        "similarity": 0.91,
                        "created_at": "2026-06-20T12:00:00+00:00",
                        "preview": SECRET,
                        "excerpt": SECRET,
                    }
                ]
            },
        )
    )
    return AgentResult(
        response="I'm here with you.",
        path="search_database",
        router="rule",
        route_reason="journal_memory_recall",
        kb_used=True,
        sources=[
            {
                "chunk_id": "chunk-1",
                "document_id": "entry-1",
                "title": "Personal Journal",
                "category": "journal",
                "similarity": 0.91,
                "created_at": "2026-06-20T12:00:00+00:00",
                "preview": SECRET,
                "excerpt": SECRET,
            }
        ],
        pipeline=pipeline,
    )


def test_internal_debug_keeps_retrieved_text_for_eval():
    result = _result_with_secret()
    full = result.to_debug_dict()
    assert SECRET in str(full)
    assert full["sources"][0]["excerpt"] == SECRET


def test_public_debug_strips_retrieved_text_keeps_metadata():
    result = _result_with_secret()
    public = result.to_public_debug_dict()
    dumped = str(public)
    assert SECRET not in dumped
    assert "excerpt" not in dumped
    assert "preview" not in dumped
    source = public["sources"][0]
    assert source["chunk_id"] == "chunk-1"
    assert source["document_id"] == "entry-1"
    assert source["category"] == "journal"
    assert source["similarity"] == 0.91
    assert source["created_at"] == "2026-06-20T12:00:00+00:00"
    layer_sources = public["pipeline"]["layers"][0]["sources"]
    assert layer_sources[0]["chunk_id"] == "chunk-1"
    assert "excerpt" not in layer_sources[0]


def test_strip_retrieved_text_helper():
    cleaned = strip_retrieved_text({"excerpt": "secret", "path": "crisis"})
    assert cleaned == {"path": "crisis"}


def _auth_supabase():
    mock_supabase = MagicMock()
    mock_user = MagicMock()
    mock_user.id = TEST_USER_ID
    mock_user_res = MagicMock()
    mock_user_res.user = mock_user
    mock_supabase.auth.get_user.return_value = mock_user_res
    mock_select = MagicMock()
    mock_select.maybe_single.return_value.execute.return_value = MagicMock(
        data={"user_id": TEST_USER_ID}
    )
    mock_supabase.table("sessions").select.return_value.eq.return_value = mock_select
    return mock_supabase


@patch("main.load_user_persona")
@patch("main.run_agent")
@patch("main.get_supabase")
def test_chat_http_debug_omits_retrieved_text(mock_get_supabase, mock_run_agent, mock_persona):
    mock_get_supabase.return_value = _auth_supabase()
    mock_persona.return_value = None

    async def fake_agent(*_args, **_kwargs):
        return _result_with_secret()

    mock_run_agent.side_effect = fake_agent
    headers = {"Authorization": "Bearer valid_token"}
    res = client.post(
        "/chat",
        json={"session_id": SESSION_ID, "message": "what did I write", "debug": True},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["response"] == "I'm here with you."
    assert SECRET not in str(body)
    trace = body["trace"]
    assert trace["path"] == "search_database"
    assert trace["sources"][0]["chunk_id"] == "chunk-1"
    assert "excerpt" not in trace["sources"][0]
    assert "preview" not in trace["sources"][0]
