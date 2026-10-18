"""User service — orchestration only."""
from app.domain import models
from app.domain.filters import UserFilter


class UserService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def list_users(self, f: UserFilter) -> dict:
        data = await self._repo.list_users(f)
        total = data["total"]
        page_size = data["page_size"]
        return {
            "items": [models.serialize_user_card(r) for r in data["items"]],
            "pagination": {
                "page": data["page"],
                "pageSize": page_size,
                "total": total,
                "totalPages": -(-total // page_size),
            },
        }

    async def get_user(self, user_id: str) -> dict | None:
        user_row, owned, member = await self._repo.get_user_full(user_id)
        if not user_row:
            return None
        return {
            "user": models.serialize_user_full(user_row),
            "ownedGroups": [models.serialize_group_card(r) for r in owned],
            "memberGroups": [models.serialize_group_card(r) for r in member],
            "ownedCount": len(owned),
            "memberCount": len(member),
        }

    async def suggest(self, q: str) -> list[dict]:
        q = (q or "").strip()[:60]
        return await self._repo.suggest_users(q)

    async def exists(self, user_id: str) -> bool:
        return await self._repo.exists(user_id)

