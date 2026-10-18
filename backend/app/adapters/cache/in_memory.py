"""In-process TTL cache adapter (mirrors the Express module-level Maps).

Analytics additionally needs LRU-style eviction with a max entry count.
"""
import time
from collections import OrderedDict
from typing import Any


class InMemoryCache:
    """Simple TTL cache. `ttl_s` is passed per-set, matching the Express
    pattern of module constants (META_TTL_MS / ANALYTICS_TTL_MS)."""

    def __init__(self, max_entries: int = 1000) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._order: OrderedDict[str, None] = OrderedDict()
        self._max_entries = max_entries

    def get(self, key: str) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if time.monotonic() > expires_at:
            self._forget(key)
            return None
        return value

    def set(self, key: str, value: Any, ttl_s: int) -> None:
        while len(self._order) >= self._max_entries:
            oldest = next(iter(self._order), None)
            if oldest is None:
                break
            self._forget(oldest)
        self._store[key] = (time.monotonic() + ttl_s, value)
        self._order[key] = None

    def _forget(self, key: str) -> None:
        self._store.pop(key, None)
        self._order.pop(key, None)
