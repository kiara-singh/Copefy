"""Query-time retrieval and clinical knowledge-base ingestion."""

__all__ = [
    "CATEGORIES",
    "ANXIETY_SUBTYPES",
    "LEGACY_ANXIETY_CATEGORIES",
    "normalize_seed_category",
]

CATEGORIES = (
    "adhd",
    "depression",
    "anxiety",
    "ocd",
    "ptsd",
)

ANXIETY_SUBTYPES = (
    "gad",
    "panic_disorder",
    "phobias",
    "social_anxiety",
)

# Old taxonomy slugs that map into anxiety + anxiety_subtype.
LEGACY_ANXIETY_CATEGORIES = ANXIETY_SUBTYPES


def normalize_seed_category(seed: str | None) -> tuple[str | None, str | None]:
    """Map legacy anxiety subtype seeds to (top-level category, anxiety_subtype)."""
    if not seed:
        return None, None
    if seed in ANXIETY_SUBTYPES:
        return "anxiety", seed
    if seed in CATEGORIES:
        return seed, None
    return None, None
