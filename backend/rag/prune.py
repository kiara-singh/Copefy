"""Trim active KB documents with label-balanced caps and anxiety subtype balance.

Deletes cascade to kb_chunks and kb_document_categories (ON DELETE CASCADE).

Usage (from backend/, venv active):

    python -m rag.prune --status
    python -m rag.prune --dry-run --max-active-docs 3000 --balance-by labels
    python -m rag.prune --confirm --max-active-docs 3000 --balance-by labels
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from config import settings
from rag import ANXIETY_SUBTYPES, CATEGORIES
from rag.store import KnowledgeStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("rag.prune")

# Optional: never drop docs in these anxiety subtypes. Empty = balance all subtypes.
PROTECTED_ANXIETY_SUBTYPES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ActiveDoc:
    id: UUID
    primary: str
    labels: frozenset[str]
    anxiety_subtype: str | None
    sort_index: int


@dataclass(frozen=True)
class CategoryPlan:
    category: str
    current: int
    keep: int
    delete: int


@dataclass(frozen=True)
class SubtypePlan:
    subtype: str
    current: int
    keep: int
    delete: int


@dataclass(frozen=True)
class PrunePlan:
    max_active_docs: int
    current_active: int
    keep_total: int
    delete_total: int
    per_category: tuple[CategoryPlan, ...]
    per_anxiety_subtype: tuple[SubtypePlan, ...]
    keep_ids: tuple[UUID, ...]
    balance_by: str


def _distribute(total: int, buckets: int) -> list[int]:
    if buckets <= 0:
        return []
    base = total // buckets
    extra = total % buckets
    return [base + (1 if i < extra else 0) for i in range(buckets)]


def _label_plan(current: dict[str, int], kept: dict[str, int]) -> tuple[CategoryPlan, ...]:
    plans: list[CategoryPlan] = []
    for cat in CATEGORIES:
        cur = current.get(cat, 0)
        keep = kept.get(cat, 0)
        plans.append(CategoryPlan(category=cat, current=cur, keep=keep, delete=cur - keep))
    return tuple(plans)


def _subtype_plan(current: dict[str, int], kept: dict[str, int]) -> tuple[SubtypePlan, ...]:
    plans: list[SubtypePlan] = []
    for st in ANXIETY_SUBTYPES:
        cur = current.get(st, 0)
        keep = kept.get(st, 0)
        plans.append(SubtypePlan(subtype=st, current=cur, keep=keep, delete=cur - keep))
    return tuple(plans)


async def _fetch_active_docs(store: KnowledgeStore) -> list[ActiveDoc]:
    rows = await store.pool.fetch(
        """
        SELECT
            d.id,
            d.category,
            d.anxiety_subtype,
            COALESCE(
                array_agg(DISTINCT dc.category) FILTER (WHERE dc.category IS NOT NULL),
                ARRAY[d.category]
            ) AS labels
        FROM kb_documents d
        LEFT JOIN kb_document_categories dc ON dc.document_id = d.id
        WHERE d.status = 'active'
        GROUP BY d.id, d.category, d.anxiety_subtype, d.created_at, d.crawled_at
        ORDER BY d.created_at DESC NULLS LAST, d.crawled_at DESC
        """
    )
    docs: list[ActiveDoc] = []
    for index, row in enumerate(rows):
        labels = frozenset(str(c) for c in (row["labels"] or [row["category"]]))
        subtype = row["anxiety_subtype"]
        docs.append(
            ActiveDoc(
                id=row["id"],
                primary=str(row["category"]),
                labels=labels,
                anxiety_subtype=str(subtype) if subtype else None,
                sort_index=index,
            )
        )
    return docs


def _count_labels(docs: list[ActiveDoc]) -> dict[str, int]:
    counts = Counter()
    for doc in docs:
        for label in doc.labels:
            counts[label] += 1
    return {cat: counts.get(cat, 0) for cat in CATEGORIES}


def _count_subtypes(docs: list[ActiveDoc]) -> dict[str, int]:
    counts = Counter()
    for doc in docs:
        if doc.anxiety_subtype:
            counts[doc.anxiety_subtype] += 1
    return {st: counts.get(st, 0) for st in ANXIETY_SUBTYPES}


def _add_doc_to_keep(
    doc: ActiveDoc,
    *,
    kept: set[UUID],
    label_counts: Counter[str],
    subtype_counts: Counter[str],
) -> None:
    kept.add(doc.id)
    for label in doc.labels:
        label_counts[label] += 1
    if doc.anxiety_subtype:
        subtype_counts[doc.anxiety_subtype] += 1


def _pick_subtype_for_anxiety(
    subtype_deficits: dict[str, int],
    subtype_counts: Counter[str],
) -> str | None:
    """Pick the subtype furthest below target; break ties by lowest current count."""
    positive = {st: d for st, d in subtype_deficits.items() if d > 0}
    if not positive:
        return None
    max_deficit = max(positive.values())
    tied = [st for st, d in positive.items() if d == max_deficit]
    return min(tied, key=lambda st: (subtype_counts[st], st))


def _anxiety_subtype_candidates(candidates: list[ActiveDoc], subtype: str) -> list[ActiveDoc]:
    """Subtype balance only applies to anxiety-primary docs with a subtype."""
    return [
        d
        for d in candidates
        if d.primary == "anxiety" and d.anxiety_subtype == subtype
    ]


def build_label_balanced_plan(
    docs: list[ActiveDoc],
    *,
    max_active_docs: int,
) -> PrunePlan:
    current_active = len(docs)
    if current_active <= max_active_docs:
        keep_ids = tuple(d.id for d in docs)
        return PrunePlan(
            max_active_docs=max_active_docs,
            current_active=current_active,
            keep_total=len(keep_ids),
            delete_total=0,
            per_category=_label_plan(_count_labels(docs), _count_labels(docs)),
            per_anxiety_subtype=_subtype_plan(_count_subtypes(docs), _count_subtypes(docs)),
            keep_ids=keep_ids,
            balance_by="labels",
        )

    label_targets = dict(zip(CATEGORIES, _distribute(max_active_docs, len(CATEGORIES)), strict=True))
    anxiety_target = label_targets["anxiety"]
    subtype_targets = dict(
        zip(ANXIETY_SUBTYPES, _distribute(anxiety_target, len(ANXIETY_SUBTYPES)), strict=True)
    )

    kept: set[UUID] = set()
    label_counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    exhausted: set[str] = set()
    subtype_exhausted: set[str] = set()

    protected = [d for d in docs if d.anxiety_subtype in PROTECTED_ANXIETY_SUBTYPES]
    if protected:
        logger.info(
            "Pre-keeping %s doc(s) in protected anxiety subtypes: %s",
            len(protected),
            sorted(PROTECTED_ANXIETY_SUBTYPES),
        )
        for doc in protected:
            if doc.id not in kept:
                _add_doc_to_keep(doc, kept=kept, label_counts=label_counts, subtype_counts=subtype_counts)
        for st in PROTECTED_ANXIETY_SUBTYPES:
            subtype_exhausted.add(st)

    def pick_doc(pool: list[ActiveDoc]) -> ActiveDoc | None:
        for doc in pool:
            if doc.id not in kept:
                return doc
        return None

    while len(kept) < max_active_docs:
        deficits = {
            cat: label_targets[cat] - label_counts[cat]
            for cat in CATEGORIES
            if cat not in exhausted
        }
        if not deficits:
            break
        cat = max(deficits, key=deficits.get)
        if deficits[cat] <= 0:
            exhausted.add(cat)
            continue

        candidates = [
            d for d in docs if d.id not in kept and cat in d.labels
        ]
        if not candidates:
            exhausted.add(cat)
            continue

        chosen: ActiveDoc | None = None
        if cat == "anxiety":
            subtype_deficits = {
                st: subtype_targets[st] - subtype_counts[st]
                for st in ANXIETY_SUBTYPES
                if st not in subtype_exhausted
            }
            target_st = _pick_subtype_for_anxiety(subtype_deficits, subtype_counts)
            if target_st:
                pool = _anxiety_subtype_candidates(candidates, target_st)
                chosen = pick_doc(pool)
                if chosen is None:
                    pool = [d for d in candidates if d.primary == "anxiety" and d.anxiety_subtype]
                    chosen = pick_doc(pool)
            else:
                chosen = pick_doc([d for d in candidates if d.primary == "anxiety"])
        else:
            chosen = pick_doc(candidates)

        if chosen is None:
            exhausted.add(cat)
            continue

        _add_doc_to_keep(chosen, kept=kept, label_counts=label_counts, subtype_counts=subtype_counts)

    if len(kept) < max_active_docs:
        remaining = [d for d in docs if d.id not in kept]
        while len(kept) < max_active_docs and remaining:
            subtype_deficits = {
                st: subtype_targets[st] - subtype_counts[st]
                for st in ANXIETY_SUBTYPES
                if st not in PROTECTED_ANXIETY_SUBTYPES
            }
            target_st = _pick_subtype_for_anxiety(subtype_deficits, subtype_counts)
            chosen: ActiveDoc | None = None
            if target_st:
                pool = _anxiety_subtype_candidates(remaining, target_st)
                chosen = pick_doc(pool)
            if chosen is None:
                chosen = remaining[0]
            remaining.remove(chosen)
            _add_doc_to_keep(chosen, kept=kept, label_counts=label_counts, subtype_counts=subtype_counts)

    keep_docs = [d for d in docs if d.id in kept]
    keep_ids = tuple(d.id for d in keep_docs)
    return PrunePlan(
        max_active_docs=max_active_docs,
        current_active=current_active,
        keep_total=len(keep_ids),
        delete_total=current_active - len(keep_ids),
        per_category=_label_plan(_count_labels(docs), _count_labels(keep_docs)),
        per_anxiety_subtype=_subtype_plan(_count_subtypes(docs), _count_subtypes(keep_docs)),
        keep_ids=keep_ids,
        balance_by="labels",
    )


async def _fetch_active_by_primary(store: KnowledgeStore) -> dict[str, list[UUID]]:
    rows = await store.pool.fetch(
        """
        SELECT id, category
        FROM kb_documents
        WHERE status = 'active'
        ORDER BY category, created_at DESC NULLS LAST, crawled_at DESC
        """
    )
    by_cat: dict[str, list[UUID]] = {cat: [] for cat in CATEGORIES}
    for row in rows:
        cat = str(row["category"])
        if cat in by_cat:
            by_cat[cat].append(row["id"])
        elif cat in ("gad", "panic_disorder", "phobias", "social_anxiety"):
            by_cat["anxiety"].append(row["id"])
    return by_cat


def build_primary_balanced_plan(
    docs: list[ActiveDoc],
    by_primary: dict[str, list[UUID]],
    *,
    max_active_docs: int,
) -> PrunePlan:
    counts = {cat: len(ids) for cat, ids in by_primary.items()}
    current_active = sum(counts.values())
    targets = dict(zip(CATEGORIES, _distribute(max_active_docs, len(CATEGORIES)), strict=True))

    keep_ids: list[UUID] = []
    plans: list[CategoryPlan] = []
    for cat in CATEGORIES:
        ids = by_primary.get(cat, [])
        keep_n = min(len(ids), targets[cat])
        keep_ids.extend(ids[:keep_n])
        plans.append(
            CategoryPlan(category=cat, current=len(ids), keep=keep_n, delete=len(ids) - keep_n)
        )

    keep_set = set(keep_ids)
    keep_docs = [d for d in docs if d.id in keep_set]
    return PrunePlan(
        max_active_docs=max_active_docs,
        current_active=current_active,
        keep_total=len(keep_ids),
        delete_total=current_active - len(keep_ids),
        per_category=tuple(plans),
        per_anxiety_subtype=_subtype_plan(_count_subtypes(docs), _count_subtypes(keep_docs)),
        keep_ids=tuple(keep_ids),
        balance_by="primary",
    )


async def build_prune_plan(
    store: KnowledgeStore,
    *,
    max_active_docs: int,
    balance_by: str,
) -> PrunePlan:
    docs = await _fetch_active_docs(store)
    if balance_by == "primary":
        by_primary = await _fetch_active_by_primary(store)
        return build_primary_balanced_plan(docs, by_primary, max_active_docs=max_active_docs)
    return build_label_balanced_plan(docs, max_active_docs=max_active_docs)


def _print_plan(plan: PrunePlan) -> None:
    logger.info(
        "Prune plan (%s): current_active=%s -> keep=%s delete=%s (target max=%s)",
        plan.balance_by,
        plan.current_active,
        plan.keep_total,
        plan.delete_total,
        plan.max_active_docs,
    )
    header = f"{'category':<16} {'current':>8} {'keep':>8} {'delete':>8}"
    logger.info("Top-level labels:")
    logger.info(header)
    for row in plan.per_category:
        logger.info(
            "%-16s %8d %8d %8d",
            row.category,
            row.current,
            row.keep,
            row.delete,
        )
    logger.info("Anxiety subtypes (within anxiety bucket; not total doc deletes):")
    header_st = f"{'subtype':<16} {'current':>8} {'keep':>8} {'delete':>8}"
    logger.info(header_st)
    for row in plan.per_anxiety_subtype:
        logger.info(
            "%-16s %8d %8d %8d",
            row.subtype,
            row.current,
            row.keep,
            row.delete,
        )


async def execute_prune(store: KnowledgeStore, plan: PrunePlan) -> int:
    if plan.delete_total <= 0:
        logger.info("Nothing to delete.")
        return 0
    keep_list = list(plan.keep_ids)
    result = await store.pool.execute(
        """
        DELETE FROM kb_documents
        WHERE status = 'active'
          AND NOT (id = ANY($1::uuid[]))
        """,
        keep_list,
    )
    try:
        deleted = int(str(result).split()[-1])
    except (TypeError, ValueError, IndexError):
        deleted = plan.delete_total
    logger.info("Deleted %s active document(s) (chunks/labels cascaded).", deleted)
    return deleted


async def print_status(store: KnowledgeStore) -> None:
    active = await store.pool.fetchval(
        "SELECT COUNT(*)::int FROM kb_documents WHERE status = 'active'"
    )
    chunks = await store.pool.fetchval("SELECT COUNT(*)::int FROM kb_chunks")
    primaries = await store.pool.fetch(
        """
        SELECT category, COUNT(*)::int AS n
        FROM kb_documents
        WHERE status = 'active'
        GROUP BY category
        ORDER BY category
        """
    )
    labels = await store.count_active_labels_by_category()
    subtypes = await store.count_active_anxiety_subtypes()
    logger.info("active_docs=%s chunks=%s", active, chunks)
    logger.info("primary_counts=%s", {str(r["category"]): int(r["n"]) for r in primaries})
    logger.info("label_counts=%s", labels)
    logger.info("anxiety_subtype_counts=%s", subtypes)


async def run_prune(
    *,
    max_active_docs: int,
    balance_by: str,
    dry_run: bool,
    confirm: bool,
    status_only: bool,
) -> int:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is missing. Set it in backend/.env")
    if balance_by not in ("labels", "primary"):
        raise SystemExit("--balance-by must be 'labels' or 'primary'")

    store = KnowledgeStore(settings.database_url)
    await store.connect()
    try:
        if status_only:
            await print_status(store)
            return 0

        plan = await build_prune_plan(
            store, max_active_docs=max_active_docs, balance_by=balance_by
        )
        _print_plan(plan)

        if dry_run or not confirm:
            if not confirm:
                logger.info("Dry run only. Re-run with --confirm to delete.")
            return 0

        if plan.delete_total <= 0:
            logger.info("Already at or below target; no deletes needed.")
            return 0

        await execute_prune(store, plan)
        await print_status(store)
        return 0
    finally:
        await store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trim active KB documents with balanced label or primary caps"
    )
    parser.add_argument(
        "--max-active-docs",
        type=int,
        default=3000,
        help="Target maximum active documents after trim (default: 3000)",
    )
    parser.add_argument(
        "--balance-by",
        choices=("labels", "primary"),
        default="labels",
        help="Balance using multi-label counts (default) or primary category",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print keep/delete plan without deleting (default if --confirm omitted)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Execute deletes (irreversible; chunks cascade)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current active/primary/label/subtype counts and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_active_docs < 1:
        raise SystemExit("--max-active-docs must be >= 1")

    dry_run = args.dry_run or not args.confirm
    if args.confirm and args.dry_run:
        raise SystemExit("Use either --dry-run or --confirm, not both")

    return asyncio.run(
        run_prune(
            max_active_docs=args.max_active_docs,
            balance_by=args.balance_by,
            dry_run=dry_run,
            confirm=args.confirm,
            status_only=args.status,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
