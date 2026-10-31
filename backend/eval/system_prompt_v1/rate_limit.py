"""Shared request pacing for generation and judge calls."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class RequestRateLimiter:
    """Space all API request starts across one process-wide RPM budget."""

    requests_per_minute: float = 4.0
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    _next_allowed: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be greater than zero")

    @property
    def interval_seconds(self) -> float:
        return 60.0 / self.requests_per_minute

    def wait(self) -> None:
        now = self.clock()
        if self._next_allowed is not None and now < self._next_allowed:
            self.sleeper(self._next_allowed - now)
            now = self.clock()
        self._next_allowed = now + self.interval_seconds

    def defer(self, seconds: float) -> None:
        """Honor a server retry delay without bypassing the shared RPM gate."""
        deferred_until = self.clock() + max(0.0, seconds)
        if self._next_allowed is None or deferred_until > self._next_allowed:
            self._next_allowed = deferred_until
