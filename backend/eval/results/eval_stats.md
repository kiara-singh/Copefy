# Copefy RAG eval — results

Diary `938c6dc2-bab8-44d9-b732-8bbd308fd838` · 112 entries · 30 questions · `journal_mmr`.

### Journal search

| Slice | n | Hit@1 | Hit@3 | MRR | Phrase recall | Snippet judge (1–5) |
|-------|--:|------:|------:|----:|--------------:|--------------------:|
| Memory (callback + paraphrase) | 21 | 76% | 90% | 0.83 | 0.90 | skipped |
| callback | 15 | 73% | 87% | 0.79 | — | — |
| paraphrase | 6 | 83% | 100% | 0.92 | — | — |
| Negatives (empty-when-forced) | 5 | — | — | — | 0/5 empty | — |

Mood traps: 4. Hit@3 misses: Victorian essay, chemistry B+.

Snippet judge skipped (`--skip-judge`). Last documented 4.7/5 on 21.

### DeepEval

26 replies · `gemini-3.5-flash-lite`.

| Metric | Mean | n |
|--------|-----:|--:|
| Faithfulness | 1.00 | 26 / 26 |
| Answer relevancy | 1.00 | 26 / 26 |
| No-diagnosis G-Eval | 0.10 | 26 / 26 |

### Prior layers (copied)

| Layer | Result |
|-------|--------|
| Router in-set | 529 cases, 100% accuracy; crisis and web-trap false positives 0 (rule router). |
| Router held-out | 831 counseling questions, 64.1% accuracy; crisis recall 95.8%. Measure only. |
| Clinical KB in-set | MMR labeled category recall 0.948 (271 labeled); 0 empty retrieves. |
| Clinical KB held-out | MMR labeled category recall 0.833 (171 labeled). Measure only. |
