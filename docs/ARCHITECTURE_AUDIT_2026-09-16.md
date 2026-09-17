# Copefy architecture audit — 2026-09-16

Scope: code and tracked SQL/configuration as checked out on `kiara/final-additions`. This is an implementation audit, not a claim about untracked Supabase dashboard configuration.

## Actual request flow

1. React restores a Supabase browser session in `frontend/src/contexts/auth_context.tsx`. Protected routes require a user and a completed profile. `ChatSessionProvider` creates/selects a server session and persists its ID in browser `localStorage`.
2. `HomePage` sends the Supabase access token with `POST /chat`. The FastAPI dependency verifies it with `supabase.auth.get_user`; `/chat` confirms that the requested `sessions.user_id` is the caller, stores the user message, loads the complete session history, loads profile preferences, and gives the last six prior turns to the agent.
3. The default rule router selects one of `crisis`, `direct_answer`, `search_database`, `web_search`, `structured_query`, or `document_extraction`. Crisis returns fixed copy and never calls Gemini. The other three tool paths currently return an `unavailable` note, then Gemini generates the reply.
4. `search_database` selects clinical, journal, or both. Clinical retrieval embeds the enriched query, calls the untracked-in-schema `match_kb_chunks` Postgres function, enriches hits from `kb_documents`, and uses the configured strategy. Journal retrieval embeds the query, queries `journal_chunks` with `WHERE user_id = $2`, then diversity-reranks. Retrieved clinical/journal chunks are concatenated into the generation prompt.
5. Gemini writes a reply; a narrow post-generation pattern check replaces therapist-identity or named-diagnosis claims. The assistant message is stored. Debug traces are returned when requested/enabled.

## RAG and model details

- Generation primary: `gemini-2.5-flash`, temperature 0.7, 1,024 output-token cap. Fallbacks are `gemini-3.5-flash-lite`, `gemini-flash-latest`, and `gemini-3.6-flash` (the primary duplicate is deduplicated at runtime).
- Embeddings: `gemini-embedding-2`, requested at 768 dimensions. The in-process query embedding cache has 1,024 entries; API calls are paced at roughly 85/minute and retry rate limits.
- Clinical retrieval default: `RAG_STRATEGY=mmr`: category-filtered (then broad fallback) pgvector candidate retrieval, 20 candidates, MMR over cosine similarity using token-Jaccard redundancy and lambda 0.7, then three prompt chunks. The clinical RPC and `kb_documents` / chunk DDL are not in tracked SQL.
- Journal ingestion: `/journal` first persists raw content, then best-effort chunks it on paragraph/sentence boundaries, embeds each chunk, deletes previous chunks for the entry, and inserts `journal_chunks`. Ingestion failure is logged but `/journal` still returns success. Journal MMR fetches 15 and returns up to three. There is no similarity cutoff, so unrelated personal entries can be returned.

## Authentication, ownership, and privacy

- Browser authentication is Supabase Auth. Backend uses the Supabase **service-role** client for JWT lookup and database/storage operations, so application-level checks are the main enforcement visible in code.
- `/chat` and message reads use an ownership check; personas and medical documents check ownership before mutation. Journal query isolation is enforced in its SQL query. Session ownership uses `404` for absent or unowned sessions to avoid existence disclosure.
- The frontend reads/writes `profiles` directly with the anon key. No RLS or Storage policy statements are tracked, so production safety of browser-side profile access and the private bucket cannot be audited from this repository.
- Medical uploads accept only a `.pdf` name, PDF MIME type, a `%PDF-` header in the first KiB, and <=10 MiB. Objects use `<user UUID>/<random>_<sanitized filename>` in the `medical-documents` bucket and only the path is stored. There is no download endpoint, malware scan, OCR/text extraction, document chunking, or medical-document retrieval.

## Tracked schema and configuration

- `database/schema_core.sql` is the closest authoritative schema: profiles, sessions, messages, triage logs, personas, journal entries/chunks, and medical-document metadata. It enables pgvector and creates the Auth-to-profile trigger.
- It has no RLS enablement/policies, Storage bucket/policies, `kb_documents`, KB chunks, `match_kb_chunks`, vector ANN index, uniqueness constraint for `(journal_entry_id, chunk_index)`, or schema migration history for most tables. `database/db.sql` is explicitly legacy and conflicts with current table/user/vector shapes.
- Backend `.env` supports Supabase URL/service key, direct `DATABASE_URL`, CORS origins, Gemini chat/embed keys and model overrides, router key/model overrides, `RAG_STRATEGY`, and `RAG_DEBUG`. Frontend uses Supabase URL/anon key, backend base URL, and `VITE_RAG_DEBUG`. Defaults put debug traces on in both example files; traces include source excerpts and similarity metadata.

## Validation baseline

| Command | Result |
| --- | --- |
| `backend\\venv\\Scripts\\python.exe -m pytest` | PASS: 79 tests; collects only `backend/tests` per `pytest.ini` (one cache-permission warning). |
| `backend\\venv\\Scripts\\python.exe -m pytest tests test_auth_endpoints.py` | FAIL: 92 passed, 2 failed. Both `/chat` tests mock `.eq(...).execute()` while production now calls `.eq(...).maybe_single().execute()`, so mocks yield no session and receive 404. One test also expects 403 although production intentionally returns 404 for an unowned session. |
| `backend\\venv\\Scripts\\python.exe -m eval.validate_golden` | PASS: 1,360 YAML cases validate. |
| `frontend\\npm run build` | PASS: `tsc -b` and Vite build. The sandbox initially blocked esbuild child-process spawning; the permitted retry passed. |

The 79 test suite covers prompt/injection helpers, retrieval scoring/MMR helpers, journal chunking/eval helpers, model fallback helpers, and eval summary helpers. The two root auth tests are outside the configured `testpaths`; there are no frontend unit/integration tests, live database integration tests, API contract tests for session/history, or real Gemini/Supabase end-to-end tests.

## Material gaps and risks

- **Retrieval/medical RAG:** clinical KB schema, source ingestion, quality/provenance, and index/RPC deployment are not versioned here. Retrieval has no score-based abstention, citations in user replies, source freshness/version controls, metadata filters beyond category, or document RAG. Journal ingestion is synchronous, best-effort, non-transactional with the source insert, and has no retry queue or operational status.
- **Evaluation:** the golden suite is substantial, but much router coverage is authored to its rules; handoffs report a much weaker held-out result. Retrieval evaluation is mostly category/phrase based. LLM judges and DeepEval are manual, rely on Gemini, omit crisis/negative reply cases, and documented scores warn of saturation/noise. No CI workflow is tracked.
- **Safety:** crisis routing/fixed response, preference-field injection filtering, and a narrow output diagnosis check exist. Chat-message and retrieved-document/KB prompt injection are not filtered; no structured risk assessment, escalation workflow, regional crisis localization, clinical advice/medication guardrail, human review, safety event persistence, or adversarial end-to-end safety suite is visible. `triage_logs` and `messages.is_safety_flagged` are defined but not written by the runtime path.
- **Privacy/security:** no tracked RLS/Storage policy or retention/deletion/export design; sensitive chat, journal, profile, and document bytes go to Supabase and prompts go to Gemini. Backend logs user/session identifiers and source URLs. Debug traces can expose retrieved journal excerpts to the browser. There is no rate limiting, audit logging, consent gate enforcement in chat, encryption/key-management documentation, or malware/content scanning.
- **Audio/video:** UI has a disabled “Voice input (coming soon)” control only. There is no capture, transcription, media upload, video path, consent model, storage lifecycle, or multimodal safety handling.

## Important implementation map

| Concern | Primary files |
| --- | --- |
| Chat UI/session/history | `frontend/src/pages/home_page.tsx`, `frontend/src/contexts/chat_session_context.tsx`, `frontend/src/lib/api.ts` |
| FastAPI/auth/documents | `backend/main.py`, `backend/auth.py`, `backend/db.py` |
| Router/generation safety | `backend/agent/orchestrator.py`, `backend/agent/routers/rule.py`, `backend/agent/prompts.py`, `backend/agent/injection_filter.py`, `backend/agent/persona.py` |
| KB/journal retrieval | `backend/rag/embed.py`, `backend/rag/search.py`, `backend/rag/retrieve.py`, `backend/rag/strategies/pipeline.py`, `backend/rag/journal_ingestion.py`, `backend/rag/journal_retrieve.py` |
| Schema/evals/tests | `database/schema_core.sql`, `backend/eval/`, `backend/tests/`, `backend/test_auth_endpoints.py` |
