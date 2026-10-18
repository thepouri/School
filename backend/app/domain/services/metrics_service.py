"""Metrics service — time-series for UI charts."""
from app.domain.models import _iso


def _clean(v: str | None) -> str | None:
    return v or None


class MetricsService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def group_series(self, group_id: str, from_: str | None, to: str | None) -> list[dict]:
        rows = await self._repo.group_series(group_id, _clean(from_), _clean(to))
        for r in rows:
            r["captured_at"] = _iso(r.get("captured_at"))
        return rows

    async def user_series(self, user_id: str, from_: str | None, to: str | None) -> list[dict]:
        rows = await self._repo.user_series(user_id, _clean(from_), _clean(to))
        for r in rows:
            r["captured_at"] = _iso(r.get("captured_at"))
        return rows
