"""Database writes — fully resistant to race conditions.

Golden rule: no read-modify-write anywhere. Every insert/update is an atomic
INSERT ... ON CONFLICT DO UPDATE:

* KEEP_FIRST → coalesce(current, new)   i.e. fill only if NULL
* everything else → coalesce(new, current)  i.e. the newest non-NULL value wins
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Group, GroupMetric, User, UserGroup, UserMetric

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


def _snapshot_group_metrics(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> None:
    """Append one group_metrics row per written group (same transaction)."""
    snapshots = []
    for row in rows:
        snapshot = {"group_id": row["id"]}
        for field in _GROUP_METRIC_FIELDS:
            value = row.get(field)
            # Numeric column wants Decimal/None, not "" — parser already
            # emits clean values, but stay defensive.
            snapshot[field] = value if value is not None else None
        snapshots.append(snapshot)
    if not snapshots:
        return
    session.add_all([GroupMetric(**s) for s in snapshots])


def _snapshot_user_metrics(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> None:
    """Append one user_metrics row per written user (same transaction).

    `owned_groups` is filled by the caller when known (link_user_groups); here
    it stays NULL — the nightly snapshot command records the authoritative
    count.
    """
    snapshots = []
    for row in rows:
        snapshot = {"user_id": row["id"]}
        for field in _USER_METRIC_FIELDS:
            snapshot[field] = row.get(field)
        snapshots.append(snapshot)
    if not snapshots:
        return
    session.add_all([UserMetric(**s) for s in snapshots])


async def upsert_groups(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    rows = [row for row in rows if row and row.get("id") and row.get("name")]
    if not rows:
        return 0
    rows = _normalize(_dedupe(_project(rows, GROUP_COLUMNS), "id"))
    if not rows:
        return 0

    written = 0
    group_columns = [column.key for column in Group.__table__.columns]
    for chunk in _batches(rows, columns=group_columns):
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
        await session.execute(stmt)
        _snapshot_group_metrics(session, chunk)
        written += len(chunk)
    return written


async def upsert_group(session: AsyncSession, row: dict[str, Any]) -> int:
    return await upsert_groups(session, [row])


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
    _snapshot_user_metrics(session, [clean])


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

    for chunk in _batches(rows):
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
            _snapshot_user_metrics(session, chunk[:inserted])
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
    session: AsyncSession, limit: int = 500
) -> list[tuple[str, str]]:
    """Groups whose about.json details have not been fetched."""
    stmt = (
        select(Group.id, Group.name)
        .where(Group.detail_fetched.is_(False))
        .where(Group.name.is_not(None))
        .limit(limit)
    )
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
