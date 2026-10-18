"""Analytics SQL — port of server/src/entities/analytics.js.

15 datasets run in parallel against group/user sources, sharing one filter
fragment per variant. Placeholder numbering matters: the KPI query embeds
the same fragment twice (second copy offset by n).
"""

from dataclasses import dataclass

from app.domain.filters import AnalyticsFilter


@dataclass(frozen=True)
class Compiled:
    sql: str
    params: list


def _parse_int(v):
    from app.domain.filters import parse_int
    return parse_int(v)


class _Args:
    def __init__(self) -> None:
        self.values: list = []
        self._n = 0

    def arg(self, v) -> str:
        self._n += 1
        self.values.append(v)
        return f"${self._n}"


def _strip_g(sql: str) -> str:
    """Queries selecting FROM skool.groups (no alias) need bare column names."""
    return sql.replace("g.", "")


def group_where(f: AnalyticsFilter, extra: str = "") -> tuple[str, list]:
    """Reusable WHERE fragment over aliased `skool.groups g`.

    Note: reference requires min/max values to be > 0 to apply.
    """
    parts: list[str] = []
    a = _Args()

    if f.min_members is not None and f.min_members > 0:
        parts.append(f"g.total_members >= {a.arg(f.min_members)}")
    if f.max_members is not None and f.max_members > 0:
        parts.append(f"g.total_members <= {a.arg(f.max_members)}")
    if f.min_posts is not None and f.min_posts > 0:
        parts.append(f"g.total_posts >= {a.arg(f.min_posts)}")
    if f.max_posts is not None and f.max_posts > 0:
        parts.append(f"g.total_posts <= {a.arg(f.max_posts)}")

    if f.categories:
        cats = f.categories[:40]
        parts.append(f"g.category_slug = ANY ({a.arg(cats)})")

    if f.created_from:
        from app.adapters.db.sql.groups_sql import as_date_param
        parts.append(f"g.created_at >= {a.arg(as_date_param(f.created_from))}")
    if f.created_to:
        from app.adapters.db.sql.groups_sql import as_date_param
        parts.append(f"g.created_at < {a.arg(as_date_param(f.created_to))} + interval '1 day'")

    if extra:
        parts.append(extra)

    where_sql = f"WHERE {' AND '.join(parts)}" if parts else ""
    return where_sql, a.values


def time_window(f: AnalyticsFilter, col: str, default_months: int = 24) -> tuple[str, list]:
    """Explicit dates win, else default N-month lookback."""
    from app.adapters.db.sql.groups_sql import as_date_param
    parts: list[str] = []
    values: list = []
    if f.created_from:
        values.append(as_date_param(f.created_from))
        parts.append(f"{col} >= ${len(values)}")
    else:
        parts.append(f"{col} >= now() - interval '{default_months} months'")
    if f.created_to:
        values.append(as_date_param(f.created_to))
        parts.append(f"{col} < ${len(values)} + interval '1 day'")
    return f"WHERE {' AND '.join(parts)}", values


def build_all(f: AnalyticsFilter) -> dict[str, tuple[str, list]]:
    """Compile all 15 dataset queries → name -> (sql, params)."""
    g_where, g_vals = group_where(f)
    eng_where, eng_vals = group_where(f, "g.total_posts > 0")
    gw_where, gw_vals = time_window(f, "g.created_at")

    # Top-communities guard baked into WHERE; rev/sweet/own variants likewise.
    top_where, top_vals = group_where(f, "g.total_members > 5000")
    rev_where, rev_vals = group_where(
        f, "g.price_usd > 0 AND g.price_interval IN ('month','year','week')"
    )
    own_where, own_vals = group_where(f, "g.owner_name IS NOT NULL")
    sweet_where, sweet_vals = group_where(f, "g.price_usd IS NOT NULL AND g.price_usd > 0")

    cats = [c for c in f.categories][:40]
    heat_where = f"AND q.category_slug = ANY ($1)" if cats else ""

    # KPI: two sub-selects share the fragment; second offsets placeholders by n.
    def offset_placeholders(sql: str, n: int) -> str:
        import re
        return re.sub(r"\$(\d+)", lambda m: f"${int(m.group(1)) + n}", sql)

    kpi_second = offset_placeholders(g_where, len(g_vals))

    g_bare = _strip_g(g_where)
    eng_inner = eng_where
    gw_bare = _strip_g(gw_where)
    top_full = top_where
    sweet_bare = _strip_g(sweet_where)

    out: dict[str, tuple[str, list]] = {
        "kpi": (
            f"""SELECT
        (SELECT count(*)::int FROM skool.groups g {g_where}) AS groups,
        (SELECT count(*)::int FROM skool.users) AS users,
        (SELECT count(*)::int FROM skool.user_groups) AS memberships,
        (SELECT COALESCE(sum(total_members), 0)::bigint FROM skool.groups g {kpi_second}) AS member_slots""",
            g_vals + g_vals,
        ),
        "groupSizes": (
            """SELECT
        CASE
          WHEN total_members IS NULL THEN 'unknown'
          WHEN total_members < 100 THEN 'under-100'
          WHEN total_members < 1000 THEN '100-1k'
          WHEN total_members < 10000 THEN '1k-10k'
          WHEN total_members < 100000 THEN '10k-100k'
          ELSE '100k+'
        END AS bucket,
        count(*)::int AS count
      FROM skool.groups
      """ + g_bare + """
      GROUP BY 1 ORDER BY min(total_members) NULLS FIRST""",
            g_vals,
        ),
        "categoryMembers": (
            """SELECT COALESCE(category_slug, 'unknown') AS value,
             count(*)::int AS count,
             COALESCE(sum(total_members), 0)::bigint AS members
      FROM skool.groups
      """ + g_bare + """
      GROUP BY 1 ORDER BY members DESC LIMIT 15""",
            g_vals,
        ),
        "priceTiers": (
            """SELECT
        CASE
          WHEN price_bucket = 'free' OR price_bucket = 'free-trial' THEN price_bucket
          WHEN price_bucket = 'paid' OR (price_bucket IS NULL AND price_usd IS NOT NULL AND price_usd > 0) THEN 'paid'
          ELSE 'free'
        END AS tier,
        count(*)::int AS count,
        COALESCE(sum(total_members), 0)::bigint AS members
      FROM skool.groups
      """ + g_bare + """
      GROUP BY 1 ORDER BY count DESC""",
            g_vals,
        ),
        "categoryEngagement": (
            """SELECT cat AS value, round(avg(ratio), 1) AS posts_per_1k, count(*)::int AS count
      FROM (
        SELECT COALESCE(g.category_slug, 'unknown') AS cat,
               1000.0 * g.total_posts / NULLIF(g.total_members, 0) AS ratio
        FROM skool.groups g
        """ + eng_inner + """
      ) q
      GROUP BY 1 ORDER BY 2 DESC""",
            eng_vals,
        ),
        "groupsMonthly": (
            """SELECT to_char(date_trunc('month', created_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month,
             count(*)::int AS count
      FROM skool.groups
      """ + gw_bare + """
      GROUP BY 1 ORDER BY 1""",
            gw_vals,
        ),
        "cohortGrowth": (
            """SELECT to_char(date_trunc('month', created_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month,
             count(*)::int AS groups,
             COALESCE(sum(total_members), 0)::bigint AS members
      FROM skool.groups
      """ + gw_bare + """
      GROUP BY 1 ORDER BY 1""",
            gw_vals,
        ),
        "topCommunities": (
            """SELECT g.name, g.display_name, g.total_members, g.total_posts,
             round(1000.0 * g.total_posts / NULLIF(g.total_members, 0), 1) AS posts_per_1k
      FROM skool.groups g
      """ + top_full + """
      ORDER BY 5 DESC LIMIT 12""",
            top_vals,
        ),
        "revenueLeaders": (
            """SELECT COALESCE(category_slug, 'unknown') AS value,
             round(COALESCE(sum(rev_monthly), 0))::bigint AS revenue_monthly,
             count(*) FILTER (WHERE rev_monthly > 0)::int AS paid_groups
      FROM (
        SELECT g.category_slug,
               CASE g.price_interval
                 WHEN 'month' THEN g.price_usd
                 WHEN 'year'  THEN g.price_usd / 12.0
                 WHEN 'week'  THEN g.price_usd * 4.33
                 ELSE NULL
               END * g.total_members AS rev_monthly
        FROM skool.groups g
        """ + rev_where + """
      ) q
      GROUP BY 1 HAVING sum(rev_monthly) > 0 ORDER BY 2 DESC LIMIT 12""",
            rev_vals,
        ),
        "monetizationByCategory": (
            """SELECT COALESCE(category_slug, 'unknown') AS value,
             count(*)::int AS total_groups,
             count(*) FILTER (WHERE monetized)::int AS monetized_groups,
             round(100.0 * count(*) FILTER (WHERE monetized) / NULLIF(count(*), 0), 1) AS monetized_pct,
             round(avg(price_usd) FILTER (WHERE monetized), 2) AS avg_price
      FROM (
        SELECT g.category_slug, g.price_usd,
               (g.price_bucket IN ('paid','free-trial')
                OR (g.price_bucket IS NULL AND g.price_usd > 0)) AS monetized
        FROM skool.groups g
        """ + g_where + """
      ) q
      GROUP BY 1 HAVING count(*) >= 20 ORDER BY 4 DESC""",
            g_vals,
        ),
        "ownerLeaderboard": (
            """SELECT g.owner_name AS value,
             MAX(u.full_name) AS full_name,
             count(*)::int AS groups,
             COALESCE(sum(g.total_members), 0)::bigint AS reach
      FROM skool.groups g
      LEFT JOIN skool.users u ON u.id = g.owner_id
      """ + own_where + """
      GROUP BY 1 HAVING count(*) >= 3 ORDER BY reach DESC LIMIT 15""",
            own_vals,
        ),
        # Cohort-year intentionally ignores dynamic filters (reference parity).
        "growthByCohortYear": (
            """SELECT date_part('year', created_at)::int AS year,
             count(*)::int AS groups,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY total_members) AS median_members,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY total_members) AS p90_members
      FROM skool.groups
      WHERE created_at IS NOT NULL AND date_part('year', created_at) >= 2020
      GROUP BY 1 ORDER BY 1""",
            [],
        ),
        "priceSweetSpot": (
            """SELECT
        CASE
          WHEN price_usd < 10 THEN '<10'
          WHEN price_usd < 25 THEN '10-25'
          WHEN price_usd < 50 THEN '25-50'
          WHEN price_usd < 100 THEN '50-100'
          WHEN price_usd < 200 THEN '100-200'
          WHEN price_usd < 500 THEN '200-500'
          WHEN price_usd < 1000 THEN '500-1k'
          ELSE '1k+'
        END AS bucket,
        count(*)::int AS count,
        COALESCE(sum(total_members), 0)::bigint AS members
      FROM skool.groups
      """ + sweet_bare + """
      GROUP BY 1 ORDER BY min(price_usd)""",
            sweet_vals,
        ),
        "topLocations": (
            """SELECT COALESCE(location, 'unknown') AS value, count(*)::int AS count
      FROM skool.users GROUP BY 1 ORDER BY 2 DESC LIMIT 10""",
            [],
        ),
        "catLangHeat": (
            """SELECT cat AS value, lang, count
      FROM (
        SELECT COALESCE(q.category_slug, 'unknown') AS cat,
               COALESCE(q.language, 'unknown') AS lang,
               count(*)::int AS count,
               row_number() OVER (
                 PARTITION BY COALESCE(q.category_slug, 'unknown')
                 ORDER BY count(*) DESC
               ) AS rn
        FROM skool.groups q
        WHERE q.category_slug IS NOT NULL AND q.language IS NOT NULL
          """ + heat_where + """
        GROUP BY 1, 2
      ) t
      WHERE rn <= 6
      ORDER BY value, count DESC""",
            [cats] if cats else [],
        ),
    }
    return out
