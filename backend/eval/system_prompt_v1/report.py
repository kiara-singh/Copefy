"""Aggregate and render System Prompt V1 evaluation results."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload["cases"]
    successful = [case for case in cases if case["generation"]["status"] == "success"]
    judged = [case for case in successful if case.get("judge")]
    deterministic = [check for case in successful for check in case["deterministic_checks"]]
    by_category: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        grouped[case["category"]].append(case)
    for category, items in grouped.items():
        category_success = [item for item in items if item["generation"]["status"] == "success"]
        category_judged = [item for item in category_success if item.get("judge")]
        by_category[category] = {
            "cases": len(items),
            "generation_successes": len(category_success),
            "judge_passes": sum(bool(item["judge"]["pass"]) for item in category_judged),
            "judge_count": len(category_judged),
            "avg_category_adherence": round(
                sum(item["judge"]["category_adherence"] for item in category_judged)
                / len(category_judged),
                3,
            ) if category_judged else None,
        }
    failure_tags = Counter(
        tag for case in judged for tag in case["judge"].get("failure_tags", [])
    )
    critical = [case["id"] for case in judged if case["judge"]["critical_failure"]]
    availability_errors = Counter()
    for case in cases:
        generation = case["generation"]
        if generation["status"] == "success":
            continue
        error = generation.get("error", "")
        code = "429" if "429" in error else "503" if "503" in error else generation.get("error_type", "unknown")
        availability_errors[str(code)] += 1
    deterministic_failures = Counter(
        check["name"] for case in successful for check in case["deterministic_checks"] if not check["passed"]
    )
    return {
        "total_cases": len(cases),
        "generation_successes": len(successful),
        "generation_success_rate": round(len(successful) / len(cases), 4) if cases else 0,
        "deterministic_checks": len(deterministic),
        "deterministic_passes": sum(check["passed"] for check in deterministic),
        "deterministic_pass_rate": round(
            sum(check["passed"] for check in deterministic) / len(deterministic), 4
        ) if deterministic else None,
        "judge_count": len(judged),
        "judge_passes": sum(bool(case["judge"]["pass"]) for case in judged),
        "judge_pass_rate": round(
            sum(bool(case["judge"]["pass"]) for case in judged) / len(judged), 4
        ) if judged else None,
        "critical_failure_count": len(critical),
        "critical_failure_case_ids": critical,
        "failure_patterns": dict(failure_tags.most_common()),
        "deterministic_failure_patterns": dict(deterministic_failures.most_common()),
        "generation_availability_errors": dict(availability_errors.most_common()),
        "judge_error_count": sum(bool(case.get("judge_error")) for case in successful),
        "generation_model_distribution": dict(
            Counter(case["generation"].get("model") for case in successful)
        ),
        "by_category": by_category,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    metadata = payload["metadata"]
    lines = [
        "# Copefy Core System Prompt V1 — Baseline Evaluation",
        "",
        "> Measurement only. Core System Prompt V1 was evaluated as-is; this report does not propose or apply prompt changes.",
        "",
        "## Run metadata",
        "",
        f"- Dataset version: `{metadata['dataset_version']}`",
        f"- Dataset SHA-256: `{metadata['dataset_sha256']}`",
        f"- Prompt version: `{metadata['prompt_version']}`",
        f"- Generation model requested: `{metadata['generation_model']}`",
        f"- Generation models allowed: `{', '.join(metadata['generation_models_allowed'])}`",
        f"- Production fallbacks enabled: {metadata['production_fallbacks_enabled']}",
        f"- Judge model requested: `{metadata.get('judge_model') or 'not run'}`",
        f"- Shared request rate: {metadata.get('requests_per_minute', 'not recorded')} RPM",
        f"- Resumed from: `{metadata.get('resumed_from') or 'fresh run'}`",
        f"- Reused generations: {metadata.get('reused_generation_count', 0)}",
        f"- Reused judgments: {metadata.get('reused_judge_count', 0)}",
        f"- Started UTC: `{metadata['started_at_utc']}`",
        f"- Completed UTC: `{metadata['completed_at_utc']}`",
        f"- Real generation calls attempted: {metadata['generation_calls_attempted']}",
        f"- Real judge calls attempted: {metadata['judge_calls_attempted']}",
        f"- Judge API requests (completed run, including retries): {metadata['judge_api_requests']}",
        f"- Aborted preflight generation requests: {metadata['aborted_preflight_generation_requests']}",
        f"- Aborted preflight generation successes: {metadata['aborted_preflight_generation_successes']}",
        f"- Aborted preflight judge cases entered: {metadata['aborted_preflight_judge_cases']} "
        "(exact HTTP retry count was not recoverable after interruption)",
        f"- Aborted preflight judges completed: {metadata['aborted_preflight_judges_completed']}",
        f"- Approximate generation input tokens this run (characters / 4): "
        f"{metadata.get('estimated_generation_input_tokens_this_run', metadata.get('estimated_generation_input_tokens', 0))}",
        f"- Approximate generation output tokens (characters / 4): {metadata['estimated_generation_output_tokens']}",
        "- API cost: not determinable from the SDK responses and model alias alone.",
        "",
        "## Aggregate results",
        "",
        f"- Generation: {summary['generation_successes']}/{summary['total_cases']} ({_pct(summary['generation_success_rate'])})",
        f"- Deterministic checks: {summary['deterministic_passes']}/{summary['deterministic_checks']} ({_pct(summary['deterministic_pass_rate'])})",
        f"- Judge pass: {summary['judge_passes']}/{summary['judge_count']} ({_pct(summary['judge_pass_rate'])})",
        f"- Critical failures: {summary['critical_failure_count']}",
        f"- Generation availability errors: {summary['generation_availability_errors']}",
        f"- Judge errors: {summary['judge_error_count']}",
        "",
        "## Evaluation validity",
        "",
    ]
    if summary["generation_successes"] < summary["total_cases"]:
        lines.extend([
            f"This is an incomplete baseline: only {summary['generation_successes']} of "
            f"{summary['total_cases']} cases generated successfully. Results describe the available "
            "sample and must not be generalized to unevaluated categories. The missing results are "
            "API availability/quota failures, not prompt failures.",
            "",
        ])
    else:
        lines.extend(["All fixed dataset cases generated successfully.", ""])
    lines.extend([
        "## Results by category",
        "",
        "| Category | Cases | Generated | Judge pass | Avg adherence |",
        "|---|---:|---:|---:|---:|",
    ])
    for category, data in summary["by_category"].items():
        judge_rate = data["judge_passes"] / data["judge_count"] if data["judge_count"] else None
        adherence = data["avg_category_adherence"]
        lines.append(
            f"| {category} | {data['cases']} | {data['generation_successes']} | "
            f"{data['judge_passes']}/{data['judge_count']} ({_pct(judge_rate)}) | "
            f"{'n/a' if adherence is None else f'{adherence:.2f}/5'} |"
        )
    lines.extend(["", "## Failure analysis", ""])
    if summary["failure_patterns"]:
        for tag, count in summary["failure_patterns"].items():
            ids = [
                case["id"] for case in payload["cases"]
                if case.get("judge") and tag in case["judge"].get("failure_tags", [])
            ]
            lines.append(f"- `{tag}` ({count}): {', '.join(ids)}")
    else:
        lines.append("No judge failure tags were returned.")
    lines.extend(["", "### Observed patterns and likely causes", ""])
    failed_checks = [
        (case, check)
        for case in payload["cases"]
        if case["generation"]["status"] == "success"
        for check in case["deterministic_checks"]
        if not check["passed"]
    ]
    no_question_ids = [case["id"] for case, check in failed_checks if check["name"] == "no_question"]
    if no_question_ids:
        lines.append(
            f"- **Excessive questioning — medium/minor; likely model behavior and dynamic style overlay.** "
            f"Cases: {', '.join(no_question_ids)}. Representative response: "
            f"“{next(case['generation']['response'] for case, check in failed_checks if check['name'] == 'no_question')}”"
        )
    bullet_ids = [case["id"] for case, check in failed_checks if check["name"] == "uses_bullets"]
    if bullet_ids:
        lines.append(
            f"- **Structured-format check — minor; evaluation uncertainty.** Cases: {', '.join(bullet_ids)}. "
            "The response may provide the requested count in prose, so the deterministic bullet check "
            "is intentionally reported but should not be treated as a prompt failure without human review."
        )
    quality_ids = [
        case["id"] for case in payload["cases"]
        if case.get("judge") and "conversational_quality" in case["judge"].get("failure_tags", [])
    ]
    if quality_ids:
        example = next(case["generation"]["response"] for case in payload["cases"] if case["id"] == quality_ids[0])
        lines.append(
            f"- **Truncated conversational output — medium; likely model behavior/generation response.** "
            f"Cases: {', '.join(quality_ids)}. Representative response: “{example}”"
        )
    if summary["generation_availability_errors"]:
        lines.append(
            "- **Generation availability/quota — evaluation blocker; model/API availability.** "
            f"Errors: {summary['generation_availability_errors']}. These cases cannot support conclusions "
            "about V1 prompt behavior."
        )
    if summary["judge_error_count"]:
        lines.append(
            f"- **Missing judge scores — evaluation uncertainty; judge model availability.** "
            f"{summary['judge_error_count']} successfully generated responses were not judged."
        )
    lines.extend(["", "## Critical failures", ""])
    if summary["critical_failure_case_ids"]:
        lines.append(", ".join(f"`{case_id}`" for case_id in summary["critical_failure_case_ids"]))
    else:
        lines.append("None identified by the judge.")
    lines.extend(["", "## Case-by-case human review", ""])
    for case in payload["cases"]:
        lines.extend([
            f"### {case['id']} — {case['category']}",
            "",
            f"**User:** {case['user_message']}",
            "",
            "**Expected behavior:** " + "; ".join(case["behavioral_expectations"]),
            "",
        ])
        generation = case["generation"]
        if generation["status"] == "success":
            lines.extend([
                f"**Model:** `{generation['model']}`",
                "",
                "**Response:**",
                "",
                generation["response"],
                "",
            ])
            failed_checks = [check for check in case["deterministic_checks"] if not check["passed"]]
            lines.append(
                "**Deterministic checks:** "
                + ("all passed" if not failed_checks else "; ".join(
                    f"{check['name']}: {check['detail']}" for check in failed_checks
                ))
            )
            lines.append("")
            if case.get("judge"):
                judge = case["judge"]
                severity = "critical" if judge["critical_failure"] else ("medium" if not judge["pass"] else "none")
                lines.extend([
                    f"**Judge:** {'PASS' if judge['pass'] else 'FAIL'}; severity `{severity}`; "
                    f"tags: {', '.join(judge['failure_tags']) or 'none'}",
                    "",
                    f"**Judge rationale:** {judge['rationale']}",
                    "",
                ])
        else:
            lines.extend([f"**Generation error:** {generation['error']}", ""])
    return "\n".join(lines).rstrip() + "\n"
