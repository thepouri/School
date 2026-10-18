"""Health service — domain orchestration for system health and readiness."""
from typing import Any, Callable, Coroutine


class HealthService:
    def __init__(self, check_db_fn: Callable[[], Coroutine[Any, Any, bool]]) -> None:
        self._check_db_fn = check_db_fn

    async def check_db(self) -> bool:
        try:
            return bool(await self._check_db_fn())
        except Exception:
            return False
