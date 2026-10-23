"""
Copefy knowledge-base ingest CLI.

Usage (from the backend/ directory, with venv active):

    python -m rag.ingest --status
    python -m rag.ingest --discover-only --min-per-category 1000
    python -m rag.ingest --estimate-only --min-per-category 1000
    python -m rag.ingest --paid --min-per-category 1000 --max-embeds 60000

Cost model: embeds are the only step that costs money. Discovery, crawling,
chunking, --status, and --estimate-only never touch the Gemini API. When
GEMINI_INGEST_API_KEY (paid project) is set, --max-embeds is mandatory.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections import Counter
from dataclasses import dataclass

from config import settings
from rag import CATEGORIES, normalize_seed_category
from rag.chunking import chunk_markdown
from rag.classify import classify_content
from rag.crawl import crawl_url
from rag.discover import (
    DEFAULT_DISCOVERED_PATH,
    discover_urls,
    load_discovered_urls,
    save_discovered_urls,
)
from rag.embed import EMBED_DIMENSIONS
from rag.kb_embed import GeminiEmbedder
from rag.parse_pdf import parse_pdf_url
from rag.store import KnowledgeStore, content_hash
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("rag.ingest")

# Paid-tier pricing for gemini-embedding-2 text input (USD per 1M tokens).
PRICE_PER_MTOK_USD = 0.20
# Throughput used by --paid (safe margin under Tier 1's 3000 RPM).
PAID_EMBED_CONCURRENCY = 8
PAID_EMBED_DELAY_SECONDS = 0.05
PAID_INGEST_CONCURRENCY = 8
# Log a spend checkpoint to the console every N embedding API calls.
SPEND_CHECKPOINT_EMBEDS = 500


def _embed_cost_ceiling_usd(embed_count: int) -> float:
    """Worst-case $ for N embeds (chars/4 token heuristic, same as startup banner)."""
    tokens_per_embed = settings.chunk_max_chars / 4
    return embed_count * tokens_per_embed / 1_000_000 * PRICE_PER_MTOK_USD


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass
class IngestStats:
    discovered: int = 0
    crawled_ok: int = 0
    skipped_unchanged: int = 0
    skipped_already_active: int = 0
    deferred_for_extras: int = 0
    upserted: int = 0
    chunks_written: int = 0
    errors: int = 0
    embeds_used: int = 0
    reused_markdown: int = 0
    est_docs: int = 0
    est_chunks: int = 0
    est_tokens: int = 0
    by_category: Counter[str] | None = None

    def __post_init__(self) -> None:
        if self.by_category is None:
            self.by_category = Counter()


def _norm_url(url: str) -> str:
    return url.strip().rstrip("/")


def _parse_categories(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    cats = [c.strip().lower() for c in raw.split(",") if c.strip()]
    unknown = sorted(set(cats) - set(CATEGORIES))
    if unknown:
        raise SystemExit(f"Unknown categories: {unknown}. Allowed: {list(CATEGORIES)}")
    return cats


def _category_targets_met(counts: dict[str, int], min_per_category: int | None) -> bool:
    if not min_per_category:
        return False
    return all(counts.get(cat, 0) >= min_per_category for cat in CATEGORIES)


def _projected_counts(baseline: dict[str, int], new_counts: Counter[str] | dict[str, int]) -> dict[str, int]:
    return {cat: baseline.get(cat, 0) + int(new_counts.get(cat, 0)) for cat in CATEGORIES}


def _underfilled_categories(
    baseline: dict[str, int],
    new_counts: Counter[str] | dict[str, int],
    target: int,
) -> set[str]:
    projected = _projected_counts(baseline, new_counts)
    return {cat for cat in CATEGORIES if projected[cat] < target}


def _interleave_by_category(items: list) -> list:
    """
    Round-robin URLs by primary category so a --max-embeds budget cut
    does not starve alphabetically-late categories (e.g. social_anxiety).
    """
    buckets: dict[str, list] = {cat: [] for cat in CATEGORIES}
    other: list = []
    for item in items:
        cat = item.category if item.category in buckets else None
        if cat is None:
            other.append(item)
        else:
            buckets[cat].append(item)
    ordered: list = []
    while any(buckets.values()):
        for cat in CATEGORIES:
            if buckets[cat]:
                ordered.append(buckets[cat].pop(0))
    ordered.extend(other)
    return ordered


def _item_labels(item) -> set[str]:
    labels = set(item.categories or (item.category,))
    labels.add(item.category)
    if item.seed_category:
        seed_cat, _ = normalize_seed_category(item.seed_category)
        if seed_cat:
            labels.add(seed_cat)
    return labels


def _split_fill_and_extras(
    items: list,
    *,
    baseline: dict[str, int],
    target: int | None,
) -> tuple[list, list]:
    """
    Phase 1 candidates: discovery labels overlap a still-short category.
    Phase 2 extras: everything else (plus any phase-1 docs deferred at runtime
    once their categories filled — those are appended later, not dropped).
    """
    if not target:
        return _interleave_by_category(items), []

    underfilled = _underfilled_categories(baseline, {}, target)
    if not underfilled:
        return [], _interleave_by_category(items)

    fill: list = []
    extras: list = []
    for item in items:
        if _item_labels(item).intersection(underfilled):
            fill.append(item)
        else:
            extras.append(item)

    fill_q = _interleave_by_category(fill)
    extras_q = _interleave_by_category(extras)
    logger.info(
        "Queue split: %s fill-priority (underfilled=%s), %s extras "
        "(extras wait until every category hits %s)",
        len(fill_q),
        sorted(underfilled),
        len(extras_q),
        target,
    )
    return fill_q, extras_q


def _max_source_chars_for(url: str) -> int:
    """PMC research articles get a larger source budget than consumer pages."""
    if "ncbi.nlm.nih.gov" in url.lower():
        return settings.max_source_chars_pmc
    return settings.max_source_chars


def _log_category_projection(
    baseline: dict[str, int],
    new_counts: Counter[str],
    target: int | None,
) -> None:
    """Per-category go/no-go table: DB active docs + this run's docs vs target."""
    lines = ["Per-category projection (active in DB + this run):"]
    header = f"{'category':<16}{'active':>8}{'new':>8}{'projected':>11}"
    if target:
        header += f"{'target':>8}  status"
    lines.append(header)
    all_ok = True
    for cat in CATEGORIES:
        active = baseline.get(cat, 0)
        new = new_counts.get(cat, 0)
        projected = active + new
        row = f"{cat:<16}{active:>8}{new:>8}{projected:>11}"
        if target:
            ok = projected >= target
            all_ok = all_ok and ok
            row += f"{target:>8}  {'OK' if ok else 'SHORT'}"
        lines.append(row)
    logger.info("\n".join(lines))
    if target and not all_ok:
        logger.warning(
            "Some categories are below target. Widen sources (PMC terms, domains) "
            "or raise discovery limits before the paid run."
        )


async def ingest(
    *,
    categories: list[str] | None,
    limit: int | None,
    use_sitemaps: bool,
    use_bfs: bool,
    concurrency: int,
    min_per_category: int | None,
    max_new_docs: int | None,
    max_embeds: int | None,
    bfs_max_depth: int | None,
    bfs_max_pages: int | None,
    refresh_active: bool = False,
    from_file: str | None = None,
    write_urls: str | None = None,
    use_pmc: bool = True,
    estimate_only: bool = False,
    paid: bool = False,
    fill_only: bool = False,
) -> IngestStats:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is missing. Set it in backend/.env")

    using_ingest_key = bool(settings.gemini_ingest_api_key)
    api_key = settings.gemini_ingest_api_key or settings.gemini_api_key
    if not estimate_only:
        if not api_key:
            raise SystemExit(
                "GEMINI_API_KEY (or GEMINI_INGEST_API_KEY) is missing. Set it in backend/.env"
            )
        if using_ingest_key and max_embeds is None:
            raise SystemExit(
                "GEMINI_INGEST_API_KEY (paid project) is set but --max-embeds is not. "
                "Refusing to run without a hard embed budget. Run --estimate-only "
                "first, then pass --max-embeds <estimate + buffer>."
            )

    embed_delay = PAID_EMBED_DELAY_SECONDS if paid else settings.embed_delay_seconds
    embed_concurrency = PAID_EMBED_CONCURRENCY if paid else settings.embed_concurrency

    if estimate_only:
        logger.info(
            "ESTIMATE ONLY: no Gemini API calls will be made. "
            "Crawled markdown is cached in the DB for the paid run."
        )
    else:
        est_ceiling = (
            _embed_cost_ceiling_usd(max_embeds) if max_embeds is not None else None
        )
        logger.info(
            "Embed config: model=%s key_slot=%s concurrency=%s delay=%.2fs "
            "max_embeds=%s est_cost_ceiling=%s "
            "(Ctrl+C anytime — resume skips docs already active)",
            settings.gemini_embed_model,
            "GEMINI_INGEST_API_KEY (paid)" if using_ingest_key else "GEMINI_API_KEY (free)",
            embed_concurrency,
            embed_delay,
            max_embeds if max_embeds is not None else "UNLIMITED",
            f"~${est_ceiling:.2f}" if est_ceiling is not None else "n/a",
        )

    stats = IngestStats()
    if from_file:
        discovered = load_discovered_urls(from_file)
        if categories:
            selected = set(categories)
            discovered = [
                item
                for item in discovered
                if item.category in selected
                or selected.intersection(item.categories or ())
            ]
        if limit is not None:
            discovered = discovered[: max(0, limit)]
    else:
        discovered = await discover_urls(
            categories,
            use_sitemaps=use_sitemaps,
            use_bfs=use_bfs,
            use_pmc=use_pmc,
            limit=limit,
            min_per_category=min_per_category,
            bfs_max_depth=bfs_max_depth,
            bfs_max_pages=bfs_max_pages,
        )
        # Always cache live discovery so key swaps can skip rediscovery.
        save_discovered_urls(discovered, write_urls or DEFAULT_DISCOVERED_PATH)

    if write_urls and from_file:
        save_discovered_urls(discovered, write_urls)

    stats.discovered = len(discovered)
    if not discovered:
        logger.warning("No URLs discovered. Check seeds / category filters.")
        return stats

    store = KnowledgeStore(settings.database_url)
    embedder: GeminiEmbedder | None = None
    if not estimate_only:
        embedder = GeminiEmbedder(
            api_key,
            model=settings.gemini_embed_model,
            dimensions=EMBED_DIMENSIONS,
            batch_size=settings.embed_batch_size,
            max_concurrency=max(1, embed_concurrency),
            inter_batch_delay_seconds=embed_delay,
        )

    await store.connect()
    try:
        await store.ensure_multilabel_schema()
        label_counts = await store.count_active_labels_by_category()
        if _category_targets_met(label_counts, min_per_category) and not estimate_only:
            if fill_only or max_embeds is None:
                logger.info(
                    "All categories already at min-per-category=%s: %s",
                    min_per_category,
                    label_counts,
                )
                return stats
            logger.info(
                "All categories already at min-per-category=%s; "
                "running extras phase until --max-embeds=%s. %s",
                min_per_category,
                max_embeds,
                label_counts,
            )
        if fill_only:
            logger.info(
                "FILL ONLY: will stop as soon as every category reaches %s "
                "(no extras / no spend-the-rest-of-$10 phase)",
                min_per_category,
            )

        work_queue = list(discovered)
        if not refresh_active:
            active_urls = {_norm_url(u) for u in await store.get_active_source_urls()}
            work_queue = [item for item in discovered if _norm_url(item.url) not in active_urls]
            stats.skipped_already_active = len(discovered) - len(work_queue)
            logger.info(
                "Skipping %s URLs already active in DB (use --refresh to re-crawl them)",
                stats.skipped_already_active,
            )

        if not work_queue:
            logger.info("Nothing new to ingest after filtering active URLs.")
            return stats

        # Phase 1: fill every category to min_per_category (round-robin).
        # Docs for already-full categories are DEFERRED (not dropped), then
        # Phase 2 round-robins deferred + extras until --max-embeds.
        if min_per_category or max_embeds is not None:
            fill_queue, extras_queue = _split_fill_and_extras(
                work_queue,
                baseline=label_counts,
                target=min_per_category,
            )
        else:
            fill_queue, extras_queue = work_queue, []

        semaphore = asyncio.Semaphore(max(1, concurrency))
        stop = asyncio.Event()
        extras_phase = asyncio.Event()
        deferred: list = []
        deferred_lock = asyncio.Lock()
        if min_per_category and _category_targets_met(label_counts, min_per_category):
            extras_phase.set()
            # Already at target: everything is extras.
            extras_queue = _interleave_by_category(fill_queue + extras_queue)
            fill_queue = []
        started = time.monotonic()
        processed = 0
        total_urls = len(fill_queue) + len(extras_queue)
        progress_lock = asyncio.Lock()
        last_spend_checkpoint = 0
        pbar = tqdm(
            total=total_urls,
            desc="Ingest",
            unit="url",
            dynamic_ncols=True,
            mininterval=0.5,
        )

        async def _log_progress() -> None:
            nonlocal processed
            async with progress_lock:
                processed += 1
                done = processed
            elapsed = time.monotonic() - started
            rate = done / elapsed if elapsed > 0 else 0.0
            remaining = max(0, total_urls - done)
            eta_s = (remaining / rate) if rate > 0 else 0.0
            embed_label = (
                f"{stats.embeds_used}/{max_embeds}"
                if max_embeds is not None
                else str(stats.embeds_used)
            )
            spend_label = (
                f"~${_embed_cost_ceiling_usd(stats.embeds_used):.2f}"
                if stats.embeds_used
                else "$0.00"
            )
            pbar.set_postfix(
                up=stats.upserted,
                skip=stats.skipped_unchanged,
                known=stats.skipped_already_active,
                defer=stats.deferred_for_extras,
                err=stats.errors,
                emb=embed_label,
                usd=spend_label,
                eta=_format_duration(eta_s) if rate > 0 else "…",
                refresh=False,
            )
            pbar.update(1)

        logger.info(
            "Starting ingest of %s new/pending URLs "
            "(discovered=%s, already_active=%s, fill=%s, extras=%s, concurrency=%s%s)",
            total_urls,
            stats.discovered,
            stats.skipped_already_active,
            len(fill_queue),
            len(extras_queue),
            concurrency,
            f", max_embeds={max_embeds}" if max_embeds is not None else "",
        )

        async def process_one(item, *, defer_if_full: bool) -> None:
            title = ""
            markdown = ""
            source_type = item.source_type
            try:
                if stop.is_set():
                    return
                async with semaphore:
                    if stop.is_set():
                        return
                    try:
                        cached = None
                        if not refresh_active:
                            cached = await store.get_reusable_markdown(item.url)
                        if cached is not None:
                            title, markdown = cached
                            title = title or item.url
                            stats.reused_markdown += 1
                            freshly_crawled = False
                        elif item.source_type == "pdf":
                            parsed = await parse_pdf_url(item.url)
                            if not parsed.ok:
                                stats.errors += 1
                                await store.mark_error(
                                    item.url, item.category, "pdf", parsed.error or "pdf failed"
                                )
                                logger.error("PDF failed %s: %s", item.url, parsed.error)
                                return
                            title = parsed.title or item.url
                            markdown = parsed.markdown
                            source_type = "pdf"
                            freshly_crawled = True
                        else:
                            crawled = await crawl_url(item.url)
                            if not crawled.ok:
                                stats.errors += 1
                                await store.mark_error(
                                    item.url, item.category, "web", crawled.error or "crawl failed"
                                )
                                logger.error("Crawl failed %s: %s", item.url, crawled.error)
                                return
                            title = crawled.title or item.url
                            markdown = crawled.markdown
                            source_type = "web"
                            freshly_crawled = True

                        stats.crawled_ok += 1
                        classification = classify_content(
                            url=item.url,
                            title=title,
                            body=markdown,
                            seed_category=item.seed_category or item.category,
                        )
                        if classification is None:
                            stats.errors += 1
                            await store.mark_error(
                                item.url,
                                item.category,
                                source_type,
                                "no category match",
                                title=title,
                                markdown=markdown,
                            )
                            return

                        primary = classification.primary
                        label_cats = classification.categories
                        anxiety_subtype = classification.anxiety_subtype or getattr(
                            item, "anxiety_subtype", None
                        )

                        existing = await store.get_existing_hash(item.url)
                        if existing and existing == content_hash(markdown):
                            row_status = await store.pool.fetchval(
                                "SELECT status FROM kb_documents WHERE source_url = $1",
                                item.url,
                            )
                            if row_status == "active":
                                await store.upsert_document_with_chunks(
                                    source_url=item.url,
                                    source_type=source_type,
                                    title=title,
                                    category=primary,
                                    categories=label_cats,
                                    anxiety_subtype=anxiety_subtype,
                                    markdown=markdown,
                                    chunks=[],
                                    embeddings=[],
                                )
                                stats.skipped_unchanged += 1
                                for cat in label_cats:
                                    stats.by_category[cat] += 1
                                logger.info("Unchanged, skip: %s", item.url)
                                return

                        source_chars = len(markdown)
                        max_source_chars = _max_source_chars_for(item.url)
                        chunks = chunk_markdown(
                            markdown,
                            category=primary,
                            title=title,
                            max_chars=settings.chunk_max_chars,
                            overlap=settings.chunk_overlap,
                            min_chars=settings.chunk_min_chars,
                            max_chunks=settings.max_chunks_per_doc,
                            max_source_chars=max_source_chars,
                        )
                        if source_chars > max_source_chars:
                            logger.warning(
                                "Truncated source for %s (%s -> %s chars)",
                                item.url,
                                source_chars,
                                max_source_chars,
                            )
                        if len(chunks) >= settings.max_chunks_per_doc:
                            logger.warning(
                                "Capped chunks for %s at %s",
                                item.url,
                                settings.max_chunks_per_doc,
                            )
                        if not chunks:
                            stats.errors += 1
                            await store.mark_error(
                                item.url,
                                primary,
                                source_type,
                                "no chunks produced",
                                title=title,
                                markdown=markdown,
                            )
                            logger.warning("No chunks for %s", item.url)
                            return

                        if estimate_only:
                            stats.est_docs += 1
                            stats.est_chunks += len(chunks)
                            stats.est_tokens += sum(c.token_estimate for c in chunks)
                            if freshly_crawled:
                                await store.save_crawl_cache(
                                    source_url=item.url,
                                    source_type=source_type,
                                    title=title,
                                    category=primary,
                                    markdown=markdown,
                                )
                            for cat in label_cats:
                                stats.by_category[cat] += 1
                            return

                        # Phase 1: embed only if doc helps a still-short category.
                        # Otherwise DEFER it for phase 2 (do not drop).
                        if (
                            defer_if_full
                            and min_per_category
                            and not extras_phase.is_set()
                        ):
                            underfilled = _underfilled_categories(
                                label_counts,
                                stats.by_category or Counter(),
                                min_per_category,
                            )
                            if not underfilled:
                                if fill_only:
                                    stop.set()
                                    logger.info(
                                        "FILL ONLY complete: all categories >= %s. "
                                        "Stopping before extras. %s",
                                        min_per_category,
                                        _projected_counts(
                                            label_counts, stats.by_category or {}
                                        ),
                                    )
                                    return
                                extras_phase.set()
                                logger.info(
                                    "All categories >= %s during fill; "
                                    "remaining docs go to extras phase. %s",
                                    min_per_category,
                                    _projected_counts(label_counts, stats.by_category or {}),
                                )
                            elif not underfilled.intersection(label_cats):
                                if fill_only:
                                    # No phase 2 — just skip; do not defer.
                                    return
                                if freshly_crawled:
                                    await store.save_crawl_cache(
                                        source_url=item.url,
                                        source_type=source_type,
                                        title=title,
                                        category=primary,
                                        markdown=markdown,
                                    )
                                async with deferred_lock:
                                    deferred.append(item)
                                    stats.deferred_for_extras += 1
                                return

                        if max_embeds is not None and stats.embeds_used + len(chunks) > max_embeds:
                            logger.warning("Max embed budget reached (%s); stopping.", max_embeds)
                            stop.set()
                            return

                        vectors = await embedder.embed_texts([c.content for c in chunks])
                        stats.embeds_used += len(chunks)
                        if not estimate_only:
                            nonlocal last_spend_checkpoint
                            checkpoint = (
                                stats.embeds_used // SPEND_CHECKPOINT_EMBEDS
                            ) * SPEND_CHECKPOINT_EMBEDS
                            if (
                                checkpoint >= SPEND_CHECKPOINT_EMBEDS
                                and checkpoint > last_spend_checkpoint
                            ):
                                last_spend_checkpoint = checkpoint
                                spent = _embed_cost_ceiling_usd(stats.embeds_used)
                                if max_embeds is not None:
                                    ceiling = _embed_cost_ceiling_usd(max_embeds)
                                    logger.info(
                                        "Spend checkpoint: embeds=%s/%s est~$%.2f of $%.2f ceiling "
                                        "(%.0f%% of run budget)",
                                        stats.embeds_used,
                                        max_embeds,
                                        spent,
                                        ceiling,
                                        100.0 * stats.embeds_used / max_embeds,
                                    )
                                else:
                                    logger.info(
                                        "Spend checkpoint: embeds=%s est~$%.2f so far",
                                        stats.embeds_used,
                                        spent,
                                    )

                        outcome = await store.upsert_document_with_chunks(
                            source_url=item.url,
                            source_type=source_type,
                            title=title,
                            category=primary,
                            categories=label_cats,
                            anxiety_subtype=anxiety_subtype,
                            markdown=markdown,
                            chunks=chunks,
                            embeddings=vectors,
                        )
                        if outcome.skipped:
                            stats.skipped_unchanged += 1
                        else:
                            stats.upserted += 1
                            stats.chunks_written += outcome.chunk_count
                            if max_new_docs is not None and stats.upserted >= max_new_docs:
                                logger.info("Max new docs reached (%s); stopping.", max_new_docs)
                                stop.set()
                        for cat in label_cats:
                            stats.by_category[cat] += 1
                        if (
                            min_per_category
                            and not extras_phase.is_set()
                            and _category_targets_met(
                                _projected_counts(label_counts, stats.by_category or {}),
                                min_per_category,
                            )
                        ):
                            if fill_only:
                                stop.set()
                                logger.info(
                                    "FILL ONLY complete: all categories >= %s. "
                                    "Stopping before extras. %s",
                                    min_per_category,
                                    _projected_counts(
                                        label_counts, stats.by_category or {}
                                    ),
                                )
                            else:
                                extras_phase.set()
                                logger.info(
                                    "Phase 2: all categories >= %s. "
                                    "Round-robin extras until embed budget. %s",
                                    min_per_category,
                                    _projected_counts(
                                        label_counts, stats.by_category or {}
                                    ),
                                )
                        logger.info(
                            "Ingested %s (%s) labels=%s chunks=%s phase=%s",
                            item.url,
                            primary,
                            label_cats,
                            outcome.chunk_count,
                            "extras" if extras_phase.is_set() else "fill",
                        )
                    except Exception as exc:  # noqa: BLE001
                        stats.errors += 1
                        logger.exception("Failed %s: %s", item.url, exc)
                        try:
                            await store.mark_error(
                                item.url,
                                item.category,
                                source_type,
                                str(exc),
                                title=title,
                                markdown=markdown or None,
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception("Could not mark error row for %s", item.url)
            finally:
                await _log_progress()

        try:
            if fill_queue:
                logger.info("Phase 1 (fill to %s): %s URLs", min_per_category, len(fill_queue))
                await asyncio.gather(
                    *(process_one(item, defer_if_full=True) for item in fill_queue)
                )

            phase2 = _interleave_by_category(deferred + extras_queue)
            if fill_only and not estimate_only:
                if phase2:
                    logger.info(
                        "FILL ONLY: skipping phase 2 (%s deferred + %s extras left unspent)",
                        len(deferred),
                        len(extras_queue),
                    )
            elif phase2 and not stop.is_set():
                extras_phase.set()
                # Deferred URLs get a second pass; extend the bar for those re-visits.
                if deferred:
                    pbar.total = (pbar.total or 0) + len(deferred)
                    total_urls += len(deferred)
                logger.info(
                    "Phase 2 (%s): %s URLs (%s deferred from fill + %s extras). projected=%s",
                    "estimate walk" if estimate_only else "extras until embed budget",
                    len(phase2),
                    len(deferred),
                    len(extras_queue),
                    _projected_counts(label_counts, stats.by_category or {}),
                )
                await asyncio.gather(
                    *(process_one(item, defer_if_full=False) for item in phase2)
                )
        finally:
            pbar.close()
        logger.info(
            "Ingest finished in %s",
            _format_duration(time.monotonic() - started),
        )
        if not estimate_only and stats.embeds_used:
            logger.info(
                "Embed spend summary: embeds=%s est~$%.2f "
                "(worst-case at $%.2f/1M tokens; check Google billing for actual)",
                stats.embeds_used,
                _embed_cost_ceiling_usd(stats.embeds_used),
                PRICE_PER_MTOK_USD,
            )

        if estimate_only:
            est_cost = stats.est_tokens / 1_000_000 * PRICE_PER_MTOK_USD
            suggested_budget = int(stats.est_chunks * 1.1) + 100
            logger.info(
                "Estimate: docs=%s chunks=%s tokens=~%s cost=~$%.2f "
                "(at $%.2f/1M tokens). Suggested flag: --max-embeds %s",
                stats.est_docs,
                stats.est_chunks,
                stats.est_tokens,
                est_cost,
                PRICE_PER_MTOK_USD,
                suggested_budget,
            )
            _log_category_projection(label_counts, stats.by_category, min_per_category)
        elif min_per_category:
            final_counts = await store.count_active_labels_by_category()
            _log_category_projection(final_counts, Counter(), min_per_category)
    finally:
        await store.close()

    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Copefy shared knowledge base")
    parser.add_argument(
        "--categories",
        type=str,
        default=None,
        help=f"Comma-separated category slugs. Default: all. Allowed: {','.join(CATEGORIES)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of URLs to process after discovery",
    )
    parser.add_argument(
        "--no-sitemaps",
        action="store_true",
        help="Skip sitemap discovery (seeds + BFS only)",
    )
    parser.add_argument(
        "--no-bfs",
        action="store_true",
        help="Skip allowlisted link crawl (seeds + sitemaps only)",
    )
    parser.add_argument(
        "--no-pmc",
        action="store_true",
        help="Skip open-access PMC top-up discovery",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Max concurrent page/PDF jobs (defaults to INGEST_CONCURRENCY)",
    )
    parser.add_argument(
        "--clear-errors",
        action="store_true",
        help="Delete kb_documents rows with status=error before ingesting",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Run discovery and print counts without crawling or embedding",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Crawl + chunk without any embed calls: prints token/$ estimate and "
        "per-category go/no-go table; caches markdown in the DB for the paid run",
    )
    parser.add_argument(
        "--paid",
        action="store_true",
        help="Paid-tier throughput (embed concurrency 8, 0.05s delay). "
        "Requires --max-embeds",
    )
    parser.add_argument(
        "--fill-only",
        action="store_true",
        help="Stop as soon as every category reaches --min-per-category; "
        "do not run the extras round-robin (saves remaining prepaid balance)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print active document counts per category label and exit",
    )
    parser.add_argument(
        "--min-per-category",
        type=int,
        default=None,
        help="Target at least N category labels per slug (multi-label counts)",
    )
    parser.add_argument(
        "--max-new-docs",
        type=int,
        default=None,
        help="Stop after upserting this many new/changed documents",
    )
    parser.add_argument(
        "--max-embeds",
        type=int,
        default=None,
        help="Stop after this many embedding API calls in this run",
    )
    parser.add_argument(
        "--bfs-max-depth",
        type=int,
        default=None,
        help="Link crawl depth (default from DISCOVERY_BFS_MAX_DEPTH)",
    )
    parser.add_argument(
        "--bfs-max-pages",
        type=int,
        default=None,
        help="Max HTML pages to fetch during BFS discovery",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-crawl URLs already active in the DB (default: skip them without crawling)",
    )
    parser.add_argument(
        "--from-file",
        type=str,
        default=None,
        help="Load discovered URLs from JSON (skip live discovery). "
        f"Default cache path after a live run: {DEFAULT_DISCOVERED_PATH}",
    )
    parser.add_argument(
        "--write-urls",
        type=str,
        default=None,
        help="Write discovered URLs to this JSON path "
        f"(live discovery also auto-saves to {DEFAULT_DISCOVERED_PATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    categories = _parse_categories(args.categories)
    if args.paid and args.max_embeds is None:
        raise SystemExit("--paid requires --max-embeds (hard spend budget)")
    if args.fill_only and args.min_per_category is None:
        raise SystemExit("--fill-only requires --min-per-category")
    concurrency = args.concurrency or (
        PAID_INGEST_CONCURRENCY if args.paid else settings.ingest_concurrency
    )
    if args.estimate_only and (args.concurrency is None):
        # Crawling is free; go wide so the estimate pass finishes quickly.
        concurrency = max(concurrency, 4)

    async def _status() -> int:
        if not settings.database_url:
            raise SystemExit("DATABASE_URL is missing. Set it in backend/.env")
        store = KnowledgeStore(settings.database_url)
        await store.connect()
        try:
            counts = await store.count_active_labels_by_category()
        finally:
            await store.close()
        _log_category_projection(counts, Counter(), args.min_per_category)
        return 0

    async def _discover_only() -> int:
        if args.from_file:
            items = load_discovered_urls(args.from_file)
        else:
            items = await discover_urls(
                categories,
                use_sitemaps=not args.no_sitemaps,
                use_bfs=not args.no_bfs,
                use_pmc=not args.no_pmc,
                limit=args.limit,
                min_per_category=args.min_per_category,
                bfs_max_depth=args.bfs_max_depth,
                bfs_max_pages=args.bfs_max_pages,
            )
            save_discovered_urls(items, args.write_urls or DEFAULT_DISCOVERED_PATH)
        if args.write_urls and args.from_file:
            save_discovered_urls(items, args.write_urls)

        baseline: dict[str, int] = {}
        active_urls: set[str] = set()
        if settings.database_url:
            store = KnowledgeStore(settings.database_url)
            await store.connect()
            try:
                baseline = await store.count_active_labels_by_category()
                active_urls = {_norm_url(u) for u in await store.get_active_source_urls()}
            finally:
                await store.close()

        discovered_labels: Counter[str] = Counter()
        new_labels: Counter[str] = Counter()
        for item in items:
            labels = item.categories or (item.category,)
            is_new = _norm_url(item.url) not in active_urls
            for cat in labels:
                discovered_labels[cat] += 1
                if is_new:
                    new_labels[cat] += 1

        logger.info("Discover-only: %s URLs (no Gemini calls)", len(items))
        logger.info("Discovery label counts (all): %s", dict(discovered_labels))
        logger.info(
            "New URLs not yet active in DB: %s",
            sum(1 for item in items if _norm_url(item.url) not in active_urls),
        )

        # Go/no-go: active in DB + new discovered URLs (avoids double-counting).
        target = args.min_per_category
        _log_category_projection(baseline, new_labels, target)
        if target:
            buffer_target = int(target * 1.3)
            short = [
                cat
                for cat in CATEGORIES
                if baseline.get(cat, 0) + new_labels.get(cat, 0) < buffer_target
            ]
            if short:
                logger.warning(
                    "Below 1.3x discovery buffer (%s) for: %s. "
                    "Widen PMC terms / domains before --estimate-only.",
                    buffer_target,
                    short,
                )
            else:
                logger.info(
                    "All categories clear 1.3x discovery buffer (%s). "
                    "Next: python -m rag.ingest --estimate-only --min-per-category %s",
                    buffer_target,
                    target,
                )
        return 0

    async def _run() -> IngestStats:
        if args.clear_errors:
            if not settings.database_url:
                raise SystemExit("DATABASE_URL is missing. Set it in backend/.env")
            store = KnowledgeStore(settings.database_url)
            await store.connect()
            try:
                deleted = await store.delete_error_rows()
                logger.info("Cleared %s error document(s)", deleted)
            finally:
                await store.close()
        return await ingest(
            categories=categories,
            limit=args.limit,
            use_sitemaps=not args.no_sitemaps,
            use_bfs=not args.no_bfs,
            concurrency=concurrency,
            min_per_category=args.min_per_category,
            max_new_docs=args.max_new_docs,
            max_embeds=args.max_embeds,
            bfs_max_depth=args.bfs_max_depth,
            bfs_max_pages=args.bfs_max_pages,
            refresh_active=args.refresh,
            from_file=args.from_file,
            write_urls=args.write_urls,
            use_pmc=not args.no_pmc,
            estimate_only=args.estimate_only,
            paid=args.paid,
            fill_only=args.fill_only,
        )

    if args.status:
        return asyncio.run(_status())

    if args.discover_only:
        return asyncio.run(_discover_only())

    stats = asyncio.run(_run())

    logger.info(
        "Done. discovered=%s already_active=%s crawled_ok=%s reused_md=%s upserted=%s "
        "skipped=%s deferred=%s chunks=%s embeds=%s errors=%s by_category=%s",
        stats.discovered,
        stats.skipped_already_active,
        stats.crawled_ok,
        stats.reused_markdown,
        stats.upserted,
        stats.skipped_unchanged,
        stats.deferred_for_extras,
        stats.chunks_written,
        stats.embeds_used,
        stats.errors,
        dict(stats.by_category or {}),
    )
    if args.estimate_only:
        return 1 if stats.errors and stats.est_docs == 0 else 0
    return 1 if stats.errors and stats.upserted == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
