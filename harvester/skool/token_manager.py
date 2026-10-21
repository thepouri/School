"""WAF Token Manager (Single-Flight, Proactive, Persistent Playwright)
and BuildId Manager (with Canary Check).

Key principles:
1. Single-Flight: multiple workers encountering 202/403 share ONE solver execution.
2. Persistent Browser Context: Playwright browser remains open; solves reload the page.
3. Proactive Refresh: refreshes token every 12-15 minutes BEFORE expiry.
4. Canary Check: validates 404 responses against an immutable Canary URL to
   disambiguate real 404 (GONE) from STALE BUILD_ID.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from .http_gateway import DEFAULT_USER_AGENT, HttpGateway, ResponseClass

log = logging.getLogger("skool.token_manager")

BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')
BASE_URL = "https://www.skool.com"
CANARY_URL_TEMPLATE = "{base}/_next/data/{build_id}/skoolers/about.json?group=skoolers"


class WafTokenManager:
    """Thread/Task-safe Single-Flight WAF Token Manager with persistent Playwright session."""

    def __init__(
        self,
        gateway: HttpGateway | None = None,
        auth_token: str | None = None,
        proactive_refresh_min: float = 12.0,
        token_cache_path: str | Path | None = None,
    ) -> None:
        self.gateway = gateway
        self.auth_token = auth_token
        self.proactive_refresh_sec = proactive_refresh_min * 60.0
        self.token_cache_path = Path(token_cache_path) if token_cache_path else None

        self.token: str | None = None
        self.obtained_at: float = 0.0
        self.generation: int = 0
        self.failure_count: int = 0

        self._lock = asyncio.Lock()
        self._current_flight: asyncio.Future[str] | None = None
        self._proactive_task: asyncio.Task[None] | None = None

        # Persistent Playwright objects
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._closed = False

        self._load_cached_token()

    def _load_cached_token(self) -> None:
        """Load previously cached token if valid and recent."""
        if self.token_cache_path and self.token_cache_path.exists():
            try:
                data = self.token_cache_path.read_text(encoding="utf-8").strip()
                if data:
                    self.token = data
                    self.obtained_at = time.time()
                    self.generation = 1
                    if self.gateway:
                        asyncio.create_task(self.gateway.set_cookie("aws-waf-token", self.token))
                    log.info("Loaded cached WAF token (%d chars)", len(self.token))
            except Exception as exc:
                log.debug("Could not read token cache: %s", exc)

    def _save_cached_token(self, token: str) -> None:
        if self.token_cache_path:
            try:
                self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.token_cache_path.write_text(token, encoding="utf-8")
            except Exception as exc:
                log.debug("Could not save token cache: %s", exc)

    def is_expired(self, ttl_sec: float = 720.0) -> bool:
        """Check if token is older than ttl (default 12 minutes)."""
        if not self.token or self.obtained_at <= 0:
            return True
        return (time.time() - self.obtained_at) >= ttl_sec

    async def _ensure_browser(self) -> None:
        """Ensure persistent Playwright browser and context are open."""
        if self._page is not None and not self._page.is_closed():
            return

        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()

        if self._browser is None:
            self._browser = await self._pw.chromium.launch(headless=True)

        user_agent = self.gateway.user_agent if self.gateway else DEFAULT_USER_AGENT
        self._context = await self._browser.new_context(user_agent=user_agent)

        if self.auth_token:
            await self._context.add_cookies([
                {
                    "name": "auth_token",
                    "value": self.auth_token,
                    "domain": ".skool.com",
                    "path": "/",
                }
            ])

        self._page = await self._context.new_page()

    async def _solve_waf(self, target_url: str = f"{BASE_URL}/discovery", timeout_sec: int = 45) -> str:
        """Internal solver using the persistent Playwright page."""
        await self._ensure_browser()

        log.info("Solving AWS WAF challenge on %s...", target_url)
        try:
            await self._page.goto(target_url, wait_until="networkidle", timeout=timeout_sec * 1000)
        except Exception as exc:
            log.warning("Navigation warning during WAF solve: %s", exc)

        token: str | None = None
        for _ in range(timeout_sec):
            cookies = await self._context.cookies()
            for c in cookies:
                if c["name"] == "aws-waf-token":
                    token = c["value"]
                    break
            if token:
                break
            await asyncio.sleep(1)

        if not token:
            raise RuntimeError(f"Failed to obtain aws-waf-token within {timeout_sec}s")

        return token

    async def get_token(self, force: bool = False, min_generation: int = 0) -> str:
        """Retrieve WAF token with Single-Flight guarantee across all workers."""
        if self._closed:
            raise RuntimeError("WafTokenManager is closed")

        # Fast path: current token is fresh and has reached or exceeded min_generation
        if not force and self.token and not self.is_expired(self.proactive_refresh_sec) and self.generation >= min_generation:
            return self.token

        loop = asyncio.get_running_loop()

        async with self._lock:
            # Recheck inside lock: maybe another worker just finished solving
            if not force and self.token and not self.is_expired(self.proactive_refresh_sec) and self.generation >= min_generation:
                return self.token

            # If a flight is already running, wait for it
            if self._current_flight is not None and not self._current_flight.done():
                flight = self._current_flight
            else:
                flight = loop.create_future()
                self._current_flight = flight

                # Launch single solve task
                asyncio.create_task(self._execute_single_flight(flight))

        return await flight

    async def _execute_single_flight(self, flight: asyncio.Future[str]) -> None:
        """Single runner executed for all concurrent waiters."""
        backoffs = [10, 30, 60, 120]
        try:
            fresh_token = await self._solve_waf()
            self.token = fresh_token
            self.obtained_at = time.time()
            self.generation += 1
            self.failure_count = 0

            log.info("aws-waf-token updated successfully (gen=%d, len=%d)", self.generation, len(fresh_token))

            if self.gateway:
                await self.gateway.set_cookie("aws-waf-token", fresh_token)

            self._save_cached_token(fresh_token)

            if not flight.done():
                flight.set_result(fresh_token)

        except Exception as exc:
            self.failure_count += 1
            idx = min(self.failure_count - 1, len(backoffs) - 1)
            delay = backoffs[idx]
            log.error("WAF solve failed (attempt %d): %s. Backoff %ds", self.failure_count, exc, delay)

            # Close page/context so next attempt creates clean context
            await self._recycle_context()

            if not flight.done():
                flight.set_exception(exc)

        finally:
            async with self._lock:
                if self._current_flight is flight:
                    self._current_flight = None

    async def _recycle_context(self) -> None:
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
            if self._context:
                await self._context.close()
        except Exception:
            pass
        self._page = None
        self._context = None

    def start_proactive_refresher(self) -> None:
        """Start background proactive token renewal."""
        if self._proactive_task is None or self._proactive_task.done():
            self._proactive_task = asyncio.create_task(self._proactive_loop())

    async def _proactive_loop(self) -> None:
        """Refreshes token before expiry in background."""
        while not self._closed:
            try:
                sleep_sec = max(60.0, self.proactive_refresh_sec - 120.0)
                await asyncio.sleep(sleep_sec)
                log.info("Proactive WAF token refresh triggered...")
                await self.get_token(force=True)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Proactive WAF refresh encountered error: %s", exc)
                await asyncio.sleep(30.0)

    async def aclose(self) -> None:
        """Shut down Playwright browser and background loops."""
        self._closed = True
        if self._proactive_task:
            self._proactive_task.cancel()
            try:
                await self._proactive_task
            except asyncio.CancelledError:
                pass

        await self._recycle_context()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None


class BuildIdManager:
    """Thread/Task-safe BuildId manager with Canary validation for 404 disambiguation."""

    def __init__(
        self,
        gateway: HttpGateway,
        waf_manager: WafTokenManager | None = None,
        initial_build_id: str | None = None,
    ) -> None:
        self.gateway = gateway
        self.waf_manager = waf_manager
        self.build_id = initial_build_id or os.getenv("SKOOL_BUILD_ID")
        self.fetched_at: float = time.time() if self.build_id else 0.0
        self.generation: int = 1 if self.build_id else 0

        self._lock = asyncio.Lock()
        self._current_flight: asyncio.Future[str] | None = None

    async def get_build_id(self, force: bool = False, min_generation: int = 0) -> str:
        """Get or refresh Next.js buildId with Single-Flight synchronization."""
        if not force and self.build_id and self.generation >= min_generation:
            return self.build_id

        loop = asyncio.get_running_loop()

        async with self._lock:
            if not force and self.build_id and self.generation >= min_generation:
                return self.build_id

            if self._current_flight is not None and not self._current_flight.done():
                flight = self._current_flight
            else:
                flight = loop.create_future()
                self._current_flight = flight
                asyncio.create_task(self._fetch_build_id_flight(flight))

        return await flight

    async def _fetch_build_id_flight(self, flight: asyncio.Future[str]) -> None:
        try:
            # Ensure WAF token is available first if WafTokenManager is attached
            if self.waf_manager:
                try:
                    await self.waf_manager.get_token()
                except Exception as exc:
                    log.warning("WAF token fetch before buildId returned: %s", exc)

            resp = await self.gateway.execute(f"{BASE_URL}/discovery")

            # If blocked or 202, try solving WAF once and re-request
            if resp.status_class in (ResponseClass.WAF_CHALLENGE, ResponseClass.WAF_BLOCK) and self.waf_manager:
                log.info("WAF challenge encountered while fetching buildId; solving token...")
                await self.waf_manager.get_token(force=True)
                resp = await self.gateway.execute(f"{BASE_URL}/discovery")

            body = resp.raw_text or ""
            match = BUILD_ID_RE.search(body)
            if not match:
                raise RuntimeError(
                    f"buildId regex not matched in /discovery response (HTTP {resp.http_status}, {len(body)} chars)"
                )

            fresh_build_id = match.group(1)
            previous = self.build_id
            self.build_id = fresh_build_id
            self.fetched_at = time.time()
            self.generation += 1

            if previous and previous != fresh_build_id:
                log.warning("Next.js buildId refreshed: %s -> %s (gen=%d)", previous, fresh_build_id, self.generation)
            else:
                log.info("Next.js buildId obtained: %s (gen=%d)", fresh_build_id, self.generation)

            if not flight.done():
                flight.set_result(fresh_build_id)

        except Exception as exc:
            log.error("Failed to fetch buildId: %s", exc)
            if not flight.done():
                flight.set_exception(exc)
        finally:
            async with self._lock:
                if self._current_flight is flight:
                    self._current_flight = None

    async def check_canary(self) -> bool:
        """Validate if the current build_id is active by requesting a guaranteed Canary URL.

        Returns:
            True: Canary succeeds (OK/200), meaning current build_id is valid!
            False: Canary returns 404/NOT_FOUND, meaning current build_id is STALE!
        """
        current_id = await self.get_build_id()
        canary_url = CANARY_URL_TEMPLATE.format(base=BASE_URL, build_id=current_id)

        resp = await self.gateway.execute(canary_url)
        if resp.status_class == ResponseClass.OK:
            return True
        elif resp.status_class == ResponseClass.NOT_FOUND:
            log.warning("Canary URL returned 404 -> build_id '%s' is STALE", current_id)
            return False
        else:
            # Transient or WAF issue; do not assume stale build_id
            return True

    async def handle_not_found(self, requested_url: str) -> tuple[bool, str]:
        """Disambiguate a 404 response.

        Returns:
            (is_stale, active_build_id)
            - If is_stale=True: build_id was refreshed; request can be retried immediately.
            - If is_stale=False: build_id is valid; entity is genuinely GONE.
        """
        is_canary_valid = await self.check_canary()
        if not is_canary_valid:
            # Canary failed -> Build ID changed on the server!
            log.warning("Disambiguation: 404 on %s was caused by STALE build_id. Refreshing...", requested_url)
            new_id = await self.get_build_id(force=True)
            return True, new_id

        # Canary passed -> True 404 (Entity is deleted or private)
        current_id = await self.get_build_id()
        return False, current_id
