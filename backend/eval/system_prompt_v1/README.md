# Core System Prompt V1 evaluation

This directory contains the fixed `system-prompt-v1-eval-v1` baseline dataset and
its evaluation harness. It measures Core System Prompt V1 as-is; it does not tune
or modify the prompt.

The runner reuses production `build_system_instruction()`, `_build_user_prompt()`,
and `_generate_reply()`. Supplied clinical and journal contexts are represented as
`RetrievedChunk` values so production context labeling is preserved without
running retrieval or changing a database.

Run the complete fixed dataset from `backend/` with one explicit model:

```powershell
.\venv\Scripts\python.exe -m eval.system_prompt_v1.run `
  --generation-model gemini-3-flash-preview `
  --judge-model gemini-3-flash-preview `
  --requests-per-minute 4
```

The default shared limit is 4 RPM: generation, judge, and judge retry requests all
pass through the same 15-second gate. Production fallbacks are rejected because
they can make multiple calls inside one generation attempt and bypass that gate.

Resume is enabled by default. The runner prefers a compatible `.partial.json`
checkpoint, then the final results file. It reuses successful generations and
completed judgments, retries only missing judgments, and regenerates only failed
cases. Use `--no-resume` only when intentionally starting a fresh run. `--limit`
is for smoke testing and must not be used for the complete baseline.

Artifacts:

- `cases_v1.yaml`: frozen 64-case dataset (eight cases per responsibility)
- `baseline_results_v1.json`: machine-readable generations, checks, judge scores,
  errors, metadata, and aggregates
- `baseline_report_v1.md`: readable results and actual responses for human review

The checked-in working-tree artifacts currently describe an incomplete run because
Gemini quota/availability stopped generation after ten successful cases. Do not
interpret unevaluated categories as passes or failures.

These September artifacts predate the October integration of exchange-based
history and dated journal-memory instructions. Their responses remain historical
evidence; the runner rejects checkpoints from that older prompt-build revision.
Use fresh output paths for a new integrated baseline. Compatible checkpoints
within the new revision still resume normally.
