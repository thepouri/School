"""Pure-domain unit tests: R1 bucket inference, R5 revenue, JS-lenient parsing."""
from datetime import datetime, timezone
import pytest

from app.domain.filters import parse_bool, parse_int, pagination_of, split_list
from app.domain.pricing import estimate_revenue, infer_bucket
from app.domain.services.group_service import GroupService
from app.domain.services.user_service import UserService
from app.domain.services.usage_service import UsageService
from app.domain.services.health_service import HealthService


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

