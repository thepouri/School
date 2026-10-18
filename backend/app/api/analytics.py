"""Analytics route (guarded)."""
from fastapi import APIRouter, Depends, Request

from app.api.deps import require_account

router = APIRouter(prefix="/api", dependencies=[Depends(require_account)])


@router.get("/analytics")
async def get_analytics(request: Request):
    return await request.app.state.container.analytics_service.get_analytics(
        request.query_params
    )
