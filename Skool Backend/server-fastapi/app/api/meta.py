"""Meta route — cached 300s."""
from fastapi import APIRouter, Depends, Request

from app.api.deps import require_account

router = APIRouter(prefix="/api", dependencies=[Depends(require_account)])


@router.get("/meta")
async def get_meta(request: Request):
    return await request.app.state.container.meta_service.get_meta()
