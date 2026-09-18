"""Audio journal upload, private storage, transcription, then text ingestion."""

from __future__ import annotations

from rag.audio_transcribe import transcribe_audio
from rag.journal_ingestion import ingest_journal_entry
from rag.media_journal import (
    MediaJournalError,
    persist_transcribed_journal,
    upload_user_object,
    user_object_path,
)

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

AudioJournalError = MediaJournalError


def _suffix(filename: str) -> str:
    from rag.media_journal import file_suffix

    return file_suffix(filename)


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


async def ingest_audio_journal(
    client,
    user_id: str,
    filename: str,
    content_type: str | None,
    contents: bytes,
) -> dict:
    """Upload audio, transcribe, persist metadata, ingest transcript as text RAG.

    Failed transcription keeps the private audio object and a journal_entries row
    with transcription_status=failed. It does not call journal chunk ingestion.
    """
    mime_type = normalize_audio_mime(filename, content_type)
    validate_audio_bytes(contents, mime_type)
    storage_path = user_object_path(user_id, filename, "journal.wav")
    upload_user_object(
        client,
        JOURNAL_AUDIO_BUCKET,
        storage_path,
        contents,
        mime_type,
        kind="audio",
    )

    def transcribe_fn() -> str:
        return transcribe_audio(contents, mime_type)

    return await persist_transcribed_journal(
        client,
        user_id,
        bucket=JOURNAL_AUDIO_BUCKET,
        storage_path=storage_path,
        row={
            "source_modality": "audio",
            "audio_storage_path": storage_path,
            "audio_filename": filename,
        },
        path_key="audio_storage_path",
        transcribe_fn=transcribe_fn,
        ingest_fn=ingest_journal_entry,
        failed_status="transcription_failed",
    )
