"""AWS WAF challenge solver.

Skool sits behind AWS WAF. The `aws-waf-token` cookie is issued after a
browser solves the (usually invisible) challenge, and it expires. This module
launches a headless Chromium via Playwright, seeds the `auth_token` cookie,
lets the challenge solve, and returns the fresh `aws-waf-token` value.

Used by the client when an authenticated request needs a WAF token: instead of
asking you to paste it from the browser's DevTools, we just generate one.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

BASE_URL = "https://www.skool.com"
SLUG = "/skoolers"


def get_waf_token(auth_token: str, timeout: int = 60) -> str:
    """Solve the AWS WAF challenge and return the `aws-waf-token` value.

    `auth_token` is the logged-in cookie that makes the page render as a real
    session. `timeout` caps how long we wait for the token to appear. Raises
    RuntimeError when the token is not obtained in time.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()

            context.add_cookies(
                [
                    {
                        "name": "auth_token",
                        "value": auth_token,
                        "domain": ".skool.com",
                        "path": "/",
                    }
                ]
            )

            page.goto(f"{BASE_URL}{SLUG}", wait_until="networkidle", timeout=timeout * 1000)

            token: str | None = None
            for _ in range(timeout):
                for cookie in context.cookies():
                    if cookie["name"] == "aws-waf-token":
                        token = cookie["value"]
                        break
                if token:
                    break
                page.wait_for_timeout(1000)  # 1 second between checks

            browser.close()

            if not token:
                raise RuntimeError("could not obtain aws-waf-token in time")
            return token
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - browser may already be closed
                pass