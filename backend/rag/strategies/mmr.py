from __future__ import annotations

from rag.retrieve import RetrievalPlan
from rag.strategies.base import StrategyConfig, StrategyResult
from rag.strategies.pipeline import run_strategy_pipeline

MMR_CONFIG = StrategyConfig(mmr_lambda=0.7)


class MmrStrategy:
    name = "mmr"

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
            config=MMR_CONFIG,
            rerank_mode="mmr",
            plan=plan,
        )
        return StrategyResult(plan=plan, chunks=chunks, metadata=meta)
