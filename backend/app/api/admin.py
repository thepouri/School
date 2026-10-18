"""Admin routes — account management + usage reports.

Guarded two-fold: valid token AND the account must be flagged admin
(app.accounts.is_admin). Bootstrap: the first created account via
`python -m app.cli create-admin ...` gets is_admin = true.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import require_account

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_account)])


async def _require_admin(request: Request):
    account = request.state.account
    auth_svc = request.app.state.container.auth_service
    if not await auth_svc.is_admin(account["id"]):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return None


@router.get("")
async def list_accounts(request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    return {"items": await request.app.state.container.admin_service.list_accounts()}


class CreateBody(BaseModel):
    email: str
    password: str
    label: str | None = None
    days: int = 30


@router.post("/accounts")
async def create_account(body: CreateBody, request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    row = await request.app.state.container.admin_service.create_account(
        body.email.strip(), body.password, body.label, max(1, min(body.days, 3650))
    )
    return row


class ExtendBody(BaseModel):
    days: int = 30


@router.post("/accounts/{account_id}/extend")
async def extend_account(account_id: int, body: ExtendBody, request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    row = await request.app.state.container.admin_service.extend_account(
        account_id, max(1, min(body.days, 3650))
    )
    if not row:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    return row


class ActiveBody(BaseModel):
    is_active: bool


@router.post("/accounts/{account_id}/active")
async def set_active(account_id: int, body: ActiveBody, request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    row = await request.app.state.container.admin_service.set_active(account_id, body.is_active)
    if not row:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    return row


class PasswordBody(BaseModel):
    password: str


@router.post("/accounts/{account_id}/password")
async def set_password(account_id: int, body: PasswordBody, request: Request):
    deny = await _require_admin(request)
    if deny:
        return deny
    await request.app.state.container.admin_service.set_password(account_id, body.password)
    return {"ok": True}


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, request: Request):
    """Hard delete — the account AND its usage_log rows are gone for good.
    Prefer POST /accounts/{id}/active {is_active:false} to just cut access."""
    deny = await _require_admin(request)
    if deny:
        return deny
    if account_id == request.state.account["id"]:
        return JSONResponse(status_code=400, content={"error": "Cannot delete your own account"})
    deleted = await request.app.state.container.admin_service.delete_account(account_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    return {"ok": True}


@router.get("/usage")
async def usage_summary(request: Request, From: str | None = None, to: str | None = None):
    """Per-account request counts. Optional from/to (YYYY-MM-DD), inclusive."""
    deny = await _require_admin(request)
    if deny:
        return deny
    return await request.app.state.container.admin_service.usage_summary(From, to)
