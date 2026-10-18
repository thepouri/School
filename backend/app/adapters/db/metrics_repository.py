"""PostgreSQL MetricsRepository — time-series from skool.group_metrics /
skool.user_metrics (snapshot tables written by the scraper).

Both series endpoints share semantics: explicit from/to narrow the window
(to inclusive-day); no params = full history, oldest first.
"""
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


class PgMetricsRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def group_series(self, group_id: str, from_: str | None, to: str | None) -> list[dict]:
        sql = """
            SELECT group_id, captured_at, price_usd, total_members,
                   total_online_members, total_posts, total_admins,
                   total_rules, num_courses, num_modules, afl_percent
            FROM skool.group_metrics
            WHERE group_id = $1 {window}
            ORDER BY captured_at
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _with_window(sql, bool(from_), bool(to)),
                group_id,
                *[_as_dt(p) for p in (from_, to) if p],
            )
        return [record_to_dict(r) for r in rows]

    async def user_series(self, user_id: str, from_: str | None, to: str | None) -> list[dict]:
        sql = """
            SELECT user_id, captured_at, total_followers, total_following,
                   total_contributions, owned_groups
            FROM skool.user_metrics
            WHERE user_id = $1 {window}
            ORDER BY captured_at
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _with_window(sql, bool(from_), bool(to)),
                user_id,
                *[_as_dt(p) for p in (from_, to) if p],
            )
        return [record_to_dict(r) for r in rows]


def _with_window(sql: str, has_from: bool, has_to: bool) -> str:
    conds, n = [], 1  # $1 is always entity id
    if has_from:
        conds.append(f"captured_at >= ${n + 1}")
        n += 1
    if has_to:
        conds.append(f"captured_at < ${n + 1}::timestamptz + interval '1 day'")
    window = f" AND {' AND '.join(conds)}" if conds else ""
    return sql.format(window=window)
