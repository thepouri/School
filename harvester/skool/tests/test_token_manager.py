"""Tests for WafTokenManager and BuildIdManager."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from skool.http_gateway import ClassifiedResponse, HttpGateway, ResponseClass
from skool.token_manager import BuildIdManager, WafTokenManager


@pytest.mark.asyncio
async def test_waf_token_manager_single_flight():
    gw = HttpGateway()
    mgr = WafTokenManager(gateway=gw)

    solve_count = 0

    async def mock_solve(*args, **kwargs):
        nonlocal solve_count
        solve_count += 1
        await asyncio.sleep(0.05)
        return f"mock_waf_token_{solve_count}"

    mgr._solve_waf = mock_solve

    # Fire 8 concurrent requests for token
    tasks = [mgr.get_token(force=True) for _ in range(8)]
    results = await asyncio.gather(*tasks)

    # Exactly ONE solve should have run
    assert solve_count == 1
    # All 8 tasks should receive the exact same token
    assert all(r == "mock_waf_token_1" for r in results)
    assert mgr.token == "mock_waf_token_1"
    assert mgr.generation == 1

    await mgr.aclose()
    await gw.aclose()


@pytest.mark.asyncio
async def test_waf_token_ttl_expiry():
    mgr = WafTokenManager()
    mgr.token = "valid_token"
    mgr.obtained_at = 100.0

    # With current time 200 and ttl 50 -> expired
    with patch("time.time", return_value=200.0):
        assert mgr.is_expired(ttl_sec=50.0) is True

    # With current time 120 and ttl 50 -> not expired
    with patch("time.time", return_value=120.0):
        assert mgr.is_expired(ttl_sec=50.0) is False

    await mgr.aclose()


@pytest.mark.asyncio
async def test_build_id_manager_single_flight():
    gw = HttpGateway()
    mgr = BuildIdManager(gateway=gw)

    call_count = 0

    async def mock_execute(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return ClassifiedResponse(
            status_class=ResponseClass.OK,
            http_status=200,
            data={},
            raw_text='<html><script id="__NEXT_DATA__">{"buildId":"test-build-123"}</script></html>',
            url=url,
        )

    gw.execute = mock_execute

    tasks = [mgr.get_build_id(force=True) for _ in range(6)]
    results = await asyncio.gather(*tasks)

    assert call_count == 1
    assert all(r == "test-build-123" for r in results)
    assert mgr.build_id == "test-build-123"
    assert mgr.generation == 1

    await gw.aclose()


@pytest.mark.asyncio
async def test_build_id_canary_disambiguation():
    gw = HttpGateway()
    mgr = BuildIdManager(gateway=gw, initial_build_id="build_v1")

    # Scenario 1: Canary returns OK -> 404 is genuine (GONE), build_id is not stale
    async def mock_execute_canary_ok(url, *args, **kwargs):
        return ClassifiedResponse(
            status_class=ResponseClass.OK,
            http_status=200,
            data={"pageProps": {}},
            raw_text="{}",
            url=url,
        )

    gw.execute = mock_execute_canary_ok
    is_stale, active_id = await mgr.handle_not_found("https://www.skool.com/_next/data/build_v1/deleted-grp/about.json")

    assert is_stale is False
    assert active_id == "build_v1"

    # Scenario 2: Canary returns 404 -> build_id is STALE! Refresh occurs.
    fetch_count = 0

    async def mock_execute_canary_404(url, *args, **kwargs):
        nonlocal fetch_count
        if "skoolers/about.json" in url:
            return ClassifiedResponse(
                status_class=ResponseClass.NOT_FOUND,
                http_status=404,
                data=None,
                raw_text="404",
                url=url,
            )
        # discovery page request to get fresh buildId
        fetch_count += 1
        return ClassifiedResponse(
            status_class=ResponseClass.OK,
            http_status=200,
            data={},
            raw_text='{"buildId":"build_v2"}',
            url=url,
        )

    gw.execute = mock_execute_canary_404
    is_stale, new_id = await mgr.handle_not_found("https://www.skool.com/_next/data/build_v1/some-grp/about.json")

    assert is_stale is True
    assert new_id == "build_v2"
    assert mgr.build_id == "build_v2"

    await gw.aclose()
