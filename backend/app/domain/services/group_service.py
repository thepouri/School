"""Group service — orchestration only, no SQL, no HTTP types."""
from app.domain import models
from app.domain.filters import GroupFilter
from app.domain.pricing import estimate_revenue  # noqa: F401  (pricing single-source)


class GroupService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def list_groups(self, f: GroupFilter) -> dict:
        data = await self._repo.list_groups(f)
        total = data["total"]
        page_size = data["page_size"]
        return {
            "items": [models.serialize_group_card(r) for r in data["items"]],
            "pagination": {
                "page": data["page"],
                "pageSize": page_size,
                "total": total,
                "totalPages": -(-total // page_size),  # ceil
            },
        }

    async def get_group(self, group_id: str) -> dict | None:
        row = await self._repo.get_group(group_id)
        if not row:
            return None
        return models.serialize_group_detail(row)

    # Keys absent from Express compare responses entirely: the leaner SELECT
    # doesn't fetch them AND serializeGroup has no `|| null` line for them,
    # so JSON.stringify drops them. (logo_big_url/favicon_url/updated_at DO
    # appear as null — serializeGroup emits them unconditionally.)
    _COMPARE_ABSENT = frozenset({
        "membership_model",
        "total_online_members", "total_admins", "total_rules",
        "num_modules", "afl_percent", "category_id",
    })

    async def compare_groups(self, ids_param: str) -> list[dict]:
        ids = [s.strip() for s in (ids_param or "").split(",") if s.strip()][:12]
        if not ids:
            return []
        rows = await self._repo.get_groups_by_ids(ids)
        out = []
        for r in rows:
            d = models.serialize_group_detail(r)
            for k in self._COMPARE_ABSENT:
                d.pop(k, None)
            out.append(d)
        return out

    async def suggest(self, q: str) -> list[dict]:
        q = (q or "").strip()[:60]
        return await self._repo.suggest_groups(q)

    async def exists(self, group_id: str) -> bool:
        return await self._repo.exists(group_id)

