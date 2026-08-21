-- DEPRECATED / LEGACY SCHEMA FILE
-- This file contains legacy SQL definitions (e.g. unlinked users table and raw_text column).
-- The authoritative schema definition for new setups is schema_core.sql.

-- Enable the pgvector extension for RAG capabilities
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. USERS
-- Core identity, routing state, and legal consent tracking
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    current_triage_tier INT DEFAULT 0, -- 0 = stable, higher numbers indicate distress
    subscription_tier VARCHAR(50) DEFAULT 'free',
    consent BOOLEAN NOT NULL DEFAULT FALSE,
    legal_consent JSONB -- Stores specific flags: {terms_accepted: true, hipaa_acknowledged: true}
);

-- 2. SESSIONS
-- Parent container for distinct conversational interactions
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    role_type VARCHAR(100) NOT NULL,
    base_personality TEXT NOT NULL,
    custom_instructions TEXT NOT NULL,
    avatar_preference JSONB, -- Stores bucket URLs for voice clones or avatar assets
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. JOURNAL ENTRIES (Vector Table)
-- Text and vector embeddings for semantic retrieval (RAG)
CREATE TABLE journal_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    tags VARCHAR(50)[],
    embedding vector(1536), -- Dimension size assumes OpenAI ada-002 or similar model
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. MEDICAL DOCUMENTS
-- Metadata and storage references for uploaded health records
CREATE TABLE medical_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    storage_url TEXT NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);