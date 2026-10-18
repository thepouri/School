"""PostgreSQL AnalyticsRepository — 15 dataset queries in parallel."""
import asyncio

import asyncpg

from app.adapters.db.pool import record_to_dict
from app.adapters.db.sql import analytics_sql
from app.domain.filters import AnalyticsFilter


class PgAnalyticsRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _fetch(self, sql: str, *params):
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql, *params)

    async def _fetch_one(self, sql: str, *params):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql, *params)

    async def get_analytics(self, f: AnalyticsFilter) -> dict:
        queries = analytics_sql.build_all(f)
        results = await asyncio.gather(
            *(self._fetch_one(sql, *params) if name == "kpi" else self._fetch(sql, *params)
              for name, (sql, params) in queries.items())
        )
        out = {}
        for name, result in zip(queries.keys(), results):
            if name == "kpi":
                row = record_to_dict(result) if result else {}
                # ::int stays number, ::bigint comes back as string (node-pg
                # semantics via the int8 codec) — pass through untouched.
                out["kpi"] = row
            else:
                out[name] = [record_to_dict(r) for r in result]
        return out
