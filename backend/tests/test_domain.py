"""Pure-domain unit tests: R1 bucket inference, R5 revenue, JS-lenient parsing."""
from datetime import datetime, timezone
import pytest

from app.domain.filters import parse_bool, parse_int, pagination_of, split_list
from app.domain.pricing import estimate_revenue, infer_bucket
from app.domain.services.group_service import GroupService
from app.domain.services.user_service import UserService
from app.domain.services.usage_service import UsageService
from app.domain.services.health_service import HealthService
from app.domain.services.scraper_service import ScraperService



class TestParsing:
    def test_parse_bool_js_lenient(self):
        assert parse_bool("true") is True and parse_bool("1") is True
        assert parse_bool("false") is False and parse_bool("0") is False
        assert parse_bool("yes") is None and parse_bool(None) is None

    def test_parse_int_leading_digits(self):
        assert parse_int("12abc") == 12  # Number.parseInt semantics
        assert parse_int("abc") is None
        assert parse_int("-3x") == -3
        assert parse_int(None) is None

    def test_split_list_cap_and_trim(self):
        assert split_list(" a , b , , c ") == ["a", "b", "c"]
        assert len(split_list(",".join(str(i) for i in range(100)))) == 40

    def test_pagination_clamps(self):
        class P(dict):
            def get(self, k, d=None): return super().get(k, d)
        p = P({"page": "0", "pageSize": "500"})
        r = pagination_of(p)
        assert (r.page, r.page_size) == (1, 100)
        r = pagination_of(P({}))
        assert (r.page, r.page_size) == (1, 24)


def _row(**kw):
    base = {"price_bucket": None, "price_usd": None,
            "price_amount_cents": None, "total_members": 1000,
            "price_interval": "month",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc)}
    base.update(kw)
    return base


class TestR1Bucket:
    def test_null_bucket_with_amount_is_paid(self):
        assert infer_bucket(_row(price_usd=29)) == "paid"

    def test_null_bucket_no_amount_is_free(self):
        assert infer_bucket(_row()) == "free"
        assert infer_bucket(_row(price_usd=0)) == "free"

    def test_explicit_bucket_wins(self):
        assert infer_bucket(_row(price_bucket="free-trial", price_usd=50)) == "free-trial"


class TestR5Revenue:
    def test_free_returns_none(self):
        assert estimate_revenue(_row(price_usd=None, price_bucket="free")) is None
        assert estimate_revenue(_row(price_usd=None)) is None

    def test_month(self):
        r = estimate_revenue(_row(price_usd=10))
        assert r["estimated_monthly_revenue_usd"] == 10000
        assert r["estimated_rev_period"] == "month"
        assert "estimated_one_time_revenue_usd" in r and r["estimated_one_time_revenue_usd"] is None

    def test_year_divides_12(self):
        assert estimate_revenue(_row(price_usd=120, price_interval="year"))["estimated_monthly_revenue_usd"] == 10000

    def test_week_multiplies_433(self):
        assert estimate_revenue(_row(price_usd=100, price_interval="week"))["estimated_monthly_revenue_usd"] == 433000

    def test_one_time_exposes_total_and_normalizes(self):
        r = estimate_revenue(_row(price_usd=1000, price_interval="one_time"))
        assert r["estimated_one_time_revenue_usd"] == 1000000
        assert 0 < r["estimated_monthly_revenue_usd"] <= 2000000

    def test_cents_fallback(self):
        # price_amount_cents used when price_usd missing
        r = estimate_revenue(_row(price_usd=None, price_amount_cents=4900))
        assert r["estimated_monthly_revenue_usd"] == 49000

    def test_no_members_returns_none(self):
        assert estimate_revenue(_row(price_usd=10, total_members=0)) is None


class MockGroupRepo:
    async def exists(self, group_id: str) -> bool:
        return group_id == "grp_123"


class MockUserRepo:
    async def exists(self, user_id: str) -> bool:
        return user_id == "usr_123"


class MockUsageRepo:
    def __init__(self):
        self.recorded = []

    async def record(self, account_id: int, path: str, status: int, duration_ms: int) -> None:
        self.recorded.append((account_id, path, status, duration_ms))


class TestDomainServices:
    @pytest.mark.anyio
    async def test_group_service_exists(self):
        service = GroupService(MockGroupRepo())
        assert await service.exists("grp_123") is True
        assert await service.exists("unknown") is False

    @pytest.mark.anyio
    async def test_user_service_exists(self):
        service = UserService(MockUserRepo())
        assert await service.exists("usr_123") is True
        assert await service.exists("unknown") is False

    @pytest.mark.anyio
    async def test_usage_service_record(self):
        repo = MockUsageRepo()
        service = UsageService(repo)
        await service.record(1, "/api/groups", 200, 15)
        assert repo.recorded == [(1, "/api/groups", 200, 15)]

    @pytest.mark.anyio
    async def test_health_service_check_db_healthy(self):
        async def mock_is_up():
            return True
        service = HealthService(mock_is_up)
        assert await service.check_db() is True

    @pytest.mark.anyio
    async def test_health_service_check_db_unhealthy_or_exception(self):
        async def mock_failing_is_up():
            raise ConnectionRefusedError("DB unavailable")
        service = HealthService(mock_failing_is_up)
        assert await service.check_db() is False


class MockScraperRepo:
    def __init__(self):
        self.enqueued = []
        self.settings = {
            "refresh_interval_days": 3,
            "discovery_interval_days": 7,
            "is_paused": False,
        }
        self.logs_requested = []

    async def get_status(self) -> dict:
        return {
            "daemon": {"status": "RUNNING", "last_heartbeat": "2026-10-18T12:00:00Z", "is_paused": False},
            "schedules": {
                "refresh": {"interval_days": 3, "cron": "0 2 */3 * *", "last_run": None, "next_run": "2026-10-21T12:00:00Z"},
                "discovery": {"interval_days": 7, "cron": "0 3 * * 0", "last_run": None, "next_run": "2026-10-25T12:00:00Z"},
            },
            "stats": {"total_groups": 100, "pending_details": 5, "pending_owners": 2},
            "active_job": None,
        }

    async def get_settings(self) -> dict:
        return dict(self.settings)

    async def update_settings(self, settings_data: dict) -> dict:
        self.settings.update(settings_data)
        return dict(self.settings)

    async def enqueue_job(self, job_type: str, trigger_type: str = "manual") -> int:
        job_id = len(self.enqueued) + 1
        self.enqueued.append((job_id, job_type, trigger_type))
        return job_id

    async def get_logs(self, limit: int = 50, job_id: int | None = None) -> list[dict]:
        self.logs_requested.append((limit, job_id))
        return [{"id": 1, "job_id": 1, "job_type": "refresh", "status": "SUCCESS", "lines": []}]

    async def get_active_job(self) -> dict | None:
        return None

    async def update_heartbeat(self) -> None:
        pass


class TestScraperDomainService:
    @pytest.mark.anyio
    async def test_get_status(self):
        repo = MockScraperRepo()
        service = ScraperService(repo)
        status = await service.get_status()
        assert status["daemon"]["status"] == "RUNNING"
        assert status["stats"]["total_groups"] == 100

    @pytest.mark.anyio
    @pytest.mark.parametrize("mode", ["refresh", "discovery", "all", "missing_owners"])
    async def test_trigger_job_valid_modes(self, mode):
        repo = MockScraperRepo()
        service = ScraperService(repo)
        res = await service.trigger_job(mode)
        assert res["status"] == "queued"
        assert res["mode"] == mode
        assert res["job_id"] == 1
        assert repo.enqueued[0] == (1, mode, "manual")

    @pytest.mark.anyio
    @pytest.mark.parametrize("bad_mode", ["invalid", "", "REFRESH_ALL", None, 123, []])
    async def test_trigger_job_invalid_modes(self, bad_mode):
        repo = MockScraperRepo()
        service = ScraperService(repo)
        with pytest.raises(ValueError):
            await service.trigger_job(bad_mode)

    @pytest.mark.anyio
    async def test_get_logs_clamping(self):
        repo = MockScraperRepo()
        service = ScraperService(repo)

        # Normal limit
        res = await service.get_logs(limit=25, job_id=5)
        assert len(res["items"]) == 1
        assert repo.logs_requested[-1] == (25, 5)

        # Clamped below 1
        await service.get_logs(limit=-10)
        assert repo.logs_requested[-1][0] == 1

        # Clamped above 200
        await service.get_logs(limit=500)
        assert repo.logs_requested[-1][0] == 200

        # Invalid type fallback
        await service.get_logs(limit="invalid")
        assert repo.logs_requested[-1][0] == 50

        # Non-positive job_id returns empty without querying repo
        curr_len = len(repo.logs_requested)
        res_zero = await service.get_logs(job_id=0)
        assert res_zero["items"] == []
        assert len(repo.logs_requested) == curr_len

        res_neg = await service.get_logs(job_id=-5)
        assert res_neg["items"] == []
        assert len(repo.logs_requested) == curr_len

        # Out-of-range bigint job_id returns empty without querying repo
        res_overflow = await service.get_logs(job_id=9_223_372_036_854_775_808)
        assert res_overflow["items"] == []
        assert len(repo.logs_requested) == curr_len

    @pytest.mark.anyio
    async def test_get_and_update_settings(self):
        repo = MockScraperRepo()
        service = ScraperService(repo)

        settings = await service.get_settings()
        assert settings["refresh_interval_days"] == 3
        assert settings["discovery_interval_days"] == 7
        assert settings["is_paused"] is False

        updated = await service.update_settings({
            "refresh_interval_days": 5,
            "discovery_interval_days": 14,
            "is_paused": True,
        })
        assert updated["status"] == "updated"
        assert updated["settings"]["refresh_interval_days"] == 5
        assert updated["settings"]["discovery_interval_days"] == 14
        assert updated["settings"]["is_paused"] is True

    @pytest.mark.anyio
    @pytest.mark.parametrize("invalid_settings", [
        {"refresh_interval_days": 0},
        {"refresh_interval_days": -1},
        {"refresh_interval_days": "abc"},
        {"refresh_interval_days": 3651},
        {"refresh_interval_days": 1000000},
        {"discovery_interval_days": 0},
        {"discovery_interval_days": -5},
        {"discovery_interval_days": "xyz"},
        {"discovery_interval_days": 3651},
        {"discovery_interval_days": 500000},
        "not_a_dict",
    ])
    async def test_update_settings_validation(self, invalid_settings):
        repo = MockScraperRepo()
        service = ScraperService(repo)
        with pytest.raises(ValueError):
            await service.update_settings(invalid_settings)


