"""Tests for Gemini chat model fallback selection."""

from agent.orchestrator import RETRYABLE_API_CODES, _chat_models, _should_try_next_model
from config import settings
from google.genai.errors import ServerError


def test_chat_models_dedupes_primary_and_fallbacks():
    models = _chat_models()
    assert models[0] == settings.gemini_chat_model
    assert len(models) == len(set(models))
    assert len(models) >= 2


def test_retryable_codes_include_transient_errors():
    assert 503 in RETRYABLE_API_CODES
    assert 429 in RETRYABLE_API_CODES
    assert 400 not in RETRYABLE_API_CODES
    assert 404 in RETRYABLE_API_CODES


def test_should_try_next_model_on_server_error():
    exc = ServerError(503, {"error": {"message": "high demand"}}, None)
    assert _should_try_next_model(exc) is True


def test_judge_models_include_fallbacks():
    from eval.judge import SKIP_MODEL_CODES, _judge_models

    models = _judge_models()
    assert models[0] == settings.agent_router_model
    assert len(models) == len(set(models))
    assert len(models) >= 2
    assert 404 in SKIP_MODEL_CODES
    assert "gemini-2.5-flash-lite" not in settings.agent_router_model_fallbacks_list
    assert "gemini-3.5-flash-lite" in settings.agent_router_model_fallbacks_list
