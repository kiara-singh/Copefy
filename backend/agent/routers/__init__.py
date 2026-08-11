"""Pluggable routers for the single 'which path?' decision."""

from __future__ import annotations

from agent.routers.ai import AIRouter
from agent.routers.base import Path, RouteDecision, Router
from agent.routers.rule import RuleRouter

ROUTERS: dict[str, Router] = {
    RuleRouter.name: RuleRouter(),
    AIRouter.name: AIRouter(),
}

DEFAULT_ROUTER = RuleRouter.name

__all__ = [
    "DEFAULT_ROUTER",
    "Path",
    "RouteDecision",
    "Router",
    "get_router",
    "router_names",
]


def get_router(name: str) -> Router:
    if name not in ROUTERS:
        available = ", ".join(sorted(ROUTERS))
        raise ValueError(f"Unknown router {name!r}. Available: {available}")
    return ROUTERS[name]


def router_names() -> list[str]:
    return sorted(ROUTERS.keys())
