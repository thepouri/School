"""HTTP client for _next/data.

curl_cffi with impersonate="chrome" — real Chrome TLS/JA3 fingerprint. No token
or cookies needed; discovery is public.

403 here means IP rate-limiting, not a fingerprint problem. So an immediate
retry only makes things worse: we have a global cooldown that stops every task
at once, with a step-wise increasing duration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import Any

from curl_cffi import requests as cffi

from .proxy import ProxyPool

log = logging.getLogger(__name__)

BASE_URL = "https://www.skool.com"
BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')
IMPERSONATE = os.getenv("SKOOL_IMPERSONATE", "chrome")

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "referer": f"{BASE_URL}/discovery",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.10; rv:40.0) Gecko/20100101 Firefox/40.0"
}

# Realistic browser user-agents. One is picked per proxy/connection so that a
# fresh IP + fresh fingerprint is presented together on each rotation.
USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
)

# Cooldown steps for consecutive 403s (seconds). With multiple proxies each
# rate-limit jumps to the next proxy and the cooldown is only for the last hop.
COOLDOWN_STEPS = (60, 120, 300, 600)


class SkoolClient:
    def __init__(
        self,
        build_id: str | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        min_delay: float = 0.0,
        max_delay: float = 0.0,
        pace: float = 0.0,
        proxies: str | list[str] | None = None,
        proxy_file: str | None = None,
        cookies: str | dict[str, str] | None = None,
    ) -> None:
        self.build_id = build_id or os.getenv("SKOOL_BUILD_ID") or None
        self.retries = retries
        self.min_delay = min_delay
        self.max_delay = max_delay
        # Minimum interval between the start of any two requests app-wide (seconds)
        self.pace = pace
        self._pace_lock = asyncio.Lock()
        self._next_slot = 0.0

        # ── account pool (multi-account rotation) ──
        # `cookies` may be a raw cookie string, a dict, or a cookies file with
        # one auth_token per line (one account per line). The pool lets the
        # client switch to the next account when a token expires or is blocked.
        self.accounts: list[dict[str, str]] = self._parse_accounts(cookies)
        if not self.accounts:
            self.accounts = [{}]
        self._account_index = 0
        self.cookies = dict(self.accounts[0])
        # any WAF token we solved ourselves (or the user provided); kept separate
        # so a fresh browser-generated one can replace an expired user token
        self._waf_token = self.cookies.pop("aws-waf-token", None)
        self._waf_lock = asyncio.Lock()
        self._waf_tried = False
        self._waf_force_count = 0

        self._impersonate = IMPERSONATE
        self._timeout = timeout
        self._build_lock = asyncio.Lock()
        self._proxies = None
        self._current_map: dict[str, str] | None = None
        self._session: cffi.AsyncSession | None = None
        self._ua_index = 0

        # Cooldown gate: open = passage allowed
        self._gate = asyncio.Event()
        self._gate.set()
        self._cool_lock = asyncio.Lock()
        self._cool_level = 0

        self.stats: dict[str, int] = {
            "requests": 0,
            "ok": 0,
            "not_found": 0,
            "errors": 0,
            "blocked": 0,
            "rate_limited": 0,
            "cooldowns": 0,
            "build_refresh": 0,
            "proxy_switches": 0,
            "proxy_os_error": 0,
            "proxy_ratelimit": 0,
            "account_switches": 0,
        }
        self._set_proxies(proxies, proxy_file)
        self.stats["proxy_count"] = self._proxies.size if self._proxies else 0
        # Build the session from the final map (none / single proxy)
        self._session = self._new_session(self._current_map)

    @staticmethod
    def _parse_accounts(cookies: str | dict[str, str] | None) -> list[dict[str, str]]:
        """Build the account pool from --cookies.

        Accepted inputs:
          * a cookies FILE with one auth_token per line (# comments allowed)
            — each non-empty line is one account:
                eyJhbGci...
                eyJhbGci...
          * a raw cookie string 'auth_token=...;aws-waf-token=...' → 1 account
          * a dict of cookie names → values → 1 account
          * a file whose lines are 'auth_token=...;...' strings also works
        """
        if not cookies:
            return []
        if isinstance(cookies, dict):
            return [dict(cookies)]

        text = cookies
        # a path that exists → read the file
        if len(cookies) < 500 and os.path.isfile(cookies):
            try:
                with open(cookies, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                return []

        accounts: list[dict[str, str]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip().strip('"').strip("'")
            if not line or line.startswith("#"):
                continue
            parsed: dict[str, str] = {}
            for part in line.split(";"):
                if "=" in part:
                    name, value = part.split("=", 1)
                    parsed[name.strip()] = value.strip()
            if "auth_token" not in parsed and line.count(".") == 2:
                # a bare JWT on its own line (header.payload.signature)
                parsed = {"auth_token": line}
            if parsed.get("auth_token"):
                accounts.append(parsed)
        # dedupe identical tokens, keep order
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for account in accounts:
            token = account["auth_token"]
            if token not in seen:
                seen.add(token)
                unique.append(account)
        return unique

    def _switch_account(self) -> bool:
        """Move to the next account. Returns False when there is no other
        account to switch to (single-account setup)."""
        if len(self.accounts) <= 1:
            return False
        self._account_index = (self._account_index + 1) % len(self.accounts)
        self.cookies = dict(self.accounts[self._account_index])
        # the old WAF token belongs to the old account's session — drop it so
        # a fresh one is solved for this account
        self._waf_token = None
        self._waf_tried = False
        self._session = self._new_session(self._current_map)
        self.stats["account_switches"] += 1
        log.warning(
            "Switched to account #%s (%s total)",
            self._account_index + 1,
            len(self.accounts),
        )
        return True

    def _set_proxies(
        self, proxies: str | list[str] | None, proxy_file: str | None
    ) -> None:
        """Load the proxies and determine the current map.

        Switching the proxy mid-session is not possible in curl_cffi, so each
        time the proxy changes we build a fresh session (`_swap_to_proxy`).
        The proxy key for libcurl itself: "all".
        """
        from .proxy import load_proxies

        raw = proxies
        if isinstance(raw, list):
            raw = ", ".join(raw)
        if raw is None:
            raw = os.getenv("PROXY_LIST_FILE")

        pool = ProxyPool(load_proxies(cli=raw, path=proxy_file))
        self._proxies = pool
        current = pool.current() if pool.enabled else None
        self._current_map = {"all": current} if current is not None else None

    def _new_session(self, session_map: dict[str, str] | None) -> cffi.AsyncSession:
        # A fresh user-agent per connection: fresh IP + fresh UA together
        # makes the pool look like distinct real browsers.
        self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
        headers = dict(HEADERS)
        headers["user-agent"] = USER_AGENTS[self._ua_index]
        cookies = dict(self.cookies) if self.cookies else None
        if self._waf_token:
            if cookies is None:
                cookies = {}
            cookies["aws-waf-token"] = self._waf_token
        return cffi.AsyncSession(
            impersonate=self._impersonate,
            headers=headers,
            timeout=self._timeout,
            proxies=session_map,
            cookies=cookies,
        )

    def _drop_proxies(self) -> None:
        """Drops all proxies — when every one of them has failed.

        Continue with a direct connection (maybe the proxies had the problem,
        not our IP).
        """
        self._proxies = None
        self._current_map = None
        self._session = self._new_session(None)

    def _has_auth(self) -> bool:
        """Whether we hold an auth_token to seed a WAF solve with."""
        return bool(self.cookies and self.cookies.get("auth_token"))

    async def _ensure_waf_token(self, force: bool = False) -> bool:
        """Solve a fresh `aws-waf-token` via Playwright.

        `force=True` re-solves even if we already hold a token (used when a
        202/403 shows the current token expired). When forced solves keep
        failing, the client rotates to the NEXT ACCOUNT and solves a fresh WAF
        token for it — that is how an expired/banned account is skipped in the
        members mode with a multi-account cookies file.

        Returns True when a (fresh) token is set on the client.
        """
        if self._waf_token and not force:
            return True
        if self._waf_tried and not force:
            return False
        self._waf_tried = True

        from .waf import get_waf_token

        # up to 2 forced re-solves per account before rotating accounts
        while True:
            if force:
                self._waf_force_count += 1
                if self._waf_force_count > 2 * max(1, len(self.accounts)):
                    log.warning("WAF keeps failing after all account attempts")
                    return bool(self._waf_token)
            if not self._has_auth():
                log.warning("auth_token missing — cannot solve AWS WAF challenge")
                return False

            try:
                log.info(
                    "Solving AWS WAF challenge (headless browser, account #%s)…",
                    self._account_index + 1,
                )
                token = await asyncio.to_thread(
                    get_waf_token, self.cookies["auth_token"]
                )
                self._waf_token = token
                self._session = self._new_session(self._current_map)
                self._waf_force_count = 0  # success resets the per-account cap
                log.info("aws-waf-token obtained (%s chars)", len(token))
                return True
            except Exception as exc:  # noqa: BLE001 - playwright fails many ways
                log.warning(
                    "WAF token solve failed for account #%s: %s",
                    self._account_index + 1,
                    exc,
                )
                # this account is probably dead/expired → try the next one;
                # _switch_account returns False when there is only one account
                if not self._switch_account():
                    return bool(self._waf_token)
                # loop again: solve for the new account

    def _swap_to_proxy(self) -> None:
        """Jump to the next proxy — build a fresh session since the proxy
        cannot be changed mid-session."""
        nextproxy = self._proxies.advance()
        self._current_map = {"all": nextproxy} if nextproxy else None
        self._session = self._new_session(self._current_map)
        self.stats["proxy_switches"] += 1

    async def __aenter__(self) -> "SkoolClient":
        await self.ensure_build_id()
        if self._proxies:
            log.info("Proxy active: %s", self._proxies.describe())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._session.close()

    # ──────────── global cooldown ────────────

    async def _cool_down(self) -> None:
        """Stops every task, but only one actually sleeps."""
        if not self._gate.is_set():
            await self._gate.wait()
            return

        async with self._cool_lock:
            if not self._gate.is_set():  # someone else got here first
                await self._gate.wait()
                return
            seconds = COOLDOWN_STEPS[min(self._cool_level, len(COOLDOWN_STEPS) - 1)]
            self._cool_level += 1
            self.stats["cooldowns"] += 1
            self._gate.clear()
            log.warning(
                "Persistent 403 — IP rate-limited. Whole pipeline stops for %s seconds",
                seconds,
            )
            try:
                await asyncio.sleep(seconds)
            finally:
                self._gate.set()

    async def _wait_turn(self) -> None:
        """Global pacemaker.

        The semaphore limits concurrent requests but not a burst: 2 tasks can
        fire 20 requests in one second. That is exactly what creates 403s.
        """
        if self.pace <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self._pace_lock:
            now = loop.time()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.pace
        delay = slot - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)

    def _cooled_ok(self) -> None:
        """A successful response lowers the cooldown level by one step."""
        if self._cool_level:
            self._cool_level -= 1

    # ──────────── buildId ────────────

    async def ensure_build_id(
        self, force: bool = False, stale: str | None = None
    ) -> str:
        async with self._build_lock:
            if self.build_id and not force:
                return self.build_id

            # If another task changed buildId in between, don't re-fetch.
            if stale is not None and self.build_id and self.build_id != stale:
                return self.build_id

            previous = self.build_id
            # buildId is a prerequisite for everything; if the proxies are dead
            # we should sweep the whole wheel rather than give up after the
            # default 3 tries.
            tries = 0
            max_tries = max(self.retries * 5, 30) if self._proxies else self.retries
            response = None
            while response is None and tries < max_tries:
                tries += 1
                response, _ = await self._get(f"{BASE_URL}/discovery")
                if response is None and tries < max_tries:
                    log.warning(
                        "buildId still not fetched (try %s/%s) — next proxy…",
                        tries,
                        max_tries,
                    )
            if response is None:
                if previous:
                    return previous
                raise RuntimeError(
                    "Could not fetch the discovery page — proxies/network are failing"
                )

            match = BUILD_ID_RE.search(response.text)
            if not match:
                if previous:
                    return previous
                raise RuntimeError("buildId not found in HTML")

            self.build_id = match.group(1)
            if previous and previous != self.build_id:
                self.stats["build_refresh"] += 1
                log.warning("buildId changed: %s -> %s", previous, self.build_id)
            elif not previous:
                log.info("buildId = %s", self.build_id)
            return self.build_id

    # ──────────── core ────────────

    async def _get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> tuple[Any | None, int | None]:
        """Returns (response, status code). The code is needed to tell 404
        apart from 403."""
        last_status: int | None = None
        attempt = 0
        rattles = 0  # independent rate-limit counter — capped so the loop can't run forever
        while attempt < self.retries:
            attempt += 1
            await self._gate.wait()  # wait while cooldown is in progress
            await self._wait_turn()
            if self.max_delay > 0:
                await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))

            try:
                self.stats["requests"] += 1
                response = await self._session.get(url, params=params)
            except Exception as exc:  # noqa: BLE001 — curl_cffi raises varied errors
                self.stats["errors"] += 1
                log.warning(
                    "Network error (%s/%s) %s : %s", attempt, self.retries, url, exc
                )
                if self._mark_failure("network"):
                    self._drop_proxies()
                await asyncio.sleep(min(2**attempt, 10))
                continue

            last_status = response.status_code

            if last_status == 200:
                self.stats["ok"] += 1
                self._cooled_ok()
                return response, 200

            if last_status == 202:
                # Skool sometimes answers a 202 bot-challenge page (HTML without
                # data) and other times a real 202 with the payload inside.
                # Judge by content, not status.
                body = response.text
                if '"buildId"' in body or '"pageProps"' in body:
                    self.stats["ok"] += 1
                    self._cooled_ok()
                    return response, 202
                # Challenge page — no real data. If authenticated, force a fresh
                # WAF token (the old one expired), then rotate proxy.
                self.stats["blocked"] += 1
                if self._has_auth():
                    await self._ensure_waf_token(force=True)
                    attempt -= 1
                    continue
                if self._mark_failure("ratelimit"):
                    await self._cool_down()
                attempt -= 1
                continue

            if last_status == 404:
                self.stats["not_found"] += 1
                return None, 404

            if last_status in (403, 429):
                # Rate-limit does not count as a failed attempt (or we'd lose the page).
                key = "blocked" if last_status == 403 else "rate_limited"
                self.stats[key] += 1
                # A 403 with auth could be a WAF rejection of an expired token.
                if last_status == 403 and self._has_auth():
                    await self._ensure_waf_token(force=True)
                    attempt -= 1
                    continue
                wrapped = self._mark_failure("ratelimit")
                # Global cooldown: after a full rotation or when no proxy at all
                if wrapped or not (self._proxies and self._proxies.has_backup()):
                    await self._cool_down()
                # Independent cap for rate-limits
                rattles += 1
                if rattles >= len(COOLDOWN_STEPS) + self.retries:
                    log.warning(
                        "Rate-limit repeated too many times (%s) — giving up on %s",
                        rattles,
                        url,
                    )
                    return None, last_status
                attempt -= 1
                continue

            if last_status >= 500:
                self.stats["errors"] += 1
                wait = min(2**attempt, 15)
                log.warning("Response %s for %s — waiting %s seconds", last_status, url, wait)
                await asyncio.sleep(wait)
                continue

            self.stats["errors"] += 1
            log.warning("Unexpected response %s for %s", last_status, url)
            return None, last_status

        log.warning(
            "After %s failed attempts (last status %s): %s",
            self.retries,
            last_status,
            url,
        )
        return None, last_status

    def _mark_failure(self, kind: str) -> bool:
        """Record a failure and swap the proxy.

        With multiple proxies it jumps. Returns "we reached the start of the
        list" i.e. a full rotation, so a global cooldown should run. With a
        single proxy or none, only stats are recorded and the cooldown is
        handled by `_get` itself.
        """
        if self._proxies and self._proxies.has_backup():
            if kind == "network":
                self.stats["proxy_os_error"] += 1
            self._swap_to_proxy()
            return self._proxies.wrapped()
        self.stats["proxy_ratelimit" if kind == "ratelimit" else "proxy_os_error"] += 1
        return False

    async def get_json(
        self, suffix: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """suffix like 'discovery.json' or '%40name.json'."""
        # Authenticated callers (member_search) need a WAF token. If we only
        # have auth_token, solve for a fresh aws-waf-token automatically —
        # once per run.
        if self._has_auth() and not self._waf_token and "/-/search.json" in suffix:
            await self._ensure_waf_token()
        build_id = await self.ensure_build_id()
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}

        response, status = await self._get(
            f"{BASE_URL}/_next/data/{build_id}/{suffix}", clean
        )

        # Only 404 could mean the buildId expired. 403 has nothing to do with it.
        if response is None and status == 404:
            fresh = await self.ensure_build_id(force=True, stale=build_id)
            if fresh == build_id:
                return None
            response, _ = await self._get(
                f"{BASE_URL}/_next/data/{fresh}/{suffix}", clean
            )

        if response is None:
            return None

        try:
            return response.json()
        except ValueError:
            self.stats["errors"] += 1
            log.warning("Response was not JSON: %s", suffix)
            return None

    # ──────────── endpoints ────────────

    async def discovery(
        self,
        page: int = 1,
        category_id: str | None = None,
        language: str | None = None,
        price: str | None = None,
        sort: str | None = None,
        group_type: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any] | None:
        """Map the parameters per function v(e) in the site itself.

        When a query is present, Skool itself drops the sort (sort: x ? void 0 : B).
        """
        params: dict[str, Any] = {"p": page}
        if query:
            params["q"] = query
        else:
            if category_id:
                params["c"] = category_id
            if sort:
                params["srt"] = sort
        if language:
            params["lang"] = language
        if price:
            params["pr"] = price
        if group_type:
            params["ty"] = group_type
        return await self.get_json("discovery.json", params)

    async def user_profile(self, user_name: str) -> dict[str, Any] | None:
        handle = user_name.lstrip("@")
        return await self.get_json(f"%40{handle}.json", {"group": f"@{handle}"})

    async def group_about(self, group_name: str) -> dict[str, Any] | None:
        return await self.get_json(f"{group_name}/about.json", {"group": group_name})

    async def member_search(
        self,
        query: str,
        page: int = 1,
        group_name: str = "skoolers",
        tab: str = "members",
    ) -> dict[str, Any] | None:
        """Authenticated member search within a group's members list.

        URL:  {group}/-/search.json?q=<query>&t=members&group=<group>&p=<page>
        Requires the `auth_token` cookie (the members/search endpoints are
        behind login). Returns up to 1000 members per page.

        Auth-failure handling: a dead/expired account does NOT return an HTTP
        error — Skool answers 200 with a JSON body of {__N_REDIRECT: /login…}.
        When that marker is seen, the client rotates to the next account
        (solving a fresh WAF token for it) and retries, instead of returning
        empty results forever.
        """
        suffix = f"{group_name}/-/search.json"
        params = {"q": query, "t": tab, "group": group_name, "p": page}
        attempts = 0
        max_account_attempts = max(1, len(self.accounts))
        while True:
            payload = await self.get_json(suffix, params)
            props = (payload or {}).get("pageProps") or {}
            if "__N_REDIRECT" not in props:
                return payload

            # this account is dead/expired → next one (with a fresh WAF solve)
            attempts += 1
            log.warning(
                "Auth redirect on account #%s — token expired/banned", self._account_index + 1
            )
            switched = self._switch_account()
            if not switched and attempts >= max_account_attempts:
                log.error("All accounts rejected — check your auth_tokens")
                return None
            # fresh WAF token for whichever account we are on now
            await self._ensure_waf_token(force=True)
            if not switched:
                # single account: retrying with the same dead token is futile
                return None
