"""Router types: the single 'which path?' decision every strategy must produce."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Path(str, Enum):
    CRISIS = "crisis"
    DIRECT_ANSWER = "direct_answer"
    SEARCH_DATABASE = "search_database"
    WEB_SEARCH = "web_search"
    STRUCTURED_QUERY = "structured_query"
    DOCUMENT_EXTRACTION = "document_extraction"


PATH_VALUES = tuple(path.value for path in Path)


@dataclass(frozen=True)
class RouteDecision:
    """One routing decision plus whatever the chosen path needs to execute."""

    path: Path
    reason: str
    router: str = ""
    # SEARCH_DATABASE only.
    search_query: str = ""
    categories: tuple[str, ...] = ()
    corpus: str | None = None
    # WEB_SEARCH only: a sanitized factual query, never the user's raw message.
    web_query: str = ""

    @property
    def searches_database(self) -> bool:
        return self.path is Path.SEARCH_DATABASE


class Router(Protocol):
    name: str

    async def decide(
        self,
        message: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> RouteDecision: ...
