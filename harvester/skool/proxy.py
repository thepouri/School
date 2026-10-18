"""Proxy configuration for the Skool client.

Several ways to supply proxies, in priority order (first found wins):

    --proxy 'http://user:pass@host:port socks5://host:2'
    --proxies-file proxies.txt
    SKOOL_PROXIES                    (env var)
    PROXY_LIST_FILE                  (env var -> or a list file)
    HTTP_PROXY / HTTPS_PROXY / ALL_PROXY

Each source yields one or more proxies. Separators for multiple proxies
within a single string: space, comma, semicolon, or newline.

Proxy formats:
    http://host:port
    https://host:port
    socks4://host:port
    socks5://host:port
    socks5h://host:port            (delegates DNS resolution to the proxy)
    host:port                      (converted to http://host:port)
    user:pass@host:port            (converted to http://user:pass@host:port)

Lines starting with # are ignored. Duplicates are removed.

With multiple proxies, the client jumps to the next one on any failure
(network error, 403, 429). With a single proxy it stays put and the
project's global cooldown applies (proxy is treated as the last resort).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Valid schemes for g.d., libcurl
_VALID_SCHEMES = frozenset({"http", "https", "socks4", "socks5", "socks5h"})
_SPLIT_RE = re.compile(r"[\s,;]+")


def _read_file(path: str) -> str | None:
    """Return the proxy list file contents; None if missing / unreadable."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _normalize_entry(token: str) -> str | None:
    """Turn one raw token into a valid proxy URL (or None).

    Handles the common provider formats:
        host:port                 -> http://host:port
        user:pass@host:port       -> http://user:pass@host:port
        host:port:user:pass       -> http://user:pass@host:port
    """
    text = token.strip().strip("\"'")
    if not text or text.startswith("#"):
        return None
    if "://" in text:
        scheme = text.split("://", 1)[0].lower()
        if scheme in _VALID_SCHEMES:
            return text
        return None
    # No scheme — infer from the field layout.
    if "@" in text:
        # user:pass@host:port
        return f"http://{text}"
    parts = text.split(":")
    if len(parts) == 4 and parts[1].isdigit():
        # host:port:user:pass
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    if len(parts) == 2 and parts[1].isdigit():
        # host:port
        return f"http://{text}"
    return None


def _parse_text(text: str) -> list[str]:
    proxies: list[str] = []
    for token in _SPLIT_RE.split(text):
        if not token:
            continue
        normalized = _normalize_entry(token)
        if normalized:
            proxies.append(normalized)
    return list(dict.fromkeys(proxies))


def load_proxies(cli: str | None = None, path: str | None = None) -> list[str]:
    """Load the proxy list respecting priority.

    `cli` may be "one continuous list" or "a path to a file"; if the string
    looks like an existing path or starts with `file:`, it is read as a file.
    """
    text: str | None = None
    if cli:
        if cli.startswith("file:"):
            text = _read_file(cli.split(":", 1)[1])
        elif Path(cli).is_file():
            text = _read_file(cli)
        else:
            text = cli
    elif path:
        text = _read_file(path)

    if text and text.strip():
        loaded = _parse_text(text)
        if loaded:
            return loaded

    # Environment variables
    env = os.getenv("SKOOL_PROXIES")
    if env and env.strip():
        loaded = _parse_text(env)
        if loaded:
            return loaded
    env_file = os.getenv("PROXY_LIST_FILE")
    if env_file:
        loaded = _parse_text(_read_file(env_file) or "")
        if loaded:
            return loaded
    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
    ):
        value = os.getenv(name)
        if value and value.strip():
            loaded = _parse_text(value)
            if loaded:
                return loaded
    return []


class ProxyPool:
    """Proxy rotation pool.

    * `advance()` — move to the next proxy (called on "failure").
    * `current()` — the active proxy now, or None (i.e. no proxy).
    * `has_backup()` — we have more than one proxy (so rotation is meaningful).
    """

    def __init__(self, proxies: list[str]) -> None:
        self._list = list(dict.fromkeys(p for p in (proxies or []) if p))
        self._index = -1  # -1 = not started yet; current() yields the first one
        self._advances = 0  # advance counter so a full cycle can be detected

    @property
    def enabled(self) -> bool:
        return bool(self._list)

    @property
    def size(self) -> int:
        return len(self._list)

    def current(self) -> str | None:
        if not self._list:
            return None
        if self._index < 0:
            self._index = 0
        return self._list[self._index]

    def advance(self) -> str | None:
        """Move to the next proxy (cyclic)."""
        if not self._list:
            return None
        if self._index < 0:
            self._index = 0
            self._advances += 1
        self._index = (self._index + 1) % len(self._list)
        self._advances += 1
        return self._list[self._index]

    def has_backup(self) -> bool:
        return len(self._list) > 1

    def wrapped(self) -> bool:
        """Full cycle of the list (back to the starting proxy)?"""
        return self._advances > 0 and self._advances % len(self._list) == 0

    def describe(self) -> str:
        if not self._list:
            return "no proxy"
        if len(self._list) == 1:
            return self._list[0]
        return f"{len(self._list)} proxies"
