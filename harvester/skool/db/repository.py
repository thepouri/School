"""Database writes — fully resistant to race conditions.

Golden rule: no read-modify-write anywhere. Every insert/update is an atomic
INSERT ... ON CONFLICT DO UPDATE:

* KEEP_FIRST → coalesce(current, new)   i.e. fill only if NULL
* everything else → coalesce(new, current)  i.e. the newest non-NULL value wins
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Sequence

from sqlalchemy import case, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Group,
    GroupMetric,
    ScraperJob,
    ScraperLog,
    ScraperSettings,
    User,
    UserGroup,
    UserMetric,
)

log = logging.getLogger(__name__)

# Parametric fields and creation date: do not touch if already set
GROUP_KEEP_FIRST = frozenset(
    {
        "category_id",
        "category_slug",
        "language",
        "price_bucket",
        "sort_seen",
        "discovered_via",
        "created_at",
    }
)
# detail_fetched is a progress flag, changed only via mark_detail_fetched
GROUP_IMMUTABLE = frozenset({"id", "detail_fetched"})

USER_KEEP_FIRST = frozenset({"created_at"})
USER_IMMUTABLE = frozenset({"id", "groups_fetched"})

# The real columns of each table — parser rows must not send extra keys
GROUP_COLUMNS = frozenset(column.key for column in Group.__table__.columns)
USER_COLUMNS = frozenset(column.key for column in User.__table__.columns)

# The bind-parameter limit of a Postgres connection is ~32767 (PG >= 17) or
# 65535. One discovery slice can reach ~1020 rows × ~40 columns = ~40k
# parameters, and several slices running at once blow the cap. We break every
# statement into chunks below the limit.
#
# We stay well below the hard cap on purpose: some deployments run behind a
# proxy that lowers it, and the error is painful (a huge wasted insert).
_BIND_LIMIT = 30_000


def _batches(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str] | None = None,
) -> list[list[dict[str, Any]]]:
    """Chunk the rows so every statement stays under the bind-parameter cap.

    `columns` is the EXACT set of columns the statement will bind (including
    the primary key). It defaults to the rows' key set, but callers with a
    known schema must pass the real table columns — deriving the per-row
    param count from the rows alone is fragile: `pg_insert(Table).values(rows)`
    binds every column of the table, not just the keys the rows carry. If a
    row is missing a column (e.g. `id` is always present but a nullable column
    is absent), the derived count under-estimates and a chunk can overshoot the
    Postgres cap.
    """
    if not rows:
        return []
    keys = list(rows[0].keys())
    if not keys:
        return [list(rows)]
    per_row = len(columns) if columns is not None else len(keys)
    chunk_size = max(1, _BIND_LIMIT // per_row)
    return [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]


def _project(rows: Sequence[dict[str, Any]], columns: frozenset[str]) -> list[dict[str, Any]]:
    """Drop unknown keys."""
    return [
        {key: value for key, value in row.items() if key in columns} for row in rows
    ]


def _build_set(
    model: Any,
    columns: Sequence[str],
    excluded: Any,
    keep_first: frozenset[str],
    immutable: frozenset[str],
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for column in columns:
        if column in immutable:
            continue
        current = getattr(model, column)
        if column in keep_first:
            updates[column] = func.coalesce(current, excluded[column])
        else:
            updates[column] = func.coalesce(excluded[column], current)
    return updates


def _dedupe(rows: Sequence[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    """One ON CONFLICT statement cannot have the same key twice. Last record wins."""
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        merged[tuple(row.get(key) for key in keys)] = row
    return list(merged.values())


def _normalize(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """All rows must have exactly the same key set."""
    columns: set[str] = set()
    for row in rows:
        columns.update(row.keys())
    return [{column: row.get(column) for column in columns} for row in rows]


_GROUP_METRIC_FIELDS = (
    "price_usd",
    "total_members",
    "total_online_members",
    "total_posts",
    "total_admins",
    "total_rules",
    "num_courses",
    "num_modules",
    "afl_percent",
)

_USER_METRIC_FIELDS = (
    "total_followers",
    "total_following",
    "total_contributions",
)


async def _snapshot_group_metrics(
    session: AsyncSession,
    rows: Sequence[dict[str, Any]],
    mode: str = "initial_only",
) -> None:
    """Record group_metrics snapshots according to mode.

    * 'initial_only': ONLY write an initial snapshot if the group currently has ZERO
      records in skool.group_metrics. If a group already has any snapshot, Discovery
      never records another snapshot.
    * 'refresh': Append a new periodic snapshot (deduplicated within 24h / same calendar day).
    * 'none': Skip snapshots entirely.
    """
    if mode == "none" or not rows:
        return

    group_ids = [row["id"] for row in rows if row and row.get("id")]
    if not group_ids:
        return

    if mode == "initial_only":
        stmt = (
            select(GroupMetric.group_id)
            .where(GroupMetric.group_id.in_(group_ids))
            .distinct()
        )
        res = await session.execute(stmt)
        existing_with_metrics = set(res.scalars().all())

        snapshots = []
        for row in rows:
            gid = row.get("id")
            if not gid or gid in existing_with_metrics:
                continue
            snapshot = {"group_id": gid}
            for field in _GROUP_METRIC_FIELDS:
                value = row.get(field)
                snapshot[field] = value if value is not None else None
            snapshots.append(snapshot)

        if snapshots:
            session.add_all([GroupMetric(**s) for s in snapshots])
        return

    if mode == "refresh":
        # 3-day refresh mode: check latest snapshot per group to avoid duplicate on same day
        stmt = (
            select(GroupMetric)
            .distinct(GroupMetric.group_id)
            .where(GroupMetric.group_id.in_(group_ids))
            .order_by(GroupMetric.group_id, GroupMetric.captured_at.desc())
        )
        res = await session.execute(stmt)
        latest_map = {m.group_id: m for m in res.scalars().all()}

        now = datetime.now(timezone.utc)
        snapshots = []
        for row in rows:
            gid = row.get("id")
            if not gid:
                continue
            latest = latest_map.get(gid)
            if latest is not None:
                lat_dt = latest.captured_at
                if lat_dt.tzinfo is None:
                    lat_dt = lat_dt.replace(tzinfo=timezone.utc)
                age_s = (now - lat_dt).total_seconds()

                changed = (
                    row.get("total_members") != latest.total_members
                    or row.get("total_online_members") != latest.total_online_members
                    or row.get("total_posts") != latest.total_posts
                    or row.get("price_usd") != latest.price_usd
                    or row.get("total_admins") != latest.total_admins
                )
                if not changed and age_s < 86400:
                    continue

            snapshot = {"group_id": gid}
            for field in _GROUP_METRIC_FIELDS:
                value = row.get(field)
                snapshot[field] = value if value is not None else None
            snapshots.append(snapshot)

        if snapshots:
            session.add_all([GroupMetric(**s) for s in snapshots])


async def _snapshot_user_metrics(
    session: AsyncSession, rows: Sequence[dict[str, Any]]
) -> None:
    """Append user_metrics rows, skipping redundant identical snapshots within 24 hours."""
    user_ids = [row["id"] for row in rows if row and row.get("id")]
    if not user_ids:
        return

    stmt = (
        select(UserMetric)
        .distinct(UserMetric.user_id)
        .where(UserMetric.user_id.in_(user_ids))
        .order_by(UserMetric.user_id, UserMetric.captured_at.desc())
    )
    res = await session.execute(stmt)
    latest_map = {m.user_id: m for m in res.scalars().all()}

    now = datetime.now(timezone.utc)
    snapshots = []
    for row in rows:
        uid = row.get("id")
        if not uid:
            continue
        latest = latest_map.get(uid)
        if latest is not None:
            lat_dt = latest.captured_at
            if lat_dt.tzinfo is None:
                lat_dt = lat_dt.replace(tzinfo=timezone.utc)
            age_s = (now - lat_dt).total_seconds()

            changed = (
                row.get("total_followers") != latest.total_followers
                or row.get("total_following") != latest.total_following
                or row.get("total_contributions") != latest.total_contributions
            )
            if not changed and age_s < 86400:
                continue

        snapshot = {"user_id": uid}
        for field in _USER_METRIC_FIELDS:
            snapshot[field] = row.get(field)
        snapshots.append(snapshot)

    if snapshots:
        session.add_all([UserMetric(**s) for s in snapshots])


async def upsert_groups(
    session: AsyncSession,
    rows: Sequence[dict[str, Any]],
    snapshot_mode: str = "initial_only",
) -> int:
    rows = [row for row in rows if row and row.get("id") and row.get("name")]
    if not rows:
        return 0
    rows = _normalize(_dedupe(_project(rows, GROUP_COLUMNS), "id"))
    if not rows:
        return 0

    # Deterministic primary key sort prevents concurrent deadlocks
    rows.sort(key=lambda r: str(r.get("id", "")))

    written = 0
    group_columns = [column.key for column in Group.__table__.columns]
    for chunk in _batches(rows, columns=group_columns):
        # Guarantee chunk ordering
        chunk.sort(key=lambda r: str(r.get("id", "")))
        stmt = pg_insert(Group).values(chunk)
        updates = _build_set(
            Group,
            list(chunk[0].keys()),
            stmt.excluded,
            GROUP_KEEP_FIRST,
            GROUP_IMMUTABLE,
        )
        updates["scraped_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=[Group.id], set_=updates)

        # Execute with deadlock retry resilience
        for attempt in range(3):
            try:
                await session.execute(stmt)
                break
            except Exception as exc:
                if "deadlock detected" in str(exc).lower() and attempt < 2:
                    log.warning(
                        "Deadlock detected during upsert_groups; retrying in %.2fs (attempt %d/3)...",
                        0.2 * (2**attempt),
                        attempt + 1,
                    )
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                raise

        await _snapshot_group_metrics(session, chunk, mode=snapshot_mode)

        # Create and link stub users for any group with owner_id/owner_name
        has_owners = any(r.get("owner_id") for r in chunk)
        if has_owners:
            owner_stubs = [
                {
                    "id": r["owner_id"],
                    "name": r["owner_name"],
                    "full_name": r.get("owner_name"),
                }
                for r in chunk
                if r.get("owner_id") and r.get("owner_name")
            ]
            if owner_stubs:
                owner_stubs = _normalize(_dedupe(_project(owner_stubs, USER_COLUMNS), "id"))
                owner_stubs.sort(key=lambda u: str(u["id"]))
                if owner_stubs:
                    u_stmt = (
                        pg_insert(User)
                        .values(owner_stubs)
                        .on_conflict_do_nothing(index_elements=[User.id])
                    )
                    await session.execute(u_stmt)

            ug_links = [
                {"user_id": r["owner_id"], "group_id": r["id"], "role": "owner"}
                for r in chunk
                if r.get("owner_id")
            ]
            if ug_links:
                ug_links = _dedupe(ug_links, "user_id", "group_id")
                ug_links.sort(key=lambda x: (str(x["user_id"]), str(x["group_id"])))
                ug_stmt = (
                    pg_insert(UserGroup)
                    .values(ug_links)
                    .on_conflict_do_nothing(
                        index_elements=[UserGroup.user_id, UserGroup.group_id]
                    )
                )
                await session.execute(ug_stmt)

        written += len(chunk)
    return written


async def upsert_group(
    session: AsyncSession,
    row: dict[str, Any],
    snapshot_mode: str = "initial_only",
) -> int:
    return await upsert_groups(session, [row], snapshot_mode=snapshot_mode)


async def filter_unfetched_group_ids(
    session: AsyncSession, group_ids: Sequence[str]
) -> set[str]:
    """Return the set of group_ids that need detail fetching (detail_fetched is False)."""
    if not group_ids:
        return set()
    stmt = (
        select(Group.id)
        .where(Group.id.in_(group_ids))
        .where(Group.detail_fetched.is_(False))
    )
    res = await session.execute(stmt)
    return set(res.scalars().all())


async def upsert_user(session: AsyncSession, row: dict[str, Any]) -> None:
    if not row or not row.get("id") or not row.get("name"):
        return
    clean = _project([row], USER_COLUMNS)[0]
    stmt = pg_insert(User).values(**clean)
    updates = _build_set(
        User, list(clean.keys()), stmt.excluded, USER_KEEP_FIRST, USER_IMMUTABLE
    )
    updates["scraped_at"] = func.now()
    stmt = stmt.on_conflict_do_update(index_elements=[User.id], set_=updates)
    await session.execute(stmt)
    await _snapshot_user_metrics(session, [clean])


async def insert_missing_users(
    session: AsyncSession, rows: Sequence[dict[str, Any]]
) -> int:
    """Insert only NEW users — existing rows are left untouched.

    ON CONFLICT DO NOTHING, chunked under the bind-parameter cap. Used by the
    member-search harvester, which only wants to add users who aren't in the
    DB yet and never overwrite a richer profile already scraped.

    Returns the number of rows handed in (not necessarily inserted — the
    conflict-skip count is not reliably exposed by asyncpg).
    """
    rows = [row for row in rows if row and row.get("id") and row.get("name")]
    if not rows:
        return 0
    rows = _normalize(_dedupe(_project(rows, USER_COLUMNS), "id"))
    if not rows:
        return 0

    rows.sort(key=lambda r: str(r.get("id", "")))

    for chunk in _batches(rows):
        chunk.sort(key=lambda r: str(r.get("id", "")))
        stmt = (
            pg_insert(User)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        result = await session.execute(stmt)
        # only the actually-inserted rows get a history entry (skipped ones
        # already exist and were snapshotted by whoever wrote them before)
        inserted = result.rowcount if result.rowcount is not None else 0
        if inserted:
            await _snapshot_user_metrics(session, chunk[:inserted])
    return len(rows)


async def link_user_groups(
    session: AsyncSession,
    user_id: str,
    group_ids: Sequence[str],
    role: str | None = None,
) -> None:
    """Link a user to their groups.

    `role` is "owner" (the user created the group) or "member" (they joined
    it). Insertion is ON CONFLICT DO NOTHING, so a group is never linked twice
    and an existing link keeps its original role. Owner links are preferred: if
    a group is already linked as "member" and the user turns out to own it, the
    role is upgraded to "owner".
    """
    rows = [
        {"user_id": user_id, "group_id": group_id, "role": role}
        for group_id in dict.fromkeys(gid for gid in group_ids if gid)
    ]
    if not rows:
        return
    ug_columns = [column.key for column in UserGroup.__table__.columns]
    for chunk in _batches(rows, columns=ug_columns):
        if role == "owner":
            # Owner link wins: an existing "member" link is upgraded to owner;
            # an existing "owner" link stays owner; a NULL role is filled.
            stmt = (
                pg_insert(UserGroup)
                .values(chunk)
                .on_conflict_do_update(
                    index_elements=[UserGroup.user_id, UserGroup.group_id],
                    set_={
                        # owner if it was NULL or member; member never wins over owner
                        "role": case(
                            (UserGroup.role.is_(None), "owner"),
                            (UserGroup.role == "member", "owner"),
                            else_=UserGroup.role,
                        ),
                        "scraped_at": func.now(),
                    },
                )
            )
        else:
            # Member link: never overwrite anything (pure insert-if-missing).
            stmt = (
                pg_insert(UserGroup)
                .values(chunk)
                .on_conflict_do_nothing(
                    index_elements=[UserGroup.user_id, UserGroup.group_id]
                )
            )
        await session.execute(stmt)


async def mark_detail_fetched(session: AsyncSession, group_ids: Sequence[str]) -> None:
    """Flag that about.json for these groups has been fetched."""
    if not group_ids:
        return
    await session.execute(
        update(Group).where(Group.id.in_(list(group_ids))).values(detail_fetched=True)
    )


async def mark_user_scraped(session: AsyncSession, user_ids: Sequence[str]) -> None:
    if not user_ids:
        return
    await session.execute(
        update(User).where(User.id.in_(list(user_ids))).values(groups_fetched=True)
    )


async def pending_detail_groups(
    session: AsyncSession, limit: int = 500, after_id: str = ""
) -> list[tuple[str, str]]:
    """Groups whose about.json details have not been fetched."""
    stmt = (
        select(Group.id, Group.name)
        .where(Group.detail_fetched.is_(False))
        .where(Group.name.is_not(None))
    )
    if after_id:
        stmt = stmt.where(Group.id > after_id)
    stmt = stmt.order_by(Group.id).limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def all_groups(
    session: AsyncSession,
    after_id: str = "",
    limit: int = 500,
    older_than_days: float | None = None,
) -> list[tuple[str, str]]:
    """Groups in the DB (keyset pagination via id >).

    `older_than_days` restricts to groups whose latest metric snapshot (or
    scraped_at when never snapshotted) is older than N days — i.e. entities
    due for a refresh. Fresh ones are skipped entirely: no request, no
    duplicate metric row.
    """
    stmt = (
        select(Group.id, Group.name)
        .where(Group.name.is_not(None))
        .where(Group.id > after_id)
    )
    if older_than_days is not None:
        # make_interval(0,0,0,N) = N days; cutoff = now() - N days.
        # make_interval takes ints — cast the bound value explicitly.
        days = int(older_than_days) or 1
        cutoff = func.now() - func.make_interval(0, 0, 0, days)
        last_capture = (
            select(func.max(GroupMetric.captured_at))
            .where(GroupMetric.group_id == Group.id)
            .correlate(Group)
            .scalar_subquery()
        )
        stmt = stmt.where(
            func.coalesce(last_capture, Group.scraped_at, func.to_timestamp(0)) < cutoff
        )
    stmt = stmt.order_by(Group.id).limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def all_users(
    session: AsyncSession,
    after_id: str = "",
    limit: int = 500,
    older_than_days: float | None = None,
) -> list[tuple[str, str]]:
    """Users in the DB (keyset pagination via id >), with the same
    staleness filter as `all_groups`."""
    stmt = (
        select(User.id, User.name)
        .where(User.name.is_not(None))
        .where(User.id > after_id)
    )
    if older_than_days is not None:
        days = int(older_than_days) or 1
        cutoff = func.now() - func.make_interval(0, 0, 0, days)
        last_capture = (
            select(func.max(UserMetric.captured_at))
            .where(UserMetric.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        stmt = stmt.where(
            func.coalesce(last_capture, User.scraped_at, func.to_timestamp(0)) < cutoff
        )
    stmt = stmt.order_by(User.id).limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def pending_owner_users(
    session: AsyncSession, limit: int = 500
) -> list[tuple[str, str]]:
    """Owners whose profile has not been fetched yet."""
    stmt = (
        select(Group.owner_id, Group.owner_name)
        .where(Group.owner_name.is_not(None))
        .where(
            ~select(User.id)
            .where(User.name == Group.owner_name)
            .where(User.groups_fetched.is_(True))
            .exists()
        )
        .distinct()
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def pending_unscraped_users(
    session: AsyncSession, limit: int = 500
) -> list[tuple[str, str]]:
    """Registered users whose profile + groups have not been fetched yet.

    Includes users added by the member-search harvest (`groups_fetched=False`).
    """
    stmt = (
        select(User.id, User.name)
        .where(User.groups_fetched.is_(False))
        .where(User.name.is_not(None))
        .order_by(User.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def user_group_ids(
    session: AsyncSession, user_id: str
) -> list[tuple[str, str]]:
    """(group_id, group_name) of the groups a user owns."""
    stmt = (
        select(Group.id, Group.name)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user_id)
        .where(UserGroup.role == "owner")
        .where(Group.name.is_not(None))
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def group_is_fetched(session: AsyncSession, group_id: str) -> bool:
    """Whether the group's details are already complete in the database."""
    result = await session.execute(
        select(Group.detail_fetched).where(Group.id == group_id)
    )
    value = result.scalar()
    return bool(value)


async def user_is_scraped(session: AsyncSession, user_name: str) -> bool:
    """Whether the user's profile (and groups) are already complete."""
    result = await session.execute(
        select(User.groups_fetched).where(User.name == user_name)
    )
    value = result.scalar()
    return bool(value)


async def counts(session: AsyncSession) -> dict[str, int]:
    async def _count(model: Any) -> int:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar() or 0)

    return {
        "groups": await _count(Group),
        "users": await _count(User),
        "user_groups": await _count(UserGroup),
    }


# ────────────────── Missing Owners Completion ──────────────────


async def pending_missing_owner_groups(
    session: AsyncSession, limit: int = 500, after_id: str = ""
) -> list[tuple[str, str]]:
    """Groups where detail_fetched = True and (owner_id IS NULL or owner_name IS NULL)."""
    stmt = (
        select(Group.id, Group.name)
        .where(Group.detail_fetched.is_(True))
        .where((Group.owner_id.is_(None)) | (Group.owner_name.is_(None)))
        .where(Group.name.is_not(None))
    )
    if after_id:
        stmt = stmt.where(Group.id > after_id)
    stmt = stmt.order_by(Group.id.asc()).limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def heal_missing_owners_internally(session: AsyncSession) -> int:
    """Tier 1: Bidirectional zero-request owner healing.

    1. Links owner_id and owner_name onto groups missing owner data by checking
       skool.user_groups WHERE role = 'owner' and joining skool.users.
    2. Inserts stub user records into skool.users and links skool.user_groups
       for any group that has owner_id and owner_name but is missing in users.
    Returns the total count of healed records.
    """
    # 1. user_groups -> groups
    stmt1 = text(
        """
        UPDATE skool.groups g
        SET owner_id = ug.user_id,
            owner_name = u.name,
            updated_at = NOW()
        FROM skool.user_groups ug
        JOIN skool.users u ON u.id = ug.user_id
        WHERE ug.group_id = g.id
          AND ug.role = 'owner'
          AND (g.owner_id IS NULL OR g.owner_name IS NULL)
        """
    )
    res1 = await session.execute(stmt1)
    healed1 = int(res1.rowcount or 0)

    # 2. groups -> users
    stmt2 = text(
        """
        INSERT INTO skool.users (id, name, full_name, created_at, updated_at)
        SELECT DISTINCT g.owner_id, g.owner_name, g.owner_name, NOW(), NOW()
        FROM skool.groups g
        WHERE g.owner_id IS NOT NULL 
          AND g.owner_name IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM skool.users u WHERE u.id = g.owner_id)
        ON CONFLICT (id) DO NOTHING
        """
    )
    res2 = await session.execute(stmt2)
    healed2 = int(res2.rowcount or 0)

    # 3. groups -> user_groups
    stmt3 = text(
        """
        INSERT INTO skool.user_groups (user_id, group_id, role, scraped_at)
        SELECT DISTINCT g.owner_id, g.id, 'owner', NOW()
        FROM skool.groups g
        WHERE g.owner_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM skool.users u WHERE u.id = g.owner_id)
        ON CONFLICT (user_id, group_id) DO NOTHING
        """
    )
    await session.execute(stmt3)

    return healed1 + healed2


# ────────────────── Harvester Scheduler DB Integration ──────────────────


async def update_daemon_heartbeat(session: AsyncSession) -> None:
    """Update daemon_heartbeat_at in skool.scraper_settings on each daemon tick."""
    stmt = text(
        """
        INSERT INTO skool.scraper_settings (
            id, refresh_interval_days, discovery_interval_days, refresh_cron, discovery_cron, is_paused,
            discovery_mode, page_concurrency, detail_concurrency, request_delay_ms, include_bigrams,
            daemon_heartbeat_at, updated_at
        )
        VALUES (1, 3, 7, '0 2 */3 * *', '0 3 * * 0', false, 'all', 4, 8, 300, false, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE SET daemon_heartbeat_at = NOW()
        """
    )
    await session.execute(stmt)


async def get_scraper_settings(session: AsyncSession) -> dict[str, Any] | None:
    """Read dynamic intervals, cron expressions, pause state, and discovery settings from skool.scraper_settings."""
    stmt = select(
        ScraperSettings.refresh_interval_days,
        ScraperSettings.discovery_interval_days,
        ScraperSettings.refresh_cron,
        ScraperSettings.discovery_cron,
        ScraperSettings.is_paused,
        ScraperSettings.discovery_mode,
        ScraperSettings.page_concurrency,
        ScraperSettings.detail_concurrency,
        ScraperSettings.request_delay_ms,
        ScraperSettings.include_bigrams,
    ).where(ScraperSettings.id == 1)
    result = await session.execute(stmt)
    row = result.one_or_none()
    if not row:
        return None
    return {
        "refresh_interval_days": int(row[0]),
        "discovery_interval_days": int(row[1]),
        "refresh_cron": str(row[2]),
        "discovery_cron": str(row[3]),
        "is_paused": bool(row[4]),
        "discovery_mode": str(row[5] or "all"),
        "page_concurrency": int(row[6] or 4),
        "detail_concurrency": int(row[7] or 8),
        "request_delay_ms": int(row[8] if row[8] is not None else 300),
        "include_bigrams": bool(row[9] if row[9] is not None else False),
    }


async def claim_next_pending_job(session: AsyncSession) -> dict[str, Any] | None:
    """Atomically claim the next queued PENDING manual job using FOR UPDATE SKIP LOCKED."""
    stmt = text(
        """
        SELECT id, job_type, trigger_type
        FROM skool.scraper_jobs
        WHERE status = 'PENDING'
        ORDER BY created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """
    )
    result = await session.execute(stmt)
    row = result.fetchone()
    if not row:
        return None
    job_id, job_type, trigger_type = row[0], row[1], row[2]

    update_stmt = text(
        """
        UPDATE skool.scraper_jobs
        SET status = 'RUNNING', started_at = NOW()
        WHERE id = :job_id
        """
    )
    await session.execute(update_stmt, {"job_id": job_id})
    return {
        "id": int(job_id),
        "job_type": str(job_type),
        "trigger_type": str(trigger_type),
    }


async def create_scraper_job(
    session: AsyncSession,
    job_type: str,
    trigger_type: str = "scheduled",
    status: str = "RUNNING",
) -> int:
    """Create a new job entry in skool.scraper_jobs (e.g. for scheduled runs)."""
    stmt = text(
        """
        INSERT INTO skool.scraper_jobs (job_type, trigger_type, status, started_at, created_at)
        VALUES (:job_type, :trigger_type, :status, NOW(), NOW())
        RETURNING id
        """
    )
    result = await session.execute(
        stmt, {"job_type": job_type, "trigger_type": trigger_type, "status": status}
    )
    row = result.fetchone()
    return int(row[0]) if row else 0


async def insert_scraper_log(
    session: AsyncSession, job_id: int, level: str, message: str
) -> None:
    """Stream an execution output log line into skool.scraper_logs."""
    stmt = text(
        """
        INSERT INTO skool.scraper_logs (job_id, level, message, created_at)
        VALUES (:job_id, :level, :message, NOW())
        """
    )
    await session.execute(
        stmt, {"job_id": job_id, "level": level[:10], "message": message}
    )


async def insert_scraper_logs_batch(
    session: AsyncSession, logs: Sequence[tuple[int, str, str]]
) -> None:
    """Batch-insert execution output log lines into skool.scraper_logs."""
    if not logs:
        return
    for jid, lvl, msg in logs:
        stmt = text(
            """
            INSERT INTO skool.scraper_logs (job_id, level, message, created_at)
            VALUES (:job_id, :level, :message, NOW())
            """
        )
        await session.execute(
            stmt, {"job_id": jid, "level": lvl[:10], "message": msg}
        )


async def finish_scraper_job(
    session: AsyncSession,
    job_id: int,
    status: str,
    exit_code: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update completion state of a scraper job in skool.scraper_jobs."""
    stmt = text(
        """
        UPDATE skool.scraper_jobs
        SET status = :status,
            finished_at = NOW(),
            exit_code = :exit_code,
            error_message = :error_message
        WHERE id = :job_id
        """
    )
    await session.execute(
        stmt,
        {
            "job_id": job_id,
            "status": status,
            "exit_code": exit_code,
            "error_message": error_message,
        },
    )


async def is_scraper_job_cancelled(session: AsyncSession, job_id: int) -> bool:
    """Check if the job has been cancelled by an administrator."""
    stmt = text("SELECT status FROM skool.scraper_jobs WHERE id = :job_id")
    result = await session.execute(stmt, {"job_id": job_id})
    row = result.fetchone()
    if not row:
        return False
    return str(row[0]).upper() == "CANCELLED"


async def cleanup_dangling_running_jobs(session: AsyncSession) -> int:
    """Mark any stale RUNNING jobs as FAILED if daemon restarted unexpectedly."""
    stmt = text(
        """
        UPDATE skool.scraper_jobs
        SET status = 'FAILED',
            finished_at = NOW(),
            error_message = 'Daemon restarted while job was running'
        WHERE status = 'RUNNING'
        """
    )
    res = await session.execute(stmt)
    return int(res.rowcount or 0)

