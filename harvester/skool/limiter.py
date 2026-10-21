"""Adaptive Rate Limiter (AIMD) and Resilient Circuit Breaker.

Key principles:
1. AdaptiveLimiter (AIMD):
   - Additive Increase (+0.25 rps after 50 consecutive OKs) up to max_rps.
   - Multiplicative Decrease (*0.5 rps on rate limit/block) down to min_rps.
   - Jittered pacing (±20%) to break machine regularity.
   - Persistence of stable RPS across restarts.

2. CircuitBreaker:
   - States: CLOSED -> OPEN -> HALF_OPEN.
   - Trips to OPEN when >= trip_threshold (3) errors occur in window_sec (60s).
   - Exponential open duration: 60s -> 120s -> 240s -> 300s.
   - Triggers proactive WAF token solve upon tripping before sleeping.
   - In HALF_OPEN: permits exactly 1 canary probe; success -> CLOSED; failure -> OPEN.
   - Does NOT consume worker task retry attempts while in OPEN state.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("skool.limiter")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class AdaptiveLimiter:
    """Additive-Increase / Multiplicative-Decrease (AIMD) Token Bucket with Jitter."""

    def __init__(
        self,
        start_rps: float = 3.0,
        min_rps: float = 0.5,
        max_rps: float = 8.0,
        increase_after_ok: int = 50,
        increase_step: float = 0.25,
        decrease_factor: float = 0.5,
        jitter: float = 0.20,
        state_file: str | Path | None = None,
    ) -> None:
        self.min_rps = min_rps
        self.max_rps = max_rps
        self.increase_after_ok = increase_after_ok
        self.increase_step = increase_step
        self.decrease_factor = decrease_factor
        self.jitter = jitter
        self.state_file = Path(state_file) if state_file else None

        self.current_rps: float = start_rps
        self.consecutive_ok: int = 0
        self._next_slot: float = 0.0
        self._lock = asyncio.Lock()

        self._load_state()

    def _load_state(self) -> None:
        if self.state_file and self.state_file.exists():
            try:
                val = float(self.state_file.read_text(encoding="utf-8").strip())
                self.current_rps = max(self.min_rps, min(self.max_rps, val))
                log.info("Loaded persisted RPS: %.2f", self.current_rps)
            except Exception as exc:
                log.debug("Could not read limiter state file: %s", exc)

    def _save_state(self) -> None:
        if self.state_file:
            try:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self.state_file.write_text(f"{self.current_rps:.2f}", encoding="utf-8")
            except Exception as exc:
                log.debug("Could not save limiter state file: %s", exc)

    async def acquire(self) -> float:
        """Pace requests according to current RPS token bucket with jitter."""
        loop = asyncio.get_running_loop()
        now = loop.time()

        base_interval = 1.0 / max(self.current_rps, 0.01)
        jitter_factor = random.uniform(1.0 - self.jitter, 1.0 + self.jitter)
        paced_interval = base_interval * jitter_factor

        async with self._lock:
            scheduled_time = max(now, self._next_slot)
            self._next_slot = scheduled_time + paced_interval

        wait_seconds = scheduled_time - now
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        return wait_seconds

    def record_success(self) -> None:
        """Additive increase after sustained successes."""
        self.consecutive_ok += 1
        if self.consecutive_ok >= self.increase_after_ok:
            old_rps = self.current_rps
            self.current_rps = min(self.max_rps, self.current_rps + self.increase_step)
            self.consecutive_ok = 0
            if self.current_rps != old_rps:
                log.info("AIMD increase: RPS %.2f -> %.2f (+%.2f)", old_rps, self.current_rps, self.increase_step)
                self._save_state()

    def record_backoff(self, reason: str = "") -> None:
        """Multiplicative decrease upon block or rate limit."""
        old_rps = self.current_rps
        self.current_rps = max(self.min_rps, self.current_rps * self.decrease_factor)
        self.consecutive_ok = 0
        log.warning("AIMD decrease (%s): RPS %.2f -> %.2f (x%.2f)", reason, old_rps, self.current_rps, self.decrease_factor)
        self._save_state()


class CircuitBreaker:
    """Stateful circuit breaker replacing crude fixed-duration cooldowns."""

    def __init__(
        self,
        window_sec: float = 60.0,
        trip_threshold: int = 3,
        open_durations_sec: list[float] | None = None,
        waf_manager: Any | None = None,
    ) -> None:
        self.window_sec = window_sec
        self.trip_threshold = trip_threshold
        self.open_durations_sec = open_durations_sec or [60.0, 120.0, 240.0, 300.0]
        self.waf_manager = waf_manager

        self.state: CircuitState = CircuitState.CLOSED
        self.recent_errors: list[float] = []
        self.trip_count: int = 0
        self.opened_at: float = 0.0
        self.open_until: float = 0.0

        self._gate = asyncio.Event()
        self._gate.set()  # set when passage is permitted
        self._lock = asyncio.Lock()
        self._half_open_probe_active = False

    async def wait_permission(self) -> None:
        """Workers call this before executing a request. Blocks when circuit is OPEN."""
        while True:
            await self._gate.wait()

            async with self._lock:
                now = time.time()
                if self.state == CircuitState.OPEN:
                    if now < self.open_until:
                        # Still open; keep waiting
                        self._gate.clear()
                        continue
                    else:
                        # Timer expired -> Transition to HALF_OPEN
                        log.info("CircuitBreaker OPEN duration expired -> Transition to HALF_OPEN")
                        self.state = CircuitState.HALF_OPEN
                        self._half_open_probe_active = False

                if self.state == CircuitState.HALF_OPEN:
                    if not self._half_open_probe_active:
                        # Allow exactly one probe request
                        self._half_open_probe_active = True
                        self._gate.clear()  # Block other workers until probe resolves
                        return
                    else:
                        # Another worker is already probing; wait
                        continue

                if self.state == CircuitState.CLOSED:
                    return

    async def record_error(self, error_class: str, limiter: AdaptiveLimiter | None = None) -> None:
        """Record a critical rate-limit or WAF block error. Trips if threshold is met."""
        if error_class not in ("WAF_BLOCK", "RATE_LIMIT"):
            return

        async with self._lock:
            now = time.time()

            if limiter:
                limiter.record_backoff(reason=error_class)

            if self.state == CircuitState.HALF_OPEN:
                # Probe failed -> Trip back to OPEN with next backoff level
                log.warning("Probe failed in HALF_OPEN state -> Trip to OPEN")
                await self._trip_circuit_locked(now)
                return

            if self.state == CircuitState.CLOSED:
                self.recent_errors.append(now)
                # Prune errors outside the rolling window
                self.recent_errors = [t for t in self.recent_errors if now - t <= self.window_sec]

                if len(self.recent_errors) >= self.trip_threshold:
                    log.warning(
                        "CircuitBreaker threshold met (%d errors in %.1fs) -> Tripping to OPEN",
                        len(self.recent_errors),
                        self.window_sec,
                    )
                    await self._trip_circuit_locked(now)

    async def _trip_circuit_locked(self, now: float) -> None:
        """Internal helper to set OPEN state and schedule duration."""
        idx = min(self.trip_count, len(self.open_durations_sec) - 1)
        base_duration = self.open_durations_sec[idx]
        jitter_factor = random.uniform(0.9, 1.1)
        duration = base_duration * jitter_factor

        self.trip_count += 1
        self.state = CircuitState.OPEN
        self.opened_at = now
        self.open_until = now + duration
        self.recent_errors.clear()
        self._gate.clear()

        log.warning(
            "CircuitBreaker OPEN for %.1f seconds (level=%d, until=%.0f)",
            duration,
            self.trip_count,
            self.open_until,
        )

        # Trigger proactive WAF solve before sleeping if WafTokenManager is present
        if self.waf_manager:
            try:
                log.info("Triggering proactive WAF token refresh upon circuit trip...")
                asyncio.create_task(self.waf_manager.get_token(force=True))
            except Exception as exc:
                log.warning("Could not trigger WAF refresh on breaker trip: %s", exc)

        # Launch unblock timer task
        asyncio.create_task(self._schedule_unblock(duration))

    async def _schedule_unblock(self, duration: float) -> None:
        """Wait for duration, then set gate to allow transition to HALF_OPEN."""
        await asyncio.sleep(duration)
        async with self._lock:
            if self.state == CircuitState.OPEN:
                log.info("CircuitBreaker open duration elapsed; ready for probe")
                self._gate.set()

    def record_success(self) -> None:
        """Notify breaker of a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            log.info("CircuitBreaker probe succeeded -> Transition to CLOSED")
            self.state = CircuitState.CLOSED
            self.trip_count = max(0, self.trip_count - 1)
            self._half_open_probe_active = False
            self.recent_errors.clear()
            self._gate.set()
        elif self.state == CircuitState.CLOSED:
            if self.recent_errors:
                now = time.time()
                self.recent_errors = [t for t in self.recent_errors if now - t <= self.window_sec]
