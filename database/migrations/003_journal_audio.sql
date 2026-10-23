-- Audio journals: keep original audio in private storage and store transcript
-- metadata on journal_entries. Searchable RAG still uses journal_chunks text
-- embeddings only. Apply in the Supabase SQL editor after 002.
-- Create a private Storage bucket named journal-audio in the dashboard.

ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS source_modality VARCHAR(20) NOT NULL DEFAULT 'text';

ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS audio_storage_path TEXT;

ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS audio_filename VARCHAR(255);

ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS transcription_status VARCHAR(32) NOT NULL DEFAULT 'not_applicable';

-- Private bucket objects live at {user_uuid}/{filename}.
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
