# Layer 3 handoff (clinical KB)

Layer 3 is **how** we search the clinical knowledge base after Layer 1 chooses `search_database`. Journal search is Layer 2 and is not in this bake-off.

## Status

**Ship `RAG_STRATEGY=mmr` for clinical KB retrieval.**

| Topic | Current state |
|-------|----------------|
| Strategies | `baseline`, `threshold_0.65`, `mmr`, `wide_then_narrow` |
| Production default | **`mmr`** (locked 2026-08-20) |
| Offline unit tests | 15 passing |
| KB under test | 1,123 `kb_documents` |
| Regression | 273 search cases (271 labeled), 0 empty retrieves |
| Held-out | 831 counseling questions (509 search, 171 labeled), measure only |

## Results

Winner rule: highest labeled category recall on regression, then fewer empties, then latency. Held-out is a sanity check, not a tuning target.

**Regression (271 labeled)**

| Strategy | Category recall | After label fix (rescored) |
|----------|-----------------|----------------------------|
| **mmr** | 0.919 | **0.948** |
| baseline / threshold_0.65 | 0.915 | 0.945 |
| wide_then_narrow | 0.913 | 0.943 |

Relabeled `gen_*` rows whose wording was OCD/ADHD/PTSD but had been tagged `anxiety`. Retrieved chunks were unchanged (daily embed quota blocked a live re-run); recall was recomputed from the saved bake-off. Shared labeled issues dropped from 16 to 7. Remaining misses are real product gaps: racing thoughts at night (no anxiety detect → PTSD), ADHD procrastination → OCD, breakup “checking” → OCD.

**Held-out (171 labeled search rows; HF unique pool is 831, not 1000)**

| Strategy | Category recall |
|----------|-----------------|
| **mmr** | **0.833** |
| baseline / threshold_0.65 | 0.827 |
| wide_then_narrow | 0.825 |

The earlier 80-row held-out had MMR 0.6pp *behind* baseline. That was noise. On 171 labeled rows MMR is 0.6pp *ahead*. Still do not retune against this file. The HuggingFace counseling set only has 831 unique questions after dedupe, and most posts never name ADHD/OCD/anxiety/etc., so Layer 3 labels cap at 171.

**Other findings**

- `threshold_0.65` matched baseline exactly: every kept hit was already above 0.65, so the cutoff did nothing on this corpus.
- No strategy returned zero chunks on labeled cases.
- Shared misses after label cleanup: racing thoughts at night, ADHD procrastination retrieving OCD, and “checking” social media after a breakup. Those need detector/KB work, not a new ranker.

## Commands

```bash
cd backend
python -m pytest tests -q
python -m eval.validate_golden
python -m eval.run_strategy_compare --strategies mmr --limit 5
python -m eval.run_strategy_compare --output eval/results/regression.json --csv eval/results/regression.csv
python -m eval.run_strategy_compare --split heldout --output eval/results/heldout.json
```

## Env

| Variable | Purpose |
|----------|---------|
| `RAG_STRATEGY` | Production strategy. Default **`mmr`**. |
| `GEMINI_API_KEY` | Query embeddings |
| `DATABASE_URL` | Direct Postgres for `match_kb_chunks` |

## Code map

| Area | Path |
|------|------|
| Strategies | `backend/rag/strategies/` |
| Shared pipeline | `backend/rag/strategies/pipeline.py` |
| Scoring | `backend/eval/retrieval_scoring.py` |
| Bake-off | `backend/eval/run_strategy_compare.py` |
| Offline tests | `backend/tests/test_retrieval_subdecisions.py`, `backend/tests/test_retrieval_scoring.py` |
