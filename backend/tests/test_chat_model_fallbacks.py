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


def test_should_try_next_model_on_server_error():
    exc = ServerError(503, {"error": {"message": "high demand"}}, None)
    assert _should_try_next_model(exc) is True
