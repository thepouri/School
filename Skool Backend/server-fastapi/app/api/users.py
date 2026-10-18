"""User routes — thin driving adapters."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import require_account
from app.domain.filters import user_filter_from_params

router = APIRouter(prefix="/api", dependencies=[Depends(require_account)])


@router.get("/users")
async def list_users(request: Request):
    f = user_filter_from_params(request.query_params)
    return await request.app.state.container.user_service.list_users(f)


@router.get("/users/suggest")
async def suggest_users(request: Request, q: str = Query(default="")):
    return await request.app.state.container.user_service.suggest(q)


@router.get("/users/{user_id}")
async def get_user(user_id: str, request: Request):
    result = await request.app.state.container.user_service.get_user(user_id)
    if not result:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    return result
