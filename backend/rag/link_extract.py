"""Extract and normalize outbound links from HTML for allowlisted BFS discovery."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from rag.config_sources import domain_allowed, path_allowed, url_excluded

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)""", re.IGNORECASE)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value.strip())


def extract_links(html: str, base_url: str) -> list[str]:
    """Return normalized, allowlisted links found in HTML."""
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        for match in _HREF_RE.finditer(html):
            parser.links.append(match.group(1))

    seen: set[str] = set()
    results: list[str] = []
    for raw in parser.links:
        if not raw or raw.startswith(("mailto:", "javascript:", "tel:")):
            continue
        absolute = urljoin(base_url, raw)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        clean = parsed._replace(fragment="").geturl().rstrip("/")
        if not clean or clean in seen:
            continue
        if not domain_allowed(clean) or url_excluded(clean) or not path_allowed(clean):
            continue
        seen.add(clean)
        results.append(clean)
    return results
