# Layer 5 handoff (eval metrics)

Layer 5 is **how we score the stack** after routing (L1), corpus choice (L2), retrieval (L3), and generation (L4). This pass measures ranked journal search and the **reply**. It does **not** change production retrieval.

Think of it as three quizzes, not one score:

1. **Did search put the right memory high enough?** Hit@k / MRR
2. **Did the reply stay grounded and on-topic?** DeepEval (manual)
3. **One page for stakeholders** that copies those numbers

## Status

**Ship the eval harness. Do not add a journal similarity cutoff yet.**

| Topic | Current state |
|-------|----------------|
| Ranked journal metrics | Hit@1 **76%**, Hit@3 **90%**, MRR **0.83** on 21 callbacks+paraphrases |
| Callback vs paraphrase | Callback Hit@3 **87%** (15); paraphrase Hit@3 **100%** (6) |
| Negatives (forced search) | **0 / 5** empty — still returns 3 unrelated real days |
| DeepEval | **26 / 26** scored. Faithfulness **1.0**, relevancy **1.0**, G-Eval no-diagnosis **0.1** (flaky scale). Judge `gemini-3.5-flash-lite`. Not CI |
| Cover sheets | Notes [`eval_summary.md`](../backend/eval/results/eval_summary.md) · slides [`eval_stats.md`](../backend/eval/results/eval_stats.md) |
| Journal cutoff | **Out of scope this pass** — still always returns top 3 |

Production search is unchanged: [`search_journal_chunks()`](../backend/rag/journal_retrieve.py#L18) with `top_k=3` from chat.

## Why this exists

We already knew phrase-match recall (~90% on the 21 real memories) and a homemade snippet judge. Interviews and the next product week need **ranked** numbers (was the gold day #1 or buried at #3?) and a **named** reply metric stack, not a second custom “is the bubble grounded?” prompt.

**DeepEval is not a smarter model.** Same idea as [`judge.py`](../backend/eval/judge.py#L1): a Gemini judge reads text and scores it. The value is the recipe — `FaithfulnessMetric` extracts claims, then checks each against snippets — plus resume language. Keep [`score_retrieval()`](../backend/eval/judge.py#L277) for snippets. Use DeepEval only for the reply.

**Faithfulness ≠ right memory.** If search injects the wrong day and the model uses it, Faithfulness can still be 1.0. Always read it next to Hit@k and empty-on-negatives.

## How it works

### 1. Hit@k and MRR (journal search)

[`gold_rank()`](../backend/eval/journal_retrieve.py#L179) · [`hit_at_k()`](../backend/eval/journal_retrieve.py#L195) · [`reciprocal_rank()`](../backend/eval/journal_retrieve.py#L201) · [`summarize_ranked_metrics()`](../backend/eval/journal_retrieve.py#L240)

For each labeled case that **has a real matching day** (callback + paraphrase only):

- Walk journal snippets in rank order.
- Gold = snippet contains the `expected_contains` phrase (or the gold entry id).
- **Hit@1 / Hit@3** — gold in the first / first three snippets.
- **MRR** — 1.0 if rank 1, 0.5 if rank 2, 0 if missing. Not production **MMR** ranking.

Wired into the existing journal judge runner: [`run_judge_compare.py` case export](../backend/eval/run_judge_compare.py#L271) and [ranked table print](../backend/eval/run_judge_compare.py#L362).

**Do not fold negatives or mood traps into the Hit@k headline.**

| Slice | What we ask |
|-------|-------------|
| 21 memory cases | Was the right day in the top k? |
| 5 negatives | If journals were searched anyway, did we return **nothing**? (today: no) |
| 4 mood traps | No gold day — judge-only / skip Hit@k |

This run’s Hit@3 misses: [`journal_victorian_essay_01`](../backend/eval/golden/journal_eval.yaml#L21) (`Victorian`) and [`journal_chem_grade_01`](../backend/eval/golden/journal_eval.yaml#L101) (`B+`).

### 2. How to think about negatives

Live chat: the corpus router should often send “my dog ate my homework” to **no journal search**. That is a **router** question. Partner tests: [`test_corpus_selection.py`](../backend/tests/test_corpus_selection.py#L1). We did **not** add a second corpus-selection eval.

The five `expect_empty` rows stay in the **retrieval** quiz as a different question: **if journals were searched, did we inject three fake memories?** Vector search always returns nearest neighbors. [`retrieve_production_journal()`](../backend/eval/journal_retrieve.py#L606) calls the same path as [`run_agent()`](../backend/agent/orchestrator.py#L302).

On the summary page: *router should often never search; this number is retrieval-when-forced.*

### 3. DeepEval on replies (manual only)

[`run_generation_eval.py`](../backend/eval/run_generation_eval.py#L1)

1. Journal **callbacks + paraphrases** from [`journal_eval.yaml`](../backend/eval/golden/journal_eval.yaml#L1) plus a few labeled clinical queries ([`CLINICAL_SEED_IDS`](../backend/eval/run_generation_eval.py#L30)). **Skip negatives.** Skip crisis (fixed 988).
2. Retrieve like chat: journals via [`retrieve_production_journal()`](../backend/eval/journal_retrieve.py#L606); clinical via `retrieve_with_strategy`.
3. Generate like L4: [`_build_user_prompt()`](../backend/agent/orchestrator.py#L100) + [`_generate_reply()`](../backend/agent/orchestrator.py#L163).
4. Wrap `LLMTestCase(input, actual_output, retrieval_context)`.
5. Metrics: Faithfulness, Answer Relevancy, G-Eval no-diagnosis ([`NO_DIAGNOSIS_STEPS`](../backend/eval/run_generation_eval.py#L38)). Gemini judge. JSON to `eval/results/deepeval_generation.json`.
6. **`assert_test` is not used.** 429s skip that metric for the turn.

Full sheet (21 journal callbacks/paraphrases + 5 clinical seeds): Faithfulness **1.0** (26/26), Answer relevancy **1.0** (26/26), G-Eval **0.1** (26/26 — treat as a broken scale; reasons still say non-diagnostic). Paid ingest key + Lite only; 429s retried. Do not delete `deepeval_generation.json`.

### 4. Stakeholder one-pager

[`write_eval_summary.py`](../backend/eval/write_eval_summary.py#L1) pastes numbers from JSON + documented L1/L3 headlines. It is **not** a second judge.

Caveats after this Hit@k run: the quiz is still easy unique-token callbacks, but Hit@3 is **90% not 100%**, so we did **not** pad the set.

## Code map

Click a link to jump to the line.

| Area | Open at line |
|------|----------------|
| Hit@k / MRR helpers | [`gold_rank`](../backend/eval/journal_retrieve.py#L179) · [`hit_at_k`](../backend/eval/journal_retrieve.py#L195) · [`reciprocal_rank`](../backend/eval/journal_retrieve.py#L201) · [`summarize_ranked_metrics`](../backend/eval/journal_retrieve.py#L240) |
| Production journal search (always top-k) | [`search_journal_chunks`](../backend/rag/journal_retrieve.py#L18) |
| Chat retrieve + generate | [`run_agent` journal branch](../backend/agent/orchestrator.py#L298) · [`_build_user_prompt`](../backend/agent/orchestrator.py#L100) · [`_generate_reply`](../backend/agent/orchestrator.py#L163) |
| Journal judge + ranked JSON | [`_judge_journal` ranked fields](../backend/eval/run_judge_compare.py#L271) · [print Hit@k](../backend/eval/run_judge_compare.py#L362) |
| Snippet LLM judge (keep) | [`score_retrieval`](../backend/eval/judge.py#L277) |
| DeepEval reply script | [`run_generation_eval`](../backend/eval/run_generation_eval.py#L1) · [metrics](../backend/eval/run_generation_eval.py#L136) · [case picker](../backend/eval/run_generation_eval.py#L55) |
| Cover sheets | [`render_summary`](../backend/eval/write_eval_summary.py#L428) · [`render_stats`](../backend/eval/write_eval_summary.py#L452) · [notes](../backend/eval/results/eval_summary.md) · [tables](../backend/eval/results/eval_stats.md) |
| Golden journal queries | [`journal_eval.yaml`](../backend/eval/golden/journal_eval.yaml#L1) |
| Rank unit tests | [`test_hit_at_k_and_mrr_on_fake_ranks`](../backend/tests/test_journal_retrieve.py#L111) |
| Router “should we search?” | [`test_corpus_selection.py`](../backend/tests/test_corpus_selection.py#L1) |
| GitHub (after push) | [evalLayer tree](https://github.com/kiara-singh/Copefy/blob/evalLayer/backend/eval/journal_retrieve.py#L179) |

Same links on GitHub (line-accurate once this branch is pushed):

- https://github.com/kiara-singh/Copefy/blob/evalLayer/backend/eval/journal_retrieve.py#L179
- https://github.com/kiara-singh/Copefy/blob/evalLayer/backend/eval/run_generation_eval.py#L1
- https://github.com/kiara-singh/Copefy/blob/evalLayer/backend/eval/results/eval_summary.md
- https://github.com/kiara-singh/Copefy/blob/evalLayer/backend/rag/journal_retrieve.py#L18
- https://github.com/kiara-singh/Copefy/blob/evalLayer/backend/agent/orchestrator.py#L298

## Commands

```bash
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_journal_retrieve.py tests/test_eval_summary.py -q
.\venv\Scripts\python.exe -m eval.run_judge_compare --corpus journal --skip-judge --output eval/results/judge_journal.json
.\venv\Scripts\python.exe -m eval.run_generation_eval --output eval/results/deepeval_generation.json --write-summary
.\venv\Scripts\python.exe -m eval.write_eval_summary
```

Use the project venv. DeepEval is **manual** — do not add it to CI. Full JSON dumps stay gitignored except `eval_summary.md` and `eval_stats.md`.

`--skip-judge` is enough for Hit@k (no snippet-judge API). Drop it when you want the 1–5 snippet scores again.

## Env

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Embeddings; chat if ingest key unset |
| `GEMINI_INGEST_API_KEY` | Eval prefers this for chat + DeepEval judge (paid project) |
| `AGENT_ROUTER_API_KEY` | Optional; next in eval key order after ingest |
| `DATABASE_URL` | Live `journal_chunks` / `kb_documents` |
| `GEMINI_CHAT_MODEL` | Production chat; eval overwrites to Lite when ingest key is set |

DeepEval extra: `deepeval` in [`requirements.txt`](../backend/requirements.txt). Install in the venv; pytest does not import it.

## Demo (interview)

**Ranked search.** “On 21 real memories, Hit@3 is 90% and Hit@1 is 76% — the right day is usually in the prompt, not always first. Two misses: Victorian essay and B+ chemistry grade.”

**Negatives.** “If we force journal search on ‘my dog ate my homework,’ we still get three **real but unrelated** days (0/5 empty). The model is not inventing a fictional dog story from nothing. The router should often skip search; the cutoff is the week-after fix.”

**DeepEval.** “Faithfulness 1.0 on 26/26 means the bubble did not add facts beyond the snippets. It will not catch a fluent reply built on the **wrong real days** — that’s why Hit@k sits next to it.”

## Not in this layer

- Journal `min_similarity` / empty retrieve in production (week after eval)
- DeepEval in CI
- New diary or clinical KB
- Retuning `RAG_STRATEGY` from this journal sample
- Chat-box jailbreaks (Layer 4 settings path only)

## Week after (presentation fix)

[`search_journal_chunks`](../backend/rag/journal_retrieve.py#L18) always returns top 3. After this baseline, add a cutoff, sweep it on the **21 positives + 5 negatives**, keep callback Hit@3, empty the negatives, re-run journal eval. Do not copy clinical `0.65` blindly — Layer 3 found that cutoff was a no-op on the KB.

## Pipeline trace (where eval sits)

| Layer | What we already measure | This pass |
|-------|-------------------------|-----------|
| **L1 routing** | Path accuracy ([`layer1_eval.py`](../backend/eval/layer1_eval.py#L1)) | Unchanged |
| **L2 corpus** | Partner tests ([`test_corpus_selection.py`](../backend/tests/test_corpus_selection.py#L1)) | Unchanged |
| **L3 retrieval** | Clinical category recall; journal phrase-match + snippet judge | **Hit@k / MRR + empty-when-forced** |
| **L4 generation** | Settings injection tests | **DeepEval on the reply** |
| **Cover sheet** | Handoff docs | **[`eval_summary.md`](../backend/eval/results/eval_summary.md)** |
