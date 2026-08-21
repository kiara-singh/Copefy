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
- A single-session React chat interface communicating with a FastAPI backend. Requests are authenticated via Bearer tokens, checking session ownership and storing messages in Supabase.
- A journal entry form submitting text under the authenticated user's ID to Supabase.

### Major Technologies & Frameworks
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Router DOM (v6), `@supabase/supabase-js`.
- **Backend**: Python 3.11+, FastAPI, Uvicorn, Pydantic Settings, `python-multipart`, `supabase-py`.
- **Database & Auth**: Supabase (PostgreSQL with Supabase Auth, Supabase Storage, and `pgvector` extension enabled in SQL schema).

---

## 2. Repository Structure

```
Copefy/
├── .agents/
│   └── rules/
│       └── project-state-maintenance.md     # Agent rule to maintain PROJECT_STATE.md
├── backend/
│   ├── config.py                            # Pydantic BaseSettings loading environment variables
│   ├── db.py                                # Cached Supabase client initializer & connection stubs
│   ├── main.py                              # Authenticated FastAPI endpoints for health, session, chat, journal, personas, and medical documents
│   ├── test_auth_endpoints.py               # Unit test suite verifying JWT auth, session ownership, persona CRUD & medical document CRUD (15/15 tests passing)
│   └── requirements.txt                     # Backend Python dependencies (includes python-multipart)
├── database/
│   ├── db.sql                               # Legacy SQL table definitions (deprecated, superseded by schema_core.sql)
│   ├── schema_core.sql                      # Authoritative SQL schema (profiles, sessions, messages, journal_entries, triage, ai_personas, medical_documents)
│   └── schema_rag.sql                       # SQL vector test table schema (pgvector test)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── app_layout.tsx               # Main container layout with Sidebar and Outlet
│   │   │   ├── communication_style_quiz.tsx # 3-round pairwise tournament preference quiz
│   │   │   ├── protected_route.tsx          # Route guard checking authentication and onboarding completion
│   │   │   ├── public_route.tsx             # Route guard redirecting authenticated users away from /login
│   │   │   └── sidebar.tsx                  # Collapsible navigation sidebar (Chat, Journal, Personas, Settings)
│   │   ├── constants/
│   │   │   └── quiz_constants.ts            # Communication style types, scenario text, and sample options
│   │   ├── contexts/
│   │   │   └── auth_context.tsx             # Supabase Auth state provider and profile fetching/updating
│   │   ├── lib/
│   │   │   ├── api.ts                       # Fetch wrapper for FastAPI backend attaching Bearer auth header & Medical Document methods
│   │   │   └── supabase_client.ts           # Supabase JS client instantiation
│   │   ├── pages/
│   │   │   ├── home_page.tsx                # Chat page interface
│   │   │   ├── journal_page.tsx             # Journal submission form
│   │   │   ├── login_page.tsx               # Auth page for sign in and registration
│   │   │   ├── onboarding_page.tsx          # 3-step user onboarding wizard
│   │   │   ├── personas_page.tsx            # AI Personas CRUD management page
│   │   │   └── settings_page.tsx            # Settings page (profile, style quiz, wellness goals, medical document upload/delete, logout)
│   │   ├── App.tsx                          # React Router route definitions
│   │   ├── main.tsx                         # React application entry point with AuthProvider & BrowserRouter
│   │   └── index.css                        # Tailwind CSS global styles
│   ├── package.json                         # Frontend dependencies and npm scripts
│   ├── tailwind.config.js                   # Tailwind CSS configuration
│   └── vite.config.ts                       # Vite build configuration
├── PROJECT_STATE.md                         # Current project status documentation
└── README.md                                # Repository setup instructions and overview
```

---

## 3. Frontend

### Structure & Framework
- Framework: React 18 with TypeScript using Vite as the bundler.
- Styling: Tailwind CSS.
- Routing: React Router DOM v6.

### Implemented Pages & Components
- **[settings_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/settings_page.tsx)**: Settings & personalization page featuring:
  1. Preferred Name form.
  2. Communication Style selection grid, custom style input, and interactive style quiz modal.
  3. Wellness Goal & Personalization Context editor.
  4. **Medical Documents Section**: PDF file picker & validator (verifying `.pdf` extension and 10 MB size limit), upload action with loading indicator, list of uploaded documents showing original filename and upload date, and a Delete Confirmation modal.
  5. Log Out button executing `supabase.auth.signOut()`.
- **[login_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/login_page.tsx)**: Handles email/password sign-in and registration via `supabase.auth.signInWithPassword()` and `supabase.auth.signUp()`.
- **[onboarding_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/onboarding_page.tsx)**: 3-step setup wizard for preferred name, communication style, and wellness goals.
- **[personas_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/personas_page.tsx)**: Custom AI Personas CRUD page (`name`, `role_type`, `base_personality`, `custom_instructions`).
- **[home_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/home_page.tsx)**: Main chat interface communicating with `/chat`.
- **[journal_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/journal_page.tsx)**: Textarea interface for submitting journal entries to `/journal`.

### Frontend Backend & Database Communication
- Direct Supabase JS Client ([supabase_client.ts](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/lib/supabase_client.ts)): Used for auth operations and querying/updating `profiles`.
- REST API Client ([api.ts](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/lib/api.ts)): Sends authenticated requests to FastAPI backend (`/session`, `/chat`, `/journal`, `/personas`, `/medical-documents`). `api_request` automatically attaches `Authorization: Bearer <access_token>` and handles `FormData` for file uploads without corrupting boundary headers.

---

## 4. Backend

### Structure
Built with Python 3.11+ and FastAPI. Configured via Pydantic Settings in [config.py](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/backend/config.py) and initialized in [main.py](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/backend/main.py).

### Authentication Dependency
Uses FastAPI `HTTPBearer` security dependency (`get_current_user`) to validate the caller's Supabase access token via `get_supabase().auth.get_user(token)`. Rejects missing, invalid, or expired tokens with HTTP 401 Unauthorized.

### Existing API Endpoints
- `GET /`: Returns `{"message": "Copefy API is running."}`
- `GET /health`: Returns `{"status": "ok"}`
- `POST /session`: Requires Bearer token. Inserts a new row into `sessions` with `user_id = authenticated_user_id` and returns `session_id`.
- `POST /chat`: Requires Bearer token and `ChatRequest(session_id, message)`. Verifies session ownership, stores user and assistant messages, returns reply.
- `POST /journal`: Requires Bearer token and `JournalRequest(text)`. Inserts journal entry for authenticated user.
- `GET /personas`, `POST /personas`, `PUT /personas/{id}`, `DELETE /personas/{id}`: Full CRUD for AI Personas owned by the authenticated user.
- `GET /medical-documents`: Requires Bearer token. Returns metadata records for medical documents owned by the authenticated user, ordered by `uploaded_at desc`.
- `POST /medical-documents`: Requires Bearer token and `file: UploadFile` (multipart/form-data). Validates PDF extension, MIME type (`application/pdf`), 10 MB size limit, and `%PDF-` magic header bytes. Uploads file to private Supabase Storage bucket `medical-documents` under user-scoped path `<user_uuid>/<unique_filename>.pdf`, inserts record into `medical_documents`, and returns created record. If database insertion fails, cleans up the uploaded storage object to prevent orphan files.
- `DELETE /medical-documents/{document_id}`: Requires Bearer token. Verifies document ownership (HTTP 404 if missing, 403 if unowned). Deletes storage object from private `medical-documents` bucket and deletes row from `public.medical_documents`.

---

## 5. Database & Storage Setup

### Infrastructure Setup (Required Manual Steps)
- **Supabase Storage Bucket**: The private storage bucket `medical-documents` must be created in the Supabase Dashboard (`Storage` -> `New Bucket` -> Name: `medical-documents`, `Public bucket`: **OFF / Private**).

### Authoritative Tables ([schema_core.sql](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/database/schema_core.sql))
1. **`profiles`**: User profiles and onboarding data.
2. **`sessions`**: Chat sessions linked to `profiles.id`.
3. **`messages`**: Chat messages linked to `sessions.id`.
4. **`journal_entries`**: Journal text and `vector(768)` embedding column.
5. **`ai_personas`**: AI persona configurations (`name`, `role_type`, `base_personality`, `custom_instructions`).
6. **`medical_documents`**:
   - Columns: `id` (UUID PRIMARY KEY), `user_id` (UUID -> `profiles.id`), `file_name` (VARCHAR(255) - original filename), `storage_url` (TEXT - private Supabase Storage object path `<user_uuid>/<unique_filename>.pdf`), `uploaded_at` (TIMESTAMP).
   - *Note on `storage_url`*: Preserved as the column name storing the private object path reference within the private `medical-documents` storage bucket (not a public URL).

---

## 6. AI / RAG Implementation

| RAG Area | Status | Implementation Details |
| --- | --- | --- |
| Knowledge base ingestion | Not implemented | No ingestion pipeline, loaders, or chunkers exist. |
| Document text extraction | **Not implemented** | Medical PDF files are uploaded and stored in private Supabase Storage. Text extraction, OCR, and parsing are explicitly NOT implemented yet. |
| Document chunking | Not implemented | No strategy or code for text chunking exists. |
| Embeddings | Not implemented | No embedding model calls or pipeline exist. |
| Vector search / retrieval | Not implemented | No similarity queries (cosine/L2 distance) implemented. |
| RAG integration | Not implemented | No prompt templates, context assembly, or RAG retrieval logic. |

---

## 7. Data Flows

### Medical Document Flow
1. User opens Settings page ([settings_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/settings_page.tsx)) -> calls `get_medical_documents()` -> `GET /medical-documents` with Bearer token.
2. User selects PDF file -> Frontend validates `.pdf` extension and 10 MB size limit.
3. User submits -> `upload_medical_document(file)` sends multipart `FormData` request to `POST /medical-documents` with Bearer token.
4. FastAPI backend validates JWT, file extension, MIME type, 10 MB file size, and `%PDF-` magic header bytes.
5. Backend uploads file to private Supabase Storage bucket `medical-documents` at path `<user_uuid>/<unique_filename>.pdf`.
6. Backend creates metadata row in `public.medical_documents` (`user_id`, `file_name`, `storage_url`). If DB insert fails, uploaded file is deleted from Storage.
7. Document list updates immediately in Settings UI.
8. User clicks Delete -> confirms modal prompt -> calls `delete_medical_document(id)` -> `DELETE /medical-documents/{id}`. Backend verifies ownership, removes object from Supabase Storage, and deletes DB row.

---

## 8. Current Implementation Status

| Component | Status | Notes |
| --- | --- | --- |
| Authentication & Auth State | Implemented | Supabase Auth integration, `AuthProvider` wrapper, and `HTTPBearer` JWT verification. |
| User Profile & Onboarding | Implemented | 3-step onboarding flow, style quiz, and DB syncing. |
| User Settings & Customization | Implemented | Editing name, communication style, wellness goals, and signing out. |
| AI Personas Management | Implemented | `/personas` page, card grid, Create/Edit/Delete modals, and authenticated `/personas` CRUD REST endpoints. |
| Medical Documents Management | **Implemented** | Settings section for uploading, listing, and deleting PDF medical records. Private Supabase Storage bucket (`medical-documents`) and backend validation (extension, MIME, 10MB limit, `%PDF-` header). |
| Chat UI | Implemented | Visual chat component with session management and message storage. |
| Journal UI | Implemented | Form to submit journal entry authenticated to user's UUID. |
| Backend Server & REST Endpoints | Implemented | FastAPI endpoints `/`, `/health`, `/session`, `/chat`, `/journal`, `/personas`, `/medical-documents`. All endpoints validate Bearer tokens. |
| Document Extraction & RAG | **Not Implemented** | Medical PDFs are stored as raw files in private Storage. PDF parsing, OCR, text extraction, chunking, and embedding generation are explicitly NOT implemented yet. |

---

## 9. Important Files for Future Development

- **Database Schema**:
  - Authoritative schema: [schema_core.sql](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/database/schema_core.sql)

- **Frontend Core & Features**:
  - Settings page with Medical Documents UI: [settings_page.tsx](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/pages/settings_page.tsx)
  - Backend API client: [api.ts](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/frontend/src/lib/api.ts)

- **Backend API & Data Services**:
  - Main FastAPI application: [main.py](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/backend/main.py)
  - Unit test suite: [test_auth_endpoints.py](file:///c:/Users/neele/Documents/Copefy%20Summer%20Internship%202026/Copefy/backend/test_auth_endpoints.py)
