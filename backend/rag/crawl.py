"""HTML crawling via Crawl4AI with a cleaned httpx fallback."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Tags whose entire subtree is chrome / non-article content.
_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "iframe",
        "button",
    }
)

# Prefer these regions when present in the raw HTML.
_MAIN_PATTERNS = (
    re.compile(r"<main\b[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<article\b[^>]*>(.*?)</article>", re.IGNORECASE | re.DOTALL),
    re.compile(
        r'<div[^>]+(?:id|class)=["\'][^"\']*(?:main-content|page-content|content-area|usa-layout-docs__main|field--name-body)[^"\']*["\'][^>]*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    ),
)

# Drop leading site chrome once we hit a real article heading.
_CONTENT_START = re.compile(
    r"(?im)^(?:#{1,3}\s+)?(?:"
    r"what is |signs and symptoms|symptoms|overview|causes|"
    r"treatment|diagnosis|attention-deficit|depression|anxiety|"
    r"obsessive-compulsive|post-traumatic|panic disorder|phobia"
    r").{0,120}$"
)

_BOILERPLATE_LINE = re.compile(
    r"(?i)^(?:"
    r"skip to main content|an official website of the|"
    r"here(?:’|')s how you know|official websites use \.gov|"
    r"secure \.gov websites use https|share sensitive information|"
    r"in crisis\? call or text 988|search the .* website|"
    r"informaci[oó]n en espa[nñ]ol|transforming the understanding|"
    r"home\s*[|>]|mental health information|get involved|"
    r"news & events|about us|quick links|share page|"
    r"last reviewed:|disclaimer|policies and notices|"
    r"federal resources|contribute to mental health research|"
    r"nih websites are changing|beginning in late july|"
    r"find help and support|additional federal resources|"
    r"menu$|top$"
    r").*$"
)


@dataclass
class CrawlResult:
    url: str
    title: str
    markdown: str
    ok: bool
    error: str | None = None


class _HTMLTextExtractor(HTMLParser):
    """HTML -> text extractor that skips nav/chrome tags."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        self._in_heading: str | None = None

    def _attrs_look_like_chrome(self, attrs: list[tuple[str, str | None]]) -> bool:
        attr_map = {k.lower(): (v or "").lower() for k, v in attrs}
        role = attr_map.get("role", "")
        class_id = f"{attr_map.get('class', '')} {attr_map.get('id', '')}"
        if role in {"navigation", "banner", "contentinfo", "search"}:
            return True
        return any(
            token in class_id
            for token in (
                "nav",
                "menu",
                "footer",
                "header",
                "breadcrumb",
                "sidebar",
                "social-share",
                "cookie",
                "usa-banner",
                "usa-nav",
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in _SKIP_TAGS or self._attrs_look_like_chrome(attrs):
            self._skip_depth = 1
            return
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2", "h3", "h4"}:
            self._in_heading = tag
            self._chunks.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in {"h1", "h2", "h3", "h4"}:
            self._in_heading = None
            self._chunks.append("\n")
        if tag in {"p", "div", "br", "li", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = text
            return
        if self._in_heading:
            level = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}[self._in_heading]
            self._chunks.append(f"{level} {text}\n")
            return
        self._chunks.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _extract_main_html(html: str) -> str:
    """Return the most likely article HTML fragment."""
    best = ""
    for pattern in _MAIN_PATTERNS:
        match = pattern.search(html)
        if match and len(match.group(1)) > len(best):
            best = match.group(1)
    return best or html


def _strip_boilerplate(text: str) -> str:
    """Remove gov/site chrome lines and keep the article body when possible."""
    lines = [line.strip() for line in text.splitlines()]
    kept: list[str] = []
    for line in lines:
        if not line:
            kept.append("")
            continue
        if _BOILERPLATE_LINE.match(line):
            continue
        # Drop pure nav link dumps (many short Title Case tokens).
        if line.count(" ") >= 8 and sum(1 for w in line.split() if w[:1].isupper()) > 10:
            if len(line) < 220 and "?" not in line and "." not in line:
                continue
        kept.append(line)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # If we can find a real content heading, drop everything before it.
    start_idx = None
    for match in _CONTENT_START.finditer(cleaned):
        start_idx = match.start()
        break
    if start_idx is not None and start_idx > 0:
        # Keep a nearby title line if present just above.
        prefix = cleaned[:start_idx].rstrip()
        title_line = ""
        for line in reversed(prefix.splitlines()):
            if line.strip():
                title_line = line.strip()
                break
        body = cleaned[start_idx:].strip()
        if title_line and not _BOILERPLATE_LINE.match(title_line):
            cleaned = f"{title_line}\n\n{body}"
        else:
            cleaned = body

    return cleaned.strip()


def _clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_boilerplate(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _crawl_with_crawl4ai(url: str) -> CrawlResult:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

    config = CrawlerRunConfig(
        word_count_threshold=50,
        exclude_external_links=True,
        process_iframes=False,
        remove_overlay_elements=True,
    )
    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(url=url, config=config)

    if not result or not getattr(result, "success", False):
        err = getattr(result, "error_message", None) or "Crawl4AI returned unsuccessful result"
        return CrawlResult(url=url, title="", markdown="", ok=False, error=str(err))

    markdown = getattr(result, "markdown", None) or ""
    if hasattr(markdown, "raw_markdown"):
        markdown = markdown.raw_markdown or ""
    # Prefer fit_markdown / main content when Crawl4AI provides it.
    for attr in ("fit_markdown", "markdown_with_citations"):
        candidate = getattr(result, attr, None)
        if candidate and str(candidate).strip() and len(str(candidate)) < len(str(markdown)):
            markdown = candidate
            break

    title = ""
    metadata = getattr(result, "metadata", None) or {}
    if isinstance(metadata, dict):
        title = str(metadata.get("title") or "")
    cleaned = _clean_markdown(str(markdown))
    return CrawlResult(
        url=url,
        title=title.strip(),
        markdown=cleaned,
        ok=bool(cleaned),
        error=None if cleaned else "Empty markdown from Crawl4AI",
    )


async def _crawl_with_httpx(url: str) -> CrawlResult:
    async with httpx.AsyncClient(
        timeout=45.0,
        follow_redirects=True,
        headers={"User-Agent": "CopefyBot/0.1 (+https://copefy.local)"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        main_html = _extract_main_html(response.text)
        parser = _HTMLTextExtractor()
        parser.feed(main_html)
        text = _clean_markdown(parser.get_text())
        return CrawlResult(
            url=url,
            title=parser.title.strip(),
            markdown=text,
            ok=bool(text),
            error=None if text else "Empty text from HTML fallback",
        )


async def crawl_url(url: str) -> CrawlResult:
    """Crawl a single HTML page. Prefer Crawl4AI; fall back to cleaned httpx HTML."""
    primary: CrawlResult | None = None
    try:
        primary = await _crawl_with_crawl4ai(url)
        if primary.ok and primary.markdown.strip():
            return primary
        logger.warning(
            "Crawl4AI returned empty/unsuccessful for %s (%s); trying fallback",
            url,
            primary.error or "empty markdown",
        )
    except ImportError:
        logger.warning("crawl4ai not installed; using httpx HTML fallback for %s", url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Crawl4AI failed for %s (%s); trying fallback", url, exc)

    try:
        fallback = await _crawl_with_httpx(url)
        if fallback.ok:
            return fallback
        if primary is not None and not primary.ok:
            return primary
        return fallback
    except Exception as exc:  # noqa: BLE001
        logger.error("HTML crawl failed for %s: %s", url, exc)
        if primary is not None:
            return primary
        return CrawlResult(url=url, title="", markdown="", ok=False, error=str(exc))


async def crawl_urls(
    urls: list[str],
    *,
    concurrency: int = 2,
    delay_seconds: float = 1.0,
) -> list[CrawlResult]:
    """Crawl many URLs with bounded concurrency and a polite delay."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[CrawlResult] = []

    async def _one(target: str) -> CrawlResult:
        async with semaphore:
            result = await crawl_url(target)
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            return result

    tasks = [asyncio.create_task(_one(url)) for url in urls]
    for task in asyncio.as_completed(tasks):
        results.append(await task)
    return results
