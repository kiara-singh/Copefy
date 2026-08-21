"""Retrieval strategy types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from rag.retrieve import RetrievalPlan, RetrievedChunk


@dataclass(frozen=True)
class StrategyConfig:
    match_count: int = 20
    top_k: int = 8
    inject_k: int = 3
    min_similarity: float | None = None
    mmr_lambda: float = 0.7


@dataclass
class StrategyResult:
    plan: RetrievalPlan
    chunks: list[RetrievedChunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalStrategy(Protocol):
    name: str

    async def retrieve(
        self,
        user_message: str,
        *,
        history: list[dict[str, str]] | None = None,
        plan: RetrievalPlan | None = None,
    ) -> StrategyResult: ...
