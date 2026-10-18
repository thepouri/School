"""PostgreSQL MetaRepository — 12 queries in parallel (port of meta.js)."""
import asyncio

import asyncpg

from app.adapters.db.pool import record_to_dict
from app.adapters.db.sql import meta_sql


class PgMetaRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _fetch(self, sql: str):
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql)

    async def _fetch_one(self, sql: str):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql)

    async def get_meta_raw(self) -> dict:
        (
            categories, languages, price_buckets, visibility, locations,
            timezones, user_socials, group_socials, price_histogram,
            price_bounds, group_bounds, user_bounds,
        ) = await asyncio.gather(
            self._fetch(meta_sql.CATEGORIES_SQL),
            self._fetch(meta_sql.LANGUAGES_SQL),
            self._fetch(meta_sql.PRICE_BUCKETS_SQL),
            self._fetch(meta_sql.VISIBILITY_SQL),
            self._fetch(meta_sql.LOCATIONS_SQL),
            self._fetch(meta_sql.TIMEZONES_SQL),
            self._fetch(meta_sql.USER_SOCIALS_SQL),
            self._fetch(meta_sql.GROUP_SOCIALS_SQL),
            self._fetch(meta_sql.PRICE_HISTOGRAM_SQL),
            self._fetch_one(meta_sql.PRICE_BOUNDS_SQL),
            self._fetch_one(meta_sql.GROUP_BOUNDS_SQL),
            self._fetch_one(meta_sql.USER_BOUNDS_SQL),
        )

        pb = record_to_dict(price_bounds)
        gb = record_to_dict(group_bounds)
        ub = record_to_dict(user_bounds)

        return {
            "categories": [record_to_dict(r) for r in categories],
            "languages": [record_to_dict(r) for r in languages],
            "priceBuckets": [record_to_dict(r) for r in price_buckets],
            "visibility": [record_to_dict(r) for r in visibility],
            "locations": [record_to_dict(r) for r in locations],
            "timezones": [record_to_dict(r) for r in timezones],
            "priceHistogram": [record_to_dict(r) for r in price_histogram],
            "priceBounds": {
                "min": round(float(pb.get("min") or 1)),
                "max": round(float(pb.get("max") or 100000)),
                "p99": round(float(pb.get("p99") or 10000)),
            },
            "groupBounds": {
                "members": int(gb.get("max_members") or 100000),
                "posts": int(gb.get("max_posts") or 20000),
            },
            "userBounds": {
                "followers": int(ub.get("max_followers") or 100000),
                "following": int(ub.get("max_following") or 10000),
                "contributions": int(ub.get("max_contributions") or 10000),
            },
            "socials": {
                "users": [record_to_dict(r) for r in user_socials],
                "groups": [record_to_dict(r) for r in group_socials],
                "available": [r["value"] for r in user_socials],
            },
        }
