"""Snapshot the current metrics of every group and user into history tables.

Two append-only tables (`skool.group_metrics`, `skool.user_metrics`) store one
row per entity per run, so long-run time-series charts are possible:

    group_metrics: price_usd, members, online, posts, admins, rules,
                   courses, modules, affiliate %
    user_metrics:  followers, following, contributions, owned-group count

The command copies the LIVE values out of `groups` / `users` in a single
INSERT ... SELECT per table — fast enough to run on the whole database.

Run:
    uv run python -m skool.snapshot_metrics            # dry-run counts
    uv run python -m skool.snapshot_metrics --write    # insert snapshots

Idempotence note: snapshots are intentionally NOT deduplicated — each run is
one point on the timeline. If you run twice in a minute you get two nearly
identical points; schedule it (e.g. daily) instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text as sql_text

from .db.db import dispose_db, session_scope

log = logging.getLogger("skool.snapshot_metrics")

GROUP_SNAPSHOT_SQL = sql_text("""
    INSERT INTO skool.group_metrics
        (group_id, captured_at, price_usd, total_members, total_online_members,
         total_posts, total_admins, total_rules, num_courses, num_modules,
         afl_percent)
    SELECT g.id, now(), g.price_usd, g.total_members, g.total_online_members,
           g.total_posts, g.total_admins, g.total_rules, g.num_courses,
           g.num_modules, g.afl_percent
    FROM skool.groups g
    WHERE g.id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM skool.group_metrics m
          WHERE m.group_id = g.id AND m.captured_at >= now() - interval '1 hour'
      )
""")

USER_SNAPSHOT_SQL = sql_text("""
    INSERT INTO skool.user_metrics
        (user_id, captured_at, total_followers, total_following,
         total_contributions, owned_groups)
    SELECT u.id, now(), u.total_followers, u.total_following,
           u.total_contributions,
           (SELECT count(*) FROM skool.groups og WHERE og.owner_id = u.id)
    FROM skool.users u
    WHERE u.id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM skool.user_metrics m
          WHERE m.user_id = u.id AND m.captured_at >= now() - interval '1 hour'
      )
""")


async def _counts(session) -> tuple[int, int]:
    groups = (
        await session.execute(sql_text("SELECT count(*) FROM skool.groups"))
    ).scalar()
    users = (
        await session.execute(sql_text("SELECT count(*) FROM skool.users"))
    ).scalar()
    return int(groups or 0), int(users or 0)


async def snapshot(write: bool = False) -> None:
    async with session_scope() as session:
        groups_total, users_total = await _counts(session)

        if not write:
            log.info(
                "Dry-run: %s groups and %s users would be snapshotted "
                "(pass --write)",
                f"{groups_total:,}",
                f"{users_total:,}",
            )
            return

        result = await session.execute(GROUP_SNAPSHOT_SQL)
        # rowcount for INSERT...SELECT is the number of inserted rows
        g_inserted = result.rowcount or 0
        result = await session.execute(USER_SNAPSHOT_SQL)
        u_inserted = result.rowcount or 0

    log.info("=" * 46)
    log.info("Snapshots written")
    log.info("  group_metrics: %s rows (of %s groups)", f"{g_inserted:,}", f"{groups_total:,}")
    log.info("  user_metrics:  %s rows (of %s users)", f"{u_inserted:,}", f"{users_total:,}")

    # show how much history we have now
    async with session_scope() as session:
        gm = (
            await session.execute(sql_text("SELECT count(*) FROM skool.group_metrics"))
        ).scalar()
        um = (
            await session.execute(sql_text("SELECT count(*) FROM skool.user_metrics"))
        ).scalar()
        distinct_g = (
            await session.execute(
                sql_text("SELECT count(DISTINCT group_id) FROM skool.group_metrics")
            )
        ).scalar()
        distinct_u = (
            await session.execute(
                sql_text("SELECT count(DISTINCT user_id) FROM skool.user_metrics")
            )
        ).scalar()
    log.info(
        "History totals: group_metrics=%s rows / %s groups | "
        "user_metrics=%s rows / %s users",
        f"{gm:,}",
        f"{distinct_g:,}",
        f"{um:,}",
        f"{distinct_u:,}",
    )


async def _run(write: bool) -> None:
    try:
        await snapshot(write=write)
    finally:
        # dispose inside the SAME event loop that owns the connections
        await dispose_db()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Snapshot current group/user metrics into history tables"
    )
    parser.add_argument(
        "--write", action="store_true", help="insert snapshots (default: dry-run)"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    asyncio.run(_run(write=args.write))


if __name__ == "__main__":
    main()
