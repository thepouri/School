"""Metrics time-series routes — snapshot history for UI charts.

Both endpoints: optional from/to (YYYY-MM-DD, to inclusive). No params =
full history, oldest first.
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import require_account

router = APIRouter(prefix="/api/metrics", dependencies=[Depends(require_account)])


@router.get("/groups/{group_id}")
async def group_metrics(
    group_id: str,
    request: Request,
    From: str | None = Query(default=None, alias="from"),
    to: str | None = None,
):
    rows = await request.app.state.container.metrics_service.group_series(
        group_id, From, to
    )
    if not rows:
        # Distinguish "no such group ever captured" from "empty range":
        # cheap existence probe via domain service.
        exists = await request.app.state.container.group_service.exists(group_id)
        if not exists:
            return JSONResponse(status_code=404, content={"error": "Group not found"})
    return {"items": rows}


@router.get("/users/{user_id}")
async def user_metrics(
    user_id: str,
    request: Request,
    From: str | None = Query(default=None, alias="from"),
    to: str | None = None,
):
    rows = await request.app.state.container.metrics_service.user_series(
        user_id, From, to
    )
    if not rows:
        exists = await request.app.state.container.user_service.exists(user_id)
        if not exists:
            return JSONResponse(status_code=404, content={"error": "User not found"})
    return {"items": rows}

