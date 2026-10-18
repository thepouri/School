"""Meta facet SQL — port of server/src/entities/meta.js (12 parallel queries)."""

CATEGORIES_SQL = """
  SELECT COALESCE(category_slug, 'unknown') AS value, count(*)::int AS count
  FROM skool.groups
  GROUP BY 1 ORDER BY 2 DESC
"""

LANGUAGES_SQL = """
  SELECT COALESCE(language, 'unknown') AS value, count(*)::int AS count
  FROM skool.groups
  GROUP BY 1 ORDER BY 2 DESC
"""

PRICE_BUCKETS_SQL = """
  SELECT
    CASE
      WHEN price_bucket = 'free' OR price_bucket = 'free-trial' THEN price_bucket
      WHEN price_bucket = 'paid' OR (price_bucket IS NULL AND price_usd IS NOT NULL AND price_usd > 0) THEN 'paid'
      ELSE 'free'
    END AS value,
    count(*)::int AS count
  FROM skool.groups
  GROUP BY 1 ORDER BY 2 DESC
"""

VISIBILITY_SQL = """
  SELECT
    CASE WHEN is_public THEN 'public' ELSE 'private' END AS value,
    count(*)::int AS count
  FROM skool.groups
  GROUP BY 1 ORDER BY 2 DESC
"""

LOCATIONS_SQL = """
  SELECT COALESCE(location, 'unknown') AS value, count(*)::int AS count
  FROM skool.users
  GROUP BY 1 ORDER BY 2 DESC
  LIMIT 40
"""

TIMEZONES_SQL = """
  SELECT COALESCE(timezone, 'unknown') AS value, count(*)::int AS count
  FROM skool.users
  GROUP BY 1 ORDER BY 2 DESC
  LIMIT 40
"""

# Per-network presence counts for user social links. Ordinal wrapper pins
# UNION ALL output order (PG does not guarantee Append order across plans).
USER_SOCIALS_SQL = """
  SELECT value, count FROM (
    SELECT 1 AS ord, 'website' AS value, count(*)::int AS count FROM skool.users WHERE link_website IS NOT NULL AND link_website <> ''
    UNION ALL SELECT 2, 'twitter',   count(*)::int FROM skool.users WHERE link_twitter   IS NOT NULL AND link_twitter   <> ''
    UNION ALL SELECT 3, 'linkedin',  count(*)::int FROM skool.users WHERE link_linkedin  IS NOT NULL AND link_linkedin  <> ''
    UNION ALL SELECT 4, 'youtube',   count(*)::int FROM skool.users WHERE link_youtube   IS NOT NULL AND link_youtube   <> ''
    UNION ALL SELECT 5, 'instagram', count(*)::int FROM skool.users WHERE link_instagram IS NOT NULL AND link_instagram <> ''
    UNION ALL SELECT 6, 'facebook',  count(*)::int FROM skool.users WHERE link_facebook  IS NOT NULL AND link_facebook  <> ''
  ) s ORDER BY ord
"""

# Group links JSON presence counts (facebook omitted — false positives)
GROUP_SOCIALS_SQL = """
  SELECT value, count FROM (
    SELECT 1 AS ord, 'instagram' AS value, count(*)::int AS count FROM skool.groups WHERE lower(links) LIKE '%instagram%'
    UNION ALL SELECT 2, 'youtube', count(*)::int FROM skool.groups WHERE lower(links) LIKE '%youtube%'
    UNION ALL SELECT 3, 'tiktok',  count(*)::int FROM skool.groups WHERE lower(links) LIKE '%tiktok%'
    UNION ALL SELECT 4, 'twitter', count(*)::int FROM skool.groups WHERE lower(links) LIKE '%twitter%' OR lower(links) LIKE '%x.com%'
  ) s ORDER BY ord
"""

PRICE_HISTOGRAM_SQL = """
  SELECT
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
    count(*)::int AS count
  FROM skool.groups
  WHERE price_usd IS NOT NULL AND price_usd > 0
  GROUP BY 1 ORDER BY min(price_usd)
"""

PRICE_BOUNDS_SQL = """
  SELECT COALESCE(min(price_usd), 1) AS min,
         COALESCE(max(price_usd), 100000) AS max,
         COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY price_usd), 10000) AS p99
  FROM skool.groups
  WHERE price_usd IS NOT NULL AND price_usd > 0
"""

# True DB maxes so every row is reachable on the sliders (log-scale rendering).
GROUP_BOUNDS_SQL = """
  SELECT
    COALESCE(max(total_members), 100000)::bigint AS max_members,
    COALESCE(max(total_posts), 20000)::bigint AS max_posts
  FROM skool.groups
"""

USER_BOUNDS_SQL = """
  SELECT
    COALESCE(max(total_followers), 100000)::bigint AS max_followers,
    COALESCE(max(total_following), 10000)::bigint AS max_following,
    COALESCE(max(total_contributions), 10000)::bigint AS max_contributions
  FROM skool.users
"""

GROUP_SORT_OPTIONS = [
    {"value": "most_members", "label": "Most members"},
    {"value": "fewest_members", "label": "Fewest members"},
    {"value": "most_posts", "label": "Most posts"},
    {"value": "fewest_posts", "label": "Fewest posts"},
    {"value": "engagement", "label": "Engagement (posts/member)"},
    {"value": "rev_desc", "label": "Revenue (high → low)"},
    {"value": "rev_asc", "label": "Revenue (low → high)"},
    {"value": "price_desc", "label": "Price (high → low)"},
    {"value": "price_asc", "label": "Price (low → high)"},
    {"value": "newest", "label": "Newest"},
    {"value": "oldest", "label": "Oldest"},
    {"value": "name", "label": "Name A–Z"},
]

USER_SORT_OPTIONS = [
    {"value": "most_followers", "label": "Most followers"},
    {"value": "most_contributions", "label": "Most contributions"},
    {"value": "newest", "label": "Newest"},
    {"value": "oldest", "label": "Oldest"},
    {"value": "name", "label": "Name A–Z"},
]
