"""Gemini Google Search grounded generation for the web-search path."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.genai import types
from google.genai.errors import APIError

WEB_SEARCH_UNAVAILABLE_RESPONSE = (
    "I couldn't access live web results right now, so I don't want to give you "
    "an answer that might be outdated. Please try again in a moment."
)


@dataclass(frozen=True)
class GroundedSearchResult:
    response: str
    model: str
    sources: list[dict[str, Any]]


class WebSearchError(RuntimeError):
    """Raised when no configured model can produce a grounded web response."""


class WebSearchBudgetExceeded(WebSearchError):
    """Raised when the local monthly grounding budget circuit breaker is open."""


class MonthlyWebSearchBudget:
    """Persistently reserve conservative query units before grounded requests.

    SQLite's BEGIN IMMEDIATE transaction makes reservations atomic across local
    threads and worker processes. Attempts are reserved before the provider call
    and are not refunded, so failures cannot weaken the spend guard.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        monthly_query_budget: int,
        query_reservation: int,
    ) -> None:
        self.database_path = Path(database_path)
        self.monthly_query_budget = monthly_query_budget
        self.query_reservation = query_reservation

    def reserve(self, *, month: str | None = None) -> int:
        if self.monthly_query_budget <= 0 or self.query_reservation <= 0:
            raise WebSearchBudgetExceeded("Grounded web search is disabled by its budget")
        if self.query_reservation > self.monthly_query_budget:
            raise WebSearchBudgetExceeded("Grounded web search reservation exceeds its budget")

        usage_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monthly_web_search_usage (
                        month TEXT PRIMARY KEY,
                        reserved_queries INTEGER NOT NULL
                    )
                    """
                )
                row = connection.execute(
                    "SELECT reserved_queries FROM monthly_web_search_usage WHERE month = ?",
                    (usage_month,),
                ).fetchone()
                current = int(row[0]) if row else 0
                requested_total = current + self.query_reservation
                if requested_total > self.monthly_query_budget:
                    connection.rollback()
                    raise WebSearchBudgetExceeded(
                        "Grounded web search monthly safety budget reached"
                    )
                connection.execute(
                    """
                    INSERT INTO monthly_web_search_usage(month, reserved_queries)
                    VALUES (?, ?)
                    ON CONFLICT(month) DO UPDATE SET reserved_queries = excluded.reserved_queries
                    """,
                    (usage_month, requested_total),
                )
                connection.commit()
                return requested_total
        except WebSearchBudgetExceeded:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            # Fail closed: an unreadable counter must never reset spending to zero.
            raise WebSearchBudgetExceeded(
                "Grounded web search usage counter is unavailable"
            ) from exc


def extract_grounding_sources(response: Any) -> list[dict[str, Any]]:
    """Return de-duplicated web sources from Gemini grounding metadata."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return []

    metadata = getattr(candidates[0], "grounding_metadata", None)
    chunks = getattr(metadata, "grounding_chunks", None) or []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web is None and isinstance(chunk, dict):
            web = chunk.get("web")
        if web is None:
            continue

        if isinstance(web, dict):
            title = web.get("title")
            url = web.get("uri") or web.get("url")
        else:
            title = getattr(web, "title", None)
            url = getattr(web, "uri", None) or getattr(web, "url", None)

        title = str(title).strip() if title else None
        url = str(url).strip() if url else None
        if not url or not url.lower().startswith(("https://", "http://")):
            continue

        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "title": title,
                "source_url": url,
                "category": "web",
            }
        )

    return sources


def web_search(
    *,
    client: Any,
    model: str,
    query: str,
    prompt: str,
    system_instruction: str,
    usage_budget: MonthlyWebSearchBudget | None = None,
) -> GroundedSearchResult:
    """Generate one final answer using Gemini's native Google Search tool."""
    if usage_budget is not None:
        usage_budget.reserve()
    grounded_prompt = (
        f"{prompt}\n\n"
        "Use Google Search for current factual information needed to answer. "
        "Use one focused search query whenever possible.\n"
        f"Sanitized search intent: {query}\n"
        "Base time-sensitive claims on the grounded search results."
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
        max_output_tokens=1024,
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=grounded_prompt,
            config=config,
        )
    except APIError as exc:
        raise WebSearchError(
            f"Grounded web search unavailable ({model}:{exc.code})"
        ) from exc
    except Exception as exc:
        raise WebSearchError(
            f"Grounded web search unavailable ({model}:provider_error)"
        ) from exc

    text = (getattr(response, "text", None) or "").strip()
    sources = extract_grounding_sources(response)
    if text and sources:
        return GroundedSearchResult(response=text, model=model, sources=sources)
    raise WebSearchError(
        f"Grounded web search unavailable ({model}:missing_grounding)"
    )
