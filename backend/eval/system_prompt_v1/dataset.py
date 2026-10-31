"""Load and validate the immutable-on-run System Prompt V1 evaluation set."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DATASET_VERSION = "system-prompt-v1-eval-v1"
DEFAULT_DATASET_PATH = Path(__file__).with_name("cases_v1.yaml")
CATEGORIES = (
    "identity_role",
    "conversational_behavior",
    "grounding_context",
    "personalization",
    "uncertainty",
    "clinical_boundaries",
    "generation_safety",
    "critical_guardrails",
)


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    user_message: str
    behavioral_expectations: tuple[str, ...]
    critical_failure_conditions: tuple[str, ...]
    quality_failure_conditions: tuple[str, ...] = ()
    conversation_history: tuple[dict[str, str], ...] = ()
    clinical_context: tuple[str, ...] = ()
    journal_context: tuple[str, ...] = ()
    personalization: dict[str, str] = field(default_factory=dict)
    deterministic_checks: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def dataset_sha256(path: Path = DEFAULT_DATASET_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_tuple(value: Any) -> tuple:
    return tuple(value or ())


def load_cases(path: Path = DEFAULT_DATASET_PATH) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != DATASET_VERSION:
        raise ValueError(f"Expected dataset version {DATASET_VERSION!r} in {path}")
    cases = []
    for item in raw.get("cases") or []:
        cases.append(
            EvalCase(
                id=str(item["id"]),
                category=str(item["category"]),
                user_message=str(item["user_message"]),
                behavioral_expectations=_as_tuple(item.get("behavioral_expectations")),
                critical_failure_conditions=_as_tuple(item.get("critical_failure_conditions")),
                quality_failure_conditions=_as_tuple(item.get("quality_failure_conditions")),
                conversation_history=_as_tuple(item.get("conversation_history")),
                clinical_context=_as_tuple(item.get("clinical_context")),
                journal_context=_as_tuple(item.get("journal_context")),
                personalization=dict(item.get("personalization") or {}),
                deterministic_checks=_as_tuple(item.get("deterministic_checks")),
                tags=_as_tuple(item.get("tags")),
            )
        )
    validate_cases(cases)
    return cases


def validate_cases(cases: list[EvalCase]) -> None:
    errors: list[str] = []
    if not 50 <= len(cases) <= 70:
        errors.append(f"case count must be 50-70, got {len(cases)}")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        errors.append("case ids must be unique")
    counts = {category: 0 for category in CATEGORIES}
    for case in cases:
        if case.category not in counts:
            errors.append(f"{case.id}: unknown category {case.category!r}")
        else:
            counts[case.category] += 1
        if not case.user_message.strip():
            errors.append(f"{case.id}: empty user_message")
        if not case.behavioral_expectations:
            errors.append(f"{case.id}: no behavioral_expectations")
        if not case.critical_failure_conditions and not case.quality_failure_conditions:
            errors.append(f"{case.id}: no failure conditions")
        for turn in case.conversation_history:
            if turn.get("role") not in {"user", "assistant"} or not turn.get("content"):
                errors.append(f"{case.id}: invalid conversation_history turn")
    for category, count in counts.items():
        if count < 5:
            errors.append(f"{category}: expected at least 5 cases, got {count}")
    if errors:
        raise ValueError("Invalid System Prompt V1 evaluation dataset:\n- " + "\n- ".join(errors))
