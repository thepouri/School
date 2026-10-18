"""Group routes — thin driving adapters."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import require_account
from app.domain.filters import group_filter_from_params

router = APIRouter(prefix="/api", dependencies=[Depends(require_account)])


@router.get("/groups")
async def list_groups(request: Request):
    f = group_filter_from_params(request.query_params)
    return await request.app.state.container.group_service.list_groups(f)


@router.get("/groups/suggest")
async def suggest_groups(request: Request, q: str = Query(default="")):
    return await request.app.state.container.group_service.suggest(q)


@router.get("/groups/compare")
async def compare_groups(request: Request, ids: str = Query(default="")):
    return await request.app.state.container.group_service.compare_groups(ids)


@router.get("/groups/{group_id}")
async def get_group(group_id: str, request: Request):
    result = await request.app.state.container.group_service.get_group(group_id)
    if not result:
        return JSONResponse(status_code=404, content={"error": "Group not found"})
    return result
