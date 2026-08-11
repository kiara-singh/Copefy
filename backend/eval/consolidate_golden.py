"""One-shot merge of fragmented golden YAMLs into core/safety/tools/edges.

Run from backend/: python -m eval.consolidate_golden
Deletes the old fragment files after a successful write.
"""

from __future__ import annotations

from pathlib import Path

import yaml

GOLDEN = Path(__file__).resolve().parent / "golden"


def _load(name: str) -> list[dict]:
    path = GOLDEN / name
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{name} must be a YAML list")
    return data


def _dump(name: str, cases: list[dict], header: str) -> None:
    body = yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=100)
    (GOLDEN / name).write_text(header + "\n" + body, encoding="utf-8")
    print(f"  wrote {name}: {len(cases)} cases")


def _has_tag(case: dict, tag: str) -> bool:
    return tag in (case.get("tags") or [])


def main() -> None:
    seeds = _load("seeds.yaml")
    generated = _load("generated.yaml")
    crisis = _load("crisis.yaml")
    tools = _load("tools.yaml")
    web_traps = _load("web_traps.yaml")
    traps = _load("traps.yaml")
    edge_crisis = _load("edge_crisis.yaml")
    edge_clinical = _load("edge_clinical.yaml")
    edge_language = _load("edge_language.yaml")
    edge_tools = _load("edge_tools.yaml")
    edge_boundaries = _load("edge_boundaries.yaml")

    # --- core: everyday coverage ---
    core = [*seeds, *generated]

    # --- safety: crisis positives + crisis/web traps ---
    safety: list[dict] = []
    safety.extend(crisis)
    for case in edge_crisis:
        safety.append(case)
    for case in traps:
        if _has_tag(case, "crisis_trap") or _has_tag(case, "web_trap"):
            safety.append(case)
        # tool traps go to tools.yaml
    safety.extend(web_traps)

    # Deduplicate by id (edge_crisis may overlap naming with traps — keep first)
    seen: set[str] = set()
    safety_dedup: list[dict] = []
    for case in safety:
        cid = case["id"]
        if cid in seen:
            continue
        seen.add(cid)
        safety_dedup.append(case)
    safety = safety_dedup

    # --- tools: positives + tool traps + edge tool cases ---
    tools_out: list[dict] = []
    tools_out.extend(tools)
    tools_out.extend(edge_tools)
    for case in traps:
        if _has_tag(case, "tool_trap"):
            tools_out.append(case)

    seen_tools: set[str] = set()
    tools_dedup: list[dict] = []
    for case in tools_out:
        cid = case["id"]
        if cid in seen_tools:
            continue
        seen_tools.add(cid)
        tools_dedup.append(case)
    tools_out = tools_dedup

    # --- edges: hard phrasing (clinical / language / boundaries) ---
    # Skip cases already claimed by safety (crisis_trap rows live in edge_language too)
    safety_ids = {c["id"] for c in safety}
    tools_ids = {c["id"] for c in tools_out}
    edges: list[dict] = []
    for case in [*edge_clinical, *edge_language, *edge_boundaries]:
        if case["id"] in safety_ids or case["id"] in tools_ids:
            continue
        # crisis_trap in edge_language already in safety via edge_crisis/traps —
        # if only in edge_language, it should be in safety
        if _has_tag(case, "crisis_trap") or _has_tag(case, "web_trap"):
            if case["id"] not in safety_ids:
                safety.append(case)
                safety_ids.add(case["id"])
            continue
        edges.append(case)

    print("Consolidating golden suite...")
    _dump(
        "core.yaml",
        core,
        "# Everyday Layer 1 coverage: hand seeds + template-generated cases.\n"
        "# Regenerate the gen_* half via: python -m eval.generate_golden\n",
    )
    _dump(
        "safety.yaml",
        safety,
        "# Crisis positives and negative traps (crisis_trap, web_trap).\n"
        "# Safety gates in layer1_eval read these tags.\n",
    )
    _dump(
        "tools.yaml",
        tools_out,
        "# Web / structured / document positives and tool_trap negatives.\n",
    )
    _dump(
        "edges.yaml",
        edges,
        "# Hard phrasing: behavioral symptoms, typos/slang, multi-turn boundaries.\n",
    )

    obsolete = [
        "seeds.yaml",
        "generated.yaml",
        "crisis.yaml",
        "web_traps.yaml",
        "traps.yaml",
        "edge_crisis.yaml",
        "edge_clinical.yaml",
        "edge_language.yaml",
        "edge_tools.yaml",
        "edge_boundaries.yaml",
        # old tools.yaml already overwritten
    ]
    # Note: tools.yaml was overwritten in place with the merged content.
    for name in obsolete:
        if name == "tools.yaml":
            continue
        path = GOLDEN / name
        if path.exists():
            path.unlink()
            print(f"  deleted {name}")

    print("Done.")


if __name__ == "__main__":
    main()
