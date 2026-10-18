# Skool Explorer — API Specification

Complete contract of the current Express backend, written for a 1:1 FastAPI port.
Base URL: `/` (all routes under `/api`). All responses are JSON.
DB: PostgreSQL, schema `skool` — tables `groups`, `users`, `user_groups`.

Conventions:
- All list endpoints accept filter params as **query strings**. Multi-value params are **comma-separated** (`category=tech,money`, max 40 items).
- Booleans accept `true/false/1/0`.
- Pagination: `page` (1-based), `pageSize` (1–100, default 24).
- Every list response wraps `items[]` + `pagination`.
- Errors: `{ "error": "..." }` with proper status code.
- Caching: server-side in-process cache — meta 5 min, analytics 2 min per query-string; HTTP `Cache-Control: public, max-age=15`.

---

## 1. GET /api/meta

Facet options, sort lists, slider bounds. Expensive → cached 5 min.

**Params:** none
**Response:**
```jsonc
{
  "categories":   [{ "value": "money", "count": 17684 }, ...],   // COALESCE(category_slug,'unknown'), ORDER count DESC
  "languages":    [{ "value": "english", "count": 50166 }, ...], // COALESCE(language,'unknown')
  "priceBuckets": [{ "value": "free"|"paid"|"free-trial", "count": int }, ...],
                  // mapping: bucket null + amount>0 => paid; null + no amount => free
  "visibility":   [{ "value": "public"|"private", "count": int }, ...], // is_public null => private
  "locations":    [{ "value": "America/New_York", "count": int }, ...], // users.location COALESCE 'unknown', LIMIT 40
  "timezones":    [{ "value": "Europe/Berlin", "count": int }, ...],    // users.timezone COALESCE 'unknown', LIMIT 40
  "socials": {
    "users":     [{ "value": "website|twitter|linkedin|youtube|instagram|facebook", "count": int }, ...],
    "groups":    [{ "value": "instagram|youtube|tiktok|twitter", "count": int }, ...], // facebook omitted (false positives)
    "available": ["twitter","linkedin","facebook","youtube","website","instagram"]     // = socials.users values
  },
  "priceHistogram": [{ "bucket": "<10|10-25|25-50|50-100|100-200|200-500|500-1k|1k+", "count": int }, ...],
  "groupBounds": { "members": int, "posts": int },        // true DB maxes
  "userBounds":  { "followers": int, "following": int, "contributions": int },
  "priceBounds": { "min": number, "max": number, "p99": number },
  "groupSorts": [
    { "value": "most_members",    "label": "Most members" },
    { "value": "fewest_members",  "label": "Fewest members" },
    { "value": "most_posts",      "label": "Most posts" },
    { "value": "fewest_posts",    "label": "Fewest posts" },
    { "value": "engagement",      "label": "Engagement (posts/member)" },
    { "value": "rev_desc",        "label": "Revenue (high→low)" },
    { "value": "rev_asc",         "label": "Revenue (low→high)" },
    { "value": "price_desc",      "label": "Price (high→low)" },
    { "value": "price_asc",       "label": "Price (low→high)" },
    { "value": "newest",          "label": "Newest" },
    { "value": "oldest",          "label": "Oldest" },
    { "value": "name",            "label": "Name A–Z" }
  ],
  "userSorts": [
    { "value": "most_followers",     "label": "Most followers" },
    { "value": "most_contributions", "label": "Most contributions" },
    { "value": "newest",             "label": "Newest" },
    { "value": "oldest",             "label": "Oldest" },
    { "value": "name",               "label": "Name A–Z" }
  ]
}
```

---

## 2. GET /api/groups

Paginated, filterable group list. Cards shape (no description/links).

**Query params (all optional):**

| Param | Type | Notes |
|---|---|---|
| `search` | string | ILIKE on name + display_name (LIKE wildcards escaped) |
| `owner` | string | ILIKE on owner_name |
| `category` | csv | values from meta.categories; `unknown` ⇒ IS NULL |
| `language` | csv | values from meta.languages; `unknown` ⇒ IS NULL |
| `price` | csv | `free`,`paid`,`free-trial` (OR-combined; see mapping above) |
| `minPriceUsd` / `maxPriceUsd` | float | on price_usd |
| `priceInterval` | enum | `month`,`year`,`one_time`,`week` |
| `visibility` | enum | `public` (=true) / `private` (=false OR null) |
| `minMembers` / `maxMembers` | int | total_members range |
| `minPosts` / `maxPosts` | int | total_posts range |
| `hasCourses` | bool | num_courses > 0 (false ⇒ null or 0) |
| `hasPosts` | bool | total_posts > 0 |
| `hasDescription` | bool | length(description) > 80 |
| `hasLinks` | bool | links non-empty and ≠ `'{"links": []}'` |
| `social` | csv | `instagram`,`youtube`,`tiktok`,`twitter` — presence in links JSON text (twitter also matches x.com) |
| `createdFrom` / `createdTo` | date `YYYY-MM-DD` | created_at >= from ; created_at < to+1day |
| `isMemberOf` | csv of **user slugs** | groups where ANY of these people is member (EXISTS user_groups ⋈ users by lower(name)) |
| `isOwnerOf` | csv user slugs | same with role='owner' |
| `notMemberOf` | csv user slugs | NOT EXISTS role IN ('member','owner') |
| `sort` | enum | groupSorts list; default `most_members` |
| `page` / `pageSize` | int | pagination |

**Response:**
```jsonc
{
  "items": [ GroupCard, ... ],
  "pagination": { "page": 1, "pageSize": 24, "total": 85550, "totalPages": 3565 }
}
```

**GroupCard object:**
```jsonc
{
  "id": "hex32",
  "name": "ai-automation-society",
  "display_name": "AI Automation Society",
  "initials": "AA",
  "color": "#0693E3",
  "cover_url": "https://assets.skool.com/...",
  "logo_url": "https://assets.skool.com/...",
  "total_members": 438471,
  "total_posts": 22900,
  "price_bucket": "free"|"paid"|"free-trial",   // inferred: null+amount=>paid, null+no amount=>free
  "price_interval": "month"|"year"|"week"|"one_time"|null,
  "price_usd": 99,
  "category_slug": "tech",
  "language": "english",
  "is_public": true,
  "owner_id": "hex32|null",
  "owner_name": "nateherk",
  "created_at": "2024-10-15T...Z",
  // revenue block (spread; absent when not monetized):
  "estimated_monthly_revenue_usd": int,         // interval-normalized: year/12, week*4.33, one_time spread over months-since-creation
  "estimated_one_time_revenue_usd": int,        // only for one_time
  "estimated_rev_period": "month"|"year"|"week"|"one_time"
}
```

---

## 3. GET /api/groups/{id}

Full group detail + resolved owner. 404 ⇒ `{ "error": "Group not found" }`.

**Path param:** `id` — hex32 group id.

Owner resolution rule (important — data quirk): join users by owner_id AND matching owner_name;
if that fails, fall back to users.name = owner_name; else owner fields null.

**Response:** GroupCard fields **plus**:
```jsonc
{
  "description": "text|null",
  "lp_description": "long text|null",
  "logo_big_url": "...",
  "favicon_url": "...",
  "membership_model": int,
  "total_online_members": int,
  "total_admins": int,
  "total_rules": int,
  "num_courses": int,
  "num_modules": int,
  "afl_percent": int,
  "category_id": "hex32|null",
  "links": [ { "url": "https://...", "label": "...", "public": true }, ... ],  // parsed JSON, http(s)-only
  "updated_at": "...",
  "owner": {                                    // null when unresolvable
    "id": "hex32", "name": "hormozi", "full_name": "Alex Hormozi",
    "bio": "...", "avatar": "url",
    "total_followers": int, "total_contributions": int, "location": "..."
  }
}
```

---

## 4. GET /api/groups/suggest?q=

Typeahead for membership filters (people). `q` trimmed, max 60 chars.

**Response:** top 8 by total_followers:
```jsonc
[ { "id": "hex32", "name": "sam", "full_name": "Sam Ovens",
    "avatar_bubble_url": "url", "total_followers": 760000 } ]
```

---

## 5. GET /api/groups/compare?ids=a,b,c

Full detail rows for up to 12 comma-separated group ids, **caller's order preserved**.

**Response:** array of GroupDetail objects (same shape as §3).

---

## 6. GET /api/users

Paginated, filterable people list.

**Query params:**

| Param | Type | Notes |
|---|---|---|
| `search` | string | ILIKE on name + full_name + bio |
| `location` | csv | exact match; `unknown` ⇒ IS NULL |
| `timezone` | csv | exact match; `unknown` ⇒ IS NULL |
| `minFollowers` / `maxFollowers` | int | |
| `minFollowing` / `maxFollowing` | int | |
| `minContributions` / `maxContributions` | int | |
| `social` | csv | `website`,`twitter`,`linkedin`,`youtube`,`instagram`,`facebook` — link column non-empty (OR) |
| `creatorsOnly` | bool | EXISTS user_groups role='owner' |
| `createdFrom` / `createdTo` | date | |
| `hasBio` / `hasAvatar` | bool | supported server-side (UI removed) |
| `sort` | enum | userSorts; default `most_followers` |
| `page` / `pageSize` | int | |

**Response:**
```jsonc
{
  "items": [{
    "id": "hex32", "name": "sam", "full_name": "Sam Ovens",
    "avatar_url": "url", "avatar_bubble_url": "url",
    "bio": "...", "location": "Los Angeles, CA",
    "total_followers": 760000, "total_following": 30, "total_contributions": 4700
  }],
  "pagination": { ... }
}
```

---

## 7. GET /api/users/{id}

Profile + owned/member communities. 404 ⇒ `{ "error": "User not found" }`.

Ownership comes from **groups.owner_id** (authoritative); memberGroups from user_groups
(role='member' OR null) excluding owned. This fixes profiles where user_groups.role is null.

**Response:**
```jsonc
{
  "user": {
    ...UserCard,
    "first_name": "...", "last_name": "...", "timezone": "...",
    "links": { "website": "...", "twitter": "...", "linkedin": "...",
               "youtube": "...", "instagram": "...", "facebook": "..." },
    "created_at": "..."
  },
  "ownedGroups":  [ GroupCard, ... ],   // ordered by total_members DESC
  "memberGroups": [ GroupCard, ... ],
  "ownedCount": int,
  "memberCount": int
}
```

---

## 8. GET /api/users/suggest?q=

Same contract as §4 (people typeahead).

---

## 9. GET /api/analytics

Dashboard datasets. Optional filters applied to group-based queries:

| Param | Effect |
|---|---|
| `minMembers` / `maxMembers` | total_members range |
| `minPosts` / `maxPosts` | total_posts range |
| `categories` | csv of category_slug |
| `createdFrom` / `createdTo` | created_at range (also bounds time-series windows; default lookback 24 months) |

Cached 2 min per query-string.

**Response keys (each an array unless noted):**
```jsonc
{
  "kpi": { "groups": int, "users": int, "memberships": int, "member_slots": bigint },

  "groupSizes":         [ { "bucket": "under-100|100-1k|1k-10k|10k-100k|100k+", "count": int } ],
  "categoryMembers":    [ { "value": "cat", "count": int, "members": bigint } ],        // top 15
  "priceTiers":         [ { "tier": "free|paid|free-trial", "count": int, "members": bigint } ],
  "categoryEngagement": [ { "value": "cat", "posts_per_1k": float, "count": int } ],      // groups >100 members, >0 posts
  "groupsMonthly":      [ { "month": "YYYY-MM", "count": int } ],                        // 24mo window
  "cohortGrowth":       [ { "month": "YYYY-MM", "groups": int, "members": bigint } ],

  "topCommunities":     [ { "name": "slug", "display_name": "...", "total_members": int,
                            "total_posts": int, "posts_per_1k": float } ],                // >5000 members, top 12

  "revenueLeaders":     [ { "value": "cat", "revenue_monthly": bigint, "paid_groups": int } ],
                        // month=price, year=/12, week=*4.33; one_time excluded
  "monetizationByCategory": [ { "value": "cat", "total_groups": int, "monetized_groups": int,
                                "monetized_pct": float, "avg_price": float } ],           // categories ≥20 groups
  "ownerLeaderboard":   [ { "value": "owner_slug", "full_name": "...", "groups": int,
                            "reach": bigint } ],                                          // owners with ≥3 groups, top 15
  "growthByCohortYear": [ { "year": int, "groups": int, "median_members": float,
                            "p90_members": float } ],                                     // years ≥2020
  "priceSweetSpot":     [ { "bucket": "<10|10-25|...", "count": int, "members": bigint } ],

  "topLocations":       [ { "value": "loc", "count": int } ],                            // top 10
  "catLangHeat":        [ { "value": "cat", "lang": "lang", "count": int } ]             // top 6 languages per category
}
```

---

## Porting notes for FastAPI

1. **SQL must be ported verbatim** — all filters are parameterized ($1..$n) with allowlisted columns/sorts. In FastAPI use asyncpg or SQLAlchemy Core `text()` with named `:param`s; keep the same WHERE semantics (esp. PRICE_CLAUSES, visibility null⇒private, facet IN + unknown⇒IS NULL).
2. **Revenue formula** (shared by §2/§3 cards and `rev_desc`/`rev_asc` sorts): price × members, normalized: `month ×1`, `year ÷12`, `week ×4.33`, `one_time ÷ months_since_creation (clamped 0.5..120, default 12)`. Keep SQL and Python versions identical.
3. **Caching**: replicate meta (300s) + analytics (120s per-query-string, LRU ≤50). `fastapi-cache2` or a dict + TTL works.
4. **Response parity**: field names are snake_case already; keep `pagination` wrapper and exact key names so the React client works unchanged (only the vite proxy target changes).
5. **Route order matters**: `/api/groups/suggest` and `/api/groups/compare` must be registered BEFORE `/api/groups/{id}` (Express ordering; FastAPI handles this naturally but keep it in mind).
6. **Errors**: 404 with `{ "error": "..." }` body for missing ids; 500s logged, never leak SQL.
7. **Compression + Cache-Control**: add GZipMiddleware + `Cache-Control: public, max-age=15` on /api to match.
