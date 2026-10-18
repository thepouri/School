"""Usage service — a customer's own request history."""
from app.domain.models import _iso


class UsageService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, account_id: int, path: str, status_code: int, latency_ms: int
    ) -> None:
        await self._repo.record(account_id, path, status_code, latency_ms)

    async def my_usage(self, account_id: int) -> dict:
        daily = await self._repo.summary_for_account(account_id)
        for d in daily:
            if hasattr(d.get("day"), "isoformat"):
                d["day"] = d["day"].isoformat()
        total = sum(d["requests"] for d in daily)
        return {"window_days": 30, "total": total, "daily": daily}
