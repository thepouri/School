"""PostgreSQL UsageRepository — per-user request accounting."""
from datetime import datetime, timezone

import asyncpg

from app.adapters.db.pool import record_to_dict


def _as_dt(s: str) -> datetime:
    """YYYY-MM-DD (or ISO datetime) → aware datetime for asyncpg."""
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


class PgUsageRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(self, account_id: int, path: str, status: int, duration_ms: int) -> None:
        sql = """
            INSERT INTO app.usage_log (account_id, path, status, duration_ms)
            VALUES ($1, $2, $3, $4)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql, account_id, path[:255], status, duration_ms)

    async def summary_for_account(self, account_id: int) -> list[dict]:
        sql = """
            SELECT date_trunc('day', created_at)::date AS day,
                   count(*)::int AS requests
            FROM app.usage_log
            WHERE account_id = $1 AND created_at > now() - interval '30 days'
            GROUP BY 1 ORDER BY 1
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, account_id)
        return [record_to_dict(r) for r in rows]

    async def admin_summary(self, from_: str | None, to: str | None) -> dict:
        """Per-account totals + per-account-per-day series.

        Window defaults to all history; explicit dates narrow it
        (to is inclusive-day via < to+1).
        """
        conds, values = [], []
        if from_:
            values.append(_as_dt(from_))
            conds.append(f"u.created_at >= ${len(values)}")
        if to:
            values.append(_as_dt(to))
            conds.append(f"u.created_at < ${len(values)}::timestamptz + interval '1 day'")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""

        totals_sql = f"""
            SELECT u.account_id, a.email, coalesce(a.label, '') AS label,
                   count(*)::int AS requests
            FROM app.usage_log u
            JOIN app.accounts a ON a.id = u.account_id
            {where}
            GROUP BY 1, 2, 3 ORDER BY requests DESC
        """
        daily_sql = f"""
            SELECT date_trunc('day', u.created_at)::date AS day,
                   u.account_id, a.email,
                   count(*)::int AS requests
            FROM app.usage_log u
            JOIN app.accounts a ON a.id = u.account_id
            {where}
            GROUP BY 1, 2, 3 ORDER BY 1
        """
        async with self._pool.acquire() as conn:
            totals = await conn.fetch(totals_sql, *values)
            daily = await conn.fetch(daily_sql, *values)
        return {
            "totals": [record_to_dict(r) for r in totals],
            "daily": [record_to_dict(r) for r in daily],
        }
