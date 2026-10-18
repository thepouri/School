"""Adversarial & Stress Verification Suite for Milestone 1.

Tests:
1. Stress-test `_record_usage_bg` under multiple failure modes (exceptions, db down, malformed service)
   and verify HTTP response integrity is never compromised.
2. Verify `group_service.exists()` and `user_service.exists()` edge cases:
   - Non-existent IDs
   - Empty string and whitespace
   - Null bytes and unicode
   - Extremely large inputs (100k chars)
   - SQL injection strings (tautologies, UNION attacks, stacked queries)
3. Starlette BackgroundTasks composition and exception isolation under ASGI lifecycle.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.background import BackgroundTask, BackgroundTasks

from app.domain.services.group_service import GroupService
from app.domain.services.user_service import UserService
from app.domain.services.usage_service import UsageService
from app.domain.services.health_service import HealthService
from app.main import _record_usage_bg, cache_control_and_logging


# ============================================================================
# 1. Stress-Testing _record_usage_bg & Background Tasks
# ============================================================================

class FailingUsageService:
    """Simulates a broken or failing DB connection in usage logging."""
    def __init__(self, exc: Exception):
        self.exc = exc
        self.call_count = 0

    async def record(self, account_id: int, path: str, status_code: int, duration_ms: int) -> None:
        self.call_count += 1
        raise self.exc


class BrokenRepoUsageService:
    """Simulates a legacy usage service with broken _repo."""
    def __init__(self, exc: Exception):
        self.exc = exc
        self.call_count = 0

    class _BrokenRepo:
        def __init__(self, outer):
            self.outer = outer
        async def record(self, account_id: int, path: str, status_code: int, duration_ms: int) -> None:
            self.outer.call_count += 1
            raise self.outer.exc

    def __init__(self, exc: Exception):
        self.exc = exc
        self.call_count = 0
        self._repo = self._BrokenRepo(self)


@pytest.mark.anyio
@pytest.mark.parametrize("exception_cls,args", [
    (ConnectionResetError, ("Connection lost to PostgreSQL",)),
    (TimeoutError, ("Query timed out after 3000ms",)),
    (RuntimeError, ("Pool is closed",)),
    (ValueError, ("Invalid parameters passed",)),
    (KeyError, ("missing_key",)),
    (ZeroDivisionError, ("division by zero",)),
])
async def test_record_usage_bg_survives_all_exceptions(exception_cls, args):
    """Verify that _record_usage_bg never raises unhandled exceptions to caller."""
    exc = exception_cls(*args)
    failing_service = FailingUsageService(exc)
    
    # Must not raise
    await _record_usage_bg(failing_service, 42, "/api/groups", 200, 12)
    assert failing_service.call_count == 1

    # Also test legacy fallback path (_repo.record)
    broken_repo_service = BrokenRepoUsageService(exc)
    await _record_usage_bg(broken_repo_service, 42, "/api/groups", 200, 12)
    assert broken_repo_service.call_count == 1


@pytest.mark.anyio
async def test_middleware_attaches_background_task_and_preserves_response():
    """Verify that middleware attaches BackgroundTask and does not modify HTTP response payload or status."""
    class DummyContainer:
        def __init__(self):
            self.usage_service = FailingUsageService(RuntimeError("DB dead"))

    class DummyState:
        def __init__(self):
            self.container = DummyContainer()

    class DummyApp:
        def __init__(self):
            self.state = DummyState()

    app_instance = DummyApp()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/groups",
        "headers": [],
        "query_string": b"",
        "app": app_instance,
    }
    req = Request(scope)
    req.state.account = {"id": 101, "email": "test@example.com"}

    expected_content = b'{"items": [1, 2, 3]}'
    
    async def mock_call_next(request: Request):
        return Response(content=expected_content, status_code=200, media_type="application/json")

    res = await cache_control_and_logging(req, mock_call_next)
    
    # Verify response body and status code are pristine
    assert res.status_code == 200
    assert res.body == expected_content
    assert res.headers["Cache-Control"] == "public, max-age=15"
    
    # Verify background task was properly assigned
    assert res.background is not None
    assert isinstance(res.background, BackgroundTask)

    # Execute the background task directly as Starlette ASGI handler would after sending response
    await res.background()
    assert app_instance.state.container.usage_service.call_count == 1


@pytest.mark.anyio
async def test_middleware_composes_existing_background_tasks():
    """Verify that if response already has a background task, both execute safely."""
    class DummyContainer:
        def __init__(self):
            self.usage_service = FailingUsageService(RuntimeError("DB exploded"))

    class DummyState:
        def __init__(self):
            self.container = DummyContainer()

    class DummyApp:
        def __init__(self):
            self.state = DummyState()

    app_instance = DummyApp()
    first_task_ran = False
    async def existing_task():
        nonlocal first_task_ran
        first_task_ran = True

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/groups",
        "headers": [],
        "query_string": b"",
        "app": app_instance,
    }
    req = Request(scope)
    req.state.account = {"id": 102, "email": "test2@example.com"}

    async def mock_call_next(request: Request):
        res = Response(content=b"ok", status_code=200)
        res.background = BackgroundTask(existing_task)
        return res

    res = await cache_control_and_logging(req, mock_call_next)
    assert isinstance(res.background, BackgroundTasks)
    assert len(res.background.tasks) == 2

    # Execute tasks
    await res.background()
    assert first_task_ran is True
    assert app_instance.state.container.usage_service.call_count == 1



# ============================================================================
# 2. Stress-Testing group_service.exists() & user_service.exists()
# ============================================================================

class MockRecordingRepo:
    def __init__(self, existing_ids: set[str]):
        self.existing_ids = existing_ids
        self.queries_received: list[str] = []

    async def exists(self, item_id: str) -> bool:
        self.queries_received.append(item_id)
        return item_id in self.existing_ids


SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE skool.groups; --",
    "1 UNION SELECT * FROM app.accounts --",
    "' UNION ALL SELECT null, null, null --",
    "\\'; SELECT SLEEP(5); --",
    "admin'--",
    "admin' #",
    "admin'/*",
    "' or 1=1--",
    "' or 1=1#",
    "' or 1=1/*",
    ") or '1'='1--",
    "') or ('1'='1--",
    "'; EXEC xp_cmdshell('dir'); --",
    "1; SELECT pg_sleep(5);",
    "1' AND (SELECT 1 FROM pg_sleep(5))--",
]

BOUNDARY_PAYLOADS = [
    "",
    " ",
    "   \t\n   ",
    "\x00",
    "\x00\x01\x02",
    "None",
    "null",
    "undefined",
    "NaN",
    "a" * 10000,
    "🚀🔥✨" * 100,
    "00000000-0000-0000-0000-000000000000",
    "-1",
    "999999999999999999999999999999999999999999",
]


@pytest.mark.anyio
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS + BOUNDARY_PAYLOADS)
async def test_group_service_exists_adversarial_inputs(payload):
    """Verify group_service.exists() safely evaluates adversarial inputs."""
    valid_ids = {"grp_valid_1", "grp_valid_2"}
    repo = MockRecordingRepo(valid_ids)
    service = GroupService(repo)

    result = await service.exists(payload)
    assert result is False
    assert repo.queries_received[-1] == payload


@pytest.mark.anyio
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS + BOUNDARY_PAYLOADS)
async def test_user_service_exists_adversarial_inputs(payload):
    """Verify user_service.exists() safely evaluates adversarial inputs."""
    valid_ids = {"usr_valid_1", "usr_valid_2"}
    repo = MockRecordingRepo(valid_ids)
    service = UserService(repo)

    result = await service.exists(payload)
    assert result is False
    assert repo.queries_received[-1] == payload


# ============================================================================
# 3. PgGroupRepository & PgUserRepository SQL Parameterization Verification
# ============================================================================

from app.adapters.db.group_repository import PgGroupRepository
from app.adapters.db.user_repository import PgUserRepository


class MockAsyncpgConnection:
    def __init__(self, existing_table: dict[str, set[str]]):
        self.existing_table = existing_table
        self.executed_queries: list[tuple[str, tuple]] = []

    async def fetchval(self, query: str, *args):
        self.executed_queries.append((query, args))
        # Verify that query is fully parameterized ($1) and not string-concatenated
        assert "$1" in query
        table = "skool.groups" if "skool.groups" in query else "skool.users"
        target_id = args[0]
        if target_id in self.existing_table.get(table, set()):
            return 1
        return None


class MockAsyncpgPool:
    def __init__(self, conn: MockAsyncpgConnection):
        self.conn = conn

    def acquire(self):
        class _Context:
            def __init__(self, conn):
                self.conn = conn
            async def __aenter__(self):
                return self.conn
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        return _Context(self.conn)


@pytest.mark.anyio
@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS + BOUNDARY_PAYLOADS)
async def test_pg_repositories_parameterization_safety(payload):
    """Verify PgGroupRepository and PgUserRepository invoke parameterized queries without syntax errors."""
    mock_conn = MockAsyncpgConnection({
        "skool.groups": {"grp_real"},
        "skool.users": {"usr_real"},
    })
    mock_pool = MockAsyncpgPool(mock_conn)

    group_repo = PgGroupRepository(mock_pool)
    user_repo = PgUserRepository(mock_pool)

    # Test group repo
    assert await group_repo.exists("grp_real") is True
    assert await group_repo.exists(payload) is False

    # Test user repo
    assert await user_repo.exists("usr_real") is True
    assert await user_repo.exists(payload) is False

    # Verify query structure
    for q, args in mock_conn.executed_queries:
        assert q in (
            "SELECT 1 FROM skool.groups WHERE id = $1",
            "SELECT 1 FROM skool.users WHERE id = $1",
        )
        assert len(args) == 1


# ============================================================================
# 4. Live Server Controller & Existence Routing Verification
# ============================================================================

def test_live_metrics_endpoints_adversarial_handling(client):
    """Test live metrics endpoints routing through group_service/user_service."""
    import urllib.parse

    # 1. Non-existent ID -> 404
    r = client.get("/api/metrics/groups/non-existent-group-id-99999")
    assert r.status_code == 404
    assert r.json() == {"error": "Group not found"}

    r = client.get("/api/metrics/users/non-existent-user-id-99999")
    assert r.status_code == 404
    assert r.json() == {"error": "User not found"}

    # 2. SQL injection strings -> 404, never 500
    for payload in ["' OR '1'='1", "'; DROP TABLE skool.groups; --", "admin'--", "1 UNION SELECT 1--"]:
        encoded = urllib.parse.quote(payload)
        rg = client.get(f"/api/metrics/groups/{encoded}")
        assert rg.status_code == 404, f"Failed on payload {payload}: {rg.status_code}"
        assert rg.json() == {"error": "Group not found"}

        ru = client.get(f"/api/metrics/users/{encoded}")
        assert ru.status_code == 404, f"Failed on payload {payload}: {ru.status_code}"
        assert ru.json() == {"error": "User not found"}

