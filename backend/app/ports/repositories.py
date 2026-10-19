"""Repository ports — services depend on these Protocols only."""
from typing import Any, Protocol

from app.domain.filters import AnalyticsFilter, GroupFilter, UserFilter


class GroupRepository(Protocol):
    async def list_groups(self, f: GroupFilter) -> dict:
        """→ {items: [row dicts], page, page_size, total}"""
        ...

    async def get_group(self, group_id: str) -> dict | None:
        """Full detail row incl. R3 owner join aliases (u_id, u_name, …)."""
        ...

    async def get_groups_by_ids(self, ids: list[str]) -> list[dict]:
        ...

    async def suggest_groups(self, q: str) -> list[dict]:
        ...

    async def exists(self, group_id: str) -> bool:
        """True if the group row exists in skool.groups."""
        ...


class UserRepository(Protocol):
    async def list_users(self, f: UserFilter) -> dict:
        ...

    async def get_user_full(self, user_id: str) -> tuple[dict | None, list[dict], list[dict]]:
        """→ (user row, owned group rows, member group rows)"""
        ...

    async def suggest_users(self, q: str) -> list[dict]:
        ...

    async def exists(self, user_id: str) -> bool:
        """True if the user row exists in skool.users."""
        ...


class MetaRepository(Protocol):
    async def get_meta_raw(self) -> dict:
        """All 12 facet/bound queries assembled into one raw dict."""
        ...


class AnalyticsRepository(Protocol):
    async def get_analytics(self, f: AnalyticsFilter) -> dict:
        ...


class AccountRepository(Protocol):
    async def get_by_email(self, email: str) -> dict | None:
        ...

    async def get_by_id(self, account_id: int) -> dict | None:
        """Includes is_active + expires_at — the guard re-checks per request."""
        ...


class UsageRepository(Protocol):
    async def record(self, account_id: int, path: str, status: int, duration_ms: int) -> None:
        ...

    async def summary_for_account(self, account_id: int) -> list[dict]:
        """→ [{day, requests}] oldest-first for the caller's own usage chart."""
        ...

    async def admin_summary(self, from_: str | None, to: str | None) -> dict:
        """→ {totals:[{account_id,email,label,requests}], daily:[{day,account_id,email,requests}]}"""
        ...


class MetricsRepository(Protocol):
    async def group_series(self, group_id: str, from_: str | None, to: str | None) -> list[dict]:
        ...

    async def user_series(self, user_id: str, from_: str | None, to: str | None) -> list[dict]:
        ...


class ScraperRepository(Protocol):
    async def get_status(self) -> dict:
        ...

    async def get_settings(self) -> dict:
        ...

    async def update_settings(self, settings: dict) -> dict:
        ...

    async def enqueue_job(self, job_type: str, trigger_type: str = "manual") -> int:
        ...

    async def get_logs(self, limit: int = 50, job_id: int | None = None) -> list[dict]:
        ...

    async def get_active_job(self) -> dict | None:
        ...

    async def update_heartbeat(self) -> None:
        ...

    async def cancel_job(self, job_id: int) -> bool:
        ...

    async def export_data(self, include_metrics: bool = True) -> dict:
        ...

    async def import_data(self, data: dict) -> dict:
        ...


