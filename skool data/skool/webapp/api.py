"""Read-only database queries for the web UI.

Every function opens its own short session via `session_scope` and issues
plain parameterized SQL. No ORM models are used here (the web layer stays
decoupled) and nothing is ever written.

Filter semantics:
  * categorical filters (category, language, price_bucket, is_public) match
    the stored value exactly; missing values are never
    coerced.
  * numeric ranges (price_usd, total_members, num_courses, total_posts,
    total_followers, total_following) use half-open [min, max).
  * `q` is a case-insensitive LIKE across visible text columns.
  * `sort` maps to a fixed allowlist of ORDER BY expressions.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import text as sql_text

from ..db.db import session_scope

# ───────────────────────────── helpers ─────────────────────────────


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _run(session: Any, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await session.execute(sql_text(query), params)
    return [dict(row) for row in result.mappings()]


# ───────────────────────────── facet data ─────────────────────────────


async def get_facets_groups() -> dict[str, Any]:
    """Distinct values for the group filter bars."""
    async with session_scope() as session:
        async def fetch(table: str, column: str) -> list[dict[str, Any]]:
            return await _run(
                session,
                f"""
                SELECT {column} AS value, count(*) AS n
                FROM skool.{table}
                WHERE {column} IS NOT NULL AND {column} <> ''
                GROUP BY {column}
                ORDER BY n DESC, {column}
                """,
                {},
            )

        return {
            "categories": await fetch("groups", "category_slug"),
            "languages": await fetch("groups", "language"),
            "price_buckets": await fetch("groups", "price_bucket"),
            "currencies": await fetch("groups", "price_currency"),
            "intervals": await fetch("groups", "price_interval"),
            "has_prices": bool(
                (await session.execute(
                    sql_text(
                        "SELECT count(*) FROM skool.groups WHERE price_usd IS NOT NULL"
                    )
                )).scalar()
            ),
            "has_courses": bool(
                (await session.execute(
                    sql_text(
                        "SELECT count(*) FROM skool.groups WHERE num_courses IS NOT NULL"
                    )
                )).scalar()
            ),
        }


async def get_facets_users() -> dict[str, Any]:
    async with session_scope() as session:
        async def fetch(column: str) -> list[dict[str, Any]]:
            return await _run(
                session,
                f"""
                SELECT {column} AS value, count(*) AS n
                FROM skool.users
                WHERE {column} IS NOT NULL AND {column} <> ''
                GROUP BY {column}
                ORDER BY n DESC, {column}
                """,
                {},
            )

        return {
            "location_sources": await fetch("location_source"),
            "timezones": await fetch("timezone"),
            "has_avatar": bool(
                (await session.execute(
                    sql_text(
                        "SELECT count(*) FROM skool.users WHERE avatar_url IS NOT NULL"
                    )
                )).scalar()
            ),
        }


# ───────────────────────────── groups ─────────────────────────────

_GROUP_LIST_COLUMNS = """
    g.id, g.name, g.display_name, g.description, g.lp_description,
    g.color, g.initials, g.cover_url, g.logo_url, g.logo_big_url,
    g.price_usd, g.price_currency, g.price_interval, g.price_bucket,
    g.total_members, g.total_online_members, g.total_posts,
    g.num_courses, g.num_modules, g.afl_percent,
    g.is_public, g.privacy, g.category_slug, g.language,
    g.owner_id, g.owner_name, g.detail_fetched,
    g.created_at, g.updated_at
"""

_GROUP_SORTS: dict[str, str] = {
    "members_desc": "g.total_members DESC NULLS LAST",
    "members_asc": "g.total_members ASC NULLS LAST",
    "price_desc": "g.price_usd DESC NULLS LAST",
    "price_asc": "g.price_usd ASC NULLS LAST",
    "courses_desc": "g.num_courses DESC NULLS LAST",
    "posts_desc": "g.total_posts DESC NULLS LAST",
    "newest": "g.created_at DESC NULLS LAST",
    "oldest": "g.created_at ASC NULLS LAST",
    "name": "g.name ASC",
    "relevance": "g.total_members DESC NULLS LAST",
}


def _group_where(params: dict[str, Any]) -> str:
    clauses: list[str] = []

    if params.get("category"):
        clauses.append("g.category_slug = :category")
    if params.get("language"):
        clauses.append("g.language = :language")
    if params.get("price_bucket"):
        clauses.append("g.price_bucket = :price_bucket")
    if params.get("currency"):
        clauses.append("g.price_currency = :currency")
    if params.get("interval"):
        clauses.append("g.price_interval = :interval")

    if params.get("is_public") in ("true", "false"):
        params["is_public"] = params["is_public"] == "true"
        clauses.append("g.is_public = :is_public")

    min_price = _num(params.get("min_price"))
    max_price = _num(params.get("max_price"))
    if min_price is not None:
        params["min_price"] = min_price
        clauses.append("g.price_usd >= :min_price")
    if max_price is not None:
        params["max_price"] = max_price
        clauses.append("g.price_usd < :max_price")

    min_members = _num(params.get("min_members"))
    max_members = _num(params.get("max_members"))
    if min_members is not None:
        params["min_members"] = int(min_members)
        clauses.append("g.total_members >= :min_members")
    if max_members is not None:
        params["max_members"] = int(max_members)
        clauses.append("g.total_members < :max_members")

    min_courses = _num(params.get("min_courses"))
    if min_courses is not None:
        params["min_courses"] = int(min_courses)
        clauses.append("g.num_courses >= :min_courses")

    min_posts = _num(params.get("min_posts"))
    if min_posts is not None:
        params["min_posts"] = int(min_posts)
        clauses.append("g.total_posts >= :min_posts")

    if params.get("detail") == "true":
        clauses.append("g.detail_fetched = true")
    if params.get("with_price") == "true":
        clauses.append("g.price_usd IS NOT NULL")

    q = (params.get("q") or "").strip()
    if q:
        params["q"] = f"%{q}%"
        clauses.append(
            """
            (
                g.name ILIKE :q OR g.display_name ILIKE :q
                OR g.description ILIKE :q OR g.owner_name ILIKE :q
            )
            """
        )

    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


async def query_groups(
    *,
    page: int = 1,
    per_page: int = 30,
    sort: str = "members_desc",
    q: str | None = None,
    category: str | None = None,
    language: str | None = None,
    price_bucket: str | None = None,
    currency: str | None = None,
    interval: str | None = None,
    is_public: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_members: int | None = None,
    max_members: int | None = None,
    min_courses: int | None = None,
    min_posts: int | None = None,
    detail: str | None = None,
    with_price: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": q,
        "category": category,
        "language": language,
        "price_bucket": price_bucket,
        "currency": currency,
        "interval": interval,
        "is_public": is_public,
    }
    where = _group_where(params)
    order = _GROUP_SORTS.get(sort, _GROUP_SORTS["members_desc"])
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 30)))
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    async with session_scope() as session:
        total = int(
            (
                await session.execute(
                    sql_text(f"SELECT count(*) FROM skool.groups g{where}"), params
                )
            ).scalar()
            or 0
        )
        rows = await _run(
            session,
            f"""
            SELECT {_GROUP_LIST_COLUMNS}
            FROM skool.groups g
            {where}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "items": rows,
    }


async def get_group_detail(group_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        rows = await _run(
            session,
            f"""
            SELECT {_GROUP_LIST_COLUMNS},
                   g.links, g.lp_description, g.src_group,
                   g.cover_url, g.logo_url, g.logo_big_url
            FROM skool.groups g
            WHERE g.id = :id
            """,
            {"id": group_id},
        )
        if not rows:
            return None
        group = rows[0]
        # owner screenshot block merged below if the owner exists
        return group


async def get_group_owner(group_id: str) -> dict[str, Any] | None:
    """Owner record of a group (NULL when the group has no owner assigned)."""
    async with session_scope() as session:
        rows = await _run(
            session,
            """
            SELECT u.id, u.name, u.first_name, u.last_name, u.full_name,
                   u.bio, u.location, u.location_source, u.timezone,
                   u.avatar_url, u.avatar_bubble_url,
                   u.link_facebook, u.link_instagram, u.link_linkedin,
                   u.link_twitter, u.link_website, u.link_youtube,
                   u.total_followers, u.total_following,
                   u.total_contributions
            FROM skool.groups g
            JOIN skool.users u ON u.id = g.owner_id
            WHERE g.id = :id
            """,
            {"id": group_id},
        )
        return rows[0] if rows else None


# ───────────────────────────── users ─────────────────────────────

_USER_LIST_COLUMNS = """
    u.id, u.name, u.first_name, u.last_name, u.full_name,
    u.bio, u.location, u.location_source, u.timezone,
    u.avatar_url, u.avatar_bubble_url,
    u.link_facebook, u.link_instagram, u.link_linkedin,
    u.link_twitter, u.link_website, u.link_youtube,
    u.total_followers, u.total_following,
    u.total_contributions, u.groups_fetched,
    (SELECT count(*) FROM skool.groups g WHERE g.owner_id = u.id) AS owned_count
"""

_USER_SORTS: dict[str, str] = {
    "followers_desc": "u.total_followers DESC NULLS LAST, u.name ASC",
    "followers_asc": "u.total_followers ASC NULLS LAST",
    "owned_desc": "owned_count DESC, u.name ASC",
    "name": "u.name ASC",
    "relevance": "u.total_followers DESC NULLS LAST, u.name ASC",
}


def _user_where(params: dict[str, Any]) -> str:
    clauses: list[str] = []

    if params.get("location_source"):
        clauses.append("u.location_source = :location_source")
    if params.get("timezone"):
        clauses.append("u.timezone = :timezone")

    if params.get("has_avatar") == "true":
        clauses.append("u.avatar_url IS NOT NULL")
    if params.get("owned") == "true":
        clauses.append(
            "u.id IN (SELECT owner_id FROM skool.groups WHERE owner_id IS NOT NULL)"
        )
    if params.get("scraped") == "true":
        clauses.append("u.groups_fetched = true")

    min_followers = _num(params.get("min_followers"))
    max_followers = _num(params.get("max_followers"))
    if min_followers is not None:
        params["min_followers"] = int(min_followers)
        clauses.append("u.total_followers >= :min_followers")
    if max_followers is not None:
        params["max_followers"] = int(max_followers)
        clauses.append("u.total_followers < :max_followers")

    q = (params.get("q") or "").strip()
    if q:
        params["q"] = f"%{q}%"
        clauses.append(
            """
            (
                u.name ILIKE :q OR u.first_name ILIKE :q
                OR u.last_name ILIKE :q OR u.full_name ILIKE :q
                OR u.location ILIKE :q OR u.bio ILIKE :q
            )
            """
        )
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


async def query_users(
    *,
    page: int = 1,
    per_page: int = 30,
    sort: str = "followers_desc",
    q: str | None = None,
    location_source: str | None = None,
    timezone: str | None = None,
    has_avatar: str | None = None,
    owned: str | None = None,
    scraped: str | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": q,
        "location_source": location_source,
        "timezone": timezone,
        "has_avatar": has_avatar,
        "owned": owned,
        "scraped": scraped,
    }
    where = _user_where(params)
    order = _USER_SORTS.get(sort, _USER_SORTS["followers_desc"])
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 30)))
    offset = (page - 1) * per_page
    params["limit"] = per_page
    params["offset"] = offset

    async with session_scope() as session:
        total = int(
            (
                await session.execute(
                    sql_text(f"SELECT count(*) FROM skool.users u{where}"), params
                )
            ).scalar()
            or 0
        )
        rows = await _run(
            session,
            f"""
            SELECT {_USER_LIST_COLUMNS}
            FROM skool.users u
            {where}
            GROUP BY u.id
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "items": rows,
    }


async def get_user_detail(user_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        rows = await _run(
            session,
            f"""
            SELECT {_USER_LIST_COLUMNS.replace('u.', 'u.')}
            FROM skool.users u
            WHERE u.id = :id
            GROUP BY u.id
            """,
            {"id": user_id},
        )
        return rows[0] if rows else None


async def get_user_groups(user_id: str) -> list[dict[str, Any]]:
    """All groups linked to a user, with their relation role.

    `role` is "owner" (the user created the group) or "member" (they joined).
    Falls back to the user's `owner_id` groups when a link row is missing.
    """
    async with session_scope() as session:
        return await _run(
            session,
            f"""
            SELECT {_GROUP_LIST_COLUMNS},
                   COALESCE(ug.role, CASE WHEN g.owner_id = :id THEN 'owner' ELSE NULL END) AS role
            FROM skool.groups g
            LEFT JOIN skool.user_groups ug ON ug.group_id = g.id AND ug.user_id = :id
            WHERE ug.user_id = :id OR g.owner_id = :id
            ORDER BY (ug.role = 'owner') DESC, g.total_members DESC NULLS LAST
            """,
            {"id": user_id},
        )