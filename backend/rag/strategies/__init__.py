"""Pluggable KB retrieval strategies for bake-off comparison."""

from __future__ import annotations

from rag.strategies.baseline import BaselineStrategy
from rag.strategies.mmr import MmrStrategy
from rag.strategies.threshold import ThresholdStrategy
from rag.strategies.wide_then_narrow import WideThenNarrowStrategy

STRATEGIES: dict[str, object] = {
    BaselineStrategy.name: BaselineStrategy(),
    ThresholdStrategy.name: ThresholdStrategy(),
    MmrStrategy.name: MmrStrategy(),
    WideThenNarrowStrategy.name: WideThenNarrowStrategy(),
}

DEFAULT_STRATEGY = MmrStrategy.name


def get_strategy(name: str):
    if name not in STRATEGIES:
        available = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown strategy {name!r}. Available: {available}")
    return STRATEGIES[name]


def strategy_names() -> list[str]:
    return sorted(STRATEGIES.keys())
