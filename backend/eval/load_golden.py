"""Load golden eval cases from every case file in eval/golden/."""

from __future__ import annotations

from pathlib import Path

import yaml

GOLDEN_DIR = Path(__file__).parent / "golden"

# templates.yaml holds template groups (a mapping), not cases — generate_golden.py
# expands it into the gen_* half of core.yaml. journal_eval.yaml is Layer 3
# journal-judge queries, not Layer 1 routing cases.
NON_CASE_FILES = {"templates.yaml", "journal_eval.yaml"}


def _load_yaml_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not data:
        return []
    if isinstance(data, list):
        return data
    raise ValueError(f"Expected YAML list in {path}")


def case_files() -> list[Path]:
    return [
        path
        for path in sorted(GOLDEN_DIR.glob("*.yaml"))
        if path.name not in NON_CASE_FILES
    ]


def load_golden_cases() -> list[dict]:
    cases: list[dict] = []
    for path in case_files():
        cases.extend(_load_yaml_list(path))
    return cases


def load_journal_eval_cases() -> list[dict]:
    return _load_yaml_list(GOLDEN_DIR / "journal_eval.yaml")
