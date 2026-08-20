"""Expand template groups into the generated half of eval/golden/core.yaml."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

GOLDEN_DIR = Path(__file__).parent / "golden"
TEMPLATES_PATH = GOLDEN_DIR / "templates.yaml"
CORE_PATH = GOLDEN_DIR / "core.yaml"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:40] or "item"


def _labels(group: dict) -> dict:
    """Label fields every generated case carries, in the golden schema order."""
    expected_path = group["expected_path"]
    labels: dict = {
        "type": group["type"],
        "expected_path": expected_path,
    }
    if expected_path == "search_database":
        labels["expected_corpus"] = group.get("expected_corpus", "clinical")
    labels["expected_categories"] = list(group.get("expected_categories", []))
    if group.get("tags"):
        labels["tags"] = list(group["tags"])
    return labels


def _expand_symptom_template(group: dict) -> list[dict]:
    cases: list[dict] = []
    prefix = group["id_prefix"]

    if "topics" in group and "query_template" in group:
        for topic in group["topics"]:
            if isinstance(topic, dict):
                text = str(topic["topic"])
                labels = _labels(group)
                if "expected_categories" in topic:
                    labels["expected_categories"] = list(topic["expected_categories"])
            else:
                text = str(topic)
                labels = _labels(group)
            cases.append(
                {
                    "id": f"{prefix}_{_slug(text)}",
                    "query": group["query_template"].format(topic=text),
                    **labels,
                }
            )
        return cases

    if "pairs" in group and "query_template" in group:
        for idx, pair in enumerate(group["pairs"], start=1):
            format_pair = {
                key: value
                for key, value in pair.items()
                if key != "expected_categories"
            }
            labels = _labels(group)
            if "expected_categories" in pair:
                labels["expected_categories"] = list(pair["expected_categories"])
            query = group["query_template"].format(**format_pair)
            cases.append(
                {
                    "id": f"{prefix}_{idx:02d}",
                    "query": query,
                    **labels,
                }
            )
        return cases

    return cases


def _expand_simple_list(group: dict, key: str = "queries") -> list[dict]:
    cases: list[dict] = []
    prefix = group["id_prefix"]
    for idx, query in enumerate(group[key], start=1):
        cases.append(
            {
                "id": f"{prefix}_{idx:02d}",
                "query": query,
                **_labels(group),
            }
        )
    return cases


def _expand_fragments(group: dict) -> list[dict]:
    cases: list[dict] = []
    prefix = group["id_prefix"]
    history = group.get("history", [])
    for fragment in group["fragments"]:
        case: dict = {
            "id": f"{prefix}_{_slug(fragment)}",
            "query": group["query"].format(fragment=fragment),
            **_labels(group),
        }
        if history:
            case["history"] = history
        cases.append(case)
    return cases


def _expand_multi_turn(groups: list[dict]) -> list[dict]:
    cases: list[dict] = []
    for group in groups:
        prefix = group["id_prefix"]
        histories = group.get("histories", [[]])
        for idx, history in enumerate(histories, start=1):
            case: dict = {
                "id": f"{prefix}_{idx:02d}",
                "query": group["query"],
                **_labels(group),
            }
            if history:
                case["history"] = history
            cases.append(case)
    return cases


def expand_templates(data: dict) -> list[dict]:
    cases: list[dict] = []

    for group in data.get("symptom_sharing", []):
        cases.extend(_expand_symptom_template(group))

    for group in data.get("vague_checkins", []):
        cases.extend(_expand_simple_list(group))

    for group in data.get("venting", []):
        cases.extend(_expand_simple_list(group))

    for group in data.get("coping_requests", []):
        cases.extend(_expand_symptom_template(group))

    for group in data.get("normalization", []):
        cases.extend(_expand_symptom_template(group))

    for group in data.get("chitchat", []):
        cases.extend(_expand_simple_list(group))

    for group in data.get("fragment_followups", []):
        cases.extend(_expand_fragments(group))

    cases.extend(_expand_multi_turn(data.get("multi_turn", [])))
    cases.extend(_expand_multi_turn(data.get("extended_multi_turn", [])))

    for group in data.get("situational_anxiety", []):
        cases.extend(_expand_symptom_template(group))

    for section in (
        "clinical_detail",
        "comorbidity",
        "extended_coping",
        "extended_normalization",
    ):
        for group in data.get(section, []):
            cases.extend(_expand_symptom_template(group))

    return cases


def generate(output_path: Path = CORE_PATH) -> list[dict]:
    """Replace gen_* cases in core.yaml; leave hand-written seed cases intact."""
    templates = yaml.safe_load(TEMPLATES_PATH.read_text(encoding="utf-8")) or {}
    generated = expand_templates(templates)

    seen: set[str] = set()
    unique: list[dict] = []
    for case in generated:
        case_id = case["id"]
        if case_id in seen:
            suffix = 2
            while f"{case_id}_{suffix}" in seen:
                suffix += 1
            case = {**case, "id": f"{case_id}_{suffix}"}
        seen.add(case["id"])
        unique.append(case)

    existing = []
    if output_path.exists():
        existing = yaml.safe_load(output_path.read_text(encoding="utf-8")) or []
    seeds = [case for case in existing if not str(case.get("id", "")).startswith("gen_")]
    merged = [*seeds, *unique]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Everyday Layer 1 coverage: hand seeds + template-generated cases.\n"
        "# Regenerate the gen_* half via: python -m eval.generate_golden\n\n"
    )
    output_path.write_text(
        header + yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate golden test cases from templates")
    parser.add_argument(
        "--output",
        type=Path,
        default=CORE_PATH,
        help="Output YAML path (default: eval/golden/core.yaml)",
    )
    args = parser.parse_args()
    cases = generate(args.output)
    print(f"Wrote {len(cases)} generated cases into {args.output}")


if __name__ == "__main__":
    main()
