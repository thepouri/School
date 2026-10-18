"""Request-scoped DI accessors + auth guard dependency.

The guard is the single gate in front of /api/*: Bearer token → fresh
account lookup → 401 on missing/invalid/expired/disabled.
"""
from fastapi import HTTPException, Request

from app.domain.services.auth_service import AuthService


class Container:
    group_service = None
    user_service = None
    meta_service = None
    analytics_service = None
    metrics_service = None
    auth_service: AuthService | None = None
    admin_service = None
    usage_service = None
    health_service = None

    async def is_healthy(self) -> bool:
        if self.health_service:
            return await self.health_service.check_db()
        return False


container = Container()


def get_auth(request: Request) -> AuthService:
    return request.app.state.container.auth_service


async def require_account(request: Request) -> dict:
    """FastAPI dependency — resolves the caller or raises a JSON 401."""
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        token = request.query_params.get("token", "") or ""
    account = await get_auth(request).resolve(token) if token else None
    if not account:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Stash for the usage middleware to record against.
    request.state.account = account
    return account
