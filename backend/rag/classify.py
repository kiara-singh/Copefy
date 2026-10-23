"""Category assignment for discovered / ingested pages."""

from __future__ import annotations

from dataclasses import dataclass

from rag import ANXIETY_SUBTYPES, CATEGORIES, normalize_seed_category
from rag.config_sources import (
    ANXIETY_SUBTYPE_KEYWORDS,
    TOP_LEVEL_KEYWORDS,
)

_URL_WEIGHT = 3.0
_TITLE_WEIGHT = 4.0
_BODY_WEIGHT = 1.0
_MIN_PRIMARY_SCORE = 2.0
_MIN_SECONDARY_SCORE = 2.5
_SEED_BOOST = 5.0


@dataclass(frozen=True)
class Classification:
    primary: str
    categories: tuple[str, ...]
    scores: dict[str, float]
    anxiety_subtype: str | None = None


def _score_text(text: str, keywords: tuple[str, ...]) -> float:
    haystack = text.lower()
    score = 0.0
    for keyword in keywords:
        kw = keyword.lower()
        if kw in haystack:
            score += 1.0 + min(2.0, haystack.count(kw) * 0.25)
    return score


def _score_keywords(
    *,
    url: str,
    title: str,
    body: str,
    keywords: tuple[str, ...],
) -> float:
    score = _score_text(url, keywords) * _URL_WEIGHT
    if title:
        score += _score_text(title, keywords) * _TITLE_WEIGHT
    if body:
        score += _score_text(body[:2000], keywords) * _BODY_WEIGHT
    return score


def _best_anxiety_subtype(
    subtype_scores: dict[str, float],
) -> str | None:
    ranked = sorted(
        ((st, sc) for st, sc in subtype_scores.items() if sc > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    return None if not ranked else ranked[0][0]


def classify_content(
    *,
    url: str,
    title: str = "",
    body: str = "",
    seed_category: str | None = None,
) -> Classification | None:
    """Return primary category, labels, and best-fit anxiety subtype when relevant."""
    seed_cat, seed_subtype = normalize_seed_category(seed_category)

    subtype_scores: dict[str, float] = {
        st: _score_keywords(url=url, title=title, body=body, keywords=ANXIETY_SUBTYPE_KEYWORDS[st])
        for st in ANXIETY_SUBTYPES
    }
    if seed_subtype:
        subtype_scores[seed_subtype] = subtype_scores.get(seed_subtype, 0.0) + _SEED_BOOST

    top_scores: dict[str, float] = {}
    for cat in CATEGORIES:
        if cat == "anxiety":
            top_scores[cat] = max(subtype_scores.values()) if subtype_scores else 0.0
        else:
            top_scores[cat] = _score_keywords(
                url=url,
                title=title,
                body=body,
                keywords=TOP_LEVEL_KEYWORDS[cat],
            )
    if seed_cat:
        top_scores[seed_cat] = top_scores.get(seed_cat, 0.0) + _SEED_BOOST

    ranked = sorted(
        ((cat, sc) for cat, sc in top_scores.items() if sc > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        return None

    primary, primary_score = ranked[0]
    if primary_score < _MIN_PRIMARY_SCORE and not seed_cat:
        return None

    labels: list[str] = [primary]
    for cat, sc in ranked[1:]:
        if len(labels) >= 2:
            break
        if sc < _MIN_SECONDARY_SCORE:
            continue
        if cat in labels:
            continue
        if cat == "anxiety" or primary == "anxiety":
            continue
        if {primary, cat} <= {"depression", "ptsd"}:
            labels.append(cat)

    if seed_cat and seed_cat not in labels:
        labels = [seed_cat] + [c for c in labels if c != seed_cat]
        labels = labels[:2]

    # Subtype is only valid when the stored primary is anxiety. A depression
    # seed on an anxiety-scoring page must not keep an anxiety subtype.
    final_primary = labels[0]
    anxiety_subtype: str | None = None
    if final_primary == "anxiety":
        anxiety_subtype = seed_subtype or _best_anxiety_subtype(subtype_scores) or "gad"

    return Classification(
        primary=final_primary,
        categories=tuple(labels),
        scores={**top_scores, **{f"anxiety:{k}": v for k, v in subtype_scores.items()}},
        anxiety_subtype=anxiety_subtype,
    )


def infer_categories_from_url(url: str, seed_category: str | None = None) -> Classification | None:
    return classify_content(url=url, seed_category=seed_category)
