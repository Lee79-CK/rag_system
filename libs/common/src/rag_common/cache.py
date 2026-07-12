"""TTL 캐시 — Binding 캐시(60s, §7.1.1 step4) 등에 사용.

PEP 695 제네릭 문법 사용 (§3.2). monotonic 시계 주입 가능(테스트).
"""

from __future__ import annotations

import time
from collections.abc import Callable


class TTLCache[K, V]:
    """단순 in-process TTL 캐시. 프로세스 로컬(멀티 replica 간 공유 아님)."""

    def __init__(self, ttl_seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._store: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if self._clock() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: K, value: V) -> None:
        self._store[key] = (self._clock() + self._ttl, value)

    def invalidate(self, key: K) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
