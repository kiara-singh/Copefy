# Layer 4 handoff (generation & persona)

Layer 4 is **how** the agent assembles the prompt and generates the reply after Layer 1 routes and Layer 3 retrieves (when applicable). Production now uses the user's onboarding **communication style**, **preferred name**, and **wellness goal** from `profiles`.

## Status

**Ship persona-aware generation with cross-layer pipeline tracing.**

| Topic | Current state |
|-------|----------------|
| Persona source | `profiles.communication_style` (+ name, goal) |
| Preset styles | Gentle & Supportive, Motivational & Encouraging, Direct & Action-Oriented, Calm & Reflective |
| Custom styles | Free-text from Settings is passed through as a custom tone instruction |
| Crisis path | Fixed 988 response — persona is not applied |
| Pipeline trace | Layers 1–4 in `/chat` trace + terminal when `RAG_DEBUG=true` |
| Layer 2 journal | Corpus field logged; journal retrieval still not wired |

## What Layer 4 includes

- `backend/agent/persona.py` — `UserPersona`, `build_system_instruction`, `closing_instruction`
- `backend/agent/prompts.py` — shared safety core + four style overlays
- `backend/profiles.py` — load persona from Supabase on each chat turn
- `backend/auth.py` — resolve user id from Supabase JWT (`Authorization: Bearer`)
- `backend/agent/pipeline_trace.py` — structured L1–L4 trace with timing
- Settings page already lets users change style, name, and goals

## Pipeline trace (all layers)

Each chat turn records:

| Layer | What you see |
|-------|----------------|
| **L1 routing** | path, router, reason |
| **L2 corpus** | clinical / journal / both (defaults to clinical until Layer 2 ships) |
| **L3 retrieval** | strategy (`mmr`), query, categories, candidate→returned counts, top similarity, sources |
| **L4 generation** | communication style, model, history turns, KB chunks in prompt, name/goal flags |

**Frontend:** set `VITE_RAG_DEBUG=true` — expandable timeline under each assistant reply.

**Terminal:** set `RAG_DEBUG=true` — `[pipeline] L1 …` lines per turn.

## Commands

```bash
cd backend
python -m pytest tests -q
python -m pytest tests/test_persona_prompt.py -q
```

## Env

| Variable | Purpose |
|----------|---------|
| `RAG_DEBUG` | Terminal pipeline logs + always include trace in `/chat` response |
| `GEMINI_API_KEY` | Chat generation |
| `GEMINI_CHAT_MODEL` | Default `gemini-flash-latest` |
| `RAG_STRATEGY` | Layer 3 strategy shown in trace (default `mmr`) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Profile load + JWT verify |

Frontend: `VITE_RAG_DEBUG=true` to show the trace panel.

## Code map

| Area | Path |
|------|------|
| Persona builder | `backend/agent/persona.py` |
| Prompts / safety | `backend/agent/prompts.py` |
| Pipeline trace | `backend/agent/pipeline_trace.py` |
| Orchestrator | `backend/agent/orchestrator.py` |
| Profile load | `backend/profiles.py` |
| Auth helper | `backend/auth.py` |
| Chat API | `backend/main.py` |
| Trace UI | `frontend/src/components/chat_trace_panel.tsx` |
| API client | `frontend/src/lib/api.ts` |
| Tests | `backend/tests/test_persona_prompt.py` |

## Manual test checklist

1. Complete onboarding with a communication style.
2. Send a clinical message in chat — expand pipeline trace (L1–L4).
3. Check backend terminal for `[pipeline]` lines.
4. Change style in Settings — next reply should reflect new L4 style.
5. Crisis message → L1 `crisis` only, fixed 988 reply.
