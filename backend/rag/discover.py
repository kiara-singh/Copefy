"""URL discovery: seeds, nested sitemaps, and allowlisted BFS link crawl."""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from config import settings
from rag.classify import Classification, infer_categories_from_url
from rag.config_sources import (
    BFS_ROOT_URLS,
    SITEMAP_URLS,
    SeedSource,
    domain_allowed,
    path_allowed,
    seeds_for_categories,
    seed_hint_category,
    url_excluded,
)
from rag.link_extract import extract_links
from rag.pmc import search_pmc_urls_by_category

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERED_PATH = Path("data") / "discovered_urls.json"


@dataclass(frozen=True)
class DiscoveredUrl:
    url: str
    category: str
    source_type: str  # web | pdf
    categories: tuple[str, ...] = ()
    seed_category: str | None = None
    anxiety_subtype: str | None = None


@dataclass
class _QueueItem:
    url: str
    depth: int
    seed_category: str | None = None


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl().rstrip("/")


def _is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def infer_category(url: str) -> str | None:
    """Backward-compatible single-category helper."""
    result = infer_categories_from_url(url)
    return None if result is None else result.primary


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.text


async def _fetch_sitemap_locs(
    client: httpx.AsyncClient,
    sitemap_url: str,
    *,
    depth: int = 0,
    max_depth: int = 3,
) -> list[str]:
    if depth > max_depth:
        return []
    try:
        text = await _fetch_text(client, sitemap_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sitemap fetch failed for %s: %s", sitemap_url, exc)
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        logger.warning("Sitemap XML parse failed for %s: %s", sitemap_url, exc)
        return []

    root_tag = root.tag.rsplit("}", 1)[-1].lower()
    nested: list[str] = []
    page_locs: list[str] = []

    if root_tag == "sitemapindex":
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1].lower()
            if tag != "sitemap":
                continue
            for child in node:
                child_tag = child.tag.rsplit("}", 1)[-1].lower()
                if child_tag == "loc" and child.text:
                    value = child.text.strip()
                    if value.startswith("http"):
                        nested.append(value)
    else:
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1].lower()
            if tag == "loc" and node.text:
                value = node.text.strip()
                if value.startswith("http"):
                    page_locs.append(value)

    urls = list(page_locs)
    seen_nested: set[str] = set()
    for nested_url in nested:
        if nested_url in seen_nested:
            continue
        seen_nested.add(nested_url)
        urls.extend(
            await _fetch_sitemap_locs(
                client,
                nested_url,
                depth=depth + 1,
                max_depth=max_depth,
            )
        )
    return urls


async def _discover_from_sitemaps(
    categories: set[str] | None,
    discovered: dict[str, DiscoveredUrl],
    category_counts: Counter[str],
    *,
    min_per_category: int | None,
) -> None:
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": settings.crawl_user_agent},
    ) as client:
        for sitemap_url in SITEMAP_URLS:
            for raw in await _fetch_sitemap_locs(client, sitemap_url):
                if min_per_category and _all_categories_full(category_counts, categories, min_per_category):
                    return
                url = _normalize_url(raw)
                if not url or url in discovered:
                    continue
                if not domain_allowed(url) or url_excluded(url) or not path_allowed(url):
                    continue
                classification = infer_categories_from_url(url)
                if classification is None:
                    continue
                if categories and not categories.intersection(classification.categories):
                    continue
                _add_discovered(
                    discovered,
                    category_counts,
                    url,
                    classification,
                    source_type="pdf" if _is_pdf(url) else "web",
                )


async def _discover_from_bfs(
    categories: set[str] | None,
    discovered: dict[str, DiscoveredUrl],
    category_counts: Counter[str],
    seeds: list[SeedSource],
    *,
    min_per_category: int | None,
    max_depth: int,
    max_pages: int,
) -> None:
    queue: deque[_QueueItem] = deque()
    seen: set[str] = set()

    for seed in seeds:
        url = _normalize_url(seed.url)
        if url:
            queue.append(_QueueItem(url=url, depth=0, seed_category=seed.category))
    for root in BFS_ROOT_URLS:
        url = _normalize_url(root)
        if url:
            queue.append(_QueueItem(url=url, depth=0, seed_category=None))

    pages_fetched = 0
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": settings.crawl_user_agent},
    ) as client:
        while queue and pages_fetched < max_pages:
            if min_per_category and _all_categories_full(category_counts, categories, min_per_category):
                break
            item = queue.popleft()
            if item.url in seen:
                continue
            seen.add(item.url)

            if item.depth == 0 or item.url not in discovered:
                seed_hint = item.seed_category if item.depth == 0 else None
                classification = infer_categories_from_url(item.url, seed_category=seed_hint)
                if classification is not None:
                    if not categories or categories.intersection(classification.categories):
                        _add_discovered(
                            discovered,
                            category_counts,
                            item.url,
                            classification,
                            source_type="pdf" if _is_pdf(item.url) else "web",
                            seed_category=item.seed_category,
                        )

            if item.depth >= max_depth:
                continue

            try:
                html = await _fetch_text(client, item.url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("BFS fetch failed %s: %s", item.url, exc)
                continue
            pages_fetched += 1

            for link in extract_links(html, item.url):
                if link in seen:
                    continue
                classification = infer_categories_from_url(link)
                if classification is None:
                    continue
                if categories and not categories.intersection(classification.categories):
                    continue
                if link not in discovered:
                    _add_discovered(
                        discovered,
                        category_counts,
                        link,
                        classification,
                        source_type="pdf" if _is_pdf(link) else "web",
                        seed_category=item.seed_category,
                    )
                queue.append(
                    _QueueItem(
                        url=link,
                        depth=item.depth + 1,
                        seed_category=item.seed_category,
                    )
                )


async def _discover_from_pmc(
    categories: set[str] | None,
    discovered: dict[str, DiscoveredUrl],
    category_counts: Counter[str],
    *,
    min_per_category: int | None,
    max_per_category: int,
) -> None:
    """Top up under-filled categories with open-access PMC articles."""
    from rag import ANXIETY_SUBTYPES, CATEGORIES

    targets = categories if categories else set(CATEGORIES)
    deficits: dict[str, int] = {}
    for cat in sorted(targets):
        if min_per_category:
            missing = min_per_category - category_counts.get(cat, 0)
            if missing <= 0:
                continue
            deficits[cat] = min(max_per_category, int(missing * 1.2) + 10)
        else:
            deficits[cat] = max_per_category

    if not deficits:
        logger.info("PMC top-up skipped: all categories already at target")
        return

    pmc_keys: set[str] = set()
    for cat in deficits:
        if cat == "anxiety":
            pmc_keys.update(ANXIETY_SUBTYPES)
        else:
            pmc_keys.add(cat)

    per_cat_urls = await search_pmc_urls_by_category(
        pmc_keys,
        max_per_category=max(deficits.values()),
    )
    for cat, urls in per_cat_urls.items():
        is_anxiety_subtype = cat in ANXIETY_SUBTYPES
        top_level = "anxiety" if is_anxiety_subtype else cat
        budget = deficits.get(top_level, 0)
        if is_anxiety_subtype:
            budget = max(1, budget // len(ANXIETY_SUBTYPES))
        added = 0
        for raw in urls:
            if added >= budget:
                break
            url = _normalize_url(raw)
            if not url or url in discovered:
                continue
            _add_discovered(
                discovered,
                category_counts,
                url,
                Classification(
                    primary=top_level,
                    categories=(top_level,),
                    scores={top_level: 10.0},
                    anxiety_subtype=cat if is_anxiety_subtype else None,
                ),
                source_type="web",
                seed_category=cat if is_anxiety_subtype else cat,
                anxiety_subtype=cat if is_anxiety_subtype else None,
            )
            added += 1
        logger.info("PMC top-up: %s +%s URLs", cat, added)


def _all_categories_full(
    counts: Counter[str],
    categories: set[str] | None,
    target: int,
) -> bool:
    from rag import CATEGORIES

    targets = categories if categories else set(CATEGORIES)
    return all(counts.get(cat, 0) >= target for cat in targets)


def _add_discovered(
    discovered: dict[str, DiscoveredUrl],
    category_counts: Counter[str],
    url: str,
    classification: Classification,
    *,
    source_type: str,
    seed_category: str | None = None,
    anxiety_subtype: str | None = None,
) -> None:
    if url in discovered:
        existing = discovered[url]
        merged = tuple(dict.fromkeys((*existing.categories, *classification.categories)))
        discovered[url] = DiscoveredUrl(
            url=url,
            category=existing.category,
            source_type=existing.source_type,
            categories=merged,
            seed_category=existing.seed_category or seed_category,
            anxiety_subtype=existing.anxiety_subtype or anxiety_subtype or classification.anxiety_subtype,
        )
        for cat in merged:
            category_counts[cat] += 0
        return

    primary = classification.primary
    discovered[url] = DiscoveredUrl(
        url=url,
        category=primary,
        source_type=source_type,
        categories=classification.categories,
        seed_category=seed_category,
        anxiety_subtype=anxiety_subtype or classification.anxiety_subtype,
    )
    for cat in classification.categories:
        category_counts[cat] += 1


async def discover_urls(
    categories: list[str] | None = None,
    *,
    use_sitemaps: bool = True,
    use_bfs: bool = True,
    use_pmc: bool = True,
    limit: int | None = None,
    min_per_category: int | None = None,
    bfs_max_depth: int | None = None,
    bfs_max_pages: int | None = None,
) -> list[DiscoveredUrl]:
    """
    Build crawl list from seeds, optional sitemaps, allowlisted BFS, and an
    open-access PMC top-up for categories still below min_per_category.

    min_per_category: keep discovering until each category has at least this many
    labeled URLs (multi-label counts). Internally discovers ~1.3x that many so
    already-active skips and crawl failures do not leave categories short.
    """
    selected = set(categories) if categories else None
    discovered: dict[str, DiscoveredUrl] = {}
    category_counts: Counter[str] = Counter()
    # Headroom over the user-facing target (active skips + crawl/classify losses).
    discover_target = (
        int(min_per_category * 1.3) if min_per_category else None
    )

    for seed in seeds_for_categories(categories):
        url = _normalize_url(seed.url)
        if not url or not domain_allowed(url):
            continue
        hint = seed_hint_category(seed)
        classification = infer_categories_from_url(url, seed_category=hint)
        if classification is None:
            classification = Classification(
                primary=seed.category,
                categories=(seed.category,),
                scores={seed.category: 10.0},
                anxiety_subtype=seed.anxiety_subtype,
            )
        _add_discovered(
            discovered,
            category_counts,
            url,
            classification,
            source_type="pdf" if seed.source_type == "pdf" or _is_pdf(url) else "web",
            seed_category=hint,
            anxiety_subtype=seed.anxiety_subtype or classification.anxiety_subtype,
        )

    if use_sitemaps:
        await _discover_from_sitemaps(
            selected, discovered, category_counts, min_per_category=discover_target
        )

    if use_bfs:
        await _discover_from_bfs(
            selected,
            discovered,
            category_counts,
            seeds_for_categories(categories),
            min_per_category=discover_target,
            max_depth=bfs_max_depth or settings.discovery_bfs_max_depth,
            max_pages=bfs_max_pages or settings.discovery_bfs_max_pages,
        )

    if use_pmc:
        await _discover_from_pmc(
            selected,
            discovered,
            category_counts,
            min_per_category=discover_target,
            max_per_category=settings.pmc_max_per_category,
        )

    results = list(discovered.values())
    results.sort(key=lambda item: (item.category, item.url))

    filter_target = discover_target or min_per_category
    if filter_target and selected:
        results = _filter_for_min_per_category(results, selected, filter_target)
    elif filter_target:
        results = _filter_for_min_per_category(results, set(category_counts.keys()), filter_target)

    if limit is not None:
        results = results[: max(0, limit)]

    logger.info(
        "Discovered %s URLs for ingest (category label counts: %s%s)",
        len(results),
        dict(category_counts),
        f", discover_target={discover_target}" if discover_target else "",
    )
    return results


def _filter_for_min_per_category(
    results: list[DiscoveredUrl],
    categories: set[str],
    target: int,
) -> list[DiscoveredUrl]:
    """Prefer URLs that help under-filled categories reach target."""
    counts: Counter[str] = Counter()
    picked: list[DiscoveredUrl] = []
    for item in results:
        if all(counts.get(cat, 0) >= target for cat in categories):
            break
        needed = any(counts.get(cat, 0) < target for cat in item.categories if cat in categories)
        if needed or not categories.intersection(item.categories):
            picked.append(item)
            for cat in item.categories:
                if cat in categories:
                    counts[cat] += 1
    return picked


def save_discovered_urls(items: list[DiscoveredUrl], path: str | Path) -> Path:
    """Persist discovery results so ingest can skip rediscovery."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "url": item.url,
            "category": item.category,
            "source_type": item.source_type,
            "categories": list(item.categories or (item.category,)),
            "seed_category": item.seed_category,
        }
        for item in items
    ]
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote %s discovered URLs to %s", len(payload), out)
    return out


def load_discovered_urls(path: str | Path) -> list[DiscoveredUrl]:
    """Load a previously saved discovery list."""
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Discovered URL file not found: {src}")
    raw = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON list in {src}")
    items: list[DiscoveredUrl] = []
    for row in raw:
        cats = tuple(row.get("categories") or [row["category"]])
        items.append(
            DiscoveredUrl(
                url=str(row["url"]),
                category=str(row["category"]),
                source_type=str(row.get("source_type") or "web"),
                categories=cats,
                seed_category=row.get("seed_category"),
            )
        )
    logger.info("Loaded %s discovered URLs from %s", len(items), src)
    return items


__all__ = [
    "DEFAULT_DISCOVERED_PATH",
    "DiscoveredUrl",
    "discover_urls",
    "infer_category",
    "load_discovered_urls",
    "save_discovered_urls",
    "SeedSource",
]


if __name__ == "__main__":
    import sys

    from rag.ingest import main

    raise SystemExit(main(["--discover-only", *sys.argv[1:]]))
