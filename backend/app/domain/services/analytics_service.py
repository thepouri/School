"""Analytics service — cached 120s per query-string, LRU ≤50 entries."""
from app.domain.filters import analytics_filter_from_params


class AnalyticsService:
    def __init__(self, repo, cache, ttl_s: int = 120) -> None:
        self._repo = repo
        self._cache = cache
        self._ttl = ttl_s

    async def get_analytics(self, params) -> dict:
        # QueryParams (starlette) has no urlencode; str() gives sorted key=value form.
        try:
            key = f"analytics:{params.urlencode()}"
        except AttributeError:
            key = f"analytics:{str(params)}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        f = analytics_filter_from_params(params)
        result = await self._repo.get_analytics(f)
        self._cache.set(key, result, self._ttl)
        return result
