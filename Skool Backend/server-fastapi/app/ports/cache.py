"""Cache port — swap the in-memory adapter for Redis without touching services."""
from typing import Any, Protocol


class Cache(Protocol):
    def get(self, key: str) -> Any | None:
        """Return the cached value if present and fresh, else None."""
        ...

    def set(self, key: str, value: Any, ttl_s: int) -> None:
        ...
