"""Probe every proxy in a list against Skool and keep only the working ones.

Each proxy is tested concurrently (asyncio + curl_cffi) by requesting
https://www.skool.com/discovery. Proxies that return an HTTP response in the
2xx/3xx range (or, with --keep-4xx, anything below 500) are kept; everything
else is removed from the file. The original file is backed up to proxy.txt.bak
and the dead proxies are saved to proxy_removed.txt so nothing is lost.

Usage:
    python test_proxies.py                        # test and prune proxy.txt
    python test_proxies.py --concurrency 100      # more parallel
    python test_proxies.py --timeout 5            # faster, stricter
    python test_proxies.py --dry-run              # only report, don't rewrite
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

from curl_cffi import requests as cffi

from proxy import _normalize_entry

DEFAULT_FILE = Path(__file__).resolve().parent / "proxy.txt"
DEFAULT_TARGET = "https://www.skool.com/discovery"


def _parse_lines(path: Path) -> list[tuple[str, str]]:
    """(normalized_proxy, original_line) preserving file order, deduped.

    Lines that are empty, comments, or unparseable are skipped.
    """
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)
    for raw in text.splitlines():
        normalized = _normalize_entry(raw)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        pairs.append((normalized, raw))
    return pairs


async def _probe(proxy: str, target: str, timeout: float) -> tuple[int | None, str | None]:
    """One proxy -> (status_code, body_marker | error). Network errors give (None, message)."""
    session = cffi.AsyncSession(
        impersonate="chrome",
        timeout=timeout,
        proxies={"all": proxy},
    )
    try:
        response = await session.get(target)
        body = response.text
        if _is_real_page(response.status_code, body):
            return response.status_code, None
        # Status/body says this proxy landed on a challenge, not the data.
        return response.status_code, "challenge-html"
    except Exception as exc:  # noqa: BLE001 - curl_cffi raises many error types
        return None, str(exc).splitlines()[0][:120]
    finally:
        await session.close()


def _is_real_page(status: int | None, body: str) -> bool:
    """A proxy "works" only when the target returned the actual data.

    Skool answers 202 + a ~2KB challenge/HTML page to suspicious IPs. That is
    NOT a working proxy for scraping — there is no buildId/JSON in it. So we
    accept only responses whose body carries the real payload marker.
    """
    if status not in (200, 202):
        return False
    return '"buildId"' in body or '"pageProps"' in body


async def run(
    pairs: list[tuple[str, str]],
    target: str,
    concurrency: int,
    timeout: float,
) -> list[tuple[str, str, int | None, str | None]]:
    """Test all proxies concurrently. Returns (proxy, line, status, error)."""
    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[str, str, int | None, str | None]] = []
    done = 0
    total = len(pairs)
    started = time.time()

    async def worker(pair: tuple[str, str]) -> None:
        nonlocal done
        proxy, line = pair
        async with sem:
            status, error = await _probe(proxy, target, timeout)
        results.append((proxy, line, status, error))
        done += 1
        if done % 25 == 0 or done == total:
            print(f"  probed {done}/{total}  ({time.time() - started:.0f}s)", flush=True)

    await asyncio.gather(*(worker(pair) for pair in pairs))
    return results


def _is_good(status: int | None, reason: str | None, keep_4xx: bool) -> bool:
    """Good == the target returned real JSON/data (not a challenge page)."""
    if status is None:
        return False
    if reason:
        return False  # challenge-html or a network error string — not real data
    if keep_4xx:
        return True  # --keep-4xx trusts any successful HTTP handshake
    return True


def _failure_reason(error: str | None) -> str:
    """Short human label for the common curl_cffi failure modes."""
    if not error:
        return "no-data"
    if "timed out" in error:
        return "timeout"
    if "CONNECT aborted" in error:
        return "proxy-rejected-CONNECT"
    if "SSL" in error:
        return "TLS-failure"
    if "Connection refused" in error:
        return "refused"
    if "challenge-html" in error:
        return "captcha-page"
    return error[:40]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe proxies against Skool and prune the dead ones.")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="proxy list file (default: proxy.txt)")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="URL to probe (default: skool discovery)")
    parser.add_argument("--concurrency", type=int, default=50, help="parallel probes (default: 50)")
    parser.add_argument("--timeout", type=float, default=8.0, help="seconds per probe (default: 8)")
    parser.add_argument("--keep-4xx", action="store_true", help="keep 4xx responses too (still reached the site)")
    parser.add_argument("--dry-run", action="store_true", help="only report; don't rewrite the file")
    args = parser.parse_args(argv)

    pairs = _parse_lines(args.file)
    if not pairs:
        print(f"no usable proxies in {args.file}", file=sys.stderr)
        return 1
    print(f"probing {len(pairs)} proxies against {args.target} "
          f"(concurrency={args.concurrency}, timeout={args.timeout}s)…")

    started = time.time()
    results = asyncio.run(run(pairs, args.target, args.concurrency, args.timeout))
    elapsed = time.time() - started

    statuses = Counter()
    good: list[tuple[str, str, int]] = []
    dead: list[tuple[str, str]] = []
    reasons: Counter = Counter()
    for proxy, line, status, error in results:
        if status is not None:
            statuses[status] += 1
        if _is_good(status, error, args.keep_4xx):
            good.append((proxy, line, status))
        else:
            dead.append((proxy, line))
            reasons[_failure_reason(error)] += 1

    print("\n" + "=" * 60)
    print(f"  {len(good)}/{len(pairs)} working  ({elapsed:.0f}s)")
    if statuses:
        top = ", ".join(f"{code}×{count}" for code, count in sorted(statuses.items()))
        print(f"  statuses: {top}")
    if reasons:
        why = ", ".join(f"{k}={count}" for count, k in sorted((v, k) for k, v in reasons.items()))
        print(f"  failures: {why}")
    if not good:
        print("  nothing worked — file left untouched", file=sys.stderr)
        return 1

    if args.dry_run:
        print("  (dry run — file not rewritten)")
        for proxy, _line, status in good[:20]:
            print(f"    OK {status} {proxy}")
        if len(good) > 20:
            print(f"    … and {len(good) - 20} more")
        return 0

    # backup + rewrite
    backup = args.file.with_suffix(args.file.suffix + ".bak")
    try:
        backup.write_text(args.file.read_text(encoding="utf-8"), encoding="utf-8")
        args.file.write_text(
            "\n".join(line for _proxy, line, _status in good) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"rewrite failed: {exc}", file=sys.stderr)
        return 1

    removed = args.file.with_name(args.file.stem + "_removed" + args.file.suffix)
    try:
        removed.write_text("\n".join(line for _proxy, line in dead) + "\n", encoding="utf-8")
    except OSError:
        pass  # writing the removed file is best-effort

    print(f"  kept  -> {args.file} ({len(good)} lines)")
    print(f"  removed -> {removed} ({len(dead)} lines)")
    print(f"  backup -> {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
