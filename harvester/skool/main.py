"""Entry point.

Requirements:
    uv pip install curl_cffi sqlalchemy asyncpg
    set DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/pouri

Examples:
    python -m apps.skool.main --reset-db --mode browse --categories tech --languages english
    python -m apps.skool.main --mode search --queries ai crypto fitness
    python -m apps.skool.main --mode details
    python -m apps.skool.main --mode all
    python -m apps.skool.main --mode all --proxies socks5://user:pass@host:1080 http://host:8080
    python -m apps.skool.main --mode all --proxies-file proxies.txt

Note: the schema changed (the plans table was removed and new columns added).
Run once with `--reset-db`, because `--init-db` does not add new columns to
an existing table.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .constants import CATEGORIES, LANGUAGES, PRICES, SORTS, TYPES, default_query_plan
from .db.db import dispose_db, init_db, reset_db, session_scope
from .pipeline import Pipeline
from .scraper import SkoolClient

log = logging.getLogger("skool")

# Project root: the directory containing main.py. Relative proxy paths
# (--proxies-file proxy.txt) resolve against this, not against cwd.
PROJECT_ROOT = Path(__file__).resolve().parent


def configure_logging(level: str) -> None:
    # The Windows console sometimes breaks on Persian text and emoji
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skool discovery harvester")
    parser.add_argument(
        "--mode",
        choices=(
            "browse",
            "search",
            "details",
            "users",
            "members",
            "complete",
            "refresh",
            "missing-owners",
            "missing_owners",
            "all",
        ),
        default="all",
    )
    parser.add_argument(
        "--missing-owners-batch",
        type=int,
        default=200,
        help="groups per batch in missing-owners mode (default: 200)",
    )
    parser.add_argument(
        "--missing-owners-max-groups",
        type=int,
        default=None,
        help="cap on groups enriched in missing-owners mode (default: all)",
    )
    parser.add_argument("--init-db", action="store_true", help="create schema and tables")
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="drop the whole skool schema and rebuild (needed after column changes)",
    )

    parser.add_argument("--categories", nargs="*", default=list(CATEGORIES.keys()))
    parser.add_argument(
        "--languages",
        nargs="*",
        default=list(LANGUAGES),
        help="language name (not code). 'none' means no lang parameter",
    )
    parser.add_argument("--prices", nargs="*", default=list(PRICES))
    parser.add_argument("--sorts", nargs="*", default=list(SORTS))
    parser.add_argument(
        "--types",
        nargs="*",
        default=["none"],
        help=f"one of {list(TYPES)} or none for no type filter",
    )

    parser.add_argument("--queries", nargs="*", default=None)
    parser.add_argument(
        "--search-languages",
        nargs="*",
        default=["all"],
        help=(
            "languages to search per keyword. Default: all languages. "
            "Pass 'none' for no language parameter, or a specific language."
        ),
    )
    parser.add_argument(
        "--search-users",
        action="store_true",
        help="on the query path also read details and owner profiles",
    )
    parser.add_argument("--no-users", action="store_true", help="disable the user stage")
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="do not read group about.json (discovery only)",
    )

    parser.add_argument("--build-id", default=None, help="manual buildId (optional)")

    parser.add_argument("--page-concurrency", type=int, default=4)
    parser.add_argument("--detail-concurrency", type=int, default=8)
    parser.add_argument(
        "--include-bigrams",
        action="store_true",
        default=False,
        help="include 676 exhaustive two-letter bigram combinations in search queries",
    )
    parser.add_argument("--max-pages", type=int, default=34)
    parser.add_argument("--min-delay", type=float, default=0.3)
    parser.add_argument("--max-delay", type=float, default=1.0)
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        help="minimum interval between any two requests across the whole app (anti-403)",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--proxies",
        nargs="*",
        default=None,
        help=(
            "proxy list for automatic rotation on failure. "
            "Each entry like socks5://user:pass@host:port. "
            "A single proxy just routes traffic; several enable failover."
        ),
    )
    parser.add_argument(
        "--proxies-file",
        default=None,
        help=(
            "proxy list file (one per line, # for comments). "
            "The PROXY_LIST_FILE env var is also supported."
        ),
    )
    parser.add_argument(
        "--cookies",
        default=None,
        help=(
            "raw cookie string, OR a cookies.txt file. Required for the member-"
            "search mode. A file may hold MULTIPLE accounts — one auth_token "
            "per line (# comments allowed); on an expired/blocked account the "
            "client switches to the next one and solves a fresh WAF token for "
            "it. Single-account string: 'auth_token=eyJ...'"
        ),
    )
    parser.add_argument(
        "--member-search-group",
        default="skoolers",
        help="group whose members to search (default: skoolers)",
    )
    parser.add_argument(
        "--member-search-queries",
        nargs="*",
        default=None,
        help="explicit member-search queries (default: alphabet + digits only)",
    )
    parser.add_argument(
        "--member-search-pages",
        type=int,
        default=None,
        help="cap on pages per member-search query (default: all)",
    )
    parser.add_argument(
        "--member-search-concurrency",
        type=int,
        default=8,
        help="parallel requests within a member-search query (default: 8)",
    )
    parser.add_argument(
        "--complete-batch",
        type=int,
        default=100,
        help="users per batch in the complete pass (default: 100)",
    )
    parser.add_argument(
        "--refresh-max-groups",
        type=int,
        default=None,
        help="cap on groups re-fetched in refresh mode (default: all)",
    )
    parser.add_argument(
        "--refresh-max-users",
        type=int,
        default=None,
        help="cap on users re-fetched in refresh mode (default: all)",
    )
    parser.add_argument(
        "--refresh-days",
        type=float,
        default=None,
        help=(
            "refresh mode only: re-fetch just entities whose last update is "
            "older than N days (e.g. --refresh-days 7). Fresh ones are skipped "
            "without a request. Default: refresh everything"
        ),
    )
    return parser


def _norm(values: list[str] | None) -> list[str | None]:
    """Convert 'none' to None."""
    if not values:
        return [None]
    return [None if str(v).lower() in ("none", "null", "-") else v for v in values]


async def run(args: argparse.Namespace) -> None:
    if args.reset_db:
        await reset_db()
        log.info("Schema rebuilt from scratch")
        await dispose_db()
        return
    elif args.init_db:
        await init_db()
        log.info("Schema and tables ready")
        await dispose_db()
        return

    languages = _norm(args.languages)
    search_languages = (
        list(LANGUAGES)
        if args.search_languages and str(args.search_languages[0]).lower() == "all"
        else _norm(args.search_languages)
    )

    proxy_file = args.proxies_file
    if proxy_file and not Path(proxy_file).exists() and not Path(proxy_file).is_absolute():
        candidate = PROJECT_ROOT / proxy_file
        if candidate.exists():
            proxy_file = str(candidate)

    # resolve a relative cookies file against the project root too
    cookie_arg = args.cookies
    if (
        cookie_arg
        and "=" not in cookie_arg.split(";")[0]
        and not Path(cookie_arg).exists()
        and not Path(cookie_arg).is_absolute()
    ):
        candidate = PROJECT_ROOT / cookie_arg
        if candidate.exists():
            cookie_arg = str(candidate)

    client = SkoolClient(
        build_id=args.build_id,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        pace=args.pace,
        proxies=args.proxies,
        proxy_file=proxy_file,
        cookies=cookie_arg,
    )
    async with client:
        pipeline = Pipeline(
            client=client,
            page_concurrency=args.page_concurrency,
            detail_concurrency=args.detail_concurrency,
            max_pages=args.max_pages,
            fetch_users=not args.no_users,
        )

        if args.mode in ("browse", "all"):
            log.info("=== Path A: category-driven ===")
            await pipeline.run_browse(
                categories=args.categories,
                languages=languages,
                prices=_norm(args.prices),
                sorts=_norm(args.sorts),
                types=_norm(args.types),
                with_details=not args.no_details,
            )

        if args.mode in ("search", "all"):
            log.info("=== Path B: query-driven ===")
            # On the search path, details are read only when explicitly requested
            await pipeline.run_search(
                queries=args.queries or default_query_plan(include_bigrams=args.include_bigrams),
                languages=search_languages,
                with_details=args.search_users and not args.no_details,
            )

        if args.mode in ("details", "all"):
            log.info("=== Backlog details ===")
            await pipeline.run_details()

        if args.mode in ("users", "all"):
            if args.no_users:
                log.info("User stage disabled (--no-users)")
            else:
                log.info("=== Backlog owners ===")
                await pipeline.run_users()

        if args.mode == "members":
            log.info("=== Member search (authenticated user harvest) ===")
            await pipeline.run_member_search(
                queries=args.member_search_queries,
                group_name=args.member_search_group,
                max_pages=args.member_search_pages,
                concurrency=args.member_search_concurrency,
            )

        if args.mode == "complete":
            log.info("=== Complete users: profile → groups → details ===")
            await pipeline.run_complete_users(batch=args.complete_batch)

        if args.mode == "refresh":
            log.info("=== Full refresh: every group + user re-fetched ===")
            # about.json / public profiles need no login — no cookies required
            await pipeline.run_refresh(
                batch=200,
                max_groups=args.refresh_max_groups,
                max_users=args.refresh_max_users,
                skip_users=args.no_users,
                older_than_days=args.refresh_days,
            )

        if args.mode in ("missing-owners", "missing_owners"):
            log.info("=== Missing owners completion (2-tier recovery) ===")
            await pipeline.run_missing_owners(
                batch=args.missing_owners_batch,
                max_groups=args.missing_owners_max_groups,
            )

        log.info("Summary: %s", pipeline.stats.as_dict())
        log.info("Client: %s", client.stats)

    async with session_scope() as session:
        from .db import repository as repo

        totals = await repo.counts(session)
    log.info(
        "Database: groups=%s users=%s user_groups=%s",
        totals["groups"],
        totals["users"],
        totals["user_groups"],
    )
    await dispose_db()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.warning("Stopped by user")


if __name__ == "__main__":
    main()

