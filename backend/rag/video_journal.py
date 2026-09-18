"""Video journal upload, private storage, local audio extract, then text RAG."""

from __future__ import annotations

from rag.audio_transcribe import transcribe_audio
from rag.journal_ingestion import ingest_journal_entry
from rag.media_journal import (
    MediaJournalError,
    persist_transcribed_journal,
    upload_user_object,
    user_object_path,
)
from rag.video_extract import AudioExtractError, extract_audio_wav

JOURNAL_VIDEO_BUCKET = "journal-video"
MAX_VIDEO_JOURNAL_SIZE = 25 * 1024 * 1024  # 25 MB

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}


def normalize_video_mime(filename: str, content_type: str | None) -> str:
    from rag.media_journal import file_suffix

    suffix = file_suffix(filename)
    if suffix and suffix not in _VIDEO_EXTENSIONS:
        raise MediaJournalError(
            "Invalid file format. Supported video: .mp4, .mov, .webm."
        )

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime.startswith("audio/"):
        raise MediaJournalError("Use /journal/audio for audio journals.")
    if mime and mime not in _VIDEO_MIME_TYPES and mime != "application/octet-stream":
        if not mime.startswith("video/"):
            raise MediaJournalError(
                "Invalid MIME type. Upload a video file (.mp4, .mov, .webm)."
            )
        raise MediaJournalError(
            "Invalid MIME type. Supported video: video/mp4, video/quicktime, video/webm."
        )

    if mime in _VIDEO_MIME_TYPES:
        return mime
    fallback = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(
        suffix
    )
    if not fallback:
        raise MediaJournalError(
            "Invalid file format. Supported video: .mp4, .mov, .webm."
        )
    return fallback


def validate_video_bytes(contents: bytes, mime_type: str) -> None:
    if not contents:
        raise MediaJournalError("Video file is empty.")
    if len(contents) > MAX_VIDEO_JOURNAL_SIZE:
        raise MediaJournalError("File size exceeds the 25 MB maximum limit.")
    if mime_type in {"video/mp4", "video/quicktime"}:
        if len(contents) < 12 or contents[4:8] != b"ftyp":
            raise MediaJournalError(
                "Invalid MP4/MOV file. Expected an ISO BMFF ftyp header."
            )
    if mime_type == "video/webm":
        if not contents.startswith(b"\x1a\x45\xdf\xa3"):
            raise MediaJournalError("Invalid WebM file. Expected an EBML header.")


async def ingest_video_journal(
    client,
    user_id: str,
    filename: str,
    content_type: str | None,
    contents: bytes,
) -> dict:
    """Upload video, extract audio locally, transcribe, ingest as text RAG.

    Extraction or transcription failure keeps the private video and a
    journal_entries row. It does not create journal_chunks.
    """
    mime_type = normalize_video_mime(filename, content_type)
    validate_video_bytes(contents, mime_type)
    storage_path = user_object_path(user_id, filename, "journal.mp4")
    upload_user_object(
        client,
        JOURNAL_VIDEO_BUCKET,
        storage_path,
        contents,
        mime_type,
        kind="video",
    )

    transcribe_fn = None
    failed_status = "extraction_failed"
    wav_bytes = None
    try:
        wav_bytes = extract_audio_wav(contents)
    except AudioExtractError:
        wav_bytes = None

    if wav_bytes is not None:
        failed_status = "transcription_failed"

        def transcribe_fn() -> str:
            return transcribe_audio(wav_bytes, "audio/wav")

    return await persist_transcribed_journal(
        client,
        user_id,
        bucket=JOURNAL_VIDEO_BUCKET,
        storage_path=storage_path,
        row={
            "source_modality": "video",
            "video_storage_path": storage_path,
            "video_filename": filename,
        },
        path_key="video_storage_path",
        transcribe_fn=transcribe_fn,
        ingest_fn=ingest_journal_entry,
        failed_status=failed_status,
    )
