"""Gemini speech-to-text for audio journals.

Transcription is the only new model call. The resulting text reuses the existing
journal chunker and gemini-embedding-2 pipeline. This module is not invoked by
unit tests; they stub transcribe_audio.
"""

from __future__ import annotations

from functools import lru_cache

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from config import settings

TRANSCRIBE_PROMPT = (
    "Transcribe this audio journal entry verbatim. "
    "Return only the spoken words, with normal punctuation. "
    "Do not summarize, translate, or add commentary."
)


class TranscriptionError(RuntimeError):
    """Raised when audio transcription fails or yields no usable text."""


@lru_cache
def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise TranscriptionError("GEMINI_API_KEY is required for audio transcription")
    return genai.Client(api_key=settings.gemini_api_key)


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Return a non-empty transcript for inline audio bytes."""
    if not audio_bytes:
        raise TranscriptionError("Audio file is empty")

    try:
        response = _client().models.generate_content(
            model=settings.gemini_transcribe_model,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                TRANSCRIBE_PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=8192,
            ),
        )
    except ClientError as exc:
        raise TranscriptionError(f"Transcription API error: {exc}") from exc
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise TranscriptionError("Transcription returned no text")
    return text
