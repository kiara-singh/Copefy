-- 1. PROFILES
-- Core identity, routing state, and legal consent tracking
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    current_triage_tier INT DEFAULT 0, -- 0 = stable, higher numbers indicate distress
    subscription_tier VARCHAR(50) DEFAULT 'free',
    consent BOOLEAN NOT NULL DEFAULT FALSE,
    legal_consent JSONB, -- Stores specific flags: {terms_accepted: true, hipaa_acknowledged: true}
    preferred_name VARCHAR(255),
    communication_style TEXT,
    wellness_goal TEXT,
    coaching_preferences TEXT,
    onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE
);

-- 2. SESSIONS
-- Parent container for distinct conversational interactions
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) DEFAULT 'active' -- 'active' or 'closed'
);

-- 3. MESSAGES
-- The back-and-forth chat text and safety flags
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL, -- 'user', 'assistant', or 'system'
    content TEXT NOT NULL,
    is_safety_flagged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. TRIAGE LOGS
-- Automated routing decisions and crisis detection history
CREATE TABLE triage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    detected_intent VARCHAR(255),
    primary_emotion VARCHAR(100),
    severity_score INT NOT NULL,
    routed_action VARCHAR(255),
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. AI PERSONAS
-- Configurations for personalized AI models and roleplay characteristics
CREATE TABLE ai_personas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    role_type VARCHAR(100) NOT NULL,
    base_personality TEXT NOT NULL,
    custom_instructions TEXT NOT NULL,
    avatar_preference JSONB, -- Stores bucket URLs for voice clones or avatar assets
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. JOURNAL ENTRIES (Vector Table)
-- Text and vector embeddings for semantic retrieval (RAG)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE journal_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    tags VARCHAR(50)[],
    embedding vector(768), -- Dimension size (768) configured for Gemini embeddings
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6b. JOURNAL CHUNKS (Derived RAG Retrieval Units)
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


-- 7. MEDICAL DOCUMENTS
-- Metadata and storage references for uploaded health records
-- Path or public URL to the file stored in Supabase Storage
CREATE TABLE medical_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    storage_url TEXT NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Trigger function to automatically create a profile when a new user signs up
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.profiles (id)
    VALUES (new.id);
    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to run the function after a user is inserted in auth.users
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Row-level security for user-owned tables lives in
-- database/migrations/002_rls_user_owned.sql (apply in Supabase).
