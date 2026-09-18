-- Defense-in-depth for user-owned tables and private medical storage.
-- Backend service-role access bypasses RLS; these policies constrain the
-- browser/anon key (authenticated JWT). Apply in the Supabase SQL editor.
-- Clinical KB tables are shared and are intentionally not covered here.

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

-- Private bucket objects live at {user_uuid}/{filename}.
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
