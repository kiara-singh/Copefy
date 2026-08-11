from __future__ import annotations

from rag.retrieve import RetrievalPlan
from rag.strategies.base import StrategyConfig, StrategyResult
from rag.strategies.pipeline import run_strategy_pipeline

DEFAULT_CONFIG = StrategyConfig()


class BaselineStrategy:
    name = "baseline"

    async def retrieve(
        self,
        user_message: str,
        *,
        history: list[dict[str, str]] | None = None,
        plan: RetrievalPlan | None = None,
    ) -> StrategyResult:
        plan, chunks, meta = await run_strategy_pipeline(
            user_message,
            history=history,
            config=DEFAULT_CONFIG,
            rerank_mode="heuristic",
            plan=plan,
        )
        return StrategyResult(plan=plan, chunks=chunks, metadata=meta)
