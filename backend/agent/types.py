"""Structured result from a single agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.pipeline_trace import PipelineTrace

_RETRIEVED_TEXT_KEYS = frozenset({"preview", "excerpt", "content", "text", "body"})


def strip_retrieved_text(value: Any) -> Any:
    """Drop raw retrieved snippet fields from a debug payload."""
    if isinstance(value, list):
        return [strip_retrieved_text(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key in _RETRIEVED_TEXT_KEYS:
            continue
        cleaned[key] = strip_retrieved_text(item)
    return cleaned


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
    communication_style: str | None = None
    pipeline: PipelineTrace | None = None

    def to_debug_dict(self, *, include_retrieved_text: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        if self.communication_style:
            payload["communication_style"] = self.communication_style
        if self.pipeline is not None:
            payload["pipeline"] = self.pipeline.to_dict()
        if include_retrieved_text:
            return payload
        return strip_retrieved_text(payload)

    def to_public_debug_dict(self) -> dict[str, Any]:
        """Metadata-only trace safe to return over HTTP."""
        return self.to_debug_dict(include_retrieved_text=False)
