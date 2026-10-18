"""Auth + own-usage routes (open: /api/auth/login; guarded: /api/me/*)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import require_account

router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def login(body: LoginBody, request: Request):
    try:
        return await request.app.state.container.auth_service.login(
            body.email, body.password
        )
    except Exception as exc:
        from app.domain.services.auth_service import AuthError
        if isinstance(exc, AuthError):
            return JSONResponse(status_code=401, content={"error": str(exc)})
        raise


@router.get("/me/usage", dependencies=[Depends(require_account)])
async def my_usage(request: Request):
    account = request.state.account
    return await request.app.state.container.usage_service.my_usage(account["id"])
