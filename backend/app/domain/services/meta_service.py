"""Meta service — cached 300s, single assembled object."""
from app.adapters.db.sql import meta_sql


class MetaService:
    def __init__(self, repo, cache, ttl_s: int = 300) -> None:
        self._repo = repo
        self._cache = cache
        self._ttl = ttl_s

    async def get_meta(self) -> dict:
        cached = self._cache.get("meta")
        if cached is not None:
            return cached
        raw = await self._repo.get_meta_raw()
        result = {
            "categories": raw["categories"],
            "languages": raw["languages"],
            "priceBuckets": raw["priceBuckets"],
            "visibility": raw["visibility"],
            "locations": raw["locations"],
            "timezones": raw["timezones"],
            "socials": raw["socials"],
            "priceHistogram": raw["priceHistogram"],
            "priceBounds": raw["priceBounds"],
            "groupBounds": raw["groupBounds"],
            "userBounds": raw["userBounds"],
            "groupSorts": meta_sql.GROUP_SORT_OPTIONS,
            "userSorts": meta_sql.USER_SORT_OPTIONS,
        }
        self._cache.set("meta", result, self._ttl)
        return result
