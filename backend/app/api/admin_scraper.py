"""Admin scraper routes — scraper daemon monitoring, manual execution triggers, logs, settings.

Guarded: Bearer token via require_account + admin privilege verification.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import require_account

router = APIRouter(prefix="/api/admin/scraper", dependencies=[Depends(require_account)])


async def _require_admin(request: Request):
    account = request.state.account
    auth_svc = request.app.state.container.auth_service
    if not await auth_svc.is_admin(account["id"]):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return None


@router.get("/status")
async def get_status(request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    svc = request.app.state.container.scraper_service
    return await svc.get_status()


class TriggerBody(BaseModel):
    mode: str = Field(..., description="Job execution mode: refresh, discovery, all, or missing_owners")


@router.post("/trigger")
async def trigger_job(body: TriggerBody, request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    svc = request.app.state.container.scraper_service
    try:
        return await svc.trigger_job(body.mode)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@router.get("/logs")
async def get_logs(request: Request, limit: int = 50, job_id: int | None = None):
    deny = await _require_admin(request)
    if deny:
        return deny
    svc = request.app.state.container.scraper_service
    return await svc.get_logs(limit=limit, job_id=job_id)


@router.get("/settings")
async def get_settings(request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    svc = request.app.state.container.scraper_service
    return await svc.get_settings()


class SettingsBody(BaseModel):
    refresh_interval_days: int = Field(..., gt=0, le=3650, description="Interval in days between group refreshes")
    discovery_interval_days: int = Field(..., gt=0, le=3650, description="Interval in days between discovery runs")
    is_paused: bool = Field(False, description="Pause all automatic scraping schedules")


@router.post("/settings")
async def update_settings(body: SettingsBody, request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    svc = request.app.state.container.scraper_service
    try:
        return await svc.update_settings(body.model_dump())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
