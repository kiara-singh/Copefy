from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.orchestrator import run_agent
from agent.pipeline_trace import PipelineTrace
from agent.tools.web_search import (
    WEB_SEARCH_UNAVAILABLE_RESPONSE,
    GroundedSearchResult,
    MonthlyWebSearchBudget,
    WebSearchBudgetExceeded,
    WebSearchError,
    extract_grounding_sources,
    web_search,
)
from agent.types import AgentResult
from config import Settings


def _grounded_response(*sources: tuple[str, str]):
    chunks = [
        SimpleNamespace(web=SimpleNamespace(title=title, uri=url))
        for title, url in sources
    ]
    metadata = SimpleNamespace(grounding_chunks=chunks)
    return SimpleNamespace(
        text="A grounded answer.",
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
    )


def test_grounding_metadata_is_parsed_and_deduplicated():
    response = _grounded_response(
        ("First source", "https://example.com/one"),
        ("Duplicate", "https://example.com/one"),
        ("Second source", "https://example.com/two"),
    )

    assert extract_grounding_sources(response) == [
        {
            "title": "First source",
            "source_url": "https://example.com/one",
            "category": "web",
        },
        {
            "title": "Second source",
            "source_url": "https://example.com/two",
            "category": "web",
        },
    ]


def test_missing_grounding_metadata_returns_empty_sources():
    response = SimpleNamespace(text="Ungrounded text", candidates=[SimpleNamespace()])
    assert extract_grounding_sources(response) == []


def test_missing_grounding_metadata_is_not_returned_as_current_answer():
    class FakeModels:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(text="Potentially current answer", candidates=[])

    with pytest.raises(WebSearchError, match="missing_grounding"):
        web_search(
            client=SimpleNamespace(models=FakeModels()),
            model="grounded-model",
            query="current information",
            prompt="CURRENT USER REQUEST:\nWhat is current?",
            system_instruction="You are Copefy.",
        )


def test_web_search_uses_native_google_search_tool():
    calls: list[dict] = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return _grounded_response(("Example", "https://example.com"))

    result = web_search(
        client=SimpleNamespace(models=FakeModels()),
        model="grounded-model",
        query="current example information",
        prompt="CURRENT USER REQUEST:\nWhat is current?",
        system_instruction="You are Copefy.",
    )

    assert result.model == "grounded-model"
    assert result.sources[0]["source_url"] == "https://example.com"
    assert calls[0]["config"].tools[0].google_search is not None
    assert "Sanitized search intent: current example information" in calls[0]["contents"]


def test_web_search_defaults_to_dedicated_paid_gemini_3_1_flash_lite():
    assert (
        Settings.model_fields["gemini_web_search_model"].default
        == "gemini-3.1-flash-lite"
    )
    assert Settings.model_fields["gemini_web_search_api_key"].default == ""


def test_monthly_budget_is_persistent_and_fails_closed_at_limit(tmp_path):
    database = tmp_path / "web-usage.sqlite3"
    budget = MonthlyWebSearchBudget(
        database, monthly_query_budget=20, query_reservation=10
    )

    assert budget.reserve(month="2026-09") == 10
    assert budget.reserve(month="2026-09") == 20

    restarted_budget = MonthlyWebSearchBudget(
        database, monthly_query_budget=20, query_reservation=10
    )
    with pytest.raises(WebSearchBudgetExceeded, match="safety budget reached"):
        restarted_budget.reserve(month="2026-09")

    assert restarted_budget.reserve(month="2026-10") == 10


def test_budget_reservation_happens_before_provider_call(tmp_path):
    calls = 0

    class FakeModels:
        def generate_content(self, **_kwargs):
            nonlocal calls
            calls += 1
            return _grounded_response(("Example", "https://example.com"))

    budget = MonthlyWebSearchBudget(
        tmp_path / "web-usage.sqlite3",
        monthly_query_budget=10,
        query_reservation=10,
    )
    web_search(
        client=SimpleNamespace(models=FakeModels()),
        model="grounded-model",
        query="current information",
        prompt="CURRENT USER REQUEST:\nWhat is current?",
        system_instruction="You are Copefy.",
        usage_budget=budget,
    )

    with pytest.raises(WebSearchBudgetExceeded):
        web_search(
            client=SimpleNamespace(models=FakeModels()),
            model="grounded-model",
            query="another current question",
            prompt="CURRENT USER REQUEST:\nWhat else is current?",
            system_instruction="You are Copefy.",
            usage_budget=budget,
        )
    assert calls == 1


def test_normal_and_web_clients_use_strictly_separate_keys(monkeypatch):
    import agent.orchestrator as orchestrator

    created_with: list[str] = []

    def fake_client(*, api_key: str):
        created_with.append(api_key)
        return object()

    orchestrator._client.cache_clear()
    orchestrator._web_search_client.cache_clear()
    monkeypatch.setattr(orchestrator.genai, "Client", fake_client)
    monkeypatch.setattr(orchestrator.settings, "gemini_api_key", "normal-key")
    monkeypatch.setattr(
        orchestrator.settings, "gemini_web_search_api_key", "paid-web-key"
    )
    monkeypatch.setattr(orchestrator.settings, "gemini_web_search_enabled", True)

    assert orchestrator._client() is not orchestrator._web_search_client()
    assert created_with == ["normal-key", "paid-web-key"]

    orchestrator._client.cache_clear()
    orchestrator._web_search_client.cache_clear()


def test_web_client_fails_closed_when_disabled(monkeypatch):
    import agent.orchestrator as orchestrator

    orchestrator._web_search_client.cache_clear()
    monkeypatch.setattr(orchestrator.settings, "gemini_web_search_enabled", False)
    with pytest.raises(WebSearchError, match="disabled"):
        orchestrator._web_search_client()
    orchestrator._web_search_client.cache_clear()


@pytest.mark.asyncio
async def test_web_path_invokes_grounded_generation_not_normal_generation(monkeypatch):
    captured: dict = {}
    paid_client = object()
    usage_budget = object()

    def fake_web_search(**kwargs):
        captured.update(kwargs)
        return GroundedSearchResult(
            response="Current grounded answer.",
            model=kwargs["model"],
            sources=[
                {
                    "title": "Current source",
                    "source_url": "https://example.com/current",
                    "category": "web",
                }
            ],
        )

    monkeypatch.setattr("agent.orchestrator.web_search", fake_web_search)
    monkeypatch.setattr("agent.orchestrator._web_search_client", lambda: paid_client)
    monkeypatch.setattr(
        "agent.orchestrator._web_search_usage_budget", lambda: usage_budget
    )
    monkeypatch.setattr(
        "agent.orchestrator.settings.gemini_web_search_model", "gemini-3.1-flash-lite"
    )
    monkeypatch.setattr(
        "agent.orchestrator._generate_reply",
        lambda *_args: (_ for _ in ()).throw(AssertionError("normal generation called")),
    )

    result = await run_agent(
        "Look up the current Mental Health Awareness Week dates.",
        user_id="user-a",
    )

    assert result.path == "web_search"
    assert result.response == "Current grounded answer."
    assert result.model == "gemini-3.1-flash-lite"
    assert result.tool_status == "success"
    assert result.tools_used == ["web_search"]
    assert result.sources[0]["source_url"] == "https://example.com/current"
    assert captured["query"] == "the current mental health awareness week dates."
    assert captured["model"] == "gemini-3.1-flash-lite"
    assert captured["client"] is paid_client
    assert captured["usage_budget"] is usage_budget


@pytest.mark.asyncio
async def test_non_web_path_does_not_enable_google_search(monkeypatch):
    monkeypatch.setattr(
        "agent.orchestrator._web_search_client",
        lambda: (_ for _ in ()).throw(AssertionError("paid web client used")),
    )
    monkeypatch.setattr(
        "agent.orchestrator.web_search",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("web search called")),
    )
    monkeypatch.setattr(
        "agent.orchestrator._generate_reply",
        lambda *_args: ("Ordinary response.", "normal-model"),
    )

    result = await run_agent("I had a rough day and need to vent.", user_id="user-a")

    assert result.path == "direct_answer"
    assert result.response == "Ordinary response."
    assert result.sources == []


@pytest.mark.asyncio
async def test_web_provider_failure_returns_clear_unavailable_response(monkeypatch):
    monkeypatch.setattr("agent.orchestrator._web_search_client", lambda: object())
    monkeypatch.setattr(
        "agent.orchestrator._web_search_usage_budget", lambda: object()
    )
    monkeypatch.setattr(
        "agent.orchestrator.settings.gemini_web_search_model", "gemini-3.1-flash-lite"
    )
    monkeypatch.setattr(
        "agent.orchestrator.web_search",
        lambda **_kwargs: (_ for _ in ()).throw(WebSearchError("provider unavailable")),
    )
    monkeypatch.setattr(
        "agent.orchestrator._generate_reply",
        lambda *_args: (_ for _ in ()).throw(AssertionError("ungrounded fallback called")),
    )

    result = await run_agent("Search online for today's guidance.", user_id="user-a")

    assert result.response == WEB_SEARCH_UNAVAILABLE_RESPONSE
    assert result.tool_status == "unavailable"
    assert result.model is None
    assert result.sources == []


@pytest.mark.asyncio
async def test_chat_serializes_grounded_web_sources(monkeypatch):
    import main

    source = {
        "title": "Example source",
        "source_url": "https://example.com/source",
        "category": "web",
    }
    result = AgentResult(
        response="Grounded answer.",
        path="web_search",
        router="rule",
        route_reason="external_fact_lookup",
        sources=[source],
        tools_used=["web_search"],
        model="grounded-model",
        tool_status="success",
        pipeline=PipelineTrace(),
    )
    monkeypatch.setattr(main, "_require_supabase", lambda: object())
    monkeypatch.setattr(main, "_require_session_access", lambda *_args: "user-a")
    monkeypatch.setattr(main, "load_user_persona", lambda _user_id: None)
    monkeypatch.setattr(main, "_insert_message", lambda *_args: None)
    monkeypatch.setattr(
        main,
        "_load_session_history",
        lambda *_args: [{"role": "user", "content": "current information"}],
    )
    monkeypatch.setattr(main, "run_agent", AsyncMock(return_value=result))

    body = await main.chat(
        main.ChatRequest(session_id="session-a", message="current information"),
        user_id="user-a",
    )

    assert body["response"] == "Grounded answer."
    assert body["sources"] == [source]
