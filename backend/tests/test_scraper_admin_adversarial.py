"""Adversarial stress and edge-case tests for Scraper Admin API and PgScraperRepository.

Validates:
1. Malicious mode injections (SQL injection, shell injection, path traversal, XSS, whitespace)
2. Normalization of valid mixed-case modes
3. Concurrency / race conditions on simultaneous triggers
4. Boundary intervals (0, negative, non-int)
5. EMPIRICAL VULNERABILITY: Timedelta overflow and Postgres int32 overflow on unbounded intervals
6. Logs clamping and edge-case query parameters
7. Auth guard security & RBAC enforcement
8. Direct live PostgreSQL repository integration & EMPIRICAL CONTRACT BUG: String vs Int ID mismatch
"""
import asyncio
from datetime import datetime, timedelta, timezone
import pytest
import httpx

from app.main import app
from app.api.deps import Container
from app.domain.services.scraper_service import ScraperService
from app.adapters.db.pool import create_pool
from app.adapters.db.scraper_repository import PgScraperRepository
from app.adapters.db.bootstrap import ensure_auth_schema


class MockRepo:
    def __init__(self):
        self.counter = 100
        self.enqueued = []
        self.settings = {
            "refresh_interval_days": 3,
            "discovery_interval_days": 7,
            "refresh_cron": "0 2 */3 * *",
            "discovery_cron": "0 3 * * 0",
            "is_paused": False,
        }
        self.heartbeat = None
        self.active_job = None
        self.logs = []

    async def get_status(self) -> dict:
        now = datetime.now(timezone.utc)
        ref_int = self.settings["refresh_interval_days"]
        disc_int = self.settings["discovery_interval_days"]

        # Replicates repository timedelta arithmetic
        next_ref = (now + timedelta(days=ref_int)).isoformat()
        next_disc = (now + timedelta(days=disc_int)).isoformat()

        hb = self.heartbeat
        if hb:
            delta = (now - hb).total_seconds()
            daemon_status = "RUNNING" if delta <= 45.0 else "STOPPED"
            hb_iso = hb.isoformat()
        else:
            daemon_status = "STOPPED"
            hb_iso = None

        return {
            "daemon": {
                "status": daemon_status,
                "last_heartbeat": hb_iso,
                "is_paused": self.settings["is_paused"],
            },
            "schedules": {
                "refresh": {
                    "interval_days": ref_int,
                    "cron": self.settings["refresh_cron"],
                    "last_run": None,
                    "next_run": next_ref,
                },
                "discovery": {
                    "interval_days": disc_int,
                    "cron": self.settings["discovery_cron"],
                    "last_run": None,
                    "next_run": next_disc,
                },
            },
            "stats": {"total_groups": 100, "pending_details": 5, "pending_owners": 2},
            "active_job": self.active_job,
        }

    async def get_settings(self) -> dict:
        return dict(self.settings)

    async def update_settings(self, settings_data: dict) -> dict:
        self.settings.update(settings_data)
        return dict(self.settings)

    async def enqueue_job(self, job_type: str, trigger_type: str = "manual") -> int:
        self.counter += 1
        job_id = self.counter
        self.enqueued.append({"id": job_id, "job_type": job_type, "trigger_type": trigger_type})
        return job_id

    async def get_logs(self, limit: int = 50, job_id: int | None = None) -> list[dict]:
        if job_id is not None:
            return [l for l in self.logs if l["job_id"] == job_id][:limit]
        return self.logs[:limit]

    async def get_active_job(self) -> dict | None:
        return self.active_job

    async def update_heartbeat(self) -> None:
        self.heartbeat = datetime.now(timezone.utc)


class MockAuthService:
    def __init__(self):
        self.admin = {"id": 1, "email": "admin@skool.local", "is_admin": True, "is_active": True}
        self.user = {"id": 2, "email": "user@skool.local", "is_admin": False, "is_active": True}

    async def resolve(self, token: str) -> dict | None:
        if token == "admin_secret":
            return self.admin
        elif token == "user_secret":
            return self.user
        return None

    async def is_admin(self, account_id: int) -> bool:
        return account_id == 1


ADMIN_HEADERS = {"Authorization": "Bearer admin_secret"}
USER_HEADERS = {"Authorization": "Bearer user_secret"}


@pytest.fixture
def mock_app():
    if not hasattr(app.state, "container") or app.state.container is None:
        app.state.container = Container()
    repo = MockRepo()
    app.state.container.scraper_service = ScraperService(repo)
    app.state.container.auth_service = MockAuthService()
    yield repo
    app.state.container = None


# =========================================================================
# 1. Adversarial Trigger Mode Tests
# =========================================================================

@pytest.mark.anyio
@pytest.mark.parametrize("malicious_mode", [
    "",
    "   ",
    "DROP TABLE skool.scraper_jobs;--",
    "refresh' OR 1=1;--",
    "../../etc/passwd",
    "../../../../windows/system32/cmd.exe",
    "<script>alert('xss')</script>",
    "refresh\x00injection",
    "refresh\nrm -rf /",
    "invalid_mode_name",
    "REFRESH_ALL",
    "delete",
    "purge",
    "123",
])
async def test_trigger_malicious_and_invalid_modes(mock_app, malicious_mode):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/api/admin/scraper/trigger",
            json={"mode": malicious_mode},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 400
        data = r.json()
        assert "error" in data
        assert "Invalid mode" in data["error"]


@pytest.mark.anyio
@pytest.mark.parametrize("valid_mixed_case", [
    ("REFRESH", "refresh"),
    ("Discovery", "discovery"),
    ("ALL", "all"),
    ("Missing_Owners", "missing_owners"),
    ("  refresh  ", "refresh"),
])
async def test_trigger_valid_mixed_case_normalized(mock_app, valid_mixed_case):
    input_mode, expected_mode = valid_mixed_case
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/api/admin/scraper/trigger",
            json={"mode": input_mode},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["mode"] == expected_mode
        assert "job_id" in data


@pytest.mark.anyio
@pytest.mark.parametrize("bad_payload", [
    {},
    {"mode": None},
    {"mode": 12345},
    {"mode": True},
    {"mode": ["refresh"]},
    {"mode": {"nested": "refresh"}},
])
async def test_trigger_bad_types(mock_app, bad_payload):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/api/admin/scraper/trigger",
            json=bad_payload,
            headers=ADMIN_HEADERS,
        )
        assert r.status_code in (400, 422)


# =========================================================================
# 2. Boundary Intervals & Vulnerability Reproductions
# =========================================================================

@pytest.mark.anyio
@pytest.mark.parametrize("invalid_interval_body", [
    {"refresh_interval_days": 0, "discovery_interval_days": 7},
    {"refresh_interval_days": -1, "discovery_interval_days": 7},
    {"refresh_interval_days": -999999, "discovery_interval_days": 7},
    {"refresh_interval_days": 3651, "discovery_interval_days": 7},
    {"refresh_interval_days": 3, "discovery_interval_days": 0},
    {"refresh_interval_days": 3, "discovery_interval_days": -5},
    {"refresh_interval_days": 3, "discovery_interval_days": 3651},
    {"refresh_interval_days": "zero", "discovery_interval_days": 7},
    {"refresh_interval_days": None, "discovery_interval_days": 7},
    {"discovery_interval_days": 7},
    {"refresh_interval_days": 3},
])
async def test_settings_invalid_boundaries(mock_app, invalid_interval_body):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/api/admin/scraper/settings",
            json=invalid_interval_body,
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 422


@pytest.mark.anyio
async def test_settings_huge_interval_overflow_vulnerability(mock_app):
    """Stress test: verifies that huge interval is rejected with 422, preventing OverflowError DoS."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Settings endpoint now rejects 10,000,000 with 422 Unprocessable Entity
        r = await client.post(
            "/api/admin/scraper/settings",
            json={"refresh_interval_days": 10_000_000, "discovery_interval_days": 7, "is_paused": False},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 422

        # Status endpoint continues functioning normally without OverflowError
        r_status = await client.get("/api/admin/scraper/status", headers=ADMIN_HEADERS)
        assert r_status.status_code == 200
        assert r_status.json()["daemon"]["status"] in ("RUNNING", "STOPPED")


@pytest.mark.anyio
async def test_settings_minimum_positive_interval(mock_app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/api/admin/scraper/settings",
            json={"refresh_interval_days": 1, "discovery_interval_days": 1, "is_paused": True},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["settings"]["refresh_interval_days"] == 1
        assert data["settings"]["discovery_interval_days"] == 1
        assert data["settings"]["is_paused"] is True


# =========================================================================
# 3. Concurrency Stress: Concurrent Job Triggers
# =========================================================================

@pytest.mark.anyio
async def test_concurrent_trigger_race_conditions(mock_app):
    """Stress test: 25 concurrent requests triggering jobs simultaneously."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        modes = ["refresh", "discovery", "all", "missing_owners", "refresh"] * 5
        tasks = [
            client.post("/api/admin/scraper/trigger", json={"mode": m}, headers=ADMIN_HEADERS)
            for m in modes
        ]
        responses = await asyncio.gather(*tasks)

        job_ids = []
        for r in responses:
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "queued"
            job_ids.append(data["job_id"])

        assert len(job_ids) == len(set(job_ids))
        assert len(job_ids) == 25


# =========================================================================
# 4. Logs Endpoint Edge Cases & Clamping
# =========================================================================

@pytest.mark.anyio
@pytest.mark.parametrize("limit_val", [0, -1, -100, 500, 99999])
async def test_logs_limit_clamping(mock_app, limit_val):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get(f"/api/admin/scraper/logs?limit={limit_val}", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data


@pytest.mark.anyio
@pytest.mark.parametrize("bad_limit", ["abc", "null", "3.14"])
async def test_logs_bad_limit_type(mock_app, bad_limit):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get(f"/api/admin/scraper/logs?limit={bad_limit}", headers=ADMIN_HEADERS)
        assert r.status_code == 422


@pytest.mark.anyio
async def test_logs_non_existent_job_id(mock_app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/admin/scraper/logs?job_id=9999999", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json() == {"items": []}


@pytest.mark.anyio
@pytest.mark.parametrize("adversarial_job_id", [
    0,
    -1,
    -999999,
    9_223_372_036_854_775_808,
    99_999_999_999_999_999_999_999_999_999,
])
async def test_logs_adversarial_job_id_sanitization(mock_app, adversarial_job_id):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get(f"/api/admin/scraper/logs?job_id={adversarial_job_id}", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json() == {"items": []}


# =========================================================================
# 5. Security & Auth Bypass Attempts
# =========================================================================

@pytest.mark.anyio
@pytest.mark.parametrize("bad_auth", [
    {},
    {"Authorization": ""},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Bearer invalid_token"},
    {"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="},
    {"Authorization": "Token admin_secret"},
])
async def test_auth_rejection(mock_app, bad_auth):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/admin/scraper/status", headers=bad_auth)
        assert r.status_code == 401


@pytest.mark.anyio
async def test_non_admin_forbidden_on_all_endpoints(mock_app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/api/admin/scraper/status", headers=USER_HEADERS)).status_code == 403
        assert (await client.post("/api/admin/scraper/trigger", json={"mode": "refresh"}, headers=USER_HEADERS)).status_code == 403
        assert (await client.get("/api/admin/scraper/logs", headers=USER_HEADERS)).status_code == 403
        assert (await client.get("/api/admin/scraper/settings", headers=USER_HEADERS)).status_code == 403
        assert (await client.post("/api/admin/scraper/settings", json={"refresh_interval_days": 3, "discovery_interval_days": 7}, headers=USER_HEADERS)).status_code == 403


@pytest.mark.anyio
async def test_query_param_token_auth(mock_app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r_admin = await client.get("/api/admin/scraper/status?token=admin_secret")
        assert r_admin.status_code == 200

        r_user = await client.get("/api/admin/scraper/status?token=user_secret")
        assert r_user.status_code == 403


# =========================================================================
# 6. Live PostgreSQL PgScraperRepository Integration & Empirical Findings
# =========================================================================

@pytest.mark.anyio
async def test_live_pg_scraper_repository_and_id_type_inspection():
    """Verify PgScraperRepository directly against PostgreSQL and identify type discrepancies."""
    pool = await create_pool()
    await ensure_auth_schema(pool)
    repo = PgScraperRepository(pool)

    job_id = None
    try:
        # 1. get_status
        status = await repo.get_status()
        assert "daemon" in status
        assert "schedules" in status
        assert "stats" in status

        # 2. update_heartbeat
        await repo.update_heartbeat()
        status_after_hb = await repo.get_status()
        assert status_after_hb["daemon"]["status"] == "RUNNING"
        assert status_after_hb["daemon"]["last_heartbeat"] is not None

        # 3. enqueue_job
        job_id = await repo.enqueue_job("refresh", trigger_type="manual")
        assert isinstance(job_id, int)
        assert job_id > 0

        # 4. Insert log line
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO skool.scraper_logs (job_id, level, message) VALUES ($1, 'INFO', 'Test log line 1')",
                job_id,
            )

        # 5. get_logs: verify that job_id and log id are strictly normalized to int
        logs = await repo.get_logs(limit=10, job_id=job_id)
        assert len(logs) == 1
        item = logs[0]
        assert item["job_id"] == job_id
        assert isinstance(item["job_id"], int)
        assert isinstance(item["id"], int)
        assert len(item["lines"]) == 1
        assert item["lines"][0]["message"] == "Test log line 1"
        assert item["lines"][0]["job_id"] == job_id
        assert isinstance(item["lines"][0]["job_id"], int)
        assert isinstance(item["lines"][0]["id"], int)

        # 5b. Verify active_job id normalization to int
        async with pool.acquire() as conn:
            await conn.execute("UPDATE skool.scraper_jobs SET status = 'RUNNING', started_at = NOW() WHERE id = $1", job_id)
        running_job = await repo.get_active_job()
        assert running_job is not None
        assert running_job["id"] == job_id
        assert isinstance(running_job["id"], int)

        status_running = await repo.get_status()
        assert status_running["active_job"] is not None
        assert status_running["active_job"]["id"] == job_id
        assert isinstance(status_running["active_job"]["id"], int)

        # 6. update_settings
        updated = await repo.update_settings({
            "refresh_interval_days": 5,
            "discovery_interval_days": 12,
            "is_paused": True,
        })
        assert updated["refresh_interval_days"] == 5
        assert updated["discovery_interval_days"] == 12
        assert updated["is_paused"] is True

        # Restore defaults
        await repo.update_settings({
            "refresh_interval_days": 3,
            "discovery_interval_days": 7,
            "is_paused": False,
        })
    finally:
        if job_id:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM skool.scraper_jobs WHERE id = $1", job_id)
        await pool.close()


@pytest.mark.anyio
async def test_live_pg_scraper_int32_overflow():
    """Empirical test: check what happens when integer > 2147483647 is passed to PgScraperRepository.update_settings."""
    pool = await create_pool()
    repo = PgScraperRepository(pool)
    try:
        import asyncpg
        with pytest.raises((asyncpg.exceptions.NumericValueOutOfRangeError, asyncpg.exceptions.DataError)):
            await repo.update_settings({"refresh_interval_days": 9_999_999_999})
    finally:
        await pool.close()


@pytest.mark.anyio
async def test_live_pg_scraper_job_id_bigint_overflow():
    """Empirical test: job_id exceeding 64-bit bigint raises NumericValueOutOfRangeError in PostgreSQL."""
    pool = await create_pool()
    repo = PgScraperRepository(pool)
    try:
        import asyncpg
        with pytest.raises((asyncpg.exceptions.NumericValueOutOfRangeError, asyncpg.exceptions.DataError)):
            await repo.get_logs(limit=10, job_id=99999999999999999999999999999)
    finally:
        await pool.close()
