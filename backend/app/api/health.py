"""Health route — intentionally unauthenticated (uptime probes)."""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
async def health(request: Request):
    db_up = await request.app.state.container.health_service.check_db()
    return {"status": "ok", "db": "up" if db_up else "down"}

