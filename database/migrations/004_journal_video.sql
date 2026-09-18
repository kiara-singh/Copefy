-- Video journals: keep original video in private storage. Searchable RAG still
-- uses journal_chunks text embeddings of the extracted-audio transcript.
-- Apply after 003. Create a private Storage bucket named journal-video.

ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS video_storage_path TEXT;

ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS video_filename VARCHAR(255);

-- Private bucket objects live at {user_uuid}/{filename}.
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
