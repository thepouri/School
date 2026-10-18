"""Group list SQL compiler — port of server/src/queryBuilder.js compileGroups.

Column names are NEVER interpolated from user input; only $n placeholders
and allowlisted literals.
"""

# R1 price bucket clauses (verbatim)
PRICE_CLAUSES = {
    "free": "(g.price_bucket = 'free' OR (g.price_bucket IS NULL AND (g.price_usd IS NULL OR g.price_usd = 0)))",
    "free-trial": "g.price_bucket = 'free-trial'",
    "paid": "(g.price_bucket = 'paid' OR (g.price_bucket IS NULL AND g.price_usd IS NOT NULL AND g.price_usd > 0))",
}

GROUP_SOCIAL = {
    "instagram": "lower(g.links) LIKE '%instagram%'",
    "youtube": "lower(g.links) LIKE '%youtube%'",
    "tiktok": "lower(g.links) LIKE '%tiktok%'",
    "twitter": "(lower(g.links) LIKE '%twitter%' OR lower(g.links) LIKE '%x.com%')",
}

GROUP_CARD_COLS = """
  g.id, g.name, g.display_name, g.initials, g.color, g.cover_url, g.logo_url,
  g.total_members, g.total_posts, g.price_bucket, g.price_interval, g.price_usd,
  g.category_slug, g.language, g.is_public, g.owner_id, g.owner_name, g.created_at
"""

MONTHS = "LEAST(GREATEST(EXTRACT(EPOCH FROM (now() - COALESCE(g.created_at, now()))) / 2592000.0, 0.5), 120)"

EFFECTIVE_PRICE = "COALESCE(g.price_usd, g.price_amount_cents / 100.0, 0)"

# R5 sort-grade revenue expression (mirrors domain/pricing.estimate_revenue)
REV = f"""CASE
    WHEN g.price_bucket = 'paid' OR g.price_bucket = 'free-trial' OR (g.price_bucket IS NULL AND COALESCE(g.price_usd, g.price_amount_cents / 100.0, 0) > 0)
      THEN COALESCE(g.price_usd, g.price_amount_cents / 100.0, 0) * COALESCE(g.total_members, 0) *
        CASE g.price_interval
          WHEN 'year' THEN 1.0 / 12.0
          WHEN 'week' THEN 4.33
          WHEN 'one_time' THEN 1.0 / {MONTHS}
          ELSE 1.0
        END
    ELSE 0 END"""

SORTS = {
    "most_members": "ORDER BY g.total_members DESC NULLS LAST, g.id",
    "fewest_members": "ORDER BY g.total_members ASC NULLS LAST, g.id",
    "most_posts": "ORDER BY g.total_posts DESC NULLS LAST, g.id",
    "fewest_posts": "ORDER BY g.total_posts ASC NULLS LAST, g.id",
    "engagement": "ORDER BY (g.total_posts::float / NULLIF(g.total_members, 0)) DESC NULLS LAST, g.id",
    "rev_desc": f"ORDER BY {REV} DESC NULLS LAST, g.id",
    "rev_asc": f"ORDER BY {REV} ASC NULLS LAST, g.id",
    "price_desc": f"ORDER BY {EFFECTIVE_PRICE} DESC NULLS LAST, g.id",
    "price_asc": f"ORDER BY {EFFECTIVE_PRICE} ASC NULLS LAST, g.id",
    "newest": "ORDER BY g.created_at DESC NULLS LAST, g.id",
    "oldest": "ORDER BY g.created_at ASC NULLS LAST, g.id",
    "name": "ORDER BY g.name ASC",
}


class SqlBuilder:
    """Accumulates WHERE fragments with auto-numbered $n placeholders."""

    def __init__(self) -> None:
        self.where: list[str] = []
        self.values: list = []
        self._n = 0

    def arg(self, v) -> str:
        self._n += 1
        self.values.append(v)
        return f"${self._n}"

    def push(self, fragment: str) -> None:
        self.where.append(fragment)

    def where_sql(self) -> str:
        return f"WHERE {' AND '.join(self.where)}" if self.where else ""


def escape_like(s: str) -> str:
    return "".join(f"\\{ch}" if ch in "\\%_" else ch for ch in s)


def as_date_param(s: str):
    """asyncpg needs datetime objects, not strings (node-pg accepted both)."""
    from datetime import datetime, timezone
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def facet_clause(b: SqlBuilder, values: list[str], col: str) -> None:
    """R6 multi-select facet: real values IN(...), 'unknown' → IS NULL, OR'd."""
    if not values:
        return
    real = [v for v in values if v != "unknown"]
    parts = []
    if real:
        params = ", ".join(b.arg(v) for v in real)
        parts.append(f"{col} IN ({params})")
    if "unknown" in values:
        parts.append(f"{col} IS NULL")
    b.push("(" + " OR ".join(parts) + ")")


def compile_groups(f) -> tuple[str, list, str]:
    """GroupFilter → (where_sql, values, order_by)."""
    b = SqlBuilder()

    if f.search:
        p = b.arg(f"%{escape_like(f.search)}%")
        b.push(f"(g.name ILIKE {p} ESCAPE '\\' OR g.display_name ILIKE {p} ESCAPE '\\')")

    if f.owner:
        p = b.arg(f"%{escape_like(f.owner)}%")
        b.push(f"g.owner_name ILIKE {p} ESCAPE '\\'")

    facet_clause(b, f.category, "g.category_slug")
    facet_clause(b, f.language, "g.language")

    price_parts = [PRICE_CLAUSES[p] for p in f.price if p in PRICE_CLAUSES]
    if price_parts:
        b.push("(" + " OR ".join(price_parts) + ")")

    if f.min_price_usd is not None and f.min_price_usd >= 0:
        b.push(f"g.price_usd >= {b.arg(f.min_price_usd)}")
    if f.max_price_usd is not None and f.max_price_usd >= 0:
        b.push(f"g.price_usd <= {b.arg(f.max_price_usd)}")

    # R2: is_public null (privacy also null, 23 rows) counts as private.
    if f.visibility == "public":
        b.push("g.is_public = true")
    elif f.visibility == "private":
        b.push("(g.is_public = false OR g.is_public IS NULL)")

    if f.min_members is not None:
        b.push(f"g.total_members >= {b.arg(f.min_members)}")
    if f.max_members is not None:
        b.push(f"g.total_members <= {b.arg(f.max_members)}")
    if f.min_posts is not None:
        b.push(f"g.total_posts >= {b.arg(f.min_posts)}")
    if f.max_posts is not None:
        b.push(f"g.total_posts <= {b.arg(f.max_posts)}")

    if f.has_courses is True:
        b.push("g.num_courses > 0")
    elif f.has_courses is False:
        b.push("(g.num_courses IS NULL OR g.num_courses = 0)")

    if f.has_posts is True:
        b.push("g.total_posts > 0")
    elif f.has_posts is False:
        b.push("(g.total_posts IS NULL OR g.total_posts = 0)")

    social_parts = [GROUP_SOCIAL[s] for s in f.social if s in GROUP_SOCIAL]
    if social_parts:
        b.push("(" + " OR ".join(social_parts) + ")")

    if f.has_description is True:
        b.push("g.description IS NOT NULL AND length(g.description) > 80")
    elif f.has_description is False:
        b.push("(g.description IS NULL OR length(g.description) <= 80)")

    if f.has_links is True:
        b.push("g.links IS NOT NULL AND g.links <> '' AND g.links <> '{\"links\": []}'")
    elif f.has_links is False:
        b.push("(g.links IS NULL OR g.links = '' OR g.links = '{\"links\": []}')")

    if f.created_from:
        b.push(f"g.created_at >= {b.arg(as_date_param(f.created_from))}")
    if f.created_to:
        p = b.arg(as_date_param(f.created_to))
        b.push(f"g.created_at < {p}::timestamptz + interval '1 day'")

    def membership(slug_list: list[str], role_sql: str) -> None:
        if not slug_list:
            return
        p = b.arg([s.lower() for s in slug_list])
        b.push(
            "EXISTS (SELECT 1 FROM skool.user_groups ug JOIN skool.users u2 ON u2.id = ug.user_id "
            f"WHERE ug.group_id = g.id AND {role_sql} AND lower(u2.name) = ANY ({p}))"
        )

    membership(f.is_member_of, "ug.role = 'member'")
    membership(f.is_owner_of, "ug.role = 'owner'")

    if f.not_member_of:
        p = b.arg([s.lower() for s in f.not_member_of])
        b.push(
            "NOT EXISTS (SELECT 1 FROM skool.user_groups ug JOIN skool.users u2 ON u2.id = ug.user_id "
            f"WHERE ug.group_id = g.id AND ug.role IN ('member','owner') AND lower(u2.name) = ANY ({p}))"
        )

    order_by = SORTS.get(f.sort, SORTS["most_members"])
    return b.where_sql(), b.values, order_by


def suggest_query(q: str) -> tuple[str, list]:
    like = f"%{escape_like(q)}%"
    return (
        """
    SELECT id, name, display_name, total_members
    FROM skool.groups
    WHERE name ILIKE $1 ESCAPE '\\' OR display_name ILIKE $1 ESCAPE '\\'
    ORDER BY total_members DESC NULLS LAST
    LIMIT 8
    """,
        [like],
    )


# Compare: leaner joinless SELECT (contract-compatible per spec §6.5)
COMPARE_COLS = """
      g.id, g.name, g.display_name, g.description, g.lp_description, g.color,
      g.initials, g.cover_url, g.logo_url, g.price_bucket, g.price_interval,
      g.price_usd, g.total_members, g.total_posts, g.num_courses, g.category_slug,
      g.language, g.is_public, g.created_at
"""

DETAIL_SQL = """
    SELECT
      g.id, g.name, g.display_name, g.description, g.lp_description, g.color,
      g.initials, g.cover_url, g.logo_url, g.logo_big_url, g.favicon_url,
      g.price_bucket, g.price_interval, g.price_usd, g.price_amount_cents,
      g.is_public, g.membership_model, g.total_members, g.total_online_members,
      g.total_posts, g.total_admins, g.total_rules, g.num_courses, g.num_modules,
      g.afl_percent, g.category_slug, g.category_id, g.language, g.links,
      g.owner_id, g.owner_name, g.created_at, g.updated_at,
      COALESCE(u2.id, fu.id, u.id) AS u_id,
      COALESCE(u2.name, fu.name, u.name) AS u_name,
      COALESCE(u2.full_name, fu.full_name, u.full_name) AS u_full_name,
      COALESCE(u2.bio, fu.bio, u.bio) AS u_bio,
      COALESCE(u2.avatar_bubble_url, fu.avatar_bubble_url, u.avatar_bubble_url) AS u_avatar,
      COALESCE(u2.total_followers, fu.total_followers, u.total_followers) AS u_followers,
      COALESCE(u2.total_contributions, fu.total_contributions, u.total_contributions) AS u_contributions,
      COALESCE(u2.location, fu.location, u.location) AS u_location
    FROM skool.groups g
    LEFT JOIN skool.users u
      ON u.id = g.owner_id
      AND lower(u.name) = lower(g.owner_name)
    LEFT JOIN skool.users fu
      ON fu.id = g.owner_id
      AND NOT (lower(u.name) = lower(g.owner_name))
    LEFT JOIN skool.users u2
      ON u2.name = g.owner_name
      AND u.id IS NULL
    WHERE g.id = $1
"""
