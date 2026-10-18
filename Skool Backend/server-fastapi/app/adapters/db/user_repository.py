"""PostgreSQL UserRepository — implements ports.UserRepository."""
import asyncio

import asyncpg

from app.adapters.db.pool import record_to_dict
from app.adapters.db.sql import users_sql
from app.domain.filters import UserFilter


class PgUserRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_users(self, f: UserFilter) -> dict:
        where_sql, values, order_by = users_sql.compile_users(f)
        limit = f.pagination.page_size
        offset = (f.pagination.page - 1) * f.pagination.page_size
        sql = f"""
    SELECT {users_sql.USER_CARD_COLS}, COUNT(*) OVER() AS _total
    FROM skool.users u
    {where_sql}
    {order_by}
    LIMIT {limit} OFFSET {offset}
  """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *values)
        items = [record_to_dict(r) for r in rows]
        total = int(items[0]["_total"]) if items else 0
        for it in items:
            it.pop("_total", None)
        return {"items": items, "page": f.pagination.page,
                "page_size": f.pagination.page_size, "total": total}

    async def _fetch(self, sql: str, *params):
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql, *params)

    async def _fetch_one(self, sql: str, *params):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql, *params)

    async def get_user_full(self, user_id: str) -> tuple[dict | None, list[dict], list[dict]]:
        # Parallel via separate pooled connections — one connection cannot run
        # concurrent operations.
        user_row, owned, member = await asyncio.gather(
            self._fetch_one(users_sql.USER_FULL_SQL, user_id),
            self._fetch(users_sql.OWNED_SQL, user_id),
            self._fetch(users_sql.MEMBER_SQL, user_id),
        )
        if not user_row:
            return None, [], []
        return (
            record_to_dict(user_row),
            [record_to_dict(r) for r in owned],
            [record_to_dict(r) for r in member],
        )

    async def suggest_users(self, q: str) -> list[dict]:
        sql, params = users_sql.suggest_query(q)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "full_name": r["full_name"] or r["name"],
                "total_followers": r["total_followers"],
            }
            for r in rows
        ]

    async def exists(self, user_id: str) -> bool:
        sql = "SELECT 1 FROM skool.users WHERE id = $1"
        async with self._pool.acquire() as conn:
            return bool(await conn.fetchval(sql, user_id))

