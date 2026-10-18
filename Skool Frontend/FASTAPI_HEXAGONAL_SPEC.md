# Skool Explorer — FastAPI Hexagonal Port Specification

> **Purpose of this document**: This is the COMPLETE, self-contained input for building the FastAPI backend as a **hexagonal architecture (ports & adapters)** that is extensible and easily scalable. After implementation it must be a **drop-in replacement** for the existing Express backend: the current React UI connects with ZERO changes (only the dev proxy target changes).
>
> Read every section. The "Business Rules" section is not optional flavor — each rule encodes a real data quirk discovered in production. Breaking any of them changes filter counts or hides data.

---

## 1. Product context

Skool Explorer is a SaaS analytics tool over a scraped PostgreSQL dataset of Skool communities:
- **Users of the product**: agencies/operators who partner with Skool group owners to help them grow & monetize.
- **Data volume**: ~110k groups, ~30k users, ~570k membership rows.
- The React client is DONE and stays. Only the API layer is being rebuilt.

## 2. Current stack → target

| Layer | Now (Express) | Target (FastAPI) |
|---|---|---|
| HTTP | express@5 router | FastAPI + uvicorn |
| Validation | manual parsing | Pydantic v2 models / query params |
| DB | `pg` pool, raw SQL, `$n` placeholders | asyncpg pool, same SQL, `$n` placeholders (asyncpg native) |
| Caching | in-process Map + TTL | same pattern (or fastapi-cache2/redis-ready port) |
| Compression | compression middleware | GZipMiddleware |
| Config | `.env` via node --env-file | pydantic-settings |

**Hard constraint**: response JSON must remain byte-compatible in shape (field names, nesting, casing) so the React client works unchanged.

---

## 3. Database (read-only)

Schema `skool`, three tables. The API never writes.

### skool.groups (~110k rows)
```
id varchar(32) PK            -- hex
name varchar(255) UNIQUE     -- slug, e.g. "ai-automation-society"
display_name varchar(512)
description text             -- short
lp_description text          -- long landing-page text (BBCode-ish markup)
color varchar(16), initials varchar(16)
cover_url, logo_url, logo_big_url, favicon_url text
price_amount_cents integer   -- legacy alt price source
price_usd numeric(12,2)
price_currency varchar(8)
price_interval varchar(24)   -- 'month' | 'year' | 'week' | 'one_time' | NULL
membership_model integer
privacy integer              -- 1 = public, 0 = private (verified exact mapping)
is_public boolean            -- NULL on only ~23 rows (their privacy is also NULL)
total_members int, total_online_members int, total_posts int
total_admins int, total_rules int
num_courses int, num_modules int
afl_percent int              -- affiliate percentage
src_group varchar(64)
links text                   -- JSON: {"links":[{url,label,public},...]}
owner_id varchar(64)         -- UNRELIABLE: sometimes points to nonexistent user,
                             -- sometimes to the WRONG user
owner_name varchar(255)      -- slug; CANONICAL owner key (unique against users.name)
category_id varchar(64)
category_slug varchar(64)    -- e.g. money/hobbies/tech/health/self_improvement/spirituality/sports/music/relationships | NULL
language varchar(32)         -- lowercase english/spanish/... | NULL
price_bucket varchar(16)     -- scraped tier | NULL very often (see rules)
sort_seen, discovered_via varchar(16)
detail_fetched boolean
created_at, updated_at timestamptz
scraped_at timestamptz NOT NULL DEFAULT now()
```

Indexes present: category_slug, language, category_slug+language, is_public,
owner_id, owner_name, name UNIQUE, price_bucket, created_at, total_members DESC,
total_posts DESC, price_usd partial.

### skool.users (~30k rows)
```
id varchar(32) PK
name varchar(255) UNIQUE     -- slug, canonical person key ("sam" => Sam Ovens)
first_name, last_name, full_name varchar(512)
bio text
location varchar(255)        -- free text OR IANA tz string (data quality varies)
location_source varchar(16)
timezone varchar(64)         -- IANA
avatar_url, avatar_bubble_url text
link_website/link_twitter/link_linkedin/link_youtube/link_instagram/link_facebook text
last_offline timestamptz
total_followers int          -- max ≈ 759,508
total_following int          -- max ≈ 6,679
total_contributions int      -- max ≈ 96,481
groups_fetched boolean
created_at, updated_at timestamptz
scraped_at timestamptz NOT NULL DEFAULT now()
```

### skool.user_groups (~570k rows)
```
user_id varchar(64) NOT NULL  (FK-ish → users.id)
group_id varchar(64) NOT NULL (FK-ish → groups.id)
role varchar(16)              -- 'member' | 'owner' | NULL   ← NULL happens (6.5k rows) and MUST be tolerated
scraped_at timestamptz NOT NULL DEFAULT now()
PK (user_id, group_id); index on group_id AND on user_id
```

**Env (defaults from current .env)**: PGHOST=localhost PGPORT=5432 PGUSER=pouri PGPASSWORD=pouri PGDATABASE=pouri, PORT=3001.
Pool settings to replicate: max 10, idle timeout 30s, statement_timeout 8s.

---

## 4. Business rules (CRITICAL — encode exactly)

These were all discovered by probing production data. Each one has a reason.

### R1 — Price bucket inference
Raw `price_bucket` is NULL on tens of thousands of rows:
- NULL bucket **with amount > 0** → treat as **paid**
- NULL bucket **with no amount** → treat as **free** (public member-carrying groups without a price page are free; the old separate "unknown" tier was removed by product decision)
- Never read raw `price_bucket` without this remap.
- Price amount source: `price_usd`, falling back to `price_amount_cents / 100`.

### R2 — Visibility
- `privacy` ↔ `is_public` verified 1↔true, 0↔false exactly.
- `is_public IS NULL` (23 rows) counts as **private** everywhere.
- No "unknown" option exists in the UI anymore.

### R3 — Owner resolution (group detail)
`owner_id` alone lies. Resolution order (single SQL with LEFT JOINs):
1. `users u ON u.id = g.owner_id AND lower(u.name) = lower(g.owner_name)` → correct
2. `users fu ON fu.id = g.owner_id AND NOT(name matches)` → wrong-person-by-id fallback fields
3. `users u2 ON u2.name = g.owner_name AND u.id IS NULL` → resolve purely by canonical slug (covers wrong-id AND orphan-id cases; the `u.id IS NULL` guard covers BOTH — do not use `fu.id IS NOT NULL`)
Owner output = COALESCE(u2, fu, u) per field. Verified live: group `e0f76dfe...` resolves to Alex Hormozi via step 3.

### R4 — User-profile ownership
A user's OWNED groups come from `groups.owner_id = :user_id` (authoritative).
MEMBERED groups come from `user_groups WHERE role='member' OR role IS NULL`, excluding owned (`g.owner_id IS DISTINCT FROM :user_id`).
Filtering user_groups by role='owner' hid real owners' communities (6.5k null-role rows; 6.5k owners missing from user_groups entirely).

### R5 — Revenue estimate (used in cards, detail, compare AND revenue sorts)
```
price = price_usd ?? price_amount_cents/100
members = total_members
monetized = price_bucket IN ('paid','free-trial') OR (bucket NULL AND price > 0)
if not monetized or no members: return nothing

total      = price × members
interval   = price_interval ?? 'month'
months_age = clamp((now - created_at)/30.44 days, 0.5 .. 120); default 12 if created_at NULL

monthly:
  month     → total
  year      → total / 12
  week      → total × 4.33
  one_time  → total / months_age        (also expose one-time total separately)
round monthly to int.
Output keys: estimated_monthly_revenue_usd, estimated_one_time_revenue_usd (only one_time), estimated_rev_period.
```
The SQL sort expressions (`rev_desc`/`rev_asc`) MUST mirror this formula exactly (they already do in the reference; see §9).

### R6 — Facets with 'unknown'
Category/language/location/timezone facets include an `'unknown'` entry whose value means `col IS NULL`.
Multi-select semantics: selected real values OR-combined via `IN (...)`; if 'unknown' also selected add `OR col IS NULL`.

### R7 — Social presence
- Users: per-network columns non-empty; whitelist {website→link_website, twitter→link_twitter, linkedin→link_linkedin, youtube→link_youtube, instagram→link_instagram, facebook→link_facebook}.
- Groups: substring match on lower(links): instagram/youtube/tiktok; twitter matches '%twitter%' OR '%x.com%'. Facebook deliberately omitted for groups (false positives from share-links).

### R8 — Search escaping
All ILIKE user input escapes `\`, `%`, `_` with `ESCAPE '\'`. Multi-value params split on comma, trimmed, empty dropped, hard cap 40 items.

### R9 — Pagination
page ≥1 default 1; pageSize clamped 1..100 default 24. Total via `COUNT(*) OVER()` window on the paged query.

---

## 5. Hexagonal architecture — required layout

```
server-fastapi/
├── app/
│   ├── main.py                     # composition root: wiring only
│   ├── core/
│   │   ├── config.py               # pydantic-settings (PG*, PORT, TTLs)
│   │   └── cache.py                # TTLCache port + in-memory adapter
│   ├── domain/
│   │   ├── models.py               # pure domain objects (GroupCard, GroupDetail, UserCard…)
│   │   ├── filters.py              # GroupFilter/UserFilter/AnalyticsFilter value objects + parsing/validation
│   │   ├── pricing.py              # revenue formula (pure functions) — single source of truth
│   │   └── services/
│   │       ├── group_service.py
│   │       ├── user_service.py
│   │       ├── meta_service.py
│   │       └── analytics_service.py
│   ├── ports/                      # interfaces (Protocol classes)
│   │   ├── repositories.py         # GroupRepository, UserRepository, MembershipRepository, AnalyticsRepository, MetaRepository
│   │   └── cache.py
│   ├── adapters/
│   │   ├── db/
│   │   │   ├── pool.py             # asyncpg pool lifecycle
│   │   │   ├── sql/                # ALL SQL lives here, as constants/modules
│   │   │   │   ├── meta_sql.py
│   │   │   │   ├── groups_sql.py   # incl. SORTS dict + REV expression
│   │   │   │   ├── users_sql.py
│   │   │   │   └── analytics_sql.py
│   │   │   ├── group_repository.py # implements ports.GroupRepository
│   │   │   ├── user_repository.py
│   │   │   ├── meta_repository.py
│   │   │   └── analytics_repository.py
│   │   └── cache/in_memory.py
│   └── api/                        # driving adapters (thin!)
│       ├── deps.py                 # DI: request-scoped services
│       ├── schemas.py              # Pydantic RESPONSE models (match JSON exactly)
│       ├── groups.py               # routes: /groups, /groups/{id}, /groups/suggest, /groups/compare
│       ├── users.py
│       ├── meta.py
│       └── analytics.py
├── tests/                          # contract tests hitting a real DB (same queries as prod)
├── .env
└── requirements.txt                # fastapi, uvicorn[standard], asyncpg, pydantic-settings
```

Rules of the architecture:
- **api/** depends on domain/services only. Services depend on ports. Adapters implement ports. Nothing imports upward.
- Services return plain dicts/domain models — never asyncpg Records, never Response objects.
- All SQL strings live under `adapters/db/sql/` — services never contain SQL.
- Filter parsing/validation belongs in `domain/filters.py` (pure), invoked by services; FastAPI Query params convert into these value objects at the edge.
- New features = new port method + new SQL module + service method. Existing files stay stable (open/closed).
- Scaling out later: swap the in-memory cache adapter for Redis (same port), put uvicorn behind nginx, or move analytics to materialized views — none of these touch services/API.

DI wiring (main.py):
```python
pool = await create_pool(...)
group_repo = PgGroupRepository(pool)
cache = InMemoryCache(ttl=...)
meta_service = MetaService(PgMetaRepository(pool), cache=cache, ttl=300)
analytics_service = AnalyticsService(PgAnalyticsRepository(pool), cache=cache, ttl=120)
...
app.include_router(build_groups_router(group_service))
```

---

## 6. API contract (must match EXACTLY — client unchanged)

Conventions:
- Base path `/api`. All GET. Responses snake_case, identical key names.
- Errors: `{"error": "<message>"}` — 404 for missing ids, 500 otherwise (never leak SQL).
- `Cache-Control: public, max-age=15` on all /api responses + GZip.
- Multi-value params: comma-separated strings, cap 40 entries.
- Booleans: accept true/false/1/0.

### 6.1 GET /api/meta → cached 300s
```jsonc
{
  categories:   [{value,count}],           // COALESCE(category_slug,'unknown'), ORDER count DESC
  languages:    [{value,count}],           // COALESCE(language,'unknown')
  priceBuckets: [{value:'free'|'paid'|'free-trial',count}],   // per R1
  visibility:   [{value:'public'|'private',count}],          // per R2
  locations:    [{value,count}],           // users.location COALESCE 'unknown' LIMIT 40
  timezones:    [{value,count}],           // users.timezone LIMIT 40
  socials: {
    users:    [{value,count}],             // 6 networks per R7
    groups:   [{value,count}],             // instagram,youtube,tiktok,twitter per R7
    available: [user network values]
  },
  priceHistogram: [{bucket:'<10'|'10-25'|'25-50'|'50-100'|'100-200'|'200-500'|'500-1k'|'1k+',count}],
  priceBounds: {min,max,p99},              // over priced groups; defaults 1/100000/10000 when empty
  groupBounds: {members,posts},            // TRUE maxes (not percentiles!) defaults 100000/20000
  userBounds:  {followers,following,contributions},  // TRUE maxes, defaults 100000/10000/10000
  groupSorts: [{value,label}...] in order:
    most_members "Most members", fewest_members, most_posts, fewest_posts,
    engagement "Engagement (posts/member)", rev_desc "Revenue (high→low)", rev_asc,
    price_desc "Price (high→low)", price_asc, newest, oldest, name "Name A–Z",
  userSorts: most_followers, most_contributions, newest, oldest, name
}
```
12 queries run in parallel; single cached object.

### 6.2 GET /api/groups
Query params (all optional):

| Param | Type | Semantics |
|---|---|---|
| search | str | ILIKE name/display_name (R8) |
| owner | str | ILIKE owner_name |
| category, language | csv | facet per R6 |
| price | csv | free/paid/free-trial per R1 clauses OR-combined |
| minPriceUsd/maxPriceUsd | float | on effective price_usd (cents fallback) |
| priceInterval | enum | month/year/week/one_time |
| visibility | enum | public ⇒ is_public=true; private ⇒ false OR NULL (R2) |
| minMembers/maxMembers, minPosts/maxPosts | int | ranges |
| hasCourses, hasPosts, hasDescription, hasLinks | bool | true/false branches: courses>0; posts>0; length(description)>80; links non-empty ≠ '{"links": []}' (each also supports false = negation) |
| social | csv | group socials per R7 |
| createdFrom/createdTo | YYYY-MM-DD | created_at >= from ; < to+1 day |
| isMemberOf/isOwnerOf/notMemberOf | csv USER slugs | EXISTS user_groups ⋈ users ON ug.user_id=u.id AND lower(u.name)=ANY(list); roles: member / owner / (member OR owner) for negative |
| sort | enum | see groupSorts; rev sorts per R5 SQL expression |
| page/pageSize | int | R9 |

Response:
```jsonc
{ items: [GroupCard], pagination: {page,pageSize,total,totalPages} }
```
GroupCard = { id, name, display_name, initials, color, cover_url, logo_url,
total_members, total_posts, price_bucket(R1), price_interval, price_usd,
category_slug, language, is_public, owner_id, owner_name, created_at } + revenue block (R5, spread; absent when not monetized).
SELECT uses CARD_COLS + COUNT(*) OVER() AS _total.

### 6.3 GET /api/groups/{id}
404 `{"error":"Group not found"}` when unknown.
Response GroupCard fields PLUS description, lp_description, logo_big_url, favicon_url,
membership_model, total_online_members, total_admins, total_rules, num_courses,
num_modules, afl_percent, category_id, updated_at,
links: parsed array [{url,label,public}] (JSON parse tolerant: invalid/empty → []; http(s)-only urls),
owner: per R3 or null.
Full reference SQL (port verbatim, placeholders $1):
the 3-way LEFT JOIN from §4-R3 with COALESCE(u2,fu,u) aliased u_id,u_name,u_full_name,u_bio,u_avatar,u_followers,u_contributions,u_location.

### 6.4 GET /api/groups/suggest?q=
q trimmed, ≤60 chars. Top 8 groups ordered by total_members DESC:
`[{id,name,display_name,total_members}]`

### 6.5 GET /api/groups/compare?ids=a,b,c
≤12 ids, dedupe not required, ORDER PRESERVED (fetch with ANY($1), re-map to caller order).
Returns array of FULL detail objects (same SELECT as 6.3 but without the owner join is NOT acceptable — reuse the same detail query per id is fine given ≤12; reference impl uses a leaner joinless SELECT + serializeGroup; either is contract-compatible as long as GroupDetail shape holds).

### 6.6 GET /api/users
Params: search (ILIKE name/full_name/bio), location csv (R6), timezone csv (R6),
minFollowers/maxFollowers, minFollowing/maxFollowing, minContributions/maxContributions (int),
social csv (R7 user networks), creatorsOnly bool (EXISTS user_groups owner),
createdFrom/createdTo, hasBio/hasAvatar (supported server-side even though UI dropped them), sort enum, page/pageSize.
Items = UserCard {id,name,full_name,avatar_url,avatar_bubble_url,bio,location,total_followers,total_following,total_contributions}.

### 6.7 GET /api/users/{id}
Parallel 3 queries (user row, owned per R4, member per R4). 404 when user row missing.
```jsonc
{ user: UserFull(+first_name,last_name,timezone,links{6 networks},created_at),
  ownedGroups:[GroupCard], memberGroups:[GroupCard], ownedCount:int, memberCount:int }
```

### 6.8 GET /api/users/suggest?q=
Top 8 users by total_followers DESC: [{id,name,full_name,total_followers}]

### 6.9 GET /api/analytics → cached 120s per query-string, LRU ≤50
Filters applied to GROUP-sourced datasets: minMembers,maxMembers,minPosts,maxPosts,categories(csv),createdFrom,createdTo.
Time-series default window: last 24 months unless explicit dates.
Datasets (exact shapes):
```
kpi:{groups,users,memberships,member_slots}                    // member_slots = Σ total_members
groupSizes:[{bucket:'under-100'|'100-1k'|'1k-10k'|'10k-100k'|'100k+',count}]
categoryMembers:[{value,count,members}]                        // top15 by members
priceTiers:[{tier:'free'|'paid'|'free-trial',count,members}]   // per R1
categoryEngagement:[{value,posts_per_1k,count}]                // members>100 & posts>0; avg(1000*posts/members)
groupsMonthly:[{month:'YYYY-MM',count}]                        // date_trunc UTC
cohortGrowth:[{month,groups,members}]
topCommunities:[{name,display_name,total_members,total_posts,posts_per_1k}]  // members>5000 top12
revenueLeaders:[{value,revenue_monthly,paid_groups}]           // month×1 year÷12 week×4.33; one_time EXCLUDED; top12 HAVING>0
monetizationByCategory:[{value,total_groups,monetized_groups,monetized_pct,avg_price}]  // cats≥20 groups
ownerLeaderboard:[{value(owner_slug),full_name,groups,reach}]  // owners≥3 groups top15 by Σmembers
growthByCohortYear:[{year,groups,median_members,p90_members}]  // years≥2020, percentile_cont
priceSweetSpot:[{bucket,count,members}]                        // same bands as histogram
topLocations:[{value,count}]                                   // top10
catLangHeat:[{value(cat),lang,count}]                          // top6 langs per cat, both NOT NULL sources coalesced 'unknown'
```
Note: the cohort-year query intentionally ignores dynamic filters in the current build (plain WHERE year>=2020). Keep behavior identical unless product asks to change it.

---

## 7. Cross-cutting

- **Logging**: structured, one line per request (path, status, ms) + slow-query warn >500ms. No SQL text in logs.
- **Statement timeout 8s**, pool max 10 (replicate).
- **Graceful startup/shutdown**: create/close asyncpg pool in FastAPI lifespan.
- **CORS**: currently same-origin through vite proxy — do NOT add permissive CORS; keep it closed (add explicit allowlist config knob for future deploys).
- **Health endpoint**: add `GET /api/health` → `{status:"ok", db:"up|down"}` (new, additive; client unaffected).
- **Tests**: contract tests per endpoint asserting exact JSON keys + the business-rule cases (R1 buckets, R2 null-private, R3 hormozi group id `e0f76dfe658a4d3ea142b8936e472b68` → owner.full_name == "Alex Hormozi", R4 profile `be59d6d34a884a3999e6d9adb18d3f42` → ownedGroups contains "Comunidad Ecommerce").

## 8. Acceptance checklist (definition of done)

1. Against the same database, every endpoint returns byte-shape-compatible JSON vs the Express reference.
2. Filter-count parity spot checks: `price=free` → 75533, `paid` → 28692, `free-trial` → 5785, `visibility=private` → 18523, `public` → 91487.
3. `/api/groups?isMemberOf=sam` returns skoolers among results; suggest endpoints return 8 rows.
4. Client swap test: point vite proxy at the FastAPI port; browse/filter/sort/detail/compare/analytics/typeahead all work with zero client edits.
5. Architecture review: no SQL outside adapters/db/sql, api layer thin, services pure-Python-testable, cache swappable.

## 9. Reference SQL fragments (port verbatim)

Effective price expression:
```sql
COALESCE(g.price_usd, g.price_amount_cents / 100.0, 0)
```
PRICE_CLAUSES:
```sql
free       := (g.price_bucket = 'free' OR (g.price_bucket IS NULL AND (g.price_usd IS NULL OR g.price_usd = 0)))
free-trial := g.price_bucket = 'free-trial'
paid       := (g.price_bucket = 'paid' OR (g.price_bucket IS NULL AND g.price_usd IS NOT NULL AND g.price_usd > 0))
```
Revenue (sort-grade; mirrors R5):
```sql
MONTHS := LEAST(GREATEST(EXTRACT(EPOCH FROM (now() - COALESCE(g.created_at, now()))) / 2592000.0, 0.5), 120)
REV := CASE
  WHEN g.price_bucket IN ('paid','free-trial') OR (g.price_bucket IS NULL AND COALESCE(g.price_usd, g.price_amount_cents/100.0, 0) > 0)
  THEN COALESCE(g.price_usd, g.price_amount_cents/100.0, 0) * COALESCE(g.total_members, 0) *
    CASE g.price_interval WHEN 'year' THEN 1.0/12.0 WHEN 'week' THEN 4.33 WHEN 'one_time' THEN 1.0/MONTHS ELSE 1.0 END
  ELSE 0 END
```
Sorts (append `, g.id` tiebreak):
most_members `total_members DESC NULLS LAST` · fewest_members ASC · most_posts DESC · fewest_posts ASC ·
engagement `(total_posts::float/NULLIF(total_members,0)) DESC` · rev_desc REV DESC · rev_asc REV ASC ·
price_desc effective-price DESC · price_asc ASC · newest created_at DESC · oldest ASC · name ASC.
Users: most_followers DESC · most_contributions DESC · newest/oldest · name.

Membership EXISTS (groups side):
```sql
EXISTS (SELECT 1 FROM skool.user_groups ug JOIN skool.users u2 ON u2.id = ug.user_id
        WHERE ug.group_id = g.id AND <role clause> AND lower(u2.name) = ANY ($n))
-- negative: NOT EXISTS ... role IN ('member','owner')
```

GROUP_CARD_COLS:
```
g.id, g.name, g.display_name, g.initials, g.color, g.cover_url, g.logo_url,
g.total_members, g.total_posts, g.price_bucket, g.price_interval, g.price_usd,
g.category_slug, g.language, g.is_public, g.owner_id, g.owner_name, g.created_at
```
USER_CARD_COLS:
```
u.id, u.name, u.full_name, u.avatar_url, u.avatar_bubble_url, u.bio,
u.location, u.total_followers, u.total_following, u.total_contributions
```

Everything else (facet SQL, analytics SQL) is described precisely enough above to regenerate; where ambiguity exists, prefer the behavior documented in Business Rules.
