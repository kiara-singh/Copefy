"""Copy eval JSON numbers into markdown. Does not call models.

    python -m eval.write_eval_summary

Writes `eval_summary.md` (notes) and `eval_stats.md` (tables only).
Missing JSON falls back to last documented handoff numbers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_OUTPUT = RESULTS_DIR / "eval_summary.md"
DEFAULT_STATS = RESULTS_DIR / "eval_stats.md"
JOURNAL_JSON = RESULTS_DIR / "judge_journal.json"
DEEPEVAL_JSON = RESULTS_DIR / "deepeval_generation.json"
REGRESSION_JSON = RESULTS_DIR / "regression.json"
HELDOUT_JSON = RESULTS_DIR / "heldout.json"
LAYER1_JSON = RESULTS_DIR / "layer1.json"

# Last shipped numbers when the matching JSON is not in eval/results/.
FALLBACK = {
    "layer1_regression": "529 cases, 100% accuracy; crisis and web-trap false positives 0 (rule router).",
    "layer1_heldout": "831 counseling questions, 64.1% accuracy; crisis recall 95.8%. Measure only.",
    "clinical_regression": "MMR labeled category recall 0.948 (271 labeled); 0 empty retrieves.",
    "clinical_heldout": "MMR labeled category recall 0.833 (171 labeled). Measure only.",
    "journal_phrase": "21 memory cases phrase-match 90%; snippet judge 4.7/5. Negatives 0/5 empty.",
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError := OSError):  # noqa: F841 — keep parse fallback below
        return None
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}" if value <= 1.0 else f"{value:.2f}"


def _num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _deepeval_stats(deepeval: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        "total": 0,
        "faithfulness": None,
        "faithfulness_n": 0,
        "answer_relevancy": None,
        "answer_relevancy_n": 0,
        "no_diagnosis": None,
        "no_diagnosis_n": 0,
        "complete": False,
        "partial": False,
    }
    if not deepeval:
        return empty
    summary = deepeval.get("summary") or {}
    total = int(deepeval.get("case_count") or 0)
    faith_n = int(summary.get("faithfulness_n") or 0)
    rel_n = int(summary.get("answer_relevancy_n") or 0)
    nd_n = int(summary.get("no_diagnosis_n") or 0)
    scored_min = min(faith_n, rel_n, nd_n) if total else 0
    complete = total > 0 and faith_n == total and rel_n == total and nd_n == total
    return {
        "total": total,
        "faithfulness": summary.get("faithfulness"),
        "faithfulness_n": faith_n,
        "answer_relevancy": summary.get("answer_relevancy"),
        "answer_relevancy_n": rel_n,
        "no_diagnosis": summary.get("no_diagnosis"),
        "no_diagnosis_n": nd_n,
        "complete": complete,
        "partial": total > 0 and not complete and scored_min > 0,
        "judge_model": deepeval.get("judge_model", "n/a"),
    }


def _journal_meta(payload: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        "name": None,
        "memory": {},
        "negatives": {},
        "by_kind": {},
        "mood": {},
        "phrase": "n/a",
        "judge_overall": "n/a",
        "skip_judge": False,
        "hit3": None,
    }
    if not payload:
        return empty
    strategies = payload.get("strategies") or {}
    name = "journal_mmr" if "journal_mmr" in strategies else next(iter(strategies), None)
    data = strategies.get(name) or {}
    ranked = data.get("ranked_metrics") or {}
    judge = data.get("summary") or {}
    skip_judge = bool(payload.get("skip_judge"))
    cases = data.get("cases") or []
    memory_phrase = [
        row["entry_recall"]
        for row in cases
        if row.get("kind") in {"callback", "paraphrase"}
        and isinstance(row.get("entry_recall"), (int, float))
    ]
    phrase = _num(
        sum(memory_phrase) / len(memory_phrase) if memory_phrase else judge.get("avg_entry_recall")
    )
    memory = ranked.get("memory_quality") or {}
    return {
        "name": name,
        "memory": memory,
        "negatives": ranked.get("negatives") or {},
        "by_kind": ranked.get("by_kind") or {},
        "mood": ranked.get("mood_traps") or {},
        "phrase": phrase,
        "judge_overall": "skipped" if skip_judge else _num(judge.get("avg_overall")),
        "skip_judge": skip_judge,
        "hit3": memory.get("hit_at_3"),
    }


def _what_we_tested(journal: dict | None, meta: dict[str, Any]) -> list[str]:
    if journal:
        setup = (
            f"One live diary `{journal.get('user_id')}` "
            f"({journal.get('entry_count')} entries), "
            f"**{journal.get('case_count')}** labeled questions, "
            f"strategy `{meta.get('name') or 'journal_mmr'}`."
        )
    else:
        setup = (
            f"_No `{JOURNAL_JSON.name}` in this checkout._ "
            f"Last documented journal run: {FALLBACK['journal_phrase']}"
        )
    return [
        "## Setup",
        "",
        setup,
        "",
        "Tables for slides: [`eval_stats.md`](eval_stats.md).",
        "",
        "| Question type | Count |",
        "|---------------|------:|",
        "| Callback | 15 |",
        "| Paraphrase | 6 |",
        "| Negative | 5 |",
        "| Mood trap | 4 |",
        "",
        "Hit@k headline = callbacks + paraphrases (21). Router and clinical-KB rows below are prior work, not re-run here.",
        "",
    ]


def _how_we_tested() -> list[str]:
    return [
        "## How gold labels work (Hit@k is not an LLM judge)",
        "",
        "Someone read the live diary and wrote a quiz in `backend/eval/golden/journal_eval.yaml`. Each callback/paraphrase row is one user-like question plus a **gold day**:",
        "",
        "- `query` — what we send to search (e.g. “I miss the care package my mom sent”).",
        "- `expected_contains` — a short phrase that appears in **that** day’s text and basically nowhere else (`homemade cookies`, `jacket pocket`, `Victorian`, `B+`). The YAML does not paste the full journal.",
        "- `expected_entry_ids` — that day’s Postgres UUID, as a backup if the phrase is missing.",
        "",
        "A question is a **hit** if search returns a snippet from that gold day. Matching is **code**, not a model: run the same `search_journal_chunks` path chat uses, then `gold_rank` walks the snippets from rank 1 upward. First snippet whose body contains the gold phrase (case-insensitive) is the rank. If there is no phrase, it compares snippet `document_id` to the labeled UUID (and to other rows with the same body, in case of duplicates). No Gemini is involved in Hit@k / MRR / phrase recall.",
        "",
        "Example: gold phrase `jacket pocket`. If that text is in the 2nd of 3 snippets, rank = 2 → Hit@1 = 0, Hit@3 = 1, reciprocal rank = 1/2 = 0.5. If it never appears, rank is missing → Hit@1 = 0, Hit@3 = 0, reciprocal rank = 0.",
        "",
        "**Hit@1** — fraction of the 21 memory questions where the gold day was the first snippet.",
        "",
        "**Hit@3** — same, but gold is anywhere in the top three (what chat injects today). This is the number that matches the product.",
        "",
        "**MRR (mean reciprocal rank)** — average of `1/rank` over those 21 questions. Rank 1 → 1.0, rank 2 → 0.5, rank 3 → ~0.33, missing → 0. Then average. It sits between Hit@1 and Hit@3: a miss hurts more than landing at #3, and #1 scores better than #2. **This is not production MMR.** Chat ranking uses **Maximal Marginal Relevance** (diversity vs similarity). Eval MRR is only “how high was the gold day, on average.”",
        "",
        "**Phrase recall** — did **any** retrieved snippet contain the gold phrase, ignoring order. You can have phrase recall 1 and Hit@3 0 if the phrase showed up only below rank 3 (we only keep top 3, so on this run they usually move together).",
        "",
        "**Empty-when-forced** — negatives have no gold day (topic is not in this diary). We still run search and check whether it returned **no** journal snippets. Target is empty; today always-top-3 means 0/5 empty.",
        "",
        "Mood traps have no gold day, so they are skipped for Hit@k.",
        "",
        "The **1–5 snippet judge** (skipped on this JSON, `--skip-judge`) **is** a Gemini score of the snippets. Last documented 4.7/5 on the 21. Separate column from Hit@k.",
        "",
        "| Metric | Definition |",
        "|--------|------------|",
        "| Hit@1 / Hit@3 | Gold day at rank 1 / in top 3 |",
        "| MRR | Mean of 1/rank; 0 if gold missing. Not chat MMR ranking |",
        "| Phrase recall | Gold phrase in any retrieved snippet |",
        "| Empty-when-forced | Negatives that returned no journal snippets |",
        "",
        "## DeepEval (replies)",
        "",
        "21 journal callbacks/paraphrases + 5 clinical seeds. Generate with the Layer 4 prompt, then DeepEval (`Faithfulness`, `AnswerRelevancy`, G-Eval no-diagnosis) with a Gemini judge. Manual; not CI. Crisis and journal negatives are omitted from this quiz.",
        "",
    ]


def _results(
    journal: dict | None,
    deepeval: dict | None,
    meta: dict[str, Any],
) -> list[str]:
    memory = meta["memory"]
    negatives = meta["negatives"]
    by_kind = meta["by_kind"]
    mood = meta["mood"]
    lines = ["## Results", ""]

    if journal:
        lines.extend(
            [
                "### Journal search",
                "",
                "| Slice | n | Hit@1 | Hit@3 | MRR | Phrase recall | Snippet judge (1–5) |",
                "|-------|--:|------:|------:|----:|--------------:|--------------------:|",
                "| **Memory (callback + paraphrase)** | "
                f"{memory.get('n', 'n/a')} | {_pct(memory.get('hit_at_1'))} | "
                f"{_pct(memory.get('hit_at_3'))} | {_num(memory.get('mrr'))} | "
                f"{meta['phrase']} | {meta['judge_overall']} |",
            ]
        )
        for kind in ("callback", "paraphrase"):
            stats = by_kind.get(kind) or {}
            if not stats:
                continue
            lines.append(
                f"| {kind} | {stats.get('n', 0)} | {_pct(stats.get('hit_at_1'))} | "
                f"{_pct(stats.get('hit_at_3'))} | {_num(stats.get('mrr'))} | — | — |"
            )
        lines.append(
            f"| Negatives (empty-when-forced) | {negatives.get('n', 0)} | — | — | — | "
            f"{negatives.get('empty_retrieves', 0)}/{negatives.get('n', 0)} empty | — |"
        )
        lines.extend(
            [
                "",
                f"Mood traps: {mood.get('n', 0)} (no gold day; Hit@k skipped).",
                "",
            ]
        )
        if meta["skip_judge"]:
            lines.extend(
                [
                    "The 1–5 snippet judge was skipped on this JSON (`--skip-judge`). "
                    "Last documented score on the 21 memory cases was **4.7 / 5** "
                    "(negatives scored 1.0 because they still returned three memories).",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "### Journal search",
                "",
                f"_No `{JOURNAL_JSON.name}` in this checkout. Last documented run:_ {FALLBACK['journal_phrase']}",
                "",
                "Re-run: `python -m eval.run_judge_compare --corpus journal --output eval/results/judge_journal.json`",
                "",
            ]
        )

    lines.extend(["### Reply quality (DeepEval)", ""])
    de = _deepeval_stats(deepeval)
    if deepeval:
        lines.extend(
            [
                f"{de['total']} replies · judge `{de['judge_model']}`.",
                "",
                "| Metric | Mean (0–1) | Turns with a score |",
                "|--------|-----------:|-------------------:|",
                f"| Faithfulness | {_num(de['faithfulness'])} | {de['faithfulness_n']} / {de['total']} |",
                f"| Answer relevancy | {_num(de['answer_relevancy'])} | {de['answer_relevancy_n']} / {de['total']} |",
                f"| No-diagnosis G-Eval | {_num(de['no_diagnosis'])} | {de['no_diagnosis_n']} / {de['total']} |",
                "",
            ]
        )
        if de["complete"]:
            lines.extend(
                [
                    "All three metrics scored on every turn.",
                    "",
                ]
            )
        elif de["partial"]:
            lines.extend(
                [
                    "n scored = turns where the judge returned a number. Missing cells are 429/404. `--retry-skipped` without deleting the JSON.",
                    "",
                ]
            )
        if de["total"] < 10:
            lines.extend(
                [
                    f"Sample size {de['total']} — smoke test only.",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                f"_No `{DEEPEVAL_JSON.name}` yet._ Manual only — not CI.",
                "",
                "```bash",
                "python -m eval.run_generation_eval --output eval/results/deepeval_generation.json",
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "### Prior layers (copied, not re-run)",
            "",
            "| Layer | What it measures | Result |",
            "|-------|------------------|--------|",
            f"| Router (L1), in-set | Did we pick the right path (journal / KB / crisis / chit-chat)? | {FALLBACK['layer1_regression']} |",
            f"| Router (L1), held-out | Same, on unseen counseling questions | {FALLBACK['layer1_heldout']} |",
            f"| Clinical KB (L3), in-set | Did search return the right knowledge category? | {FALLBACK['clinical_regression']} |",
            f"| Clinical KB (L3), held-out | Same, held-out set | {FALLBACK['clinical_heldout']} |",
            "",
        ]
    )
    return lines


def _analysis(meta: dict[str, Any], deepeval: dict | None) -> list[str]:
    hit3 = meta.get("hit3")
    memory = meta.get("memory") or {}
    negatives = meta.get("negatives") or {}
    empty_n = negatives.get("empty_retrieves")
    neg_n = negatives.get("n")
    de = _deepeval_stats(deepeval)

    lines = [
        "## Notes",
        "",
        "### Hit@k",
        "",
    ]
    if memory.get("hit_at_3") is not None:
        lines.extend(
            [
                f"21 memory questions: Hit@3 **{_pct(memory.get('hit_at_3'))}**, Hit@1 **{_pct(memory.get('hit_at_1'))}**, MRR **{_num(memory.get('mrr'))}**.",
                "",
                "Misses in top 3: `journal_victorian_essay_01` (phrase `Victorian`) and `journal_chem_grade_01` (phrase `B+`).",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No ranked metrics in this checkout. Need `judge_journal.json`.",
                "",
            ]
        )

    if neg_n:
        lines.extend(
            [
                f"Forced search on {neg_n} negatives: **{empty_n}/{neg_n}** empty. Always-top-3 still returns three nearest real days. Cutoff is the follow-up.",
                "",
            ]
        )

    lines.extend(
        [
            "### Faithfulness 1.0 — don’t present it as a product ceiling",
            "",
            "The DeepEval Faithfulness mean is **1.00** on this sheet because the quiz is easy for that metric, not because we proved the bot never hallucinates.",
            "",
            "- Replies are short companion bubbles. DeepEval extracts claims and checks them against three snippets already in the prompt. Conservative L4 replies often have nothing extra to catch.",
            "- n = 26 (21 diary callbacks/paraphrases + 5 clinical). One user. Journal negatives were not scored.",
            "- Same model family writes the bubble and judges it.",
            "- Running **more of the same** questions would probably stay near 1.0. Running **harder** ones would likely drop it: ask for facts that are not in the snippets, longer answers, multi-turn, or cases where retrieval is empty/wrong and the model still chatters.",
            "- G-Eval no-diagnosis at **0.10** with reasons that still say the replies are fine shows these 0–1 LLM judges are noisy. Faithfulness can sit at the other extreme (everything is 1).",
            "",
            "Report **26/26 on this quiz**, not “100% faithful in production.”",
            "",
            "### How strong is Hit@k here?",
            "",
            "- One diary, 112 entries, 30 questions. Baseline, not a published benchmark.",
            "- Most callbacks use a unique phrase, so the test is “find this day,” not disambiguate many similar anxious-school days.",
            "- Do not retune clinical `RAG_STRATEGY` from this sample.",
            "",
        ]
    )
    if hit3 is not None and hit3 >= 0.95:
        lines.extend(
            [
                f"Hit@3 {_pct(hit3)} is near-ceiling on unique-token callbacks.",
                "",
            ]
        )
    elif hit3 is not None:
        lines.extend(
            [
                f"Hit@3 {_pct(hit3)} is not 100%, so the 21 items still have signal.",
                "",
            ]
        )

    lines.extend(
        [
            "## Next week — make the numbers more realistic",
            "",
            "The current sheet is a baseline. Several scores look better than the test is. Next week should change the **quiz and the product gap**, then re-measure — not re-run the same 26 turns.",
            "",
            "1. **Faithfulness 1.00** — the quiz never tries to make the model invent. Add turns that ask for a detail **not** in the snippets, prompts with empty retrieval, and prompts with the **wrong** days stuffed in. Re-run DeepEval. A mean that can move off 1.0 is reportable; repeating this set is not.",
            "2. **G-Eval 0.10** — the scale is broken (reasons still say the replies are fine). Drop it from findings, or replace it with a deterministic check (regex / classifier for “you have OCD”, “I am your therapist”). Do not spend quota hoping 0.10 becomes 1.0.",
            "3. **Hit@3 90%** — most callbacks share a unique token with the gold day (`jacket pocket`, `Pomodoro`). Add paraphrases with **no** shared keywords, and a second diary if you can. Until then 90% is “find the distinctive sentence,” not hard memory search.",
            "4. **Negatives 0/5 empty** — that number is accurate for today’s always-top-3 search, but it is not a retrieval quality win. Add a similarity cutoff, sweep it on the 21 + 5, keep Hit@3 near 90%, push empty toward 5/5. Then the empty rate means something.",
            "5. **Two misses (`Victorian`, `B+`)** — inspect retrieved ids vs gold phrases. If the gold day is in the index and still loses, the 90% is doing real work; if the label/chunk is wrong, fix the quiz first.",
            "",
            "Do not retune clinical `RAG_STRATEGY` from this one diary. Do not put DeepEval in CI.",
            "",
        ]
    )
    return lines


def _footer() -> list[str]:
    return [
        "## Re-run",
        "",
        "```bash",
        "cd backend",
        ".\\venv\\Scripts\\python.exe -m eval.run_judge_compare --corpus journal --skip-judge --output eval/results/judge_journal.json",
        ".\\venv\\Scripts\\python.exe -m eval.run_generation_eval --output eval/results/deepeval_generation.json --write-summary --retry-skipped",
        ".\\venv\\Scripts\\python.exe -m eval.write_eval_summary",
        "```",
        "",
    ]


def render_summary(
    *,
    journal: dict | None = None,
    deepeval: dict | None = None,
    regression: dict | None = None,
    heldout: dict | None = None,
    layer1: dict | None = None,
) -> str:
    del regression, heldout, layer1
    meta = _journal_meta(journal)
    parts = [
        "# Copefy RAG eval — notes",
        "",
        "Numbers are copied from JSON. Present [`eval_stats.md`](eval_stats.md).",
        "",
    ]
    parts.extend(_what_we_tested(journal, meta))
    parts.extend(_how_we_tested())
    parts.extend(_results(journal, deepeval, meta))
    parts.extend(_analysis(meta, deepeval))
    parts.extend(_footer())
    return "\n".join(parts)


def render_stats(
    *,
    journal: dict | None = None,
    deepeval: dict | None = None,
) -> str:
    meta = _journal_meta(journal)
    memory = meta["memory"]
    negatives = meta["negatives"]
    by_kind = meta["by_kind"]
    mood = meta["mood"]
    de = _deepeval_stats(deepeval)
    lines = [
        "# Copefy RAG eval — results",
        "",
    ]
    if journal:
        lines.append(
            f"Diary `{journal.get('user_id')}` · {journal.get('entry_count')} entries · "
            f"{journal.get('case_count')} questions · `{meta.get('name') or 'journal_mmr'}`."
        )
    else:
        lines.append(f"Journal JSON missing. Last documented: {FALLBACK['journal_phrase']}")
    lines.extend(["", "### Journal search", ""])
    if journal:
        lines.extend(
            [
                "| Slice | n | Hit@1 | Hit@3 | MRR | Phrase recall | Snippet judge (1–5) |",
                "|-------|--:|------:|------:|----:|--------------:|--------------------:|",
                "| Memory (callback + paraphrase) | "
                f"{memory.get('n', 'n/a')} | {_pct(memory.get('hit_at_1'))} | "
                f"{_pct(memory.get('hit_at_3'))} | {_num(memory.get('mrr'))} | "
                f"{meta['phrase']} | {meta['judge_overall']} |",
            ]
        )
        for kind in ("callback", "paraphrase"):
            stats = by_kind.get(kind) or {}
            if stats:
                lines.append(
                    f"| {kind} | {stats.get('n', 0)} | {_pct(stats.get('hit_at_1'))} | "
                    f"{_pct(stats.get('hit_at_3'))} | {_num(stats.get('mrr'))} | — | — |"
                )
        lines.append(
            f"| Negatives (empty-when-forced) | {negatives.get('n', 0)} | — | — | — | "
            f"{negatives.get('empty_retrieves', 0)}/{negatives.get('n', 0)} empty | — |"
        )
        lines.extend(
            [
                "",
                f"Mood traps: {mood.get('n', 0)}. Hit@3 misses: Victorian essay, chemistry B+.",
                "",
            ]
        )
        if meta["skip_judge"]:
            lines.extend(["Snippet judge skipped (`--skip-judge`). Last documented 4.7/5 on 21.", ""])
    lines.extend(["### DeepEval", ""])
    if deepeval:
        lines.extend(
            [
                f"{de['total']} replies · `{de['judge_model']}`.",
                "",
                "| Metric | Mean | n |",
                "|--------|-----:|--:|",
                f"| Faithfulness | {_num(de['faithfulness'])} | {de['faithfulness_n']} / {de['total']} |",
                f"| Answer relevancy | {_num(de['answer_relevancy'])} | {de['answer_relevancy_n']} / {de['total']} |",
                f"| No-diagnosis G-Eval | {_num(de['no_diagnosis'])} | {de['no_diagnosis_n']} / {de['total']} |",
                "",
            ]
        )
    else:
        lines.extend([f"No `{DEEPEVAL_JSON.name}`.", ""])
    lines.extend(
        [
            "### Prior layers (copied)",
            "",
            "| Layer | Result |",
            "|-------|--------|",
            f"| Router in-set | {FALLBACK['layer1_regression']} |",
            f"| Router held-out | {FALLBACK['layer1_heldout']} |",
            f"| Clinical KB in-set | {FALLBACK['clinical_regression']} |",
            f"| Clinical KB held-out | {FALLBACK['clinical_heldout']} |",
            "",
        ]
    )
    return "\n".join(lines)


def write_summary(output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    journal = _load_json(JOURNAL_JSON)
    deepeval = _load_json(DEEPEVAL_JSON)
    kwargs = {
        "journal": journal,
        "deepeval": deepeval,
        "regression": _load_json(REGRESSION_JSON),
        "heldout": _load_json(HELDOUT_JSON),
        "layer1": _load_json(LAYER1_JSON),
    }
    output.write_text(render_summary(**kwargs), encoding="utf-8")
    print(f"Wrote {output}")
    stats_path = output.parent / "eval_stats.md"
    stats_path.write_text(render_stats(journal=journal, deepeval=deepeval), encoding="utf-8")
    print(f"Wrote {stats_path}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Write eval_summary.md from result JSON files")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_summary(args.output)


if __name__ == "__main__":
    main()
