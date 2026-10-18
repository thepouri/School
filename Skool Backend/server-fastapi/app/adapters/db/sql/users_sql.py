"""User list SQL compiler — port of compileUsers + user entity SQL."""

USER_CARD_COLS = """
  u.id, u.name, u.full_name, u.avatar_url, u.avatar_bubble_url, u.bio,
  u.location, u.total_followers, u.total_following, u.total_contributions
"""

GROUP_CARD_COLS = """
  g.id, g.name, g.display_name, g.initials, g.color, g.cover_url, g.logo_url,
  g.total_members, g.total_posts, g.price_bucket, g.price_interval, g.price_usd,
  g.category_slug, g.language, g.is_public, g.owner_id, g.owner_name, g.created_at
"""

USER_SOCIAL = {
    "website": "link_website",
    "twitter": "link_twitter",
    "linkedin": "link_linkedin",
    "youtube": "link_youtube",
    "instagram": "link_instagram",
    "facebook": "link_facebook",
}

USER_SORTS = {
    "most_followers": "ORDER BY u.total_followers DESC NULLS LAST, u.id",
    "most_contributions": "ORDER BY u.total_contributions DESC NULLS LAST, u.id",
    "newest": "ORDER BY u.created_at DESC NULLS LAST, u.id",
    "oldest": "ORDER BY u.created_at ASC NULLS LAST, u.id",
    "name": "ORDER BY u.name ASC",
}

from app.adapters.db.sql.groups_sql import (  # noqa: E402
    SqlBuilder,
    as_date_param,
    escape_like,
    facet_clause,
)


def compile_users(f) -> tuple[str, list, str]:
    """UserFilter → (where_sql, values, order_by)."""
    b = SqlBuilder()

    if f.search:
        p = b.arg(f"%{escape_like(f.search)}%")
        b.push(
            f"(u.name ILIKE {p} ESCAPE '\\' OR u.full_name ILIKE {p} ESCAPE '\\' OR u.bio ILIKE {p} ESCAPE '\\')"
        )

    if f.has_bio is True:
        b.push("u.bio IS NOT NULL AND u.bio <> ''")
    elif f.has_bio is False:
        b.push("(u.bio IS NULL OR u.bio = '')")

    # avatar_url is non-null on every row; require a real http(s) scheme.
    if f.has_avatar is True:
        b.push("u.avatar_url ~ '^https?://'")
    elif f.has_avatar is False:
        b.push("(u.avatar_url IS NULL OR u.avatar_url !~ '^https?://')")

    facet_clause(b, f.location, "u.location")
    facet_clause(b, f.timezone, "u.timezone")

    if f.min_followers is not None:
        b.push(f"u.total_followers >= {b.arg(f.min_followers)}")
    if f.max_followers is not None:
        b.push(f"u.total_followers <= {b.arg(f.max_followers)}")
    if f.min_following is not None:
        b.push(f"u.total_following >= {b.arg(f.min_following)}")
    if f.max_following is not None:
        b.push(f"u.total_following <= {b.arg(f.max_following)}")
    if f.min_contributions is not None:
        b.push(f"u.total_contributions >= {b.arg(f.min_contributions)}")
    if f.max_contributions is not None:
        b.push(f"u.total_contributions <= {b.arg(f.max_contributions)}")

    social_parts = []
    for s in f.social:
        col = USER_SOCIAL.get(s)
        if col:
            social_parts.append(f"u.{col} IS NOT NULL AND u.{col} <> ''")
    if social_parts:
        b.push("(" + " OR ".join(social_parts) + ")")

    # creatorsOnly uses user_groups role='owner' (matches reference exactly).
    if f.creators_only is True:
        b.push("EXISTS (SELECT 1 FROM skool.user_groups ug WHERE ug.user_id = u.id AND ug.role = 'owner')")
    elif f.creators_only is False:
        b.push("NOT EXISTS (SELECT 1 FROM skool.user_groups ug WHERE ug.user_id = u.id AND ug.role = 'owner')")

    if f.created_from:
        b.push(f"u.created_at >= {b.arg(as_date_param(f.created_from))}")
    if f.created_to:
        p = b.arg(as_date_param(f.created_to))
        b.push(f"u.created_at < {p}::timestamptz + interval '1 day'")

    order_by = USER_SORTS.get(f.sort, USER_SORTS["most_followers"])
    return b.where_sql(), b.values, order_by


def suggest_query(q: str) -> tuple[str, list]:
    like = f"%{escape_like(q)}%"
    return (
        """
    SELECT id, name, full_name, total_followers
    FROM skool.users
    WHERE name ILIKE $1 ESCAPE '\\' OR full_name ILIKE $1 ESCAPE '\\'
    ORDER BY total_followers DESC NULLS LAST
    LIMIT 8
    """,
        [like],
    )


USER_FULL_SQL = """
    SELECT
      u.id, u.name, u.full_name, u.first_name, u.last_name, u.bio, u.location,
      u.timezone, u.avatar_url, u.avatar_bubble_url, u.total_followers,
      u.total_following, u.total_contributions, u.link_website, u.link_twitter,
      u.link_linkedin, u.link_youtube, u.link_instagram, u.link_facebook,
      u.created_at
    FROM skool.users u
    WHERE u.id = $1
"""

# R4: ownership comes from groups.owner_id (authoritative — user_groups role
# sometimes null / missing for owners, which hid their communities).
OWNED_SQL = f"""
    SELECT {GROUP_CARD_COLS}
    FROM skool.groups g
    WHERE g.owner_id = $1
    ORDER BY g.total_members DESC NULLS LAST, g.id
"""

# R4: membership = role 'member' or NULL, excluding the group they own.
MEMBER_SQL = f"""
    SELECT {GROUP_CARD_COLS}
    FROM skool.user_groups ug
    JOIN skool.groups g ON g.id = ug.group_id
    WHERE ug.user_id = $1 AND (ug.role = 'member' OR ug.role IS NULL)
      AND g.owner_id IS DISTINCT FROM $1
    ORDER BY g.total_members DESC NULLS LAST, g.id
"""
