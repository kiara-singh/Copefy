"""LLM-as-judge for retrieved snippets (not the full companion reply).

Scores 1–5 on useful / on_topic / grounded / non_redundant. Overall is the mean.
The judge never sees the strategy name. Empty retrieves skip the API and score 1.
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

LAYER3_MISS_IDS = frozenset(
    {
        "coping_01",
        "gen_coping_my_mind_won_t_stop_racing_at_night",
        "adhd_procrastination_01",
        "contextual_breakup_01",
        "gen_anxiety_detail_constant_restlessness",
        "gen_ocd_detail_avoiding_certain_numbers_or_words",
        "edge_lang_stmt_question_02",
    }
)

JUDGE_INSTRUCTION = """You score retrieved context for Copefy, a mental health companion.

You see a user message (optional short history) and up to three retrieved snippets.
Score the SNIPPETS only — not a generated reply. Do not guess a strategy name.

Score each dimension from 1 (poor) to 5 (excellent):

- useful: would these snippets help a helper reply to THIS message?
- on_topic: right clinical topic, or the right past personal context for a journal search?
- grounded: snippets actually relate to the message; not a near-miss dump from the wrong bucket
- non_redundant: the snippets add distinct information rather than restating the same idea

If no snippets were retrieved, all scores are 1.
Respond with JSON only.
"""

RATE_LIMIT_RETRIES = 6
RATE_LIMIT_BACKOFF_S = 15
RETRYABLE_CODES = {429, 503}
# Retired / unknown model ids. Skip immediately; do not sleep-retry the same name.
SKIP_MODEL_CODES = {404}

_local = threading.local()


def _clamp(value: Any, default: int = 3) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(1, min(5, number))


@dataclass
class JudgeScore:
    useful: int
    on_topic: int
    grounded: int
    non_redundant: int
    rationale: str = ""
    overall: float = 0.0

    def __post_init__(self) -> None:
        self.useful = _clamp(self.useful)
        self.on_topic = _clamp(self.on_topic)
        self.grounded = _clamp(self.grounded)
        self.non_redundant = _clamp(self.non_redundant)
        self.overall = round(
            (self.useful + self.on_topic + self.grounded + self.non_redundant) / 4.0,
            3,
        )


EMPTY_SCORE = JudgeScore(
    useful=1,
    on_topic=1,
    grounded=1,
    non_redundant=1,
    rationale="no snippets retrieved",
)


@dataclass
class JudgeSummary:
    strategy: str
    cases: int
    empty_retrieves: int
    avg_overall: float
    avg_useful: float
    avg_on_topic: float
    avg_grounded: float
    avg_non_redundant: float
    avg_entry_recall: float | None = None


def parse_judge_payload(payload: dict) -> JudgeScore:
    """Build a JudgeScore from model JSON. Safe for unit tests."""
    return JudgeScore(
        useful=_clamp(payload.get("useful")),
        on_topic=_clamp(payload.get("on_topic")),
        grounded=_clamp(payload.get("grounded")),
        non_redundant=_clamp(payload.get("non_redundant")),
        rationale=str(payload.get("rationale") or "")[:240],
    )


def format_snippets(chunks: list, *, max_chars: int = 500) -> str:
    if not chunks:
        return "(no snippets retrieved)"
    lines: list[str] = []
    for index, chunk in enumerate(chunks[:3], start=1):
        title = getattr(chunk, "title", None) or "untitled"
        category = getattr(chunk, "category", None) or "uncategorized"
        body = (getattr(chunk, "content", "") or "")[:max_chars]
        lines.append(f"[{index}] title={title} category={category}\n{body}")
    return "\n\n".join(lines)


def format_history(history: list[dict[str, str]] | None, *, limit: int = 4) -> str:
    if not history:
        return ""
    recent = history[-limit:]
    lines = [f"{entry.get('role', '?').upper()}: {entry.get('content', '')}" for entry in recent]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


def build_judge_prompt(
    query: str,
    chunks: list,
    *,
    history: list[dict[str, str]] | None = None,
    corpus: str = "clinical",
) -> str:
    if corpus == "clinical":
        corpus_line = "Corpus: clinical knowledge base snippets."
    elif corpus == "both":
        corpus_line = (
            "Corpus: mixed clinical knowledge base snippets and this user's journal entries."
        )
    else:
        corpus_line = "Corpus: this user's past journal entries."
    return (
        f"{corpus_line}\n\n"
        f"{format_history(history)}"
        f"User message: {query}\n\n"
        f"Retrieved snippets:\n{format_snippets(chunks)}"
    )


def _retry_delay_s(exc: Any, attempt: int) -> float:
    fallback = RATE_LIMIT_BACKOFF_S * (attempt + 1)
    details = (getattr(exc, "details", None) or {}).get("error", {}).get("details", [])
    for detail in details:
        raw = detail.get("retryDelay")
        if raw:
            try:
                return max(fallback, float(str(raw).rstrip("s")) + 1)
            except ValueError:
                break
    return fallback


def _client():
    from google import genai

    from config import settings

    api_key = settings.agent_router_api_key or settings.gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the retrieval judge")
    client = getattr(_local, "client", None)
    if client is None:
        client = genai.Client(api_key=api_key)
        _local.client = client
    return client


def _judge_models() -> list[str]:
    from config import settings

    models = [settings.agent_router_model, *settings.agent_router_model_fallbacks_list]
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _call_judge_api(prompt: str) -> JudgeScore:
    from google.genai import types
    from google.genai.errors import APIError

    schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "useful": types.Schema(type=types.Type.INTEGER),
            "on_topic": types.Schema(type=types.Type.INTEGER),
            "grounded": types.Schema(type=types.Type.INTEGER),
            "non_redundant": types.Schema(type=types.Type.INTEGER),
            "rationale": types.Schema(type=types.Type.STRING),
        },
        required=["useful", "on_topic", "grounded", "non_redundant", "rationale"],
    )
    config = types.GenerateContentConfig(
        system_instruction=JUDGE_INSTRUCTION,
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=schema,
        max_output_tokens=256,
    )
    last_error: Exception | None = None
    attempts_per_model = 2
    models = _judge_models()

    for model in models:
        for attempt in range(attempts_per_model):
            try:
                response = _client().models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                raw = ((response.text if response else None) or "").strip()
                if not raw:
                    raise json.JSONDecodeError("empty judge response", "", 0)
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise json.JSONDecodeError("judge JSON was not an object", raw, 0)
                if model != models[0]:
                    print(f"    judge used fallback model {model}")
                return parse_judge_payload(parsed)
            except APIError as exc:
                last_error = exc
                code = getattr(exc, "code", None)
                if code in SKIP_MODEL_CODES:
                    print(f"    judge skip unavailable model {model} ({code})")
                    break
                if code not in RETRYABLE_CODES:
                    raise
                if attempt + 1 < attempts_per_model:
                    delay = _retry_delay_s(exc, attempt)
                    print(
                        f"    judge retry {attempt + 1}/{attempts_per_model} "
                        f"on {model} after {code} (sleep {delay:.0f}s)"
                    )
                    time.sleep(delay)
                    continue
                print(f"    judge fallback after {code} on {model}")
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt + 1 < attempts_per_model:
                    delay = RATE_LIMIT_BACKOFF_S * (attempt + 1)
                    print(
                        f"    judge retry {attempt + 1}/{attempts_per_model} "
                        f"on {model} after invalid JSON (sleep {delay:.0f}s)"
                    )
                    time.sleep(delay)
                    continue
                print(f"    judge fallback after invalid JSON on {model}")

    print("    all judge models failed; using default scores")
    if last_error and not isinstance(last_error, (APIError, json.JSONDecodeError)):
        raise last_error
    return parse_judge_payload({})


def score_retrieval(
    query: str,
    chunks: list,
    *,
    history: list[dict[str, str]] | None = None,
    corpus: str = "clinical",
) -> JudgeScore:
    if not chunks:
        return EMPTY_SCORE
    prompt = build_judge_prompt(query, chunks, history=history, corpus=corpus)
    return _call_judge_api(prompt)


def stratify_sample(
    cases: list[dict],
    n: int,
    *,
    seed: str = "copefy-judge",
    must_include: frozenset[str] = LAYER3_MISS_IDS,
) -> list[dict]:
    """Always keep known Layer 3 misses, then fill by category+type round-robin."""
    if n <= 0 or n >= len(cases):
        return list(cases)

    by_id = {case["id"]: case for case in cases}
    selected: list[dict] = []
    seen: set[str] = set()
    for case_id in must_include:
        case = by_id.get(case_id)
        if case is not None and case_id not in seen:
            selected.append(case)
            seen.add(case_id)

    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for case in cases:
        if case["id"] in seen:
            continue
        cats = case.get("expected_categories") or ["unlabeled"]
        key = (str(cats[0]), str(case.get("type", "unknown")))
        buckets[key].append(case)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    keys = sorted(buckets)
    index = 0
    while len(selected) < n and any(buckets.values()):
        key = keys[index % len(keys)]
        if buckets[key]:
            selected.append(buckets[key].pop())
        index += 1
        if index > n * 20:
            break
    return selected[:n]


def summarize_scores(
    strategy: str,
    scores: list[JudgeScore],
    *,
    empty_retrieves: int = 0,
    entry_recalls: list[float] | None = None,
) -> JudgeSummary:
    if not scores:
        return JudgeSummary(
            strategy=strategy,
            cases=0,
            empty_retrieves=empty_retrieves,
            avg_overall=0.0,
            avg_useful=0.0,
            avg_on_topic=0.0,
            avg_grounded=0.0,
            avg_non_redundant=0.0,
        )
    count = len(scores)
    labeled_recalls = [r for r in (entry_recalls or []) if r == r]
    return JudgeSummary(
        strategy=strategy,
        cases=count,
        empty_retrieves=empty_retrieves,
        avg_overall=sum(s.overall for s in scores) / count,
        avg_useful=sum(s.useful for s in scores) / count,
        avg_on_topic=sum(s.on_topic for s in scores) / count,
        avg_grounded=sum(s.grounded for s in scores) / count,
        avg_non_redundant=sum(s.non_redundant for s in scores) / count,
        avg_entry_recall=(sum(labeled_recalls) / len(labeled_recalls) if labeled_recalls else None),
    )


def pairwise_mmr_vs_baseline(
    scores_by_case: dict[str, dict[str, JudgeScore]],
) -> dict[str, int]:
    """Per-case comparison of overall scores. No extra model call."""
    mmr_wins = 0
    baseline_wins = 0
    ties = 0
    for by_strategy in scores_by_case.values():
        mmr = by_strategy.get("mmr")
        baseline = by_strategy.get("baseline")
        if mmr is None or baseline is None:
            continue
        if mmr.overall > baseline.overall:
            mmr_wins += 1
        elif baseline.overall > mmr.overall:
            baseline_wins += 1
        else:
            ties += 1
    return {
        "mmr_wins": mmr_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "n": mmr_wins + baseline_wins + ties,
    }


def summary_asdict(summary: JudgeSummary) -> dict:
    return asdict(summary)
