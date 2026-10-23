"""Focused video-journal ingestion tests. No live Gemini, ffmpeg, or Supabase."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from rag.media_journal import MediaJournalError
from rag.video_extract import AudioExtractError
from rag.video_journal import ingest_video_journal, normalize_video_mime
from rag.journal_retrieve import search_journal_chunks
from tests.fixtures import synthetic_mp4_bytes, synthetic_wav_bytes

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
TRANSCRIPT = (
    "I used the lavender tea ritual after the panic at the bus stop on Maple Street."
)


def _auth_client(mock_get_supabase: MagicMock) -> tuple[TestClient, MagicMock]:
    from main import app

    mock_supabase = MagicMock()
    mock_user = MagicMock()
    mock_user.id = TEST_USER_ID
    mock_user_res = MagicMock()
    mock_user_res.user = mock_user
    mock_supabase.auth.get_user.return_value = mock_user_res
    mock_get_supabase.return_value = mock_supabase
    return TestClient(app), mock_supabase


class FakeJournalConn:
    def __init__(self) -> None:
        self.chunks: list[dict] = []
        self.entries: dict[str, dict] = {}

    async def execute(self, sql: str, *args) -> None:
        if "DELETE FROM journal_chunks" in sql:
            journal_entry_id = str(args[0])
            self.chunks = [
                row for row in self.chunks if str(row["journal_entry_id"]) != journal_entry_id
            ]

    async def fetchrow(self, sql: str, *args):
        if "INSERT INTO journal_chunks" in sql:
            row = {
                "id": str(uuid.uuid4()),
                "journal_entry_id": str(args[0]),
                "user_id": str(args[1]),
                "chunk_index": args[2],
                "content": args[3],
                "embedding": args[4],
                "created_at": datetime.now(timezone.utc),
            }
            self.chunks.append(row)
            return row
        return None

    async def fetch(self, sql: str, *args):
        user_id = str(args[1])
        now = datetime.now(timezone.utc)
        hits = []
        for row in self.chunks:
            if str(row["user_id"]) != user_id:
                continue
            entry = self.entries.get(str(row["journal_entry_id"]), {})
            hits.append(
                {
                    "id": row["id"],
                    "journal_entry_id": row["journal_entry_id"],
                    "user_id": row["user_id"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "similarity": 0.92 if "lavender" in row["content"].lower() else 0.2,
                    "entry_created_at": entry.get("created_at", now),
                }
            )
        hits.sort(key=lambda item: item["similarity"], reverse=True)
        return hits[: int(args[2])]


def _pool(conn: FakeJournalConn):
    @asynccontextmanager
    async def acquire():
        yield conn

    return SimpleNamespace(acquire=acquire)


def test_rejects_audio_and_unknown_video_types():
    with pytest.raises(MediaJournalError, match="/journal/audio"):
        normalize_video_mime("clip.mp4", "audio/mp4")
    with pytest.raises(MediaJournalError, match="Invalid file format"):
        normalize_video_mime("notes.txt", "text/plain")
    assert normalize_video_mime("clip.MP4", "video/mp4") == "video/mp4"


def test_unauthenticated_video_journal_is_rejected():
    from main import app

    client = TestClient(app)
    res = client.post(
        "/journal/video",
        files={"file": ("clip.mp4", synthetic_mp4_bytes(), "video/mp4")},
    )
    assert res.status_code in (401, 403)


@patch("main.get_supabase")
def test_invalid_mp4_is_rejected_before_storage(mock_get_supabase):
    client, mock_supabase = _auth_client(mock_get_supabase)
    res = client.post(
        "/journal/video",
        files={"file": ("fake.mp4", b"not-an-mp4", "video/mp4")},
        headers={"Authorization": "Bearer valid_token"},
    )
    assert res.status_code == 400
    mock_supabase.storage.from_.assert_not_called()


def test_extraction_failure_stores_video_but_skips_chunks():
    client = MagicMock()
    client.storage.from_.return_value.upload.return_value = None
    client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "journal-failed", "user_id": TEST_USER_ID}]
    )
    ingest = AsyncMock()
    transcribe = MagicMock(side_effect=AssertionError("must not transcribe"))

    async def _run():
        with (
            patch("rag.video_journal.extract_audio_wav", side_effect=AudioExtractError("no audio")),
            patch("rag.video_journal.transcribe_audio", transcribe),
            patch("rag.video_journal.ingest_journal_entry", ingest),
        ):
            return await ingest_video_journal(
                client,
                TEST_USER_ID,
                "clip.mp4",
                "video/mp4",
                synthetic_mp4_bytes(),
            )

    result = asyncio.run(_run())

    assert result["status"] == "extraction_failed"
    inserted = client.table("journal_entries").insert.call_args[0][0]
    assert inserted["user_id"] == TEST_USER_ID
    assert inserted["content"] == ""
    assert inserted["source_modality"] == "video"
    assert inserted["transcription_status"] == "failed"
    assert inserted["video_storage_path"].startswith(f"{TEST_USER_ID}/")
    assert inserted["video_filename"] == "clip.mp4"
    transcribe.assert_not_called()
    ingest.assert_not_awaited()


def test_video_upload_extract_transcribe_ingest_and_retrieve():
    conn = FakeJournalConn()
    journal_id = str(uuid.uuid4())
    supabase = MagicMock()
    supabase.storage.from_.return_value.upload.return_value = None
    supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": journal_id, "user_id": TEST_USER_ID}]
    )

    def fake_embed(text: str) -> list[float]:
        vec = [0.01] * 768
        if "lavender" in text.lower() or "bus stop" in text.lower():
            vec[0] = 1.0
        return vec

    async def _run():
        with (
            patch("rag.video_journal.extract_audio_wav", return_value=synthetic_wav_bytes()),
            patch("rag.video_journal.transcribe_audio", return_value=TRANSCRIPT),
            patch("rag.journal_ingestion.embed_query", side_effect=fake_embed),
            patch("rag.journal_retrieve.embed_query", side_effect=fake_embed),
            patch("db.get_pool", AsyncMock(return_value=_pool(conn))),
        ):
            result = await ingest_video_journal(
                supabase,
                TEST_USER_ID,
                "clip.mp4",
                "video/mp4",
                synthetic_mp4_bytes(),
            )
            inserted = supabase.table("journal_entries").insert.call_args[0][0]
            conn.entries[journal_id] = {
                "user_id": TEST_USER_ID,
                "content": TRANSCRIPT,
                "created_at": datetime.now(timezone.utc),
                "source_modality": "video",
                "video_storage_path": inserted["video_storage_path"],
            }
            owner_hits = await search_journal_chunks(
                TEST_USER_ID, "What did I say about the lavender tea ritual?", top_k=3
            )
            stranger_hits = await search_journal_chunks(
                OTHER_USER_ID, "What did I say about the lavender tea ritual?", top_k=3
            )
            return result, inserted, owner_hits, stranger_hits

    result, inserted, owner_hits, stranger_hits = asyncio.run(_run())

    assert result["status"] == "success"
    assert result["source_modality"] == "video"
    assert inserted["content"] == TRANSCRIPT
    assert inserted["video_storage_path"].startswith(f"{TEST_USER_ID}/")
    upload_kw = supabase.storage.from_.return_value.upload.call_args.kwargs
    assert upload_kw["path"].startswith(f"{TEST_USER_ID}/")
    assert conn.chunks and all(row["user_id"] == TEST_USER_ID for row in conn.chunks)
    assert [hit.content for hit in owner_hits] == [TRANSCRIPT]
    assert stranger_hits == []


@patch("rag.video_journal.ingest_journal_entry", new_callable=AsyncMock)
@patch("rag.video_journal.transcribe_audio", return_value=TRANSCRIPT)
@patch("rag.video_journal.extract_audio_wav", return_value=b"RIFF0000WAVEfake")
@patch("main.get_supabase")
def test_http_video_journal_requires_owner_token(
    mock_get_supabase, _extract, _transcribe, mock_ingest
):
    http, mock_supabase = _auth_client(mock_get_supabase)
    mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "http-video", "user_id": TEST_USER_ID}]
    )
    res = http.post(
        "/journal/video",
        files={"file": ("clip.mp4", synthetic_mp4_bytes(), "video/mp4")},
        headers={"Authorization": "Bearer valid_token"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["source_modality"] == "video"
    inserted = mock_supabase.table("journal_entries").insert.call_args[0][0]
    assert inserted["user_id"] == TEST_USER_ID
    mock_ingest.assert_awaited()
    assert mock_ingest.await_args.args[2] == TRANSCRIPT
