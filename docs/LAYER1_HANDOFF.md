# Layer 1 handoff

## Status

Layer 1 (agent orchestration / routing) is **done and shipped as rule-based**.

| Decision | Choice | Why |
|----------|--------|-----|
| Production router | `AGENT_ROUTER=rule` | Free, ~0.3ms/message, 100% on regression, safety gates green |
| AI router | Built, optional | Keep for experiments; do not put on the hot path (API cost) |
| Model spend | Response generation only | Routing should not burn quota |

## What changed (high level)

- Single decision point: `agent/routers/` (`rule`, `ai`) → `orchestrator.py`
- Six paths: crisis, direct_answer, search_database, web_search, structured_query, document_extraction
- Golden suite consolidated to five case files + templates (see strategy map)
- Held-out counseling set measures generalization; **do not tune keywords against it**

## Golden files (read this first)

| File | Meaning |
|------|---------|
| `eval/golden/core.yaml` | Everyday cases |
| `eval/golden/safety.yaml` | Crisis + must-not-overfire traps |
| `eval/golden/tools.yaml` | Web / structured / document |
| `eval/golden/edges.yaml` | Hard phrasing |
| `eval/golden/heldout_counseling.yaml` | External check only |
| `eval/golden/templates.yaml` | Generators for `gen_*` in core |

## Commands

```bash
cd backend
python -m eval.validate_golden
python -m eval.layer1_eval --router rule --exclude-tag heldout
python -m eval.layer1_eval --router rule --tag heldout --no-gate
```

Latest scores: regression **100%** (529); held-out **75.5%** (200); crisis recall **100%** on both; crisis/web traps **0** on regression.

## Env knobs

- `AGENT_ROUTER=rule` (default) or `ai`
- `AGENT_ROUTER_MODEL` — model for AI router
- `AGENT_ROUTER_API_KEY` — optional paid key for AI router evals only

## Who owns what next

- **Partner — Layer 2:** corpus selection (clinical vs journal vs both) once journal retrieval exists. Schema field `expected_corpus` is already on search cases.
- **You — Layer 3:** retrieval strategy bake-off (`python -m eval.run_strategy_compare`).

## Code map

- Routers: `backend/agent/routers/`
- Orchestrator: `backend/agent/orchestrator.py`
- Clinical gating vocab: `backend/rag/retrieve.py` (`CATEGORY_KEYWORDS`, `CLINICAL_SIGNALS`)
- Eval: `backend/eval/layer1_eval.py`, `backend/eval/validate_golden.py`
- Full strategy write-up: `docs/agentic_rag_testing_strategy_map.md`
