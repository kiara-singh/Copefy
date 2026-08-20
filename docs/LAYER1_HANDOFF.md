# Layer 1 handoff

Context for anyone continuing Copefy’s agentic RAG work. Layer 1 is the step that decides **which capability handles each user message** before a reply is generated.

## Status

**Layer 1 is complete and should ship with the rule-based router.**

In practice that means: every chat message goes through one routing decision (crisis, direct answer, search the knowledge base, web search, structured query, or document extraction). The live default is pattern matching (`AGENT_ROUTER=rule`), not an LLM call. That keeps routing free and fast (~0.3 ms per message) and reserves model spend for writing the actual response.

An AI router is implemented and can be swapped in for experiments, but it is not the production default. Free-tier quotas make full AI bake-offs slow and expensive relative to the value; the rule router already clears the regression suite and the safety gates.

| Topic | Current state |
|-------|----------------|
| Production default | `AGENT_ROUTER=rule` |
| AI router | Built under `agent/routers/ai.py`; optional via config |
| Regression suite | 529 cases at 100% accuracy; crisis and web trap false positives at 0 |
| Held-out check | 831 external counseling questions at 64.1%; crisis recall 95.8% |
| Safety gates | Eval exits non-zero if crisis recall drops or trap false positives appear |

The 100% regression score is for cases authored with the router. The held-out score is the honest generalization check. **Do not add keywords to chase the held-out file** — treat it as measurement only.

## What Layer 1 includes

- One decision point: `backend/agent/routers/` (`rule` and `ai`) called from `orchestrator.py`
- Six paths: `crisis`, `direct_answer`, `search_database`, `web_search`, `structured_query`, `document_extraction`
- Golden eval suite consolidated into five case files plus templates (below)
- Held-out counseling set from HuggingFace for generalization checks

Tool backends for web search, structured query, and document extraction are still stubs. Routing to them works; executing those tools is later work.

## Golden files

All under `backend/eval/golden/`. Every `*.yaml` except `templates.yaml` is loaded and scored.

| File | What it is |
|------|------------|
| `core.yaml` | Everyday coverage (hand-written seeds + template-generated cases) |
| `safety.yaml` | Crisis positives and negative traps (`crisis_trap`, `web_trap`) |
| `tools.yaml` | Web / structured / document positives and `tool_trap` negatives |
| `edges.yaml` | Hard phrasing: behavioral symptoms, typos/slang, multi-turn |
| `heldout_counseling.yaml` | External counseling questions — **measure only, do not tune against** |
| `templates.yaml` | Generators for the `gen_*` rows inside `core.yaml` |

## Commands

```bash
cd backend
python -m eval.validate_golden
python -m eval.layer1_eval --router rule --exclude-tag heldout
python -m eval.layer1_eval --router rule --tag heldout --no-gate
```

Re-run the regression command whenever routing patterns or golden labels change.

## Environment

| Variable | Purpose |
|----------|---------|
| `AGENT_ROUTER` | `rule` (default) or `ai` |
| `AGENT_ROUTER_MODEL` | Model id when using the AI router |
| `AGENT_ROUTER_API_KEY` | Optional separate API key for AI router evals (avoids burning the main app key) |

## Suggested next work

These layers are described in more detail in `docs/agentic_rag_testing_strategy_map.md`.

| Layer | Focus | Notes |
|-------|--------|------|
| **2 — Corpus selection** | After `search_database`, choose clinical KB vs journal vs both | `expected_corpus` is already on search cases; blocked on journal retrieval existing |
| **3 — Retrieval strategies** | How to fetch and rank chunks inside a corpus | Clinical bake-off done; production default `mmr` — see `docs/LAYER3_HANDOFF.md` |
| **Tool backends** | Implement web / structured / document tools | Router already selects these paths |

## Code map

| Area | Path |
|------|------|
| Routers | `backend/agent/routers/` |
| Orchestrator | `backend/agent/orchestrator.py` |
| Clinical vocabulary used by the rule router | `backend/rag/retrieve.py` (`CATEGORY_KEYWORDS`, `CLINICAL_SIGNALS`) |
| Layer 1 eval | `backend/eval/layer1_eval.py`, `backend/eval/validate_golden.py` |
| Layer 3 eval | `backend/eval/run_strategy_compare.py`, `backend/eval/retrieval_scoring.py` |
| Full strategy map | `docs/agentic_rag_testing_strategy_map.md` |
