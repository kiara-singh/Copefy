"""Cross-layer pipeline trace for manual debugging (Layers 1–4)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LayerStep:
    layer: int
    name: str
    decision: str
    details: dict[str, Any] = field(default_factory=dict)
    ms: float = 0.0


@dataclass
class PipelineTrace:
    layers: list[LayerStep] = field(default_factory=list)

    def add_timed(
        self,
        layer: int,
        name: str,
        decision: str,
        started: float,
        **details: Any,
    ) -> None:
        ms = round((time.perf_counter() - started) * 1000, 1)
        self.layers.append(
            LayerStep(layer=layer, name=name, decision=decision, details=details, ms=ms)
        )

    @property
    def total_ms(self) -> float:
        return round(sum(step.ms for step in self.layers), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_ms": self.total_ms,
            "layers": [
                {
                    "layer": step.layer,
                    "name": step.name,
                    "decision": step.decision,
                    **step.details,
                    "ms": step.ms,
                }
                for step in self.layers
            ],
        }

    def log_to_terminal(self) -> None:
        # print() so lines show under uvicorn; logger.info alone often does not.
        for step in self.layers:
            extra = self._format_step(step)
            line = (
                f"[pipeline] L{step.layer} {step.name} → {step.decision} "
                f"{extra} [{step.ms}ms]"
            )
            print(line, flush=True)
            logger.info(line)
        total = f"[pipeline] total {self.total_ms}ms"
        print(total, flush=True)
        logger.info(total)

    @staticmethod
    def _format_step(step: LayerStep) -> str:
        if step.name == "routing":
            router = step.details.get("router", "?")
            reason = step.details.get("reason", "")
            return f"({router}) — {reason}" if reason else f"({router})"
        if step.name == "corpus":
            return f"— {step.details.get('reason', '')}"
        if step.name == "retrieval":
            cats = step.details.get("categories") or []
            cat_str = ", ".join(cats) if cats else "none"
            candidates = step.details.get("candidates", 0)
            returned = step.details.get("returned", 0)
            top = step.details.get("top_similarity")
            top_str = f" | top={top}" if top is not None else ""
            return f"| {step.details.get('strategy', '?')} | {cat_str} | {candidates}→{returned} chunks{top_str}"
        if step.name == "generation":
            style = step.details.get("communication_style", "?")
            model = step.details.get("model", "?")
            turns = step.details.get("history_turns", 0)
            return f"| {style} | {model} | {turns} history turns"
        return ""
