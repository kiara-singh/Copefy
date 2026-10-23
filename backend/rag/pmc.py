"""Open-access PMC article discovery via NCBI E-utilities (free, no key).

Used to top up categories that consumer health sites cannot fill to the
per-category document target (phobias, panic_disorder, social_anxiety).
Only discovery happens here; crawling and embedding stay in the normal
ingest pipeline.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from rag.config_sources import PMC_SEARCH_TERMS

logger = logging.getLogger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
# NCBI allows 3 req/s without an API key; stay politely under that.
_REQUEST_DELAY_SECONDS = 0.4
# esearch caps retmax at 10000; our per-category needs are far lower.
_RETMAX_CAP = 10000


def pmc_article_url(pmcid: str) -> str:
    """Canonical article URL on the allowlisted www.ncbi.nlm.nih.gov host."""
    return f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}"


async def _esearch_pmc_ids(
    client: httpx.AsyncClient,
    term: str,
    *,
    retmax: int,
) -> list[str]:
    params = {
        "db": "pmc",
        "term": f'"{term}" AND open access[filter]',
        "retmode": "json",
        "retmax": str(min(retmax, _RETMAX_CAP)),
        "sort": "relevance",
        "tool": "copefy-rag",
    }
    response = await client.get(_ESEARCH_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    ids = payload.get("esearchresult", {}).get("idlist", [])
    return [str(i) for i in ids if str(i).isdigit()]


async def search_pmc_urls_by_category(
    categories: set[str] | None,
    *,
    max_per_category: int,
) -> dict[str, list[str]]:
    """
    Return {category: [article urls]} from open-access PMC.

    Runs one esearch per configured phrase, deduplicates PMCIDs per category,
    and caps the result list at max_per_category.
    """
    selected = {c for c in PMC_SEARCH_TERMS if categories is None or c in categories}
    results: dict[str, list[str]] = {}
    if not selected or max_per_category <= 0:
        return results

    async with httpx.AsyncClient(timeout=30.0) as client:
        for category in sorted(selected):
            seen: set[str] = set()
            urls: list[str] = []
            for term in PMC_SEARCH_TERMS[category]:
                if len(urls) >= max_per_category:
                    break
                try:
                    ids = await _esearch_pmc_ids(
                        client,
                        term,
                        retmax=max_per_category,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("PMC search failed for %r: %s", term, exc)
                    continue
                for pmcid in ids:
                    if pmcid in seen:
                        continue
                    seen.add(pmcid)
                    urls.append(pmc_article_url(pmcid))
                    if len(urls) >= max_per_category:
                        break
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)
            results[category] = urls
            logger.info("PMC discovery: %s -> %s article URLs", category, len(urls))
    return results


__all__ = ["pmc_article_url", "search_pmc_urls_by_category"]
