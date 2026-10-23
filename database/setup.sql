-- Copefy schema for a fresh Supabase project.
-- Run in the Supabase SQL editor. Safe to re-run when the schema already matches:
-- tables use IF NOT EXISTS, policies are dropped and recreated, and the
-- auth trigger is replaced.
-- This file does not migrate an older database that is missing columns.
-- Leave database/db.sql and database/schema_rag.sql unused.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    current_triage_tier INT DEFAULT 0,
    subscription_tier VARCHAR(50) DEFAULT 'free',
    consent BOOLEAN NOT NULL DEFAULT FALSE,
    legal_consent JSONB,
    preferred_name VARCHAR(255),
    communication_style TEXT,
    wellness_goal TEXT,
    coaching_preferences TEXT,
    onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    is_safety_flagged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS triage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    detected_intent VARCHAR(255),
    primary_emotion VARCHAR(100),
    severity_score INT NOT NULL,
    routed_action VARCHAR(255),
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    role_type VARCHAR(100) NOT NULL,
    base_personality TEXT NOT NULL,
    custom_instructions TEXT NOT NULL,
    avatar_preference JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    tags VARCHAR(50)[],
    embedding vector(768),
    source_modality VARCHAR(20) NOT NULL DEFAULT 'text',
    audio_storage_path TEXT,
    audio_filename VARCHAR(255),
    video_storage_path TEXT,
    video_filename VARCHAR(255),
    transcription_status VARCHAR(32) NOT NULL DEFAULT 'not_applicable',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_entry_id UUID NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_journal_chunks_user_id ON journal_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_journal_chunks_entry_id ON journal_chunks(journal_entry_id);

CREATE TABLE IF NOT EXISTS medical_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    storage_url TEXT NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.profiles (id)
    VALUES (new.id);
    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.triage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_personas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.journal_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.journal_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medical_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_select_own ON public.profiles;
CREATE POLICY profiles_select_own ON public.profiles
  FOR SELECT TO authenticated
  USING (id = auth.uid());

DROP POLICY IF EXISTS profiles_insert_own ON public.profiles;
CREATE POLICY profiles_insert_own ON public.profiles
  FOR INSERT TO authenticated
  WITH CHECK (id = auth.uid());

DROP POLICY IF EXISTS profiles_update_own ON public.profiles;
CREATE POLICY profiles_update_own ON public.profiles
  FOR UPDATE TO authenticated
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

DROP POLICY IF EXISTS sessions_select_own ON public.sessions;
CREATE POLICY sessions_select_own ON public.sessions
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS sessions_insert_own ON public.sessions;
CREATE POLICY sessions_insert_own ON public.sessions
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS sessions_update_own ON public.sessions;
CREATE POLICY sessions_update_own ON public.sessions
  FOR UPDATE TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS sessions_delete_own ON public.sessions;
CREATE POLICY sessions_delete_own ON public.sessions
  FOR DELETE TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS messages_select_own ON public.messages;
CREATE POLICY messages_select_own ON public.messages
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.id = messages.session_id AND s.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS messages_insert_own ON public.messages;
CREATE POLICY messages_insert_own ON public.messages
  FOR INSERT TO authenticated
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.id = messages.session_id AND s.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS messages_delete_own ON public.messages;
CREATE POLICY messages_delete_own ON public.messages
  FOR DELETE TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.sessions s
      WHERE s.id = messages.session_id AND s.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS triage_logs_select_own ON public.triage_logs;
CREATE POLICY triage_logs_select_own ON public.triage_logs
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS triage_logs_insert_own ON public.triage_logs;
CREATE POLICY triage_logs_insert_own ON public.triage_logs
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS ai_personas_all_own ON public.ai_personas;
CREATE POLICY ai_personas_all_own ON public.ai_personas
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS journal_entries_select_own ON public.journal_entries;
CREATE POLICY journal_entries_select_own ON public.journal_entries
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS journal_entries_insert_own ON public.journal_entries;
CREATE POLICY journal_entries_insert_own ON public.journal_entries
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS journal_entries_update_own ON public.journal_entries;
CREATE POLICY journal_entries_update_own ON public.journal_entries
  FOR UPDATE TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS journal_entries_delete_own ON public.journal_entries;
CREATE POLICY journal_entries_delete_own ON public.journal_entries
  FOR DELETE TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS journal_chunks_select_own ON public.journal_chunks;
CREATE POLICY journal_chunks_select_own ON public.journal_chunks
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS medical_documents_all_own ON public.medical_documents;
CREATE POLICY medical_documents_all_own ON public.medical_documents
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

INSERT INTO storage.buckets (id, name, public)
VALUES
  ('medical-documents', 'medical-documents', false),
  ('journal-audio', 'journal-audio', false),
  ('journal-video', 'journal-video', false)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS medical_docs_select_own ON storage.objects;
CREATE POLICY medical_docs_select_own ON storage.objects
  FOR SELECT TO authenticated
  USING (
    bucket_id = 'medical-documents'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS medical_docs_insert_own ON storage.objects;
CREATE POLICY medical_docs_insert_own ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'medical-documents'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS medical_docs_update_own ON storage.objects;
CREATE POLICY medical_docs_update_own ON storage.objects
  FOR UPDATE TO authenticated
  USING (
    bucket_id = 'medical-documents'
    AND split_part(name, '/', 1) = auth.uid()::text
  )
  WITH CHECK (
    bucket_id = 'medical-documents'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS medical_docs_delete_own ON storage.objects;
CREATE POLICY medical_docs_delete_own ON storage.objects
  FOR DELETE TO authenticated
  USING (
    bucket_id = 'medical-documents'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_audio_select_own ON storage.objects;
CREATE POLICY journal_audio_select_own ON storage.objects
  FOR SELECT TO authenticated
  USING (
    bucket_id = 'journal-audio'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_audio_insert_own ON storage.objects;
CREATE POLICY journal_audio_insert_own ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'journal-audio'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_audio_update_own ON storage.objects;
CREATE POLICY journal_audio_update_own ON storage.objects
  FOR UPDATE TO authenticated
  USING (
    bucket_id = 'journal-audio'
    AND split_part(name, '/', 1) = auth.uid()::text
  )
  WITH CHECK (
    bucket_id = 'journal-audio'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_audio_delete_own ON storage.objects;
CREATE POLICY journal_audio_delete_own ON storage.objects
  FOR DELETE TO authenticated
  USING (
    bucket_id = 'journal-audio'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_video_select_own ON storage.objects;
CREATE POLICY journal_video_select_own ON storage.objects
  FOR SELECT TO authenticated
  USING (
    bucket_id = 'journal-video'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_video_insert_own ON storage.objects;
CREATE POLICY journal_video_insert_own ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'journal-video'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_video_update_own ON storage.objects;
CREATE POLICY journal_video_update_own ON storage.objects
  FOR UPDATE TO authenticated
  USING (
    bucket_id = 'journal-video'
    AND split_part(name, '/', 1) = auth.uid()::text
  )
  WITH CHECK (
    bucket_id = 'journal-video'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

DROP POLICY IF EXISTS journal_video_delete_own ON storage.objects;
CREATE POLICY journal_video_delete_own ON storage.objects
  FOR DELETE TO authenticated
  USING (
    bucket_id = 'journal-video'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

-- Clinical knowledge base. Backend retrieval calls:
--   match_kb_chunks(vector(768), match_count, filter_category)
-- and then reads kb_documents(id, title, source_url, category).
-- Ingest and search use DATABASE_URL (owner bypasses RLS).

CREATE TABLE IF NOT EXISTS kb_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN ('web', 'pdf')),
    title TEXT,
    category TEXT NOT NULL CHECK (
        category IN ('adhd', 'depression', 'anxiety', 'ocd', 'ptsd')
    ),
    domain TEXT,
    content_hash TEXT NOT NULL,
    raw_markdown TEXT,
    anxiety_subtype TEXT CHECK (
        anxiety_subtype IS NULL
        OR (
            category = 'anxiety'
            AND anxiety_subtype IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety')
        )
    ),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'skipped', 'error')),
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    token_estimate INT,
    embedding vector(768) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS kb_document_categories (
    document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (
        category IN ('adhd', 'depression', 'anxiety', 'ocd', 'ptsd')
    ),
    confidence REAL NOT NULL DEFAULT 1.0,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (document_id, category)
);

CREATE INDEX IF NOT EXISTS kb_documents_category_idx ON kb_documents (category);
CREATE INDEX IF NOT EXISTS kb_documents_domain_idx ON kb_documents (domain);
CREATE INDEX IF NOT EXISTS kb_documents_content_hash_idx ON kb_documents (content_hash);
CREATE INDEX IF NOT EXISTS kb_documents_anxiety_subtype_idx
    ON kb_documents (anxiety_subtype)
    WHERE anxiety_subtype IS NOT NULL;
CREATE INDEX IF NOT EXISTS kb_document_categories_category_idx
    ON kb_document_categories (category);
CREATE INDEX IF NOT EXISTS kb_chunks_document_id_idx ON kb_chunks (document_id);
CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw_idx
    ON kb_chunks
    USING hnsw (embedding vector_cosine_ops);

ALTER TABLE kb_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_document_categories ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE kb_documents FROM anon, authenticated;
REVOKE ALL ON TABLE kb_chunks FROM anon, authenticated;
REVOKE ALL ON TABLE kb_document_categories FROM anon, authenticated;

INSERT INTO kb_document_categories (document_id, category, confidence, is_primary)
SELECT id, category, 1.0, TRUE
FROM kb_documents
WHERE status = 'active'
ON CONFLICT (document_id, category) DO NOTHING;

CREATE OR REPLACE FUNCTION match_kb_chunks(
    query_embedding vector(768),
    match_count INT DEFAULT 8,
    filter_category TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    document_id UUID,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        c.id,
        c.document_id,
        c.content,
        c.metadata,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE d.status = 'active'
      AND (
          filter_category IS NULL
          OR EXISTS (
              SELECT 1 FROM kb_document_categories dc
              WHERE dc.document_id = d.id AND dc.category = filter_category
          )
          OR (
              NOT EXISTS (
                  SELECT 1 FROM kb_document_categories dc2
                  WHERE dc2.document_id = d.id
              )
              AND d.category = filter_category
          )
      )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;
