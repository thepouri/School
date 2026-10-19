"""Empirical Challenger Verification Test Suite for Milestone M5 Round 2.

Authoritative checks requested by Orchestrator:
1. POST /api/admin/scraper/settings with huge interval days returns HTTP 422 Unprocessable Entity.
2. GET /api/admin/scraper/status never crashes with OverflowError.
3. GET /api/admin/scraper/logs returns integer IDs ("id": 1, "job_id": 101) rather than strings.
4. GET /api/admin/scraper/logs?job_id=999999999999999999999999999 safely returns HTTP 200 with {"items": []} without crashing PostgreSQL.
"""
from datetime import datetime, timezone
import pytest
import httpx

from app.adapters.db.pool import create_pool
from app.adapters.db.bootstrap import ensure_auth_schema
from app.adapters.db.scraper_repository import PgScraperRepository
from app.api.deps import Container
from app.domain.services.scraper_service import ScraperService
from app.main import app

ADMIN_HEADERS = {"Authorization": "Bearer admin_secret"}


class MockScraperRepo:
    """Mock repository matching ScraperRepository protocol with BigInt simulation."""

    def __init__(self):
        self.settings = {
            "refresh_interval_days": 3,
            "discovery_interval_days": 7,
            "refresh_cron": "0 2 */3 * *",
            "discovery_cron": "0 3 * * 0",
            "is_paused": False,
            "daemon_heartbeat_at": datetime.now(timezone.utc),
        }
        self.jobs = [
            {
                "id": 101,  # Normalized integer
                "job_type": "refresh",
                "trigger_type": "manual",
                "status": "SUCCESS",
                "started_at": datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc),
                "finished_at": datetime(2026, 10, 18, 12, 5, 0, tzinfo=timezone.utc),
                "created_at": datetime(2026, 10, 18, 11, 59, 0, tzinfo=timezone.utc),
                "exit_code": 0,
                "error_message": None,
                "lines": [
                    {
                        "id": 1,  # Normalized integer
                        "job_id": 101,  # Normalized integer
                        "level": "INFO",
                        "message": "Harvest started",
                        "created_at": "2026-10-18T12:00:01+00:00",
                    }
                ],
            }
        ]

    async def get_status(self):
        return {
            "daemon": {"status": "RUNNING", "last_heartbeat": self.settings["daemon_heartbeat_at"].isoformat(), "is_paused": False},
            "schedules": {
                "refresh": {"interval_days": self.settings["refresh_interval_days"], "cron": "0 2 */3 * *", "last_run": None, "next_run": "2026-10-21T00:00:00Z"},
                "discovery": {"interval_days": self.settings["discovery_interval_days"], "cron": "0 3 * * 0", "last_run": None, "next_run": "2026-10-25T00:00:00Z"},
            },
            "stats": {"total_groups": 100, "pending_details": 5, "pending_owners": 2},
            "active_job": None,
        }

    async def update_heartbeat(self):
        self.settings["daemon_heartbeat_at"] = datetime.now(timezone.utc)

    async def enqueue_job(self, mode: str, trigger_type: str = "manual") -> int:
        new_id = len(self.jobs) + 101
        self.jobs.append({
            "id": new_id,
            "job_type": mode,
            "trigger_type": trigger_type,
            "status": "PENDING",
            "started_at": None,
            "finished_at": None,
            "created_at": datetime.now(timezone.utc),
            "exit_code": None,
            "error_message": None,
            "lines": [],
        })
        return new_id

    async def get_logs(self, limit: int = 50, job_id: int | None = None):
        res = []
        for j in self.jobs:
            if job_id is not None and j["id"] != job_id:
                continue
            item = dict(j)
            item["id"] = int(item["id"])
            item["job_id"] = int(item["id"])
            item["started_at"] = item["started_at"].isoformat() if item["started_at"] else None
            item["finished_at"] = item["finished_at"].isoformat() if item["finished_at"] else None
            item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
            res.append(item)
            if len(res) >= limit:
                break
        return res

    async def get_active_job(self):
        return None

    async def get_settings(self):
        return dict(self.settings)

    async def update_settings(self, new_settings: dict):
        self.settings.update(new_settings)
        return dict(self.settings)


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


@pytest.fixture
def mock_app():
    if not hasattr(app.state, "container") or app.state.container is None:
        app.state.container = Container()
    repo = MockScraperRepo()
    app.state.container.scraper_service = ScraperService(repo)
    app.state.container.auth_service = MockAuthService()
    yield repo
    app.state.container = None


# ============================================================================
# Task 1: POST /api/admin/scraper/settings validation and upper bound
# ============================================================================

class TestTask1SettingsValidation:
    """Task 1: Verify POST /api/admin/scraper/settings with huge intervals returns 422."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("huge_payload", [
        {"refresh_interval_days": 10_000_000, "discovery_interval_days": 7, "is_paused": False},
        {"refresh_interval_days": 3651, "discovery_interval_days": 7, "is_paused": False},
        {"refresh_interval_days": 3, "discovery_interval_days": 3651, "is_paused": False},
        {"refresh_interval_days": 99_999_999_999_999_999_999, "discovery_interval_days": 7, "is_paused": False},
        {"refresh_interval_days": 0, "discovery_interval_days": 7, "is_paused": False},
        {"refresh_interval_days": -1, "discovery_interval_days": 7, "is_paused": False},
        {"refresh_interval_days": -99999, "discovery_interval_days": 7, "is_paused": False},
    ])
    async def test_huge_or_invalid_interval_returns_422(self, mock_app, huge_payload):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post("/api/admin/scraper/settings", json=huge_payload, headers=ADMIN_HEADERS)
            assert resp.status_code == 422, f"Expected 422 for payload {huge_payload}, got {resp.status_code}"

    @pytest.mark.anyio
    @pytest.mark.parametrize("valid_payload", [
        {"refresh_interval_days": 3650, "discovery_interval_days": 3650, "is_paused": False},
        {"refresh_interval_days": 1, "discovery_interval_days": 1, "is_paused": True},
        {"refresh_interval_days": 3, "discovery_interval_days": 7, "is_paused": False},
    ])
    async def test_valid_interval_boundaries_succeed(self, mock_app, valid_payload):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post("/api/admin/scraper/settings", json=valid_payload, headers=ADMIN_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "updated"
            assert data["settings"]["refresh_interval_days"] == valid_payload["refresh_interval_days"]
            assert data["settings"]["discovery_interval_days"] == valid_payload["discovery_interval_days"]
            assert data["settings"]["is_paused"] == valid_payload["is_paused"]

    @pytest.mark.anyio
    async def test_domain_service_update_settings_enforces_upper_bound(self, mock_app):
        svc = ScraperService(mock_app)
        with pytest.raises(ValueError, match="refresh_interval_days must not exceed 3650 days"):
            await svc.update_settings({"refresh_interval_days": 3651})

        with pytest.raises(ValueError, match="discovery_interval_days must not exceed 3650 days"):
            await svc.update_settings({"discovery_interval_days": 10000})


# ============================================================================
# Task 2: GET /api/admin/scraper/status never crashes with OverflowError
# ============================================================================

class TestTask2StatusNeverCrashesWithOverflow:
    """Task 2: Verify GET /api/admin/scraper/status never crashes with OverflowError."""

    @pytest.mark.anyio
    async def test_status_endpoint_never_crashes(self, mock_app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # First set to boundary value (3650 days)
            await client.post(
                "/api/admin/scraper/settings",
                json={"refresh_interval_days": 3650, "discovery_interval_days": 3650, "is_paused": False},
                headers=ADMIN_HEADERS,
            )

            # Query status multiple times
            for _ in range(5):
                resp = await client.get("/api/admin/scraper/status", headers=ADMIN_HEADERS)
                assert resp.status_code == 200
                data = resp.json()
                assert "daemon" in data
                assert "schedules" in data
                assert "stats" in data
                assert data["daemon"]["status"] in ("RUNNING", "STOPPED")


# ============================================================================
# Task 3: GET /api/admin/scraper/logs returns integer IDs
# ============================================================================

class TestTask3LogsIntegerIdsContract:
    """Task 3: Verify GET /api/admin/scraper/logs returns integer IDs rather than strings."""

    @pytest.mark.anyio
    async def test_logs_endpoint_returns_integer_ids_over_asgi(self, mock_app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/api/admin/scraper/logs", headers=ADMIN_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert "items" in data
            assert len(data["items"]) >= 1

            for item in data["items"]:
                assert isinstance(item["id"], int), f"item.id was {type(item['id'])}: {item['id']}"
                assert isinstance(item["job_id"], int), f"item.job_id was {type(item['job_id'])}: {item['job_id']}"
                assert item["id"] == item["job_id"]
                for line in item["lines"]:
                    assert isinstance(line["id"], int), f"line.id was {type(line['id'])}: {line['id']}"
                    assert isinstance(line["job_id"], int), f"line.job_id was {type(line['job_id'])}: {line['job_id']}"

    @pytest.mark.anyio
    async def test_live_postgres_id_normalization_types(self):
        """Live test verifying PgScraperRepository integer normalization against real PostgreSQL."""
        pool = await create_pool()
        await ensure_auth_schema(pool)
        repo = PgScraperRepository(pool)
        test_job_id = None
        try:
            # Enqueue a job
            test_job_id = await repo.enqueue_job("refresh", trigger_type="manual")
            assert isinstance(test_job_id, int)

            # Insert a log row directly
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO skool.scraper_logs (job_id, level, message) VALUES ($1, 'INFO', 'Challenger verification log')",
                    test_job_id,
                )

            # Call repo.get_logs
            logs = await repo.get_logs(limit=5, job_id=test_job_id)
            assert len(logs) == 1
            item = logs[0]

            # Strict integer type assertions (NOT strings!)
            assert isinstance(item["id"], int), f"Expected int for item['id'], got {type(item['id'])}: {item['id']}"
            assert isinstance(item["job_id"], int), f"Expected int for item['job_id'], got {type(item['job_id'])}: {item['job_id']}"
            assert item["id"] == test_job_id
            assert item["job_id"] == test_job_id

            assert len(item["lines"]) == 1
            log_line = item["lines"][0]
            assert isinstance(log_line["id"], int), f"Expected int for line['id'], got {type(log_line['id'])}: {log_line['id']}"
            assert isinstance(log_line["job_id"], int), f"Expected int for line['job_id'], got {type(log_line['job_id'])}: {log_line['job_id']}"
            assert log_line["job_id"] == test_job_id

            # Active job normalization
            async with pool.acquire() as conn:
                await conn.execute("UPDATE skool.scraper_jobs SET status = 'RUNNING', started_at = NOW() WHERE id = $1", test_job_id)

            active_job = await repo.get_active_job()
            assert active_job is not None
            assert isinstance(active_job["id"], int)
            assert active_job["id"] == test_job_id

            status = await repo.get_status()
            assert status["active_job"] is not None
            assert isinstance(status["active_job"]["id"], int)
            assert status["active_job"]["id"] == test_job_id

        finally:
            if test_job_id:
                async with pool.acquire() as conn:
                    await conn.execute("DELETE FROM skool.scraper_jobs WHERE id = $1", test_job_id)
            await pool.close()


# ============================================================================
# Task 4: GET /api/admin/scraper/logs with out-of-range job_id
# ============================================================================

class TestTask4OutOfRangeJobIdSanitization:
    """Task 4: Verify GET /api/admin/scraper/logs?job_id=999999999999999999999999999 returns 200 {"items": []}."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("extreme_job_id", [
        "999999999999999999999999999",
        "9223372036854775808",  # int64 max + 1
        "18446744073709551616",  # 2^64
        "0",
        "-1",
        "-999999999999999999",
    ])
    async def test_logs_extreme_job_id_returns_empty_items(self, mock_app, extreme_job_id):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/api/admin/scraper/logs?job_id={extreme_job_id}", headers=ADMIN_HEADERS)
            assert resp.status_code == 200, f"Expected 200 for job_id={extreme_job_id}, got {resp.status_code}"
            assert resp.json() == {"items": []}

    @pytest.mark.anyio
    async def test_live_postgres_domain_service_extreme_job_id_no_crash(self):
        """Ensure that ScraperService directly connected to real PostgreSQL handles extreme job_id safely."""
        pool = await create_pool()
        await ensure_auth_schema(pool)
        repo = PgScraperRepository(pool)
        svc = ScraperService(repo)
        try:
            # Extreme out of range job_id should return empty items without database query error
            res = await svc.get_logs(job_id=999999999999999999999999999)
            assert res == {"items": []}

            res2 = await svc.get_logs(job_id=9_223_372_036_854_775_808)
            assert res2 == {"items": []}

            res3 = await svc.get_logs(job_id=0)
            assert res3 == {"items": []}

            res4 = await svc.get_logs(job_id=-500)
            assert res4 == {"items": []}
        finally:
            await pool.close()
