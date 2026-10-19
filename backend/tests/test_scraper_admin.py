"""Tests for Scraper Admin API (/api/admin/scraper).

Verifies:
- 401 Unauthorized for missing / invalid tokens
- 403 Forbidden for non-admin accounts
- 200 OK for admin on GET /status, POST /trigger, GET /logs, GET /settings, POST /settings
- 400 Bad Request for invalid trigger modes
- 422 Unprocessable Entity for invalid settings payloads
"""
import pytest
import httpx

from app.main import app
from app.api.deps import Container
from app.domain.services.scraper_service import ScraperService
from app.ports.repositories import ScraperRepository


class FakeScraperRepo:
    def __init__(self):
        self.enqueued = []
        self.settings = {
            "refresh_interval_days": 3,
            "discovery_interval_days": 7,
            "refresh_cron": "0 2 */3 * *",
            "discovery_cron": "0 3 * * 0",
            "is_paused": False,
        }
        self.logs = [
            {
                "id": 1,
                "job_id": 101,
                "job_type": "refresh",
                "trigger_type": "manual",
                "status": "SUCCESS",
                "started_at": "2026-10-18T10:00:00Z",
                "finished_at": "2026-10-18T10:05:00Z",
                "created_at": "2026-10-18T10:00:00Z",
                "exit_code": 0,
                "error_message": None,
                "lines": [
                    {"id": 1, "level": "INFO", "message": "Starting refresh", "created_at": "2026-10-18T10:00:01Z"}
                ],
            }
        ]

    async def get_status(self) -> dict:
        return {
            "daemon": {
                "status": "RUNNING",
                "last_heartbeat": "2026-10-18T12:00:00Z",
                "is_paused": self.settings["is_paused"],
            },
            "schedules": {
                "refresh": {
                    "interval_days": self.settings["refresh_interval_days"],
                    "cron": self.settings["refresh_cron"],
                    "last_run": "2026-10-18T10:00:00Z",
                    "next_run": "2026-10-21T10:00:00Z",
                },
                "discovery": {
                    "interval_days": self.settings["discovery_interval_days"],
                    "cron": self.settings["discovery_cron"],
                    "last_run": None,
                    "next_run": "2026-10-25T10:00:00Z",
                },
            },
            "stats": {
                "total_groups": 1250,
                "pending_details": 42,
                "pending_owners": 10,
            },
            "active_job": None,
        }

    async def get_settings(self) -> dict:
        return dict(self.settings)

    async def update_settings(self, settings_data: dict) -> dict:
        self.settings.update(settings_data)
        return dict(self.settings)

    async def enqueue_job(self, job_type: str, trigger_type: str = "manual") -> int:
        job_id = len(self.enqueued) + 100
        self.enqueued.append((job_id, job_type, trigger_type))
        return job_id

    async def get_logs(self, limit: int = 50, job_id: int | None = None) -> list[dict]:
        if job_id:
            return [l for l in self.logs if l["job_id"] == job_id][:limit]
        return self.logs[:limit]

    async def get_active_job(self) -> dict | None:
        return None

    async def update_heartbeat(self) -> None:
        pass


class FakeAuthService:
    def __init__(self):
        self.admin_account = {"id": 1, "email": "admin@skool.local", "is_admin": True, "is_active": True}
        self.regular_account = {"id": 2, "email": "user@skool.local", "is_admin": False, "is_active": True}

    async def resolve(self, token: str) -> dict | None:
        if token == "admin_token":
            return self.admin_account
        elif token == "user_token":
            return self.regular_account
        return None

    async def is_admin(self, account_id: int) -> bool:
        return account_id == 1


@pytest.fixture(autouse=True)
def setup_test_container():
    if not hasattr(app.state, "container") or app.state.container is None:
        app.state.container = Container()

    repo = FakeScraperRepo()
    app.state.container.scraper_service = ScraperService(repo)
    app.state.container.auth_service = FakeAuthService()
    yield
    app.state.container = None


ADMIN_HEADERS = {"Authorization": "Bearer admin_token"}
USER_HEADERS = {"Authorization": "Bearer user_token"}


@pytest.mark.anyio
async def test_scraper_admin_unauthorized_without_token():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/admin/scraper/status")
        assert r.status_code == 401

        r = await client.post("/api/admin/scraper/trigger", json={"mode": "refresh"})
        assert r.status_code == 401

        r = await client.get("/api/admin/scraper/logs")
        assert r.status_code == 401

        r = await client.get("/api/admin/scraper/settings")
        assert r.status_code == 401


@pytest.mark.anyio
async def test_scraper_admin_forbidden_for_non_admin():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/admin/scraper/status", headers=USER_HEADERS)
        assert r.status_code == 403
        assert r.json() == {"error": "Forbidden"}

        r = await client.post("/api/admin/scraper/trigger", json={"mode": "refresh"}, headers=USER_HEADERS)
        assert r.status_code == 403

        r = await client.get("/api/admin/scraper/logs", headers=USER_HEADERS)
        assert r.status_code == 403

        r = await client.get("/api/admin/scraper/settings", headers=USER_HEADERS)
        assert r.status_code == 403

        r = await client.post(
            "/api/admin/scraper/settings",
            json={"refresh_interval_days": 3, "discovery_interval_days": 7, "is_paused": False},
            headers=USER_HEADERS,
        )
        assert r.status_code == 403


@pytest.mark.anyio
async def test_scraper_admin_get_status_success():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/admin/scraper/status", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["daemon"]["status"] == "RUNNING"
        assert data["daemon"]["is_paused"] is False
        assert "schedules" in data
        assert data["schedules"]["refresh"]["interval_days"] == 3
        assert data["schedules"]["discovery"]["interval_days"] == 7
        assert data["stats"]["total_groups"] == 1250
        assert data["stats"]["pending_details"] == 42
        assert data["stats"]["pending_owners"] == 10


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["refresh", "discovery", "all", "missing_owners"])
async def test_scraper_admin_trigger_valid_modes(mode):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/admin/scraper/trigger", json={"mode": mode}, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["mode"] == mode
        assert "job_id" in data


@pytest.mark.anyio
async def test_scraper_admin_trigger_invalid_mode():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/admin/scraper/trigger", json={"mode": "unsupported_mode"}, headers=ADMIN_HEADERS)
        assert r.status_code == 400
        assert "error" in r.json()
        assert "Invalid mode" in r.json()["error"]


@pytest.mark.anyio
async def test_scraper_admin_get_logs():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/admin/scraper/logs", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["job_id"] == 101
        assert item["job_type"] == "refresh"
        assert len(item["lines"]) == 1
        assert item["lines"][0]["message"] == "Starting refresh"


@pytest.mark.anyio
async def test_scraper_admin_get_and_post_settings():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GET settings
        r = await client.get("/api/admin/scraper/settings", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["refresh_interval_days"] == 3
        assert data["discovery_interval_days"] == 7
        assert data["is_paused"] is False

        # POST settings
        update_payload = {
            "refresh_interval_days": 4,
            "discovery_interval_days": 10,
            "is_paused": True,
        }
        r2 = await client.post("/api/admin/scraper/settings", json=update_payload, headers=ADMIN_HEADERS)
        assert r2.status_code == 200
        res = r2.json()
        assert res["status"] == "updated"
        assert res["settings"]["refresh_interval_days"] == 4
        assert res["settings"]["discovery_interval_days"] == 10
        assert res["settings"]["is_paused"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_body", [
    {"refresh_interval_days": 0, "discovery_interval_days": 7},
    {"refresh_interval_days": -2, "discovery_interval_days": 7},
    {"refresh_interval_days": 3, "discovery_interval_days": 0},
    {"refresh_interval_days": "not_an_int", "discovery_interval_days": 7},
    {"refresh_interval_days": 3651, "discovery_interval_days": 7},
    {"refresh_interval_days": 3, "discovery_interval_days": 3651},
    {"refresh_interval_days": 10_000_000, "discovery_interval_days": 7},
])
async def test_scraper_admin_post_settings_invalid(invalid_body):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/admin/scraper/settings", json=invalid_body, headers=ADMIN_HEADERS)
        assert r.status_code == 422


@pytest.mark.anyio
async def test_scraper_admin_post_settings_max_boundary():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/api/admin/scraper/settings",
            json={"refresh_interval_days": 3650, "discovery_interval_days": 3650, "is_paused": False},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["settings"]["refresh_interval_days"] == 3650
        assert data["settings"]["discovery_interval_days"] == 3650
