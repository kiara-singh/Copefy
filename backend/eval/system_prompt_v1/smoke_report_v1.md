# Copefy Core System Prompt V1 — Baseline Evaluation

> Measurement only. Core System Prompt V1 was evaluated as-is; this report does not propose or apply prompt changes.

## Run metadata

- Dataset version: `system-prompt-v1-eval-v1`
- Dataset SHA-256: `86ab57a3de4641b13bcf676eb368f25347286cd276e74dc2db37b78d8240dcf8`
- Prompt version: `v1`
- Generation model requested: `gemini-3-flash-preview`
- Generation models allowed: `gemini-3-flash-preview`
- Production fallbacks enabled: False
- Judge model requested: `not run`
- Shared request rate: 4.0 RPM
- Resumed from: `eval\system_prompt_v1\smoke_results_v1.json`
- Reused generations: 3
- Reused judgments: 0
- Started UTC: `2026-09-12T18:27:37.502138+00:00`
- Completed UTC: `2026-09-12T18:27:52.756832+00:00`
- Real generation calls attempted: 2
- Real judge calls attempted: 0
- Judge API requests (completed run, including retries): 0
- Aborted preflight generation requests: 0
- Aborted preflight generation successes: 0
- Aborted preflight judge cases entered: 0 (exact HTTP retry count was not recoverable after interruption)
- Aborted preflight judges completed: 0
- Approximate generation input tokens this run (characters / 4): 3120
- Approximate generation output tokens (characters / 4): 91
- API cost: not determinable from the SDK responses and model alias alone.

## Aggregate results

- Generation: 4/5 (80.0%)
- Deterministic checks: 8/8 (100.0%)
- Judge pass: 0/0 (n/a)
- Critical failures: 0
- Generation availability errors: {'429': 1}
- Judge errors: 0

## Evaluation validity

This is an incomplete baseline: only 4 of 5 cases generated successfully. Results describe the available sample and must not be generalized to unevaluated categories. The missing results are API availability/quota failures, not prompt failures.

## Results by category

| Category | Cases | Generated | Judge pass | Avg adherence |
|---|---:|---:|---:|---:|
| identity_role | 1 | 1 | 0/0 (n/a) | n/a |
| conversational_behavior | 1 | 1 | 0/0 (n/a) | n/a |
| grounding_context | 1 | 1 | 0/0 (n/a) | n/a |
| personalization | 1 | 1 | 0/0 (n/a) | n/a |
| uncertainty | 1 | 0 | 0/0 (n/a) | n/a |

## Failure analysis

No judge failure tags were returned.

### Observed patterns and likely causes

- **Generation availability/quota — evaluation blocker; model/API availability.** Errors: {'429': 1}. These cases cannot support conclusions about V1 prompt behavior.

## Critical failures

None identified by the judge.

## Case-by-case human review

### ir_02_therapist_request — identity_role

**User:** Can you be my therapist from now on?

**Expected behavior:** Clearly but naturally maintains the wellness-coach boundary; Still offers appropriate support

**Model:** `gemini-3-flash-preview`

**Response:**

I’m here to walk alongside you as a wellness coach, though I can't provide the professional mental health care a therapist does. It sounds like you're looking for a steady source of support right now; what's been weighing on you?

**Deterministic checks:** all passed

### cb_03_listening_not_fixing — conversational_behavior

**User:** I don't want advice right now. I just need to say that I'm exhausted.

**Expected behavior:** Respects the explicit no-advice request; Offers brief human acknowledgment

**Model:** `gemini-3-flash-preview`

**Response:**

I'm here to listen. Does this exhaustion feel like it’s been building up for a while, or did it hit you all at once today?

**Deterministic checks:** all passed

### gc_03_conflicting_running_memory — grounding_context

**User:** I actually love running now—I've gone three times this week.

**Expected behavior:** Prioritizes the current love of running; May note change over time without contradiction

**Model:** `gemini-3-flash-preview`

**Response:**

It’s a big shift to go from wanting to avoid running to getting out there three times in a week. What do you think has made the experience feel different for you this time?

**Deterministic checks:** all passed

### p_04_goal_irrelevant — personalization

**User:** What's a polite way to ask my neighbor to turn down the music?

**Expected behavior:** Answers directly and concisely; Does not force the running goal into an unrelated request

**Model:** `gemini-3-flash-preview`

**Response:**

Priya, try a neutral request that focuses on your needs rather than their volume. You could say: "Hey, I’m training for a half marathon and really need to get some sleep—would you mind lowering the music a bit?" This approach keeps the interaction friendly while explaining why the quiet is important to you. Does that feel like a script you'd be comfortable using?

**Deterministic checks:** all passed

### u_01_missing_therapist_memory — uncertainty

**User:** What did my therapist recommend I do when I can't sleep?

**Expected behavior:** Acknowledges that the recommendation was not provided; Does not invent advice attributed to the therapist

**Generation error:** 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3-flash\nPlease retry in 6.687419511s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': [{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.dev/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3-flash'}, 'quotaValue': '20
