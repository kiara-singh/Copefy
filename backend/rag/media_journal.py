"""Shared private-storage + transcript ingest for audio and video journals."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from rag.journal_ingestion import ingest_journal_entry

logger = logging.getLogger(__name__)


class MediaJournalError(RuntimeError):
    """User-facing media journal validation or persistence failure."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def file_suffix(filename: str) -> str:
    lower = filename.lower()
    dot = lower.rfind(".")
    return lower[dot:] if dot >= 0 else ""


def safe_filename(filename: str, fallback: str = "journal.bin") -> str:
    cleaned = "".join(c for c in filename if c.isalnum() or c in "._-").strip()
    return cleaned or fallback


def user_object_path(user_id: str, filename: str, fallback: str) -> str:
    return f"{user_id}/{uuid.uuid4()}_{safe_filename(filename, fallback)}"


def remove_storage(client: Any, bucket: str, storage_path: str) -> None:
    try:
        client.storage.from_(bucket).remove([storage_path])
    except Exception:
        logger.warning("Failed to remove %s object %s", bucket, storage_path)


def upload_user_object(
    client: Any,
    bucket: str,
    storage_path: str,
    contents: bytes,
    mime_type: str,
    *,
    kind: str,
) -> None:
    try:
        client.storage.from_(bucket).upload(
            path=storage_path,
            file=contents,
            file_options={"content-type": mime_type},
        )
    except Exception as err:
        err_msg = str(err)
        if "not_found" in err_msg.lower() or "bucket" in err_msg.lower():
            detail = (
                f"Storage bucket '{bucket}' was not found in Supabase. "
                f"Create a private '{bucket}' bucket in the Supabase dashboard."
            )
        else:
            detail = f"Failed to upload {kind} to private storage: {err_msg}"
        raise MediaJournalError(detail, status_code=500) from err


def insert_journal_entry(client: Any, row: dict[str, Any]) -> dict[str, Any]:
    res = client.table("journal_entries").insert(row).execute()
    if not res.data:
        raise MediaJournalError(
            "Failed to record journal metadata.",
            status_code=500,
        )
    return res.data[0]


async def persist_transcribed_journal(
    client: Any,
    user_id: str,
    *,
    bucket: str,
    storage_path: str,
    row: dict[str, Any],
    path_key: str,
    transcribe_fn: Callable[[], str] | None,
    ingest_fn: Callable[..., Any] = ingest_journal_entry,
    failed_status: str = "transcription_failed",
) -> dict[str, Any]:
    """Insert journal metadata, transcribe if possible, ingest chunks only on success.

    `transcribe_fn` is None when extraction already failed (no audio to send).
    """
    transcript = ""
    transcription_status = "failed"
    if transcribe_fn is not None:
        try:
            transcript = await asyncio.to_thread(transcribe_fn)
            transcription_status = "completed"
        except Exception as err:
            logger.warning("Transcription failed for user %s: %s", user_id, err)

    payload = {
        **row,
        "user_id": user_id,
        "content": transcript,
        "transcription_status": transcription_status,
    }
    try:
        record = insert_journal_entry(client, payload)
    except Exception as err:
        remove_storage(client, bucket, storage_path)
        if isinstance(err, MediaJournalError):
            raise
        raise MediaJournalError(
            f"Failed to record journal metadata: {err}",
            status_code=500,
        ) from err

    journal_id = str(record["id"])
    response = {
        "journal_id": journal_id,
        "source_modality": payload["source_modality"],
        "transcription_status": transcription_status,
        path_key: storage_path,
    }
    if transcription_status != "completed":
        response["status"] = failed_status
        return response

    try:
        await ingest_fn(journal_id, user_id, transcript)
    except Exception as err:
        logger.warning(
            "Journal ingestion failed for %s entry %s: %s",
            payload["source_modality"],
            journal_id,
            err,
        )

    response["status"] = "success"
    return response
