"""Admin service — account management + usage reporting (no SQL, no HTTP)."""
from app.domain.models import _iso


class AdminService:
    def __init__(self, accounts, usage) -> None:
        self._accounts = accounts
        self._usage = usage

    async def list_accounts(self) -> list[dict]:
        rows = await self._accounts.list_accounts()
        for r in rows:
            r["expires_at"] = _iso(r.get("expires_at"))
            r["created_at"] = _iso(r.get("created_at"))
        return rows

    async def create_account(self, email: str, password: str, label: str | None, days: int):
        row = await self._accounts.create_account(email, password, label, days)
        return _shape(row)

    async def extend_account(self, account_id: int, days: int):
        row = await self._accounts.extend(account_id, days)
        return _shape(row)

    async def set_active(self, account_id: int, is_active: bool):
        row = await self._accounts.set_active(account_id, is_active)
        return _shape(row)

    async def set_password(self, account_id: int, password: str) -> None:
        await self._accounts.set_password(account_id, password)

    async def delete_account(self, account_id: int) -> bool:
        """Hard delete. Returns False when the id doesn't exist."""
        return await self._accounts.delete(account_id)

    async def usage_summary(self, from_: str | None, to: str | None) -> dict:
        out = await self._usage.admin_summary(from_, to)
        for d in out["daily"]:
            if hasattr(d.get("day"), "isoformat"):
                d["day"] = d["day"].isoformat()
        return out


def _shape(row: dict | None) -> dict | None:
    if not row:
        return None
    row["expires_at"] = _iso(row.get("expires_at"))
    row["created_at"] = _iso(row.get("created_at"))
    return row
