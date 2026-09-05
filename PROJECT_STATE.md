# Project State: Copefy

This document captures the current implementation state of the Copefy repository as of August 2026. It serves as an accurate map of the codebase for engineers and AI subagents without relying on planned functionality or design specifications.

---

## 1. Project Overview

Copefy is an early-stage web application scaffold for an AI mental health and wellness companion. Currently, the application provides:
- User authentication (sign up, sign in, sign out) powered by Supabase Auth.
- A 3-step onboarding flow collecting preferred name, communication style preferences (via a quiz tournament or manual input), and wellness goals, stored in Supabase Postgres.
- User settings management for profile updates, communication style adjustments, wellness goals, and medical document uploads.
- An AI Personas management feature allowing authenticated users to create, view, edit, and delete custom chatbot persona configurations (`name`, `role_type`, `base_personality`, `custom_instructions`).
- A Medical Documents management feature inside Settings allowing authenticated users to upload PDF health records (validated for `.pdf` extension, MIME type, 10 MB size limit, and `%PDF-` magic header bytes), view uploaded documents, and delete them. Files are stored in a private Supabase Storage bucket (`medical-documents`) with metadata tracked in PostgreSQL.
- An Agentic RAG Pipeline with:
  - **Layer 1 Router**: Production default `AGENT_ROUTER=rule` pattern-based router (100.0% accuracy on 529 golden regression cases, 0 crisis/web false positives, 0.2 ms/case latency).
  - **Layer 3 Clinical KB Retrieval**: Production default `RAG_STRATEGY=mmr` diversity-reranked vector search over 1,123 clinical KB documents using 768-dimensional Gemini embeddings (`gemini-embedding-2` / `text-embedding-004`).
  - **Layer 2 User Journal Corpus**: Derived RAG retrieval system (`journal_chunks` table) using structure-aware paragraph/sentence-boundary chunking, 768-dim Gemini embeddings, idempotent ingestion, strict database-level user isolation (`WHERE user_id = authenticated_user_id`), MMR reranking, synthetic dataset seeder, and multi-corpus orchestration (`clinical`, `journal`, and `both`).
- **Prompt Architecture**: Versioned Core System Prompt registry (`backend/agent/prompts.py`) separating the static system instruction baseline (`CORE_SYSTEM_PROMPT_V1`) from dynamic runtime user personalization context (`backend/agent/persona.py`). Dynamically assembled via `build_system_instruction(persona, version=settings.system_prompt_version)` with deprecated backward-compatibility aliases preserved.
- A single-session React chat interface communicating with FastAPI backend `/chat`. Requests are authenticated via Bearer tokens, checking session ownership and storing messages in Supabase.
- A journal entry form submitting text under the authenticated user's ID to Supabase with automatic structure-aware chunking and vector embedding ingestion.

### Major Technologies & Frameworks
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Router DOM (v6), `@supabase/supabase-js`.
- **Backend**: Python 3.11+, FastAPI, Uvicorn, Pydantic Settings, `python-multipart`, `google-genai`, `asyncpg`, `pytest`, `supabase-py`.
- **Database & Auth**: Supabase (PostgreSQL with Supabase Auth, Supabase Storage, and `pgvector` extension enabled in SQL schema).

---

## 2. Repository Structure

```
Copefy/
├── .agents/
│   └── rules/
│       └── project-state-maintenance.md     # Agent rule to maintain PROJECT_STATE.md
├── backend/
│   ├── agent/                               # Agentic RAG Layer 1 router & orchestrator
│   │   ├── routers/                         # Rule-based router (rule.py) and AI router (ai.py)
│   │   ├── tools/                           # Tools: semantic_search.py, journal_search.py, web_search.py, etc.
│   │   ├── orchestrator.py                  # Agent orchestrator running Layer 1 routing, tool execution, and reply generation
│   │   ├── persona.py                       # User persona prompt builder and communication style formatter
│   │   ├── prompts.py                       # Versioned Core System Prompts (V1), prompt registry, and crisis response templates
│   │   └── types.py                         # AgentResult data model and trace serialization
│   ├── config.py                            # Pydantic BaseSettings loading environment variables
│   ├── db.py                                # Cached Supabase client & asyncpg pool manager
│   ├── debug_trace.py                       # JSON trace logging utility
│   ├── eval/                                # Layer 1 & Layer 3 golden evaluation suite and harness
│   │   └── golden/                          # Core, safety, tools, edges, and heldout YAML test suites
│   ├── main.py                              # Authenticated FastAPI endpoints for health, session, chat, journal, personas, and medical documents
│   ├── rag/                                 # Layer 2 & Layer 3 Retrieval Engine
│   │   ├── embed.py                         # 768-dim Gemini query & chunk embedding generation
│   │   ├── journal_chunking.py              # V1 Structure-aware paragraph and sentence-boundary journal chunker
│   │   ├── journal_ingestion.py             # Reusable idempotent journal chunking + embedding + DB insertion
│   │   ├── journal_retrieve.py              # User-isolated pgvector retrieval + MMR reranking over journal_chunks
│   │   ├── retrieve.py                      # KB retrieval plan builder, clinical signal detector, and strategy runner
│   │   ├── search.py                        # pgvector query execution over kb_chunks
│   │   └── strategies/                      # RAG retrieval strategies (mmr.py, baseline.py, threshold.py, etc.)
│   ├── scripts/
│   │   └── seed_dummy_journals.py           # Real-path synthetic dataset seeder (10 entries across topics)
│   ├── tests/                               # Backend pytest test suite
│   │   ├── test_journal_rag.py              # Journal chunking, embedding, user isolation, and smoke tests (5/5 PASS)
│   │   ├── test_retrieval_scoring.py        # Retrieval scoring tests
│   │   └── test_retrieval_subdecisions.py   # Retrieval subdecision tests
│   ├── test_auth_endpoints.py               # Unit test suite verifying JWT auth, session ownership, persona CRUD & medical document CRUD (15/15 PASS)
│   └── requirements.txt                     # Backend Python dependencies
├── database/
│   ├── db.sql                               # Legacy SQL table definitions (deprecated, superseded by schema_core.sql)
│   ├── schema_core.sql                      # Authoritative SQL schema (profiles, sessions, messages, journal_entries, journal_chunks, ai_personas, medical_documents)
│   └── schema_rag.sql                       # SQL vector test table schema
├── docs/                                    # Handoff docs & architecture maps (LAYER1_HANDOFF.md, LAYER3_HANDOFF.md)
├── frontend/
│   ├── src/
│   │   ├── components/                      # AppLayout, Sidebar, CommunicationStyleQuiz, ChatTracePanel, ProtectedRoute, PublicRoute
│   │   ├── contexts/                        # AuthContext provider
│   │   ├── lib/                             # Backend API client (api.ts) & Supabase client (supabase_client.ts)
│   │   └── pages/                           # Home, Journal, Personas, Settings, Login, Onboarding pages
│   ├── package.json                         # Frontend dependencies
│   └── vite.config.ts                       # Vite configuration
├── PROJECT_STATE.md                         # Current project status documentation
└── README.md                                # Repository setup instructions and overview
```

---

## 3. Frontend

### Implemented Pages & Components
- **[settings_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/settings_page.tsx)**: Preferred Name, Communication Style grid/quiz, Wellness Goals, Medical Documents upload/delete, and Sign Out.
- **[login_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/login_page.tsx)**: Auth page for sign-in and registration.
- **[onboarding_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/onboarding_page.tsx)**: 3-step user onboarding wizard.
- **[personas_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/personas_page.tsx)**: Custom AI Personas CRUD page (`name`, `role_type`, `base_personality`, `custom_instructions`).
- **[home_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/home_page.tsx)**: Main chat interface communicating with `/chat` with optional RAG debug trace drawer.
- **[journal_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/journal_page.tsx)**: Form submitting journal entries to `/journal`.

---

## 4. Backend & API Endpoints

- `GET /`: API status message.
- `GET /health`: System health status (`{"status": "ok"}`).
- `POST /session`: Requires Bearer token. Inserts a new row into `sessions` with `user_id = authenticated_user_id` and returns `session_id`.
- `POST /chat`: Requires Bearer token and `ChatRequest(session_id, message, debug)`. Verifies session ownership, runs Layer 1 router (`rule`), executes database vector retrieval (`clinical`, `journal`, or `both`), generates AI reply, stores messages, and returns reply + optional debug trace.
- `POST /journal`: Requires Bearer token and `JournalRequest(text)`. Inserts raw entry into `journal_entries` and triggers structure-aware chunking + 768-dim embedding ingestion into `journal_chunks`.
- `GET /personas`, `POST /personas`, `PUT /personas/{id}`, `DELETE /personas/{id}`: Authenticated CRUD for AI personas.
- `GET /medical-documents`, `POST /medical-documents`, `DELETE /medical-documents/{id}`: Authenticated PDF health records management with private Supabase Storage persistence.

---

## 5. Database Schema ([schema_core.sql](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/database/schema_core.sql))

1. **`profiles`**: User profiles and onboarding data.
2. **`sessions`**: Chat sessions linked to `profiles.id`.
3. **`messages`**: Chat messages linked to `sessions.id`.
4. **`journal_entries`**: Source-of-truth table containing original raw journal submissions (`id`, `user_id`, `content`, `created_at`).
5. **`journal_chunks`**: Derived RAG retrieval units table:
   - Columns: `id` (UUID PRIMARY KEY), `journal_entry_id` (UUID -> `journal_entries.id ON DELETE CASCADE`), `user_id` (UUID -> `profiles.id ON DELETE CASCADE`), `chunk_index` (INT), `content` (TEXT), `embedding` (vector(768)), `created_at` (TIMESTAMP).
   - Indexes: `idx_journal_chunks_user_id`, `idx_journal_chunks_entry_id`.
6. **`ai_personas`**: AI persona configurations (`name`, `role_type`, `base_personality`, `custom_instructions`).
7. **`medical_documents`**: Metadata for uploaded PDF files stored in private Supabase Storage bucket `medical-documents`.

---

## 6. AI & RAG Pipeline Implementation Status

| RAG Component | Status | Implementation Details |
| --- | --- | --- |
| **Layer 1 Router** | **Implemented** | `AGENT_ROUTER=rule` pattern matching router (`backend/agent/routers/rule.py`). 100.0% accuracy on 529 golden regression cases, 0 crisis/web false positives, 0.2 ms/case. |
| **Layer 2 Corpus Selection** | **Implemented** | Two-signal intent routing ($S_{\text{clinical}}$ vs. $S_{\text{journal}}$) in `backend/agent/routers/rule.py` accurately directing queries to `clinical`, `journal`, `both`, or `none`. 100.0% accuracy on 36-case contrast group suite, 0 false retrieval activations. |
| **Layer 3 Clinical KB Retrieval** | **Implemented** | `RAG_STRATEGY=mmr` over 1,123 `kb_documents`. Relevance + token Jaccard diversity reranking (`lambda_mult = 0.7`). |
| **Layer 2 Journal Corpus** | **Implemented** | Structure-aware paragraph/sentence-boundary chunking (`journal_chunking.py`), 768-dim Gemini embeddings (`embed.py`), idempotent ingestion (`journal_ingestion.py`), strict user-isolated pgvector search (`WHERE user_id = authenticated_user_id`), MMR reranking (`journal_retrieve.py`), synthetic dataset seeder (`seed_dummy_journals.py`), and `clinical`/`journal`/`both` multi-corpus orchestration (`orchestrator.py`). |
| **V1 Journal Chunking Approach** | **Implemented** | V1 structure-aware boundary chunking (preserves paragraph boundaries `\n\n` and sentence integrity without mid-sentence splits or arbitrary length cuts). *Note: Sophisticated model-based semantic chunking has NOT yet been implemented.* |
| **Medical Document RAG** | Not Implemented | PDF documents are stored in private Supabase Storage. Text extraction, OCR, document chunking, and medical RAG retrieval are explicitly NOT implemented yet. |

---

## 7. Verification & Test Suite

- **Backend Pytest Suite**: 37/37 passing (`tests/test_corpus_selection.py`, `tests/test_journal_rag.py`, `tests/test_retrieval_scoring.py`, `tests/test_retrieval_subdecisions.py`, `test_auth_endpoints.py`).
- **Layer 1 Golden Eval Suite**: 529/529 cases passing (100.0% overall accuracy, 100.0% crisis recall, 0 false positives).
- **Layer 2 Corpus Selection Suite**: 36/36 cases passing (100.0% accuracy across clinical, journal, both, none).
- **Synthetic Dataset**: 112 unique synthetic journal entries across 12 realistic life themes and timeline spreads, ingested into `journal_entries` and `journal_chunks` (114 chunks) with real 768-dimensional Gemini embeddings (`gemini-embedding-2`).

