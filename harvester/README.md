# skool harvester

Scrapes data from the Skool site's `_next/data` and stores it in Postgres
(the `skool` schema).

## Setup

```bash
# 1) database
 docker compose up -d
 export DATABASE_URL=postgresql+asyncpg://pouri:pouri@localhost:5432/pouri

# 2) dependencies
 uv pip install -e .        # or: pip install sqlalchemy asyncpg curl_cffi

# 3) create tables and run a small crawl
 python -m skool.main --reset-db --mode browse \
     --categories tech --languages english --prices free --sorts trending \
     --pace 0.5
```

> Important: the schema changed (the `plans` table was removed, new columns
> like `groups.is_public` were added, and `users.display_name`, `users.email`,
> `users.myers_briggs`, `users.disc_top`, `users.total_groups` and
> `user_groups.role` were dropped). `--init-db` only creates missing tables and
> does not add new columns to an existing table; run once with `--reset-db`
> (previous data is wiped).

## Per-group chain

1. `discovery.json` → the group's base record (name, description, cover, price, member count)
2. `{group}/about.json` → full details: privacy, post/admin/rule counts,
   courses, group links, landing page and **price** — plus the **owner** block
   in the same response (no extra request)
3. `@{owner}.json` → the owner's full profile (name, timezone, all social
   links, stats) **inline, in the same pass** — not a separate nested stage
4. The owner's groups are written from that profile: owned groups
   (`groupsCreatedByUser`, `role='owner'`) and joined groups
   (`groupsMemberOf`, `role='member'`)
5. Then it moves on to the next group

> A user's groups come from two lists on the profile page:
> * `profileData.groupsCreatedByUser` → linked with `role='owner'`
> * `profileData.groupsMemberOf` → linked with `role='member'` (groups the user
>   merely joined)
>
> `user_groups.role` says which relation it is; `owner` links win on conflict.

**Database-completeness checks** (no re-requests): before requesting a group,
the pipeline checks `groups.detail_fetched` — if complete, the group is
skipped. Before requesting a user's profile, it checks `users.groups_fetched` —
if complete, the user is skipped. So a re-run only fetches what's missing.
There is **no deep snowball**: member-group owners are not recursively walked;
each user is fetched exactly once per run (`_seen_users` dedups in-memory too).

Price: first `metadata.displayPrice`, and if absent `metadata.currentMBp`. Both
are JSON strings (`{"currency":"usd","amount":99700}`) and land in
`price_amount_cents` / `price_usd` / `price_currency` / `price_interval`.
`currentMBp` sometimes lacks `recurring_interval`.

## Tables

* `groups` — in addition to before: `color`, `initials`, `logo_big_url`,
  `favicon_url`, `total_online_members`, `total_rules`, `afl_percent`,
  `src_group`, `links`, `price_amount_cents`, `price_usd`, `price_currency`,
  `price_interval`, `privacy`, **`is_public`**, `owner_id`, `owner_name`,
  `detail_fetched`

  `is_public` is a readable boolean derived from the group metadata:
  numeric `privacy` equal to `1` → `true` (public), `2` and above → `false`
  (private). If the site ever returns a string field
  (`groupType`/`visibility` = public/private), that is read too. If neither is
  present, `NULL` stays (i.e. unknown, not private).
* `users` — `first_name`, `last_name`, `full_name`, `timezone`, `bio`,
  `location`, `location_source`, `avatar_url`, `avatar_bubble_url`,
  `last_offline`, `link_facebook`, `link_instagram`, `link_linkedin`,
  `link_twitter`, `link_website`, `link_youtube`, stats (`total_followers`,
  `total_following`, `total_contributions`), `groups_fetched`

  Removed columns: `display_name` (the site doesn't have it), `email` (always
  `""`), `myers_briggs` and `disc_top` (almost always empty/useless),
  `total_groups` (the site's `totalGroups` includes memberships), and
  `total_posts` (the site has no such user stat). Get the correct owned-group
  count from the database:

  ```sql
  SELECT u.name, count(g.id) AS groups_owned
  FROM skool.users u
  LEFT JOIN skool.groups g ON g.owner_id = u.id
  GROUP BY u.name;
  ```
* `user_groups` — `user_id` + `group_id` + `role` (`owner` = the user created
  the group, `member` = they merely joined). `owner` links win on conflict.
* ~~`plans`~~ — **removed**. `plans.json` is not public and was always empty;
  the price now lives on `groups` itself.

## Modes

| mode | work |
| --- | --- |
| `browse` | category × language × price × sort × type |
| `search` | search terms (no `c` and `srt`) |
| `details` | complete the `about.json` of backlog groups |
| `users` | backlog owner profiles + snowball |
| `members` | **authenticated member search** — add matching users to the DB |
| `complete` | complete registered-but-incomplete users → their groups' details |
| `all` | all the steps above in sequence |

Useful flags: `--no-details` (discovery only), `--no-users` (no snowball),

### Member search (`--mode members`)

The authenticated `skoolers/-/search.json?q=…&t=members` endpoint returns
members matching a query (each page ~10 users). This mode runs the **alphabet
+ digits** query plan (36 short queries — the fast, high-coverage core; no
bigrams/keywords by default) and **inserts only users not already in the DB**
(`ON CONFLICT DO NOTHING`) — existing rows are never overwritten.

Pages within a query are fetched **concurrently** (`--member-search-concurrency`,
default 8), so a query's pages run in parallel instead of one-by-one.

### Complete users (`--mode complete`)

Walks every registered-but-incomplete user (`groups_fetched=False`, including
users added by `--mode members`) through the full chain:

1. **user profile** → writes the user, their owned groups (`role='owner'`) and
   joined groups (`role='member'`) into `user_groups`, marks the user scraped
2. **group details** → for each owned group, fetches `about.json` and writes
   its details (DB-completeness check skips already-fetched groups)

```bash
python -m skool.main --mode complete --cookies 'auth_token=...'
python -m skool.main --mode complete --complete-batch 100
```

Requires your logged-in `auth_token` cookie. The `aws-waf-token` is **solved
automatically**: when the client has an `auth_token` but no WAF token, it
launches a headless Chromium via Playwright, lets the AWS WAF challenge solve,
and uses the fresh token — so you only ever paste the `auth_token`:

```bash
python -m skool.main --mode members --cookies 'auth_token=eyJ...'

# custom query list / group / page cap
python -m skool.main --mode members --cookies 'auth_token=...' \
    --member-search-queries ai crypto \
    --member-search-group skoolers \
    --member-search-pages 2
```

Playwright needs its browser installed once:
```bash
uv run playwright install chromium
```

If you already have a valid `aws-waf-token`, pass it too and it's used
directly (no browser launch): `--cookies 'auth_token=...;aws-waf-token=...'`.
On a 202 challenge / WAF block the token is refreshed automatically.

This pass only **registers users** (it doesn't fetch their groups). A later
pass walks users who are registered but have no groups yet.
`--pace` (minimum interval between any two requests — the most effective
anti-403 weapon), `--reset-db` (rebuild the schema).

## Search coverage (`--mode search`)

The default query plan is built for near-total coverage of the Skool
catalogue, ordered by yield:

1. **319 keyword seeds** across every niche (business, money, health, tech/AI,
   education, creative, relationships, spirituality, hobbies, …)
2. **295 multi-word phrases** (`passive income`, `course creation`, …)
3. **57 non-Latin tokens** — one catch-all per script (CJK, Cyrillic, Arabic,
   Hebrew, Greek, Thai, Vietnamese, Indonesian, Hindi, Japanese) so groups
   whose names aren't Latin still get caught
4. **single letters + digits** (a–z, 0–9) — catches every 1-char ASCII name
5. **676 bigrams** (aa…zz) — the exhaustive ASCII fallback: every group name of
   length ≥ 2 contains at least one bigram, so running them all means no
   ASCII-named group can be missed

That's **1354 queries** total. Combined with the default `--search-languages
all` (48 languages), a full run issues ~65,000 discovery slices.

**Per-language queries**: when no explicit `--queries` is given, the search
uses `LANGUAGE_QUERIES` — a native keyword set per language. A German search
uses German words (`kurs`, `geld`, `unternehmen`), Japanese uses Japanese
(`コース`, `ビジネス`), Arabic uses Arabic (`دورة`, `أعمال`), etc. All 48
languages have a dedicated set; `english` uses the generic keyword plan. Pass
`--queries ai crypto` (or `--search-languages english`) to revert to one list
across languages.

To trim the plan: set `default_query_plan(include_bigrams=False)` in code for
681 queries.

## Proxy

You can supply proxies several ways (in priority order — the first found wins):

```bash
# 1) command line: multiple proxies separated by space/comma/semicolon
python -m skool.main --mode all \
    --proxies socks5://user:pass@host:1080 http://host:8080

# 2) list file (one per line, # for comments)
python -m skool.main --mode all --proxies-file proxies.txt

# 3) environment variable
SKOOL_PROXIES='http://a:80, socks5://b:1080' python -m skool.main --mode all

# 4) environment variable pointing to a file
PROXY_LIST_FILE=proxies.txt python -m skool.main --mode all

# 5) HTTP_PROXY / HTTPS_PROXY / ALL_PROXY (standard)
```

`--proxies` is read as a file itself if it's an existing path; otherwise it is
treated as a proxy list. The `file:` prefix does the same thing
(`--proxies file:proxies.txt`).

Acceptable formats: `http://`, `https://`, `socks4://`, `socks5://`,
`socks5h://` (DNS resolved by the proxy itself), `host:port` (converted to
http) and `user:pass@host:port`. Plain `host:port` lines in a list file work
too — they become `http://host:port`.

**Automatic rotation:** with multiple proxies, every 403/429 or network error
jumps to the next proxy (a fresh session is built per jump). When the full
cycle completes and every proxy has 403'd, the global step-wise cooldown runs
as before. With a single proxy or none, the previous behavior is preserved:
step-wise cooldown on the same route. You can also give just one proxy to
route all traffic through it (no rotation).

To fetch buildId (the prerequisite for every request), if you have proxies it
cycles up to 30 times to find a live one; without proxies it uses the usual
`retries`. So a mostly-dead proxy list should not kill the whole run before it
starts.

Proxy counters are visible in the final `client.stats` log:
`proxy_count`, `proxy_switches`, `proxy_os_error`, `proxy_ratelimit`.

## Data analysis (analyze)

The `skool.analyze` module runs 31 exploratory analyses (EDA) on the same
three database tables: text + tables in the terminal, plus PNG charts and a
`report.md` / `report.json`.

```bash
# 1) analysis dependencies (separate from the scraper itself)
uv pip install -e '.[analyze]'      # or: pip install pandas numpy matplotlib

# 2) list the analyses
python -m skool.analyze --list

# 3) full run
python -m skool.analyze
```

Default output lives in `analysis_out/`:

```
analysis_out/
├── report.md          # full report with markdown tables
├── report.json        # all metrics for machine consumption
├── report.txt         # the same thing printed to the terminal
├── charts/*.png       # ~47 charts
└── tables/*.csv       # only with --csv-tables
```

### Analysis groups

| # | group | analyses |
| --- | --- | --- |
| 1 | Data coverage & health | `overview`, `missingness`, `integrity` |
| 2 | Price & money | `price_distribution`, `price_points`, `price_by_interval`, `price_by_category`, `currency_mix`, `affiliate`, `market_size` |
| 3 | Members, engagement & relationships | `members_distribution`, `price_vs_members`, `free_vs_paid`, `engagement`, `numeric_correlations`, `outliers` |
| 4 | Access, category & language | `public_private`, `category_breakdown`, `language_breakdown`, `category_x_price`, `discovery_bias` |
| 5 | Time, growth & recency | `growth`, `recency`, `age_effects` |
| 6 | Owners & social networks | `owner_portfolio`, `owner_socials`, `owner_geography`, `owner_influence` |
| 7 | Content, text & market segmentation | `text_stats`, `content_depth`, `market_segments` |

The `integrity`, `currency_mix`, `outliers`, `discovery_bias` and
`owner_geography` analyses are intentionally chartless — they only print
text/tables.

### Sample commands

```bash
python -m skool.analyze --only price_distribution price_vs_members
python -m skool.analyze --groups 2 3            # only the price & members groups
python -m skool.analyze --groups price --no-charts
python -m skool.analyze --skip outliers text_stats
python -m skool.analyze --detailed-only --min-members 100
python -m skool.analyze --paid-only --category tech money
python -m skool.analyze --public-only --language en --since 2024-01-01
python -m skool.analyze --csv-tables --top 30 --chart-format svg

# snapshot: read from the database once, then analyze offline
python -m skool.analyze --dump-csv snapshot
python -m skool.analyze --from-csv snapshot --out-dir out2
```

Flags: `--only/--skip/--groups`, `--out-dir`, `--no-charts`, `--no-report`,
`--csv-tables`, `--chart-format {png,svg,pdf}`, `--dpi`, `--top`,
`--min-group`, `--from-csv`, `--dump-csv`, `--limit`, the filters
`--detailed-only/--paid-only/--public-only/--min-members/--category/--language/--since`,
and `--quiet` / `--log-level`.

### From code

```python
from skool.analyze import run_analysis

outcome = run_analysis(out_dir="analysis_out", charts=False)
print(outcome["metrics"]["price_vs_members.spearman"])
print(outcome["console"])
```

Methodology note: `est_mrr_usd` and `market_size` are very rough estimates
(the assumption "every member is an active customer"), only good for relative
comparison between groups. Correlation is not causation; Spearman is reported
instead of Pearson because the distributions are heavily skewed.

## Tests

```bash
# no network and no database (parser only, on real JSON)
python -m unittest skool.tests.test_parser -v

# the analysis module on synthetic data (needs pandas/numpy)
python -m unittest skool.tests.test_analyze -v

# the database layer on a real Postgres (rebuilds the schema!)
SKOOL_DB_TESTS=1 python -m unittest skool.tests.test_db_smoke -v
```

## Architecture notes

* Each unit of work takes its own session (`session_scope`); a SQLAlchemy
  session is not safe across tasks.
* All inserts are atomic `INSERT ... ON CONFLICT DO UPDATE` — no read-modify-write.
* Parametric fields are filled with `coalesce(current, new)`, content fields
  with `coalesce(new, current)`.
* `detail_fetched` and `groups_fetched` are progress flags and are only changed
  via `mark_*`.
* Unknown parser keys are dropped before insert using the table column names.
* Empty strings become `NULL` everywhere so the database doesn't fill up with `""`.
* `lastOffline` is a nanosecond timestamp; the parser detects
  seconds/milli/micro/nano.
* 403 = IP rate-limit; there is a step-wise global cooldown and rate-limit
  attempts do not count toward the retry budget.
* With multiple proxies, a 403/429 immediately jumps to the next proxy;
  the cooldown only runs once the whole cycle has 403'd.
