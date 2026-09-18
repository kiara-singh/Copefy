"""Tracked RLS migration covers user-owned tables and private storage paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "database" / "migrations" / "002_rls_user_owned.sql"

USER_TABLES = (
    "profiles",
    "sessions",
    "messages",
    "triage_logs",
    "ai_personas",
    "journal_entries",
    "journal_chunks",
    "medical_documents",
)


def test_rls_migration_enables_policies_for_user_owned_tables():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "auth.uid()" in sql
    assert "TO authenticated" in sql
    for table in USER_TABLES:
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"auth.uid()" in sql
    assert "journal_chunks_select_own" in sql
    assert "profiles_update_own" in sql
    assert "messages_select_own" in sql
    assert "FROM public.sessions s" in sql
    assert "bucket_id = 'medical-documents'" in sql
    assert "split_part(name, '/', 1) = auth.uid()::text" in sql
    assert "service-role" in sql.lower() or "service role" in sql.lower()
