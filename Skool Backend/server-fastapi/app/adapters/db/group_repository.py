"""PostgreSQL GroupRepository — implements ports.GroupRepository."""
import asyncpg

from app.adapters.db.pool import record_to_dict
from app.adapters.db.sql import groups_sql
from app.domain.filters import GroupFilter


class PgGroupRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_groups(self, f: GroupFilter) -> dict:
        where_sql, values, order_by = groups_sql.compile_groups(f)
        limit = f.pagination.page_size
        offset = (f.pagination.page - 1) * f.pagination.page_size
        sql = f"""
    SELECT {groups_sql.GROUP_CARD_COLS}, COUNT(*) OVER() AS _total
    FROM skool.groups g
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

    async def get_group(self, group_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(groups_sql.DETAIL_SQL, group_id)
        return record_to_dict(row) if row else None

    async def get_groups_by_ids(self, ids: list[str]) -> list[dict]:
        sql = f"""
    SELECT {groups_sql.COMPARE_COLS}
    FROM skool.groups g
    WHERE g.id = ANY ($1)
  """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, ids)
        by_id = {r["id"]: record_to_dict(r) for r in rows}
        # Preserve caller's id order (ANY() returns arbitrary order).
        return [by_id[i] for i in ids if i in by_id]

    async def suggest_groups(self, q: str) -> list[dict]:
        sql, params = groups_sql.suggest_query(q)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "display_name": r["display_name"] or r["name"],
                "total_members": r["total_members"],
            }
            for r in rows
        ]

    async def exists(self, group_id: str) -> bool:
        sql = "SELECT 1 FROM skool.groups WHERE id = $1"
        async with self._pool.acquire() as conn:
            return bool(await conn.fetchval(sql, group_id))

