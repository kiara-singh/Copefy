"""Run the fixed Core System Prompt V1 baseline through production prompt/generation code."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.orchestrator import _build_user_prompt, _generate_reply
from agent.persona import UserPersona, build_system_instruction
from agent.prompts import DEFAULT_SYSTEM_PROMPT_VERSION
from config import settings
from eval.system_prompt_v1.dataset import (
    DATASET_VERSION,
    DEFAULT_DATASET_PATH,
    EvalCase,
    dataset_sha256,
    load_cases,
)
from eval.system_prompt_v1.deterministic import evaluate_deterministic
from eval.system_prompt_v1.judge import score_response
from eval.system_prompt_v1.rate_limit import RequestRateLimiter
from eval.system_prompt_v1.report import render_markdown, summarize
from rag.retrieve import RetrievedChunk

DEFAULT_RESULTS_PATH = Path(__file__).with_name("baseline_results_v1.json")
DEFAULT_REPORT_PATH = Path(__file__).with_name("baseline_report_v1.md")
PROMPT_BUILD_REVISION = "v1-integrated-history-journal-2026-10"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persona(case: EvalCase) -> UserPersona:
    return UserPersona(**case.personalization)


def _chunks(case: EvalCase) -> list[RetrievedChunk]:
    chunks = [
        RetrievedChunk(content=text, source_url=None, title="Evaluation clinical context", category="clinical", similarity=1.0)
        for text in case.clinical_context
    ]
    chunks.extend(
        RetrievedChunk(content=text, source_url=None, title="Evaluation journal context", category="journal", similarity=1.0)
        for text in case.journal_context
    )
    return chunks


def build_generation_inputs(case: EvalCase, *, prompt_version: str) -> tuple[str, str]:
    persona = _persona(case)
    chunks = _chunks(case)
    system_instruction = build_system_instruction(
        persona, version=prompt_version,
        journal_memories=any(chunk.category == "journal" for chunk in chunks),
    )
    prompt, _ = _build_user_prompt(
        case.user_message,
        list(case.conversation_history),
        chunks,
        None,
        persona,
        context_nonce=f"eval_{case.id}",
    )
    return prompt, system_instruction


def _case_payload(case: EvalCase) -> dict:
    return {
        "id": case.id,
        "category": case.category,
        "user_message": case.user_message,
        "conversation_history": list(case.conversation_history),
        "clinical_context": list(case.clinical_context),
        "journal_context": list(case.journal_context),
        "personalization": case.personalization,
        "behavioral_expectations": list(case.behavioral_expectations),
        "critical_failure_conditions": list(case.critical_failure_conditions),
        "quality_failure_conditions": list(case.quality_failure_conditions),
        "tags": list(case.tags),
    }


def _generation_inputs_match(case: EvalCase, record: dict) -> bool:
    """Criteria may change without invalidating an otherwise identical generation."""
    expected = _case_payload(case)
    fields = (
        "id",
        "user_message",
        "conversation_history",
        "clinical_context",
        "journal_context",
        "personalization",
    )
    return all(record.get(field) == expected[field] for field in fields)


def _load_resume_records(
    args: argparse.Namespace,
    *,
    prompt_version: str,
    dataset_digest: str,
) -> tuple[dict[str, dict], dict | None, Path | None]:
    if not args.resume:
        return {}, None, None
    candidates = [args.results.with_suffix(".partial.json"), args.results]
    if args.resume_from is not None:
        candidates.append(args.resume_from)
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        return {}, None, None
    payload = json.loads(source.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    expected = {
        "dataset_version": DATASET_VERSION,
        "prompt_version": prompt_version,
        "prompt_build_revision": PROMPT_BUILD_REVISION,
        "generation_model": args.generation_model,
    }
    mismatches = [
        f"{key}: checkpoint={metadata.get(key)!r}, requested={value!r}"
        for key, value in expected.items()
        if metadata.get(key) != value
    ]
    if mismatches:
        raise ValueError("Cannot resume incompatible evaluation:\n- " + "\n- ".join(mismatches))
    return {record["id"]: record for record in payload.get("cases") or []}, metadata, source


def _is_complete(record: dict, *, skip_judge: bool, reuse_judge: bool = True) -> bool:
    if (record.get("generation") or {}).get("status") != "success":
        return False
    return skip_judge or (reuse_judge and bool(record.get("judge")))


def run(args: argparse.Namespace) -> dict:
    cases = load_cases(args.dataset)
    if args.case_ids:
        cases_by_id = {case.id: case for case in cases}
        unknown = [case_id for case_id in args.case_ids if case_id not in cases_by_id]
        if unknown:
            raise ValueError(f"Unknown case ids: {unknown}")
        if len(args.case_ids) != len(set(args.case_ids)):
            raise ValueError("--case-ids must not contain duplicates")
        cases = [cases_by_id[case_id] for case_id in args.case_ids]
    elif args.limit:
        cases = cases[: args.limit]
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the System Prompt V1 evaluation")
    prompt_version = args.prompt_version
    if prompt_version != DEFAULT_SYSTEM_PROMPT_VERSION:
        raise ValueError("This runner is intentionally restricted to Core System Prompt V1")
    if args.requests_per_minute >= 5:
        raise ValueError("requests_per_minute must remain below the 5 RPM free-tier ceiling")
    if args.allow_production_fallbacks:
        raise ValueError(
            "Rate-safe evaluation requires one model; production fallbacks can issue "
            "multiple ungated requests inside one generation attempt"
        )

    dataset_digest = dataset_sha256(args.dataset)
    existing_by_id, resume_metadata, resume_source = _load_resume_records(
        args,
        prompt_version=prompt_version,
        dataset_digest=dataset_digest,
    )
    criteria_match = bool(
        resume_metadata
        and resume_metadata.get("dataset_sha256") == dataset_digest
        and resume_metadata.get("judge_model") == (None if args.skip_judge else args.judge_model)
    )
    rate_limiter = RequestRateLimiter(args.requests_per_minute)

    # Constrain the existing production fallback path to exactly one requested model.
    original_primary = settings.gemini_chat_model
    original_fallbacks = settings.gemini_chat_model_fallbacks
    settings.gemini_chat_model = args.generation_model
    if not args.allow_production_fallbacks:
        settings.gemini_chat_model_fallbacks = args.generation_model
    allowed_generation_models = [
        settings.gemini_chat_model,
        *settings.gemini_chat_model_fallbacks_list,
    ]
    allowed_generation_models = list(dict.fromkeys(allowed_generation_models))

    started = _utc_now()
    records: list[dict] = []
    working_by_id = dict(existing_by_id)
    generation_calls = 0
    judge_calls = 0
    judge_api_requests = 0
    generation_input_chars = 0
    generation_output_chars = 0
    judge_key = settings.agent_router_api_key or settings.gemini_api_key
    reused_generations = 0
    reused_judges = 0
    stop_reason: str | None = None
    try:
        for index, case in enumerate(cases, start=1):
            existing = existing_by_id.get(case.id)
            if existing and (existing.get("generation") or {}).get("status") == "success":
                if not _generation_inputs_match(case, existing):
                    raise ValueError(
                        f"Cannot reuse {case.id}: message/context/personalization changed"
                    )
                refreshed = _case_payload(case)
                refreshed["generation"] = existing["generation"]
                refreshed["generation_origin"] = existing.get(
                    "generation_origin", "reused_existing_artifact"
                )
                refreshed["deterministic_checks"] = evaluate_deterministic(
                    case, existing["generation"]["response"]
                )
                if not args.skip_judge and criteria_match and existing.get("judge"):
                    refreshed["judge"] = existing["judge"]
                existing = refreshed
                working_by_id[case.id] = refreshed
            if existing and _is_complete(
                existing,
                skip_judge=args.skip_judge,
                reuse_judge=criteria_match,
            ):
                print(f"[{index}/{len(cases)}] {case.id} (reused complete case)", flush=True)
                records.append(existing)
                reused_generations += 1
                reused_judges += int(bool(existing.get("judge")))
                continue
            print(f"[{index}/{len(cases)}] {case.id}", flush=True)
            prompt, system_instruction = build_generation_inputs(case, prompt_version=prompt_version)
            record = existing if existing and (existing.get("generation") or {}).get("status") == "success" else _case_payload(case)
            if (record.get("generation") or {}).get("status") == "success":
                reused_generations += 1
            else:
                generation_input_chars += len(prompt) + len(system_instruction)
                generation_calls += 1
                started_case = time.perf_counter()
                rate_limiter.wait()
                try:
                    response, model = _generate_reply(prompt, system_instruction)
                    generation_output_chars += len(response)
                    record["generation"] = {
                        "status": "success",
                        "model": model,
                        "response": response,
                        "latency_ms": round((time.perf_counter() - started_case) * 1000, 1),
                    }
                    record["generation_origin"] = "new"
                    record["deterministic_checks"] = evaluate_deterministic(case, response)
                except Exception as exc:  # preserve partial evidence and continue the bounded run
                    record["generation"] = {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                        "latency_ms": round((time.perf_counter() - started_case) * 1000, 1),
                    }
                    record["generation_origin"] = "new_attempt_failed"
                    record["deterministic_checks"] = []
            if record["generation"]["status"] == "success" and not args.skip_judge:
                judge_calls += 1
                record.pop("judge_error", None)
                try:
                    record["judge"] = score_response(
                        case,
                        record["generation"]["response"],
                        model=args.judge_model,
                        api_key=judge_key,
                        max_retries=args.judge_retries,
                        rate_limiter=rate_limiter,
                    ).to_dict()
                    judge_api_requests += record["judge"]["api_attempts"]
                except Exception as exc:  # keep the successful generation available for review
                    judge_api_requests += int(getattr(exc, "eval_api_attempts", 1))
                    record["judge_error"] = {
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                    }
            records.append(record)
            working_by_id[case.id] = record
            checkpoint = {
                "metadata": {
                    "dataset_version": DATASET_VERSION,
                    "dataset_sha256": dataset_sha256(args.dataset),
                    "prompt_version": prompt_version,
                    "prompt_build_revision": PROMPT_BUILD_REVISION,
                    "generation_model": args.generation_model,
                    "judge_model": None if args.skip_judge else args.judge_model,
                    "started_at_utc": started,
                    "checkpointed_at_utc": _utc_now(),
                    "requests_per_minute": args.requests_per_minute,
                    "resumed_from": str(resume_source) if resume_source else None,
                },
                # Preserve unvisited records from the resume source as well as
                # newly updated cases, so an interruption never loses successes
                # that appeared later in an earlier run.
                "cases": [
                    working_by_id[item.id]
                    for item in cases
                    if item.id in working_by_id
                ],
            }
            args.results.with_suffix(".partial.json").write_text(
                json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if (
                args.stop_on_quota_error
                and record["generation"]["status"] == "failed"
                and "429" in record["generation"].get("error", "")
            ):
                stop_reason = f"quota error on {case.id}"
                break
            if args.max_new_generations and generation_calls >= args.max_new_generations:
                stop_reason = f"max new generations reached ({args.max_new_generations})"
                break
    finally:
        settings.gemini_chat_model = original_primary
        settings.gemini_chat_model_fallbacks = original_fallbacks

    payload = {
        "metadata": {
            "dataset_version": DATASET_VERSION,
            "dataset_sha256": dataset_sha256(args.dataset),
            "prompt_version": prompt_version,
            "prompt_build_revision": PROMPT_BUILD_REVISION,
            "generation_model": args.generation_model,
            "generation_models_allowed": allowed_generation_models,
            "production_fallbacks_enabled": args.allow_production_fallbacks,
            "judge_model": None if args.skip_judge else args.judge_model,
            "started_at_utc": started,
            "completed_at_utc": _utc_now(),
            "generation_calls_attempted": generation_calls,
            "judge_calls_attempted": judge_calls,
            "judge_api_requests": judge_api_requests,
            "requests_per_minute": args.requests_per_minute,
            "request_interval_seconds": rate_limiter.interval_seconds,
            "resumed_from": str(resume_source) if resume_source else None,
            "resume_metadata": resume_metadata,
            "reused_generation_count": reused_generations,
            "reused_judge_count": reused_judges,
            "selected_case_ids": [case.id for case in cases],
            "stop_reason": stop_reason,
            "aborted_preflight_generation_requests": args.preflight_generation_requests,
            "aborted_preflight_judge_cases": args.preflight_judge_cases,
            "aborted_preflight_generation_successes": args.preflight_generation_successes,
            "aborted_preflight_judges_completed": args.preflight_judges_completed,
            "estimated_generation_input_tokens_this_run": round(generation_input_chars / 4),
            "estimated_generation_output_tokens": round(generation_output_chars / 4),
        },
        "cases": records,
    }
    payload["summary"] = summarize(payload)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    args.report.write_text(render_markdown(payload), encoding="utf-8")
    args.results.with_suffix(".partial.json").unlink(missing_ok=True)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--prompt-version", default="v1", choices=("v1",))
    parser.add_argument("--generation-model", required=True, help="Single Gemini model; fallbacks are disabled")
    parser.add_argument("--judge-model", required=True, help="Gemini model used for blind response judging")
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Smoke-test only; full baseline uses 0")
    parser.add_argument("--case-ids", nargs="*", default=[], help="Run only these exact case ids")
    parser.add_argument(
        "--requests-per-minute",
        type=float,
        default=4.0,
        help="Shared generation+judge request budget; must remain below the 5 RPM free-tier ceiling",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse compatible completed generations/judgments from the partial or final results file",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        default=None,
        help="Optional compatible results artifact to seed generation reuse",
    )
    parser.add_argument(
        "--max-new-generations",
        type=int,
        default=0,
        help="Stop after this many new generation attempts; 0 disables the cap",
    )
    parser.add_argument(
        "--stop-on-quota-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop immediately after the first generation 429",
    )
    parser.add_argument("--judge-retries", type=int, default=1)
    parser.add_argument("--preflight-generation-requests", type=int, default=0)
    parser.add_argument("--preflight-judge-cases", type=int, default=0)
    parser.add_argument("--preflight-generation-successes", type=int, default=0)
    parser.add_argument("--preflight-judges-completed", type=int, default=0)
    parser.add_argument(
        "--allow-production-fallbacks",
        action="store_true",
        help="Use configured production fallbacks when a controlled single model is unavailable",
    )
    return parser.parse_args()


def main() -> None:
    payload = run(parse_args())
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
