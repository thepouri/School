"""Tests for AdaptiveLimiter and CircuitBreaker."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from skool.limiter import AdaptiveLimiter, CircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_adaptive_limiter_aimd(tmp_path):
    state_file = tmp_path / "limiter_rps.txt"
    limiter = AdaptiveLimiter(
        start_rps=2.0,
        min_rps=1.0,
        max_rps=4.0,
        increase_after_ok=3,  # test with 3 for speed
        increase_step=0.5,
        decrease_factor=0.5,
        jitter=0.0,
        state_file=state_file,
    )

    assert limiter.current_rps == 2.0

    # 3 successes -> should increase
    limiter.record_success()
    limiter.record_success()
    limiter.record_success()
    assert limiter.current_rps == 2.5

    # 3 more -> 3.0
    limiter.record_success()
    limiter.record_success()
    limiter.record_success()
    assert limiter.current_rps == 3.0

    # Multiplicative decrease
    limiter.record_backoff("WAF_BLOCK")
    assert limiter.current_rps == 1.5

    limiter.record_backoff("RATE_LIMIT")
    assert limiter.current_rps == 1.0  # capped by min_rps

    # Verify persistence
    new_limiter = AdaptiveLimiter(start_rps=2.0, min_rps=1.0, max_rps=4.0, state_file=state_file)
    assert new_limiter.current_rps == 1.0


@pytest.mark.asyncio
async def test_circuit_breaker_transitions():
    waf_mock = AsyncMock()
    breaker = CircuitBreaker(
        window_sec=10.0,
        trip_threshold=3,
        open_durations_sec=[0.1, 0.2],  # very short for fast test
        waf_manager=waf_mock,
    )

    assert breaker.state == CircuitState.CLOSED

    # 2 errors do not trip
    await breaker.record_error("RATE_LIMIT")
    await breaker.record_error("WAF_BLOCK")
    assert breaker.state == CircuitState.CLOSED

    # 3rd error trips to OPEN
    await breaker.record_error("RATE_LIMIT")
    assert breaker.state == CircuitState.OPEN
    assert waf_mock.get_token.called

    # Wait for unblock duration (0.1s)
    await asyncio.sleep(0.15)

    # Calling wait_permission now should transition to HALF_OPEN and permit 1 probe
    await breaker.wait_permission()
    assert breaker.state == CircuitState.HALF_OPEN

    # Probe succeeds -> CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.trip_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_failure():
    breaker = CircuitBreaker(
        window_sec=10.0,
        trip_threshold=2,
        open_durations_sec=[0.05, 0.1],
    )

    # Trip to OPEN
    await breaker.record_error("WAF_BLOCK")
    await breaker.record_error("WAF_BLOCK")
    assert breaker.state == CircuitState.OPEN

    await asyncio.sleep(0.08)
    await breaker.wait_permission()
    assert breaker.state == CircuitState.HALF_OPEN

    # Probe fails -> Trips back to OPEN with level 2
    await breaker.record_error("WAF_BLOCK")
    assert breaker.state == CircuitState.OPEN
    assert breaker.trip_count == 2
