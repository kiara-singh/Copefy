"""Audio journal upload, private storage, transcription, then text ingestion."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from rag.audio_transcribe import TranscriptionError, transcribe_audio
from rag.journal_ingestion import ingest_journal_entry

logger = logging.getLogger(__name__)

JOURNAL_AUDIO_BUCKET = "journal-audio"
MAX_AUDIO_JOURNAL_SIZE = 10 * 1024 * 1024  # 10 MB

# Audio only. Video containers and video/* MIME types are rejected.
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}
_AUDIO_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/ogg",
    "audio/webm",
    "audio/flac",
    "audio/x-flac",
}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


class AudioJournalError(RuntimeError):
    """User-facing audio journal validation or persistence failure."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _suffix(filename: str) -> str:
    lower = filename.lower()
    dot = lower.rfind(".")
    return lower[dot:] if dot >= 0 else ""


def normalize_audio_mime(filename: str, content_type: str | None) -> str:
    suffix = _suffix(filename)
    if suffix in _VIDEO_EXTENSIONS:
        raise AudioJournalError("Video journals are not supported.")
    if suffix and suffix not in _AUDIO_EXTENSIONS:
        raise AudioJournalError(
            "Invalid file format. Supported audio: .wav, .mp3, .m4a, .ogg, .webm, .flac."
        )

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime.startswith("video/"):
        raise AudioJournalError("Video journals are not supported.")
    if mime and mime not in _AUDIO_MIME_TYPES and mime != "application/octet-stream":
        raise AudioJournalError(
            "Invalid MIME type. Upload an audio file (wav, mp3, m4a, ogg, webm, flac)."
        )

    if mime in _AUDIO_MIME_TYPES:
        if mime in {"audio/x-wav", "audio/wave"}:
            return "audio/wav"
        if mime in {"audio/mp3"}:
            return "audio/mpeg"
        if mime in {"audio/m4a", "audio/x-m4a"}:
            return "audio/mp4"
        if mime in {"audio/x-flac"}:
            return "audio/flac"
        return mime

    fallback = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }.get(suffix)
    if not fallback:
        raise AudioJournalError(
            "Invalid file format. Supported audio: .wav, .mp3, .m4a, .ogg, .webm, .flac."
        )
    return fallback


def validate_audio_bytes(contents: bytes, mime_type: str) -> None:
    if not contents:
        raise AudioJournalError("Audio file is empty.")
    if len(contents) > MAX_AUDIO_JOURNAL_SIZE:
        raise AudioJournalError("File size exceeds the 10 MB maximum limit.")
    if mime_type == "audio/wav":
        if len(contents) < 12 or contents[0:4] != b"RIFF" or contents[8:12] != b"WAVE":
            raise AudioJournalError("Invalid WAV file. Expected a RIFF/WAVE header.")


def _safe_filename(filename: str) -> str:
    cleaned = "".join(c for c in filename if c.isalnum() or c in "._-").strip()
    return cleaned or "journal.wav"


def _remove_storage(client: Any, storage_path: str) -> None:
    try:
        client.storage.from_(JOURNAL_AUDIO_BUCKET).remove([storage_path])
    except Exception:
        logger.warning("Failed to remove journal audio object %s", storage_path)


def _insert_entry(client: Any, row: dict[str, Any]) -> dict[str, Any]:
    res = client.table("journal_entries").insert(row).execute()
    if not res.data:
        raise AudioJournalError(
            "Failed to record audio journal metadata.",
            status_code=500,
        )
    return res.data[0]


async def ingest_audio_journal(
    client: Any,
    user_id: str,
    filename: str,
    content_type: str | None,
    contents: bytes,
) -> dict[str, Any]:
    """Upload audio, transcribe, persist metadata, ingest transcript as text RAG.

    Failed transcription keeps the private audio object and a journal_entries row
    with transcription_status=failed. It does not call journal chunk ingestion.
    """
    mime_type = normalize_audio_mime(filename, content_type)
    validate_audio_bytes(contents, mime_type)

    storage_path = f"{user_id}/{uuid.uuid4()}_{_safe_filename(filename)}"
    try:
        client.storage.from_(JOURNAL_AUDIO_BUCKET).upload(
            path=storage_path,
            file=contents,
            file_options={"content-type": mime_type},
        )
    except Exception as err:
        err_msg = str(err)
        if "not_found" in err_msg.lower() or "bucket" in err_msg.lower():
            detail = (
                "Storage bucket 'journal-audio' was not found in Supabase. "
                "Create a private 'journal-audio' bucket in the Supabase dashboard."
            )
        else:
            detail = f"Failed to upload audio to private storage: {err_msg}"
        raise AudioJournalError(detail, status_code=500) from err

    transcript = ""
    transcription_status = "failed"
    try:
        transcript = await asyncio.to_thread(transcribe_audio, contents, mime_type)
        transcription_status = "completed"
    except TranscriptionError as err:
        logger.warning("Audio transcription failed for user %s: %s", user_id, err)

    try:
        record = _insert_entry(
            client,
            {
                "user_id": user_id,
                "content": transcript,
                "source_modality": "audio",
                "audio_storage_path": storage_path,
                "audio_filename": filename,
                "transcription_status": transcription_status,
            },
        )
    except Exception as err:
        _remove_storage(client, storage_path)
        if isinstance(err, AudioJournalError):
            raise
        raise AudioJournalError(
            f"Failed to record audio journal metadata: {err}",
            status_code=500,
        ) from err

    journal_id = str(record["id"])
    if transcription_status != "completed":
        return {
            "status": "transcription_failed",
            "journal_id": journal_id,
            "source_modality": "audio",
            "transcription_status": transcription_status,
            "audio_storage_path": storage_path,
        }

    try:
        await ingest_journal_entry(journal_id, user_id, transcript)
    except Exception as err:
        logger.warning(
            "Journal ingestion failed for audio entry %s: %s", journal_id, err
        )

    return {
        "status": "success",
        "journal_id": journal_id,
        "source_modality": "audio",
        "transcription_status": transcription_status,
        "audio_storage_path": storage_path,
    }
