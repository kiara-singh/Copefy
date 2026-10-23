"""Download and parse public PDF documents from allowlisted URLs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from rag.config_sources import ALLOWED_DOMAINS

logger = logging.getLogger(__name__)

# Skip unusually large PDFs on the free tier / small DB plans.
MAX_PDF_BYTES = 15 * 1024 * 1024


@dataclass
class PdfParseResult:
    url: str
    title: str
    markdown: str
    ok: bool
    error: str | None = None


def _domain_allowed(url: str) -> bool:
    return urlparse(url).netloc.lower() in ALLOWED_DOMAINS


def _pdf_bytes_to_markdown(data: bytes, fallback_title: str) -> tuple[str, str]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        title = (doc.metadata or {}).get("title") or fallback_title
        parts: list[str] = []
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            parts.append(f"## Page {page_index}\n\n{text}")
        markdown = "\n\n".join(parts).strip()
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return title.strip(), markdown
    finally:
        doc.close()


async def parse_pdf_url(url: str) -> PdfParseResult:
    """Fetch a public PDF and extract text with PyMuPDF."""
    if not _domain_allowed(url):
        return PdfParseResult(
            url=url,
            title="",
            markdown="",
            ok=False,
            error=f"Domain not allowlisted: {urlparse(url).netloc}",
        )

    try:
        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "CopefyBot/0.1 (+https://copefy.local)"},
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        return PdfParseResult(
                            url=url,
                            title="",
                            markdown="",
                            ok=False,
                            error=f"PDF exceeds {MAX_PDF_BYTES} bytes",
                        )
                    chunks.append(chunk)
                data = b"".join(chunks)
    except Exception as exc:  # noqa: BLE001
        logger.error("PDF download failed for %s: %s", url, exc)
        return PdfParseResult(url=url, title="", markdown="", ok=False, error=str(exc))

    try:
        fallback = urlparse(url).path.rsplit("/", 1)[-1] or "document.pdf"
        title, markdown = _pdf_bytes_to_markdown(data, fallback)
        if not markdown:
            return PdfParseResult(
                url=url,
                title=title,
                markdown="",
                ok=False,
                error="No extractable text (possible scanned PDF)",
            )
        return PdfParseResult(url=url, title=title, markdown=markdown, ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("PDF parse failed for %s: %s", url, exc)
        return PdfParseResult(url=url, title="", markdown="", ok=False, error=str(exc))
