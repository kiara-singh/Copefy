"""Structured result from a single agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    response: str
    path: str
    router: str
    route_reason: str
    kb_used: bool = False
    categories: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    search_query: str | None = None
    model: str | None = None
    tool_status: str | None = None

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "router": self.router,
            "route_reason": self.route_reason,
            "tools_used": self.tools_used,
            "kb_used": self.kb_used,
            "search_query": self.search_query,
            "categories": self.categories,
            "model": self.model,
            "tool_status": self.tool_status,
            "chunk_count": len(self.sources),
            "sources": self.sources,
        }
