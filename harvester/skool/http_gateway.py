"""Centralized HTTP Gateway and Response Classifier for Skool harvesting.

Features:
- Single long-lived curl_cffi.requests.AsyncSession with connection reuse.
- Browser impersonation ("chrome") with consistent User-Agent.
- Shared cookie jar with atomic runtime updates for auth_token and aws-waf-token.
- Strict response classification per redesign plan:
  OK, AUTH_EXPIRED, GONE, WAF_SOFT, WAF_CHALLENGE, WAF_BLOCK, RATE_LIMIT, NOT_FOUND, TRANSIENT.
- Raw response persistence into skool.raw_responses for diagnostics/offline reparse.
- Real-time latency and status counters for observability.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from curl_cffi import requests as cffi

log = logging.getLogger("skool.http_gateway")

# Standard Chromium User-Agent matching Playwright headless browser on Windows
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate, br",
    "referer": "https://www.skool.com/discovery",
}


class ResponseClass(str, Enum):
    OK = "OK"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    GONE = "GONE"
    WAF_SOFT = "WAF_SOFT"
    WAF_CHALLENGE = "WAF_CHALLENGE"
    WAF_BLOCK = "WAF_BLOCK"
    RATE_LIMIT = "RATE_LIMIT"
    NOT_FOUND = "NOT_FOUND"
    TRANSIENT = "TRANSIENT"


@dataclass
class ClassifiedResponse:
    status_class: ResponseClass
    http_status: int | None
    data: dict[str, Any] | None
    raw_text: str | None
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0
    error_message: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.status_class == ResponseClass.OK

    @property
    def page_props(self) -> dict[str, Any]:
        """Extract Next.js pageProps if present."""
        if isinstance(self.data, dict):
            props = self.data.get("pageProps")
            if isinstance(props, dict):
                return props
        return {}


class ResponseClassifier:
    """Deterministic classifier for all HTTP responses and exceptions."""

    @staticmethod
    def classify(
        http_status: int,
        text: str,
        headers: Mapping[str, str],
        url: str,
    ) -> tuple[ResponseClass, dict[str, Any] | None, str | None]:
        """Classify HTTP response based on status code, headers, and parsed content.

        Returns:
            (ResponseClass, parsed_json_dict_or_None, error_or_reason_string)
        """
        # 1. 200 OK: Must have valid JSON + pageProps (for Next.js data routes)
        if http_status == 200:
            if not text or not text.strip():
                return ResponseClass.WAF_SOFT, None, "HTTP 200 with empty body"

            try:
                parsed = json.loads(text)
            except Exception:
                # 200 OK but HTML or broken JSON -> soft challenge or WAF intercept
                return ResponseClass.WAF_SOFT, None, "HTTP 200 with non-JSON (HTML/challenge) body"

            if not isinstance(parsed, dict):
                return ResponseClass.WAF_SOFT, None, "HTTP 200 with non-object JSON body"

            # If Next.js data route, check pageProps
            if "/_next/data/" in url:
                if "pageProps" not in parsed:
                    return ResponseClass.WAF_SOFT, parsed, "Next.js data response missing pageProps"

                page_props = parsed.get("pageProps")
                if not isinstance(page_props, dict):
                    return ResponseClass.WAF_SOFT, parsed, "pageProps is not a dictionary"

                redirect = page_props.get("__N_REDIRECT")
                if redirect:
                    if "/login" in str(redirect):
                        return ResponseClass.AUTH_EXPIRED, parsed, f"Redirect to login: {redirect}"
                    return ResponseClass.GONE, parsed, f"Redirected to non-login path: {redirect}"

                if page_props.get("notFound") is True or page_props.get("is404") is True:
                    return ResponseClass.GONE, parsed, "Entity marked notFound in pageProps"

            return ResponseClass.OK, parsed, None

        # 2. 202 Challenge
        if http_status == 202:
            # Occasionally a 202 contains valid JSON pageProps
            if text and ("pageProps" in text or "buildId" in text):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and "pageProps" in parsed:
                        return ResponseClass.OK, parsed, None
                except Exception:
                    pass
            return ResponseClass.WAF_CHALLENGE, None, "HTTP 202 AWS WAF Challenge"

        # 3. 403 Forbidden / WAF block
        if http_status == 403:
            return ResponseClass.WAF_BLOCK, None, "HTTP 403 Forbidden / AWS WAF Block"

        # 4. 429 Rate Limit
        if http_status == 429:
            return ResponseClass.RATE_LIMIT, None, "HTTP 429 Too Many Requests"

        # 5. 404 Not Found (Caller handles canary check to disambiguate from STALE BUILD_ID)
        if http_status == 404:
            return ResponseClass.NOT_FOUND, None, "HTTP 404 Not Found"

        # 6. 5xx Server Errors & Transient issues
        if 500 <= http_status < 600:
            return ResponseClass.TRANSIENT, None, f"HTTP {http_status} Server Error"

        # Any other code
        return ResponseClass.TRANSIENT, None, f"HTTP {http_status} Unexpected Status"

    @staticmethod
    def classify_exception(exc: Exception, url: str) -> tuple[ResponseClass, str]:
        """Classify network/transport level exceptions."""
        exc_str = str(exc)
        return ResponseClass.TRANSIENT, f"Transport exception: {type(exc).__name__}: {exc_str}"


class HttpGateway:
    """Thread-safe and async connection-reusing HTTP gateway."""

    def __init__(
        self,
        impersonate: str = "chrome",
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: float = 30.0,
        cookies: dict[str, str] | None = None,
        proxies: dict[str, str] | None = None,
    ) -> None:
        self.impersonate = impersonate
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self._proxies = proxies
        self._cookies: dict[str, str] = dict(cookies or {})

        self._session: cffi.AsyncSession | None = None
        self._lock = asyncio.Lock()
        self._closed = False

        # Live telemetry counters
        self.stats: dict[str, int] = {
            "total_requests": 0,
            "class_ok": 0,
            "class_auth_expired": 0,
            "class_gone": 0,
            "class_waf_soft": 0,
            "class_waf_challenge": 0,
            "class_waf_block": 0,
            "class_rate_limit": 0,
            "class_not_found": 0,
            "class_transient": 0,
        }

    async def _get_or_create_session(self) -> cffi.AsyncSession:
        if self._session is not None:
            return self._session

        async with self._lock:
            if self._session is not None:
                return self._session

            headers = dict(DEFAULT_HEADERS)
            headers["user-agent"] = self.user_agent

            self._session = cffi.AsyncSession(
                impersonate=self.impersonate,
                headers=headers,
                timeout=self.timeout_s,
                proxies=self._proxies,
                cookies=dict(self._cookies),
            )
            return self._session

    async def set_cookie(self, name: str, value: str) -> None:
        """Update a cookie in the shared jar without breaking connection reuse."""
        async with self._lock:
            self._cookies[name] = value
            if self._session is not None:
                # Update in session cookie jar directly
                self._session.cookies[name] = value

    async def update_tokens(self, waf_token: str | None = None, auth_token: str | None = None) -> None:
        """Atomically update WAF and/or Auth tokens."""
        async with self._lock:
            if waf_token:
                self._cookies["aws-waf-token"] = waf_token
                if self._session is not None:
                    self._session.cookies["aws-waf-token"] = waf_token
            if auth_token:
                self._cookies["auth_token"] = auth_token
                if self._session is not None:
                    self._session.cookies["auth_token"] = auth_token

    def get_cookie(self, name: str) -> str | None:
        return self._cookies.get(name)

    async def execute(
        self,
        url: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
        timeout_s: float | None = None,
    ) -> ClassifiedResponse:
        """Execute HTTP request and return strongly-typed ClassifiedResponse."""
        session = await self._get_or_create_session()
        start_time = time.perf_counter()
        timeout = timeout_s or self.timeout_s

        merged_headers = dict(session.headers)
        if headers:
            merged_headers.update(headers)

        self.stats["total_requests"] += 1

        try:
            resp = await session.request(
                method=method,
                url=url,
                params=params,
                headers=merged_headers,
                data=data,
                timeout=timeout,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            resp_headers = dict(resp.headers)
            body_text = resp.text

            status_class, parsed_data, err_msg = ResponseClassifier.classify(
                http_status=resp.status_code,
                text=body_text,
                headers=resp_headers,
                url=url,
            )

            # Record metrics
            stat_key = f"class_{status_class.value.lower()}"
            if stat_key in self.stats:
                self.stats[stat_key] += 1

            return ClassifiedResponse(
                status_class=status_class,
                http_status=resp.status_code,
                data=parsed_data,
                raw_text=body_text,
                url=url,
                headers=resp_headers,
                latency_ms=elapsed_ms,
                error_message=err_msg,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            status_class, err_msg = ResponseClassifier.classify_exception(exc, url)

            stat_key = f"class_{status_class.value.lower()}"
            if stat_key in self.stats:
                self.stats[stat_key] += 1

            return ClassifiedResponse(
                status_class=status_class,
                http_status=None,
                data=None,
                raw_text=None,
                url=url,
                headers={},
                latency_ms=elapsed_ms,
                error_message=err_msg,
            )

    async def record_raw_response(
        self,
        kind: str,
        key: str,
        response: ClassifiedResponse,
        session_scope_func: Any,
    ) -> None:
        """Persist raw response into skool.raw_responses if needed."""
        if not session_scope_func:
            return

        from .db.models import RawResponse

        try:
            async with session_scope_func() as db_session:
                row = RawResponse(
                    kind=kind,
                    key=key,
                    http_status=response.http_status,
                    body=response.data,
                )
                db_session.add(row)
        except Exception as exc:
            log.warning("Failed to record raw response for key '%s': %s", key, exc)

    async def aclose(self) -> None:
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None
            self._closed = True

    async def __aenter__(self) -> HttpGateway:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
