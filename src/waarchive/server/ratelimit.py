"""Exponential backoff after repeated failures (in-memory, injectable clock)."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass

MAX_KEYS = 10_000


@dataclass
class _Entry:
    failures: int = 0
    locked_until: float = 0.0


class Backoff:
    def __init__(
        self, clock: Callable[[], float], *, free: int, base: float, maximum: float
    ) -> None:
        self._clock, self._free, self._base, self._max = clock, free, base, maximum
        self._e: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Seconds the caller must wait (0 = allowed)."""
        with self._lock:
            e = self._e.get(key)
            if not e:
                return 0
            return max(0, math.ceil(e.locked_until - self._clock()))

    def fail(self, key: str) -> None:
        with self._lock:
            if len(self._e) >= MAX_KEYS and key not in self._e:
                now = self._clock()
                self._e = {k: v for k, v in self._e.items() if v.locked_until > now}
            e = self._e.setdefault(key, _Entry())
            e.failures += 1
            over = e.failures - self._free
            if over > 0:
                delay = min(self._base * (2 ** (over - 1)), self._max)
                e.locked_until = self._clock() + delay

    def success(self, key: str) -> None:
        with self._lock:
            self._e.pop(key, None)
