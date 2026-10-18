"""Composition root — wiring only.

Lifespan creates/closes the asyncpg pool; routers are built against the
service container. No business logic lives here.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask, BackgroundTasks

from app.adapters.db.bootstrap import ensure_auth_schema
from app.adapters.cache.in_memory import InMemoryCache
from app.adapters.db.account_repository import PgAccountRepository
from app.adapters.db.analytics_repository import PgAnalyticsRepository
from app.adapters.db.group_repository import PgGroupRepository
from app.adapters.db.meta_repository import PgMetaRepository
from app.adapters.db.metrics_repository import PgMetricsRepository
from app.adapters.db.pool import create_pool
from app.adapters.db.usage_repository import PgUsageRepository
from app.adapters.db.user_repository import PgUserRepository
from app.api import admin, analytics, auth, groups, health, meta, metrics, users
from app.core.config import settings
from app.domain.services.analytics_service import AnalyticsService
from app.domain.services.auth_service import AuthService
from app.domain.services.group_service import GroupService
from app.domain.services.meta_service import MetaService
from app.domain.services.metrics_service import MetricsService
from app.domain.services.user_service import UserService

logger = logging.getLogger("skool")
logging.basicConfig(level=logging.INFO, format="%(message)s")

ensure_schema = ensure_auth_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await create_pool()
    app.state.pool = pool
    await ensure_schema(pool)
    from app.api.deps import Container
    container = Container()
    app.state.container = container

    cache = InMemoryCache(max_entries=1000)
    analytics_cache = InMemoryCache(max_entries=settings.analytics_cache_max)

    container.group_service = GroupService(PgGroupRepository(pool))
    container.user_service = UserService(PgUserRepository(pool))
    container.meta_service = MetaService(
        PgMetaRepository(pool), cache=cache, ttl_s=settings.meta_cache_ttl_s
    )
    container.analytics_service = AnalyticsService(
        PgAnalyticsRepository(pool), cache=analytics_cache, ttl_s=settings.analytics_cache_ttl_s
    )
    container.metrics_service = MetricsService(PgMetricsRepository(pool))
    accounts = PgAccountRepository(pool)
    usage = PgUsageRepository(pool)
    container.auth_service = AuthService(
        accounts, secret=settings.auth_jwt_secret, token_days=settings.auth_token_days
    )
    from app.domain.services.admin_service import AdminService
    from app.domain.services.usage_service import UsageService
    from app.domain.services.health_service import HealthService
    from app.adapters.db.pool import is_up
    container.admin_service = AdminService(accounts, usage)
    container.usage_service = UsageService(usage)
    container.health_service = HealthService(lambda: is_up(pool))

    logger.info(f"[server] API listening on http://localhost:{settings.port}")
    yield
    await pool.close()


app = FastAPI(title="Skool Explorer API", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)


async def _record_usage_bg(usage_service, account_id: int, path: str, status_code: int, duration_ms: int) -> None:
    """Execute usage logging in the background after response delivery."""
    try:
        if hasattr(usage_service, "record"):
            await usage_service.record(account_id, path, status_code, duration_ms)
        else:
            await usage_service._repo.record(account_id, path, status_code, duration_ms)
    except Exception as exc:  # never fail a request or background task over accounting
        logger.warning(f"[usage] background record failed: {type(exc).__name__}: {exc}")


@app.middleware("http")
async def cache_control_and_logging(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "public, max-age=15"
        logger.info(f"{request.method} {request.url.path} {response.status_code} {ms:.0f}ms")
        if ms > 500:
            logger.warning(f"slow query {request.url.path} {ms:.0f}ms")
        # Usage accounting: every authenticated /api call gets one row offloaded to BackgroundTask.
        account = getattr(request.state, "account", None)
        if account and request.url.path != "/api/health":
            usage = request.app.state.container.usage_service
            task = BackgroundTask(
                _record_usage_bg,
                usage,
                account["id"],
                request.url.path,
                response.status_code,
                int(ms),
            )
            if response.background is None:
                response.background = task
            elif isinstance(response.background, BackgroundTasks):
                response.background.tasks.append(task)
            else:
                response.background = BackgroundTasks([response.background, task])
    return response


# Closed by default (same-origin via vite proxy); explicit allowlist knob for
# future deploys.
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.error(f"[server] unhandled error {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


app.include_router(health.router)
app.include_router(meta.router)
app.include_router(groups.router)
app.include_router(users.router)
app.include_router(analytics.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(admin.router)
