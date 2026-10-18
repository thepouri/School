# Skool Browser (webapp)

A clean, read-only web UI for browsing the harvested Skool database.

- **No scraper coupling.** It talks to PostgreSQL only, through
  `skool.db.session_scope` — it never imports the parser, pipeline or client.
- **No writes.** Every endpoint is a `SELECT`.
- **English UI**, dark theme, fully responsive, no build step (vanilla HTML/CSS/JS).

## Run

```bash
# from the project root
uv run python -m skool.webapp --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>.

`DATABASE_URL` is read the same way as the scraper
(`postgresql+asyncpg://...`, default `pouri:pouri@localhost:5432/pouri`).

## Pages

| View | What it shows |
| --- | --- |
| **Groups** | All groups as cards (cover + logo, price, members, courses). Filters: search, category, language, price bucket, visibility, interval, min/max price, min/max members, min courses, min posts, detailed-only, sort. Paginated. |
| **Users** | Owners as cards (avatar, name, followers, owned-group count). Filters: search, location source, timezone, has avatar, owns groups, scraped, min/max followers, sort. Paginated. |

Click any card → modal:
- **Group modal**: cover hero, logo, metrics (members/posts/courses/modules/admins/price),
  description, links JSON, and the **owner** block with avatar, bio, location and
  social links — with a button to jump into the owner's own profile.
- **User modal**: avatar hero, bio, social links, metrics, and the list of
  **owned groups** (each clickable → that group's modal).

Images are loaded directly from the stored `cover_url` / `logo_url` /
`avatar_url` fields (assets.skool.com), with an initials-tile fallback when a
URL is missing or fails.

## API

All JSON under `/api`:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/groups` | Filtered + paginated groups |
| `GET /api/groups/{id}` | Group detail + `owner` |
| `GET /api/users` | Filtered + paginated users |
| `GET /api/users/{id}` | User detail + `groups` (all linked, each with `role` = `owner`/`member`) |
| `GET /api/filters/groups` | Facet values for group filter bars |
| `GET /api/filters/users` | Facet values for user filter bars |

Query params for `/api/groups`: `page`, `per_page` (≤200), `sort`
(`members_desc`|`members_asc`|`price_desc`|`price_asc`|`courses_desc`|
`posts_desc`|`newest`|`oldest`|`name`), `q`, `category`, `language`,
`price_bucket`, `currency`, `interval`, `is_public`
(`true`|`false`), `min_price`, `max_price`, `min_members`, `max_members`,
`min_courses`, `min_posts`, `detail` (`true`).

For `/api/users`: `page`, `per_page`, `sort`
(`followers_desc`|`followers_asc`|`owned_desc`|`name`), `q`,
`location_source`, `timezone`, `has_avatar` (`true`), `owned` (`true`),
`scraped` (`true`), `min_followers`, `max_followers`.

## Layout

```
skool/webapp/
├── __init__.py     # FastAPI app + routes
├── api.py          # read-only SQL query layer (filters / facets / details)
├── __main__.py     # CLI entry (uvicorn)
├── static/
│   ├── index.html  # page shell + styles
│   └── app.js      # SPA logic (views, filters, pagination, modals)
└── README.md
```
