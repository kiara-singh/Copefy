from __future__ import annotations

from rag.retrieve import RetrievalPlan
from rag.strategies.base import StrategyConfig, StrategyResult
from rag.strategies.pipeline import run_strategy_pipeline

THRESHOLD_CONFIG = StrategyConfig(min_similarity=0.65)


class ThresholdStrategy:
    name = "threshold_0.65"

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
            config=THRESHOLD_CONFIG,
            rerank_mode="heuristic",
            plan=plan,
        )
        return StrategyResult(plan=plan, chunks=chunks, metadata=meta)
