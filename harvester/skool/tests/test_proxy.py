"""Tests for proxy configuration and rotation — offline, no network or database.

    python -m unittest skool.tests.test_proxy -v
"""

from __future__ import annotations

import os
import unittest

from ..proxy import ProxyPool, _parse_text, _normalize_entry, load_proxies


class TestNormalize(unittest.TestCase):
    def test_schemes(self) -> None:
        self.assertEqual(_normalize_entry("http://h:1"), "http://h:1")
        self.assertEqual(_normalize_entry("https://h:1"), "https://h:1")
        self.assertEqual(_normalize_entry("socks4://h:1"), "socks4://h:1")
        self.assertEqual(_normalize_entry("socks5://h:1"), "socks5://h:1")
        self.assertEqual(_normalize_entry("socks5h://h:1"), "socks5h://h:1")

    def test_scheme_less(self) -> None:
        self.assertEqual(_normalize_entry("host:8080"), "http://host:8080")
        self.assertEqual(
            _normalize_entry("user:pass@host:8080"), "http://user:pass@host:8080"
        )

    def test_invalid(self) -> None:
        self.assertIsNone(_normalize_entry(""))
        self.assertIsNone(_normalize_entry("  "))
        self.assertIsNone(_normalize_entry("#comment"))
        self.assertIsNone(_normalize_entry("ftp://host:1"))
        self.assertIsNone(_normalize_entry("plain"))


class TestParseText(unittest.TestCase):
    def test_separators_and_dedup(self) -> None:
        text = "http://a:1 socks5://b:2,http://c:3;\n#comment\nhttp://a:1\n"
        self.assertEqual(
            _parse_text(text), ["http://a:1", "socks5://b:2", "http://c:3"]
        )

    def test_empty(self) -> None:
        self.assertEqual(_parse_text(""), [])
        self.assertEqual(_parse_text("# only a comment"), [])


class TestLoadProxies(unittest.TestCase):
    def test_cli_wins_over_env(self) -> None:
        os.environ["SKOOL_PROXIES"] = "http://env:80"
        try:
            result = load_proxies(cli="http://cli:80")
            self.assertEqual(result, ["http://cli:80"])
        finally:
            os.environ.pop("SKOOL_PROXIES", None)

    def test_env_fallback(self) -> None:
        os.environ["SKOOL_PROXIES"] = "socks5://env:1080"
        try:
            self.assertEqual(load_proxies(), ["socks5://env:1080"])
        finally:
            os.environ.pop("SKOOL_PROXIES", None)

    def test_nothing(self) -> None:
        for key in (
            "SKOOL_PROXIES",
            "PROXY_LIST_FILE",
            "ALL_PROXY",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "all_proxy",
            "https_proxy",
            "http_proxy",
        ):
            os.environ.pop(key, None)
        self.assertEqual(load_proxies(), [])


class TestProxyPool(unittest.TestCase):
    def test_single(self) -> None:
        pool = ProxyPool(["http://a:1"])
        self.assertTrue(pool.enabled)
        self.assertFalse(pool.has_backup())
        self.assertEqual(pool.current(), "http://a:1")
        self.assertEqual(pool.advance(), "http://a:1")  # no backup list, returns itself

    def test_empty(self) -> None:
        pool = ProxyPool([])
        self.assertFalse(pool.enabled)
        self.assertIsNone(pool.current())
        self.assertIsNone(pool.advance())

    def test_rotation_and_wrap(self) -> None:
        pool = ProxyPool(["a", "b", "c"])
        self.assertEqual(pool.current(), "a")
        self.assertEqual(pool.advance(), "b")
        self.assertFalse(pool.wrapped())
        self.assertEqual(pool.advance(), "c")
        self.assertEqual(pool.advance(), "a")  # full rotation
        self.assertTrue(pool.wrapped())

    def test_dedup(self) -> None:
        pool = ProxyPool(["a", "a", "b", "b"])
        self.assertEqual(pool.size, 2)


if __name__ == "__main__":
    unittest.main()
