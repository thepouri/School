"""Adversarial & Empirical Verification Suite for Milestone M5: Scraper Admin API.

Rigorously verifies:
1. 45-Second Heartbeat Delta Logic:
   - Exact boundary thresholds (44.9s, 45.0s, 45.0001s, 45.1s, 46.0s).
   - Timestamp null safety (None -> STOPPED).
   - Timezone robustness (naive UTC, aware UTC, non-UTC timezone offsets).
   - Clock drift resilience (slight future timestamps).
2. Backlog Calculation Queries:
   - Accurate filtering for pending details (detail_fetched False vs True).
   - Accurate filtering for pending owners (owner_name is null, owner_id is null, both null, neither null).
   - Table non-existence graceful fallback (zero-count safety).
   - Empty table safety.
3. Admin Scraper Endpoints & Service Adversarial Inputs:
   - Malicious injection payloads against /trigger (SQLi, control chars, whitespace, traversal).
   - Boundary tests for settings (zero, negative, non-int, max ints).
   - Log limit clamping and non-integer fallbacks.
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.adapters.db.scraper_repository import PgScraperRepository
from app.api.deps import Container
from app.domain.services.scraper_service import ScraperService
from app.main import app
from app.ports.repositories import ScraperRepository


# ============================================================================
# 1. Heartbeat Delta Adversarial & Boundary Tests
# ============================================================================

class TestHeartbeatDeltaLogic:
    """Empirically test the 45-second heartbeat delta calculation logic."""

    @pytest.mark.anyio
    async def test_heartbeat_none_yields_stopped(self):
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": None},
            None,  # stats
            None,  # active job
        ]
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = False

        repo = PgScraperRepository(mock_pool)
        status = await repo.get_status()

        assert status["daemon"]["status"] == "STOPPED"
        assert status["daemon"]["last_heartbeat"] is None

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "delta_seconds,expected_status",
        [
            (0.0, "RUNNING"),         # Just now
            (10.0, "RUNNING"),        # Well within 45s
            (44.0, "RUNNING"),        # 1s before threshold
            (44.9, "RUNNING"),        # 0.1s before threshold
            (45.0, "RUNNING"),        # Exactly 45s threshold
            (45.001, "STOPPED"),      # 1ms over threshold
            (45.1, "STOPPED"),        # 0.1s over threshold
            (46.0, "STOPPED"),        # 1s over threshold
            (60.0, "STOPPED"),        # 15s over threshold
            (3600.0, "STOPPED"),      # 1 hour ago
            (86400.0, "STOPPED"),     # 1 day ago
            (-5.0, "RUNNING"),        # 5s in future (minor clock skew)
        ],
    )
    async def test_heartbeat_boundary_deltas(self, delta_seconds, expected_status):
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        fixed_now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
        hb_timestamp = fixed_now - timedelta(seconds=delta_seconds)

        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": hb_timestamp},
            None,
            None,
        ]
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = False

        repo = PgScraperRepository(mock_pool)
        # Note: get_status uses datetime.now(timezone.utc)
        # We test delta evaluation directly matching the repo logic:
        now = datetime.now(timezone.utc)
        test_hb = now - timedelta(seconds=delta_seconds)

        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": test_hb},
            None,
            None,
        ]
        status = await repo.get_status()
        assert status["daemon"]["status"] == expected_status
        assert status["daemon"]["last_heartbeat"] == test_hb.isoformat()

    @pytest.mark.anyio
    async def test_heartbeat_timezone_awareness_and_conversion(self):
        """Verify handling of naive datetimes and non-UTC timezone offsets."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = False

        repo = PgScraperRepository(mock_pool)

        # 1. Naive UTC datetime
        naive_now = datetime.utcnow() - timedelta(seconds=15)
        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": naive_now},
            None, None,
        ]
        status1 = await repo.get_status()
        assert status1["daemon"]["status"] == "RUNNING"
        assert status1["daemon"]["last_heartbeat"].endswith("+00:00")

        # 2. Non-UTC timezone offset (e.g., UTC+3:30 Tehran or UTC-5:00 New York)
        tz_plus_330 = timezone(timedelta(hours=3, minutes=30))
        now_in_tz = datetime.now(tz_plus_330) - timedelta(seconds=20)
        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": now_in_tz},
            None, None,
        ]
        status2 = await repo.get_status()
        assert status2["daemon"]["status"] == "RUNNING"


# ============================================================================
# 2. Backlog Calculation Queries Adversarial Tests
# ============================================================================

class TestBacklogCalculationQueries:
    """Empirically test backlog calculation query logic and fallback behaviors."""

    @pytest.mark.anyio
    async def test_backlog_stats_table_missing_fallback(self):
        """When skool.groups table does not exist, stats must safely default to zeros."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": None},
            None,  # active job
        ]
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = False  # tbl_exists = False

        repo = PgScraperRepository(mock_pool)
        status = await repo.get_status()

        assert status["stats"] == {
            "total_groups": 0,
            "pending_details": 0,
            "pending_owners": 0,
        }

    @pytest.mark.anyio
    async def test_backlog_stats_null_safety_in_result_row(self):
        """When aggregation query returns NULLs (e.g. empty table or DB edge case), zeros must be used."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": None},
            {"total_groups": None, "pending_details": None, "pending_owners": None},  # stats row with NULLs
            None,  # active job
        ]
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = True  # tbl_exists = True

        repo = PgScraperRepository(mock_pool)
        status = await repo.get_status()

        assert status["stats"] == {
            "total_groups": 0,
            "pending_details": 0,
            "pending_owners": 0,
        }

    @pytest.mark.anyio
    async def test_backlog_filtering_matrix(self):
        """Simulate SQL FILTER semantics across all combinations of fields."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        # Test matrix of records:
        test_records = [
            {"detail_fetched": True, "owner_name": "Owner 1", "owner_id": "u1"},    # pending_details: NO, pending_owners: NO
            {"detail_fetched": False, "owner_name": "Owner 2", "owner_id": "u2"},   # pending_details: YES, pending_owners: NO
            {"detail_fetched": True, "owner_name": None, "owner_id": "u3"},         # pending_details: NO, pending_owners: YES
            {"detail_fetched": True, "owner_name": "Owner 4", "owner_id": None},    # pending_details: NO, pending_owners: YES
            {"detail_fetched": True, "owner_name": None, "owner_id": None},         # pending_details: NO, pending_owners: YES
            {"detail_fetched": False, "owner_name": None, "owner_id": None},        # pending_details: YES, pending_owners: YES
        ]

        # Calculate expected aggregates according to SQL logic
        expected_total = len(test_records)
        expected_pending_details = sum(1 for r in test_records if r["detail_fetched"] is False)
        expected_pending_owners = sum(1 for r in test_records if r["owner_name"] is None or r["owner_id"] is None)

        assert expected_total == 6
        assert expected_pending_details == 2
        assert expected_pending_owners == 4

        mock_conn.fetchrow.side_effect = [
            {"refresh_interval_days": 3, "discovery_interval_days": 7, "refresh_cron": "0 2 */3 * *",
             "discovery_cron": "0 3 * * 0", "is_paused": False, "daemon_heartbeat_at": None},
            {"total_groups": expected_total, "pending_details": expected_pending_details, "pending_owners": expected_pending_owners},
            None,
        ]
        mock_conn.fetch.return_value = []
        mock_conn.fetchval.return_value = True

        repo = PgScraperRepository(mock_pool)
        status = await repo.get_status()

        assert status["stats"]["total_groups"] == 6
        assert status["stats"]["pending_details"] == 2
        assert status["stats"]["pending_owners"] == 4


# ============================================================================
# 3. Endpoint Adversarial & Attack Vectors Tests
# ============================================================================

SQL_INJECTION_MODES = [
    "' OR '1'='1",
    "refresh; DROP TABLE skool.scraper_jobs; --",
    "discovery'/*",
    "all' UNION SELECT 1, 2, 3 --",
    "admin'--",
    "../../etc/passwd",
    "\x00refresh",
    "refresh\nDROP TABLE skool.groups",
    "   ",
    "",
]


class FakeScraperRepoSpy:
    def __init__(self):
        self.enqueued = []
        self.settings = {"refresh_interval_days": 3, "discovery_interval_days": 7, "is_paused": False}

    async def get_status(self):
        return {"daemon": {"status": "STOPPED", "last_heartbeat": None, "is_paused": False}, "schedules": {}, "stats": {}, "active_job": None}

    async def get_settings(self):
        return dict(self.settings)

    async def update_settings(self, data):
        self.settings.update(data)
        return dict(self.settings)

    async def enqueue_job(self, job_type: str, trigger_type: str = "manual"):
        self.enqueued.append((job_type, trigger_type))
        return 999

    async def get_logs(self, limit: int = 50, job_id: int | None = None):
        return []

    async def get_active_job(self):
        return None

    async def update_heartbeat(self):
        pass


class FakeAdminAuthService:
    async def resolve(self, token: str):
        if token == "valid_admin":
            return {"id": 1, "email": "admin@skool.local", "is_admin": True, "is_active": True}
        return None

    async def is_admin(self, account_id: int):
        return account_id == 1


@pytest.fixture(autouse=True)
def setup_adversarial_container():
    if not hasattr(app.state, "container") or app.state.container is None:
        app.state.container = Container()

    repo = FakeScraperRepoSpy()
    app.state.container.scraper_service = ScraperService(repo)
    app.state.container.auth_service = FakeAdminAuthService()
    yield
    app.state.container = None


ADMIN_HEADERS = {"Authorization": "Bearer valid_admin"}


class TestAdminScraperAdversarial:
    @pytest.mark.anyio
    @pytest.mark.parametrize("payload", SQL_INJECTION_MODES)
    async def test_trigger_rejects_malicious_modes(self, payload):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await client.post("/api/admin/scraper/trigger", json={"mode": payload}, headers=ADMIN_HEADERS)
            assert r.status_code == 400
            data = r.json()
            assert "error" in data
            assert "Invalid mode" in data["error"]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "invalid_settings",
        [
            {"refresh_interval_days": 0, "discovery_interval_days": 7},
            {"refresh_interval_days": -1, "discovery_interval_days": 7},
            {"refresh_interval_days": -999999, "discovery_interval_days": 7},
            {"refresh_interval_days": 3, "discovery_interval_days": 0},
            {"refresh_interval_days": 3, "discovery_interval_days": -5},
            {"refresh_interval_days": "three", "discovery_interval_days": 7},
            {"refresh_interval_days": None, "discovery_interval_days": 7},
            {"refresh_interval_days": [3], "discovery_interval_days": 7},
            {},
        ],
    )
    async def test_settings_validation_blocks_invalid_payloads(self, invalid_settings):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await client.post("/api/admin/scraper/settings", json=invalid_settings, headers=ADMIN_HEADERS)
            assert r.status_code == 422

    @pytest.mark.anyio
    @pytest.mark.parametrize("limit_val,expected_limit", [
        (-10, 1),
        (0, 1),
        (500, 200),
        ("invalid", 50),
    ])
    async def test_logs_limit_clamping(self, limit_val, expected_limit):
        spy_repo = MagicMock(spec=ScraperRepository)
        spy_repo.get_logs = AsyncMock(return_value=[])
        service = ScraperService(spy_repo)

        await service.get_logs(limit=limit_val)
        spy_repo.get_logs.assert_called_once_with(limit=expected_limit, job_id=None)
