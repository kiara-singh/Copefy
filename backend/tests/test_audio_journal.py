"""Focused audio-journal ingestion tests. No live Gemini or Supabase calls."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from rag.audio_journal import AudioJournalError, ingest_audio_journal, normalize_audio_mime
from rag.audio_transcribe import TranscriptionError
from rag.journal_retrieve import search_journal_chunks
from tests.fixtures import SYNTHETIC_WAV_PATH, synthetic_wav_bytes, write_synthetic_wav

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
TRANSCRIPT = (
    "I used the lavender tea ritual after the panic at the bus stop on Maple Street."
)

write_synthetic_wav()


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


def _table_insert(row_id: str) -> MagicMock:
    insert = MagicMock()
    insert.execute.return_value = MagicMock(
        data=[{"id": row_id, "user_id": TEST_USER_ID}]
    )
    return insert


class FakeJournalConn:
    """In-memory journal_entries/journal_chunks enough for ingest + retrieve SQL."""

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


def test_synthetic_wav_fixture_is_valid_riff():
    payload = SYNTHETIC_WAV_PATH.read_bytes()
    assert payload == synthetic_wav_bytes()
    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WAVE"


def test_rejects_video_and_unknown_audio_types():
    with pytest.raises(AudioJournalError, match="Video"):
        normalize_audio_mime("clip.mp4", "video/mp4")
    with pytest.raises(AudioJournalError, match="Invalid file format"):
        normalize_audio_mime("notes.txt", "text/plain")
    assert normalize_audio_mime("voice.WAV", "audio/x-wav") == "audio/wav"


def test_unauthenticated_audio_journal_is_rejected():
    from main import app

    client = TestClient(app)
    res = client.post(
        "/journal/audio",
        files={"file": ("synthetic_journal.wav", synthetic_wav_bytes(), "audio/wav")},
    )
    assert res.status_code in (401, 403)


@patch("main.get_supabase")
def test_invalid_wav_is_rejected_before_storage(mock_get_supabase):
    client, mock_supabase = _auth_client(mock_get_supabase)
    res = client.post(
        "/journal/audio",
        files={"file": ("fake.wav", b"not-a-wav", "audio/wav")},
        headers={"Authorization": "Bearer valid_token"},
    )
    assert res.status_code == 400
    mock_supabase.storage.from_.assert_not_called()


def test_failed_transcription_stores_audio_but_skips_chunks():
    client = MagicMock()
    client.storage.from_.return_value.upload.return_value = None
    client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "journal-failed", "user_id": TEST_USER_ID}]
    )
    ingest = AsyncMock()

    async def _run():
        with (
            patch("rag.audio_journal.transcribe_audio", side_effect=TranscriptionError("boom")),
            patch("rag.audio_journal.ingest_journal_entry", ingest),
        ):
            return await ingest_audio_journal(
                client,
                TEST_USER_ID,
                "synthetic_journal.wav",
                "audio/wav",
                synthetic_wav_bytes(),
            )

    result = asyncio.run(_run())

    assert result["status"] == "transcription_failed"
    inserted = client.table("journal_entries").insert.call_args[0][0]
    assert inserted["user_id"] == TEST_USER_ID
    assert inserted["content"] == ""
    assert inserted["source_modality"] == "audio"
    assert inserted["transcription_status"] == "failed"
    assert inserted["audio_storage_path"].startswith(f"{TEST_USER_ID}/")
    storage_kw = client.storage.from_.return_value.upload.call_args.kwargs
    assert storage_kw["path"].startswith(f"{TEST_USER_ID}/")
    ingest.assert_not_awaited()


def test_audio_upload_transcribe_ingest_and_retrieve_e2e():
    """Upload -> transcribe -> existing chunk/embed ingest -> user-scoped retrieve."""
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
            patch("rag.audio_journal.transcribe_audio", return_value=TRANSCRIPT),
            patch("rag.journal_ingestion.embed_query", side_effect=fake_embed),
            patch("rag.journal_retrieve.embed_query", side_effect=fake_embed),
            patch("db.get_pool", AsyncMock(return_value=_pool(conn))),
        ):
            result = await ingest_audio_journal(
                supabase,
                TEST_USER_ID,
                "synthetic_journal.wav",
                "audio/wav",
                SYNTHETIC_WAV_PATH.read_bytes(),
            )
            inserted = supabase.table("journal_entries").insert.call_args[0][0]
            conn.entries[journal_id] = {
                "user_id": TEST_USER_ID,
                "content": TRANSCRIPT,
                "created_at": datetime.now(timezone.utc),
                "source_modality": "audio",
                "audio_storage_path": inserted["audio_storage_path"],
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
    assert result["transcription_status"] == "completed"
    assert inserted["content"] == TRANSCRIPT
    assert inserted["source_modality"] == "audio"
    assert inserted["audio_storage_path"].startswith(f"{TEST_USER_ID}/")

    assert result["journal_id"] == journal_id
    assert conn.chunks, "successful transcription must create journal_chunks"
    assert all(row["content"] == TRANSCRIPT for row in conn.chunks)
    assert all(row["user_id"] == TEST_USER_ID for row in conn.chunks)
    assert [hit.content for hit in owner_hits] == [TRANSCRIPT]
    assert stranger_hits == []


@patch("rag.audio_journal.ingest_journal_entry", new_callable=AsyncMock)
@patch("rag.audio_journal.transcribe_audio", return_value=TRANSCRIPT)
@patch("main.get_supabase")
def test_http_audio_journal_requires_owner_token(
    mock_get_supabase, _transcribe, mock_ingest
):
    http, mock_supabase = _auth_client(mock_get_supabase)
    mock_supabase.table.return_value.insert.return_value = _table_insert("http-journal")
    res = http.post(
        "/journal/audio",
        files={
            "file": (
                "synthetic_journal.wav",
                SYNTHETIC_WAV_PATH.read_bytes(),
                "audio/wav",
            )
        },
        headers={"Authorization": "Bearer valid_token"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["source_modality"] == "audio"
    inserted = mock_supabase.table("journal_entries").insert.call_args[0][0]
    assert inserted["user_id"] == TEST_USER_ID
    mock_ingest.assert_awaited()
    assert mock_ingest.await_args.args[0] == "http-journal"
    assert mock_ingest.await_args.args[1] == TEST_USER_ID
    assert mock_ingest.await_args.args[2] == TRANSCRIPT
