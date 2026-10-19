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
        dicts = [record_to_dict(r) for r in rows]
        return _dedupe_group_series(dicts)

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
        dicts = [record_to_dict(r) for r in rows]
        return _dedupe_user_series(dicts)


def _dedupe_group_series(rows: list[dict]) -> list[dict]:
    if len(rows) <= 1:
        return rows
    deduped = []
    prev = None
    for r in rows:
        if prev is None:
            deduped.append(r)
            prev = r
            continue
        dt_curr = r.get("captured_at")
        dt_prev = prev.get("captured_at")
        same_day = False
        if dt_curr and dt_prev:
            same_day = (str(dt_curr)[:10] == str(dt_prev)[:10])

        changed = (
            r.get("total_members") != prev.get("total_members")
            or r.get("total_online_members") != prev.get("total_online_members")
            or r.get("total_posts") != prev.get("total_posts")
            or r.get("price_usd") != prev.get("price_usd")
        )
        if same_day and not changed:
            continue
        deduped.append(r)
        prev = r
    return deduped


def _dedupe_user_series(rows: list[dict]) -> list[dict]:
    if len(rows) <= 1:
        return rows
    deduped = []
    prev = None
    for r in rows:
        if prev is None:
            deduped.append(r)
            prev = r
            continue
        dt_curr = r.get("captured_at")
        dt_prev = prev.get("captured_at")
        same_day = False
        if dt_curr and dt_prev:
            same_day = (str(dt_curr)[:10] == str(dt_prev)[:10])

        changed = (
            r.get("total_followers") != prev.get("total_followers")
            or r.get("total_following") != prev.get("total_following")
            or r.get("total_contributions") != prev.get("total_contributions")
            or r.get("owned_groups") != prev.get("owned_groups")
        )
        if same_day and not changed:
            continue
        deduped.append(r)
        prev = r
    return deduped


def _with_window(sql: str, has_from: bool, has_to: bool) -> str:
    conds, n = [], 1  # $1 is always entity id
    if has_from:
        conds.append(f"captured_at >= ${n + 1}")
        n += 1
    if has_to:
        conds.append(f"captured_at < ${n + 1}::timestamptz + interval '1 day'")
    window = f" AND {' AND '.join(conds)}" if conds else ""
    return sql.format(window=window)
