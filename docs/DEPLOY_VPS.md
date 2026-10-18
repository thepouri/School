# Deploy Guide — Skool Explorer on a Linux VPS

Target: Ubuntu 22.04/24.04 VPS + a domain name. Stack: **Caddy** (web server +
free HTTPS) serving the built React app and reverse-proxying `/api` to
**FastAPI/uvicorn**, with **PostgreSQL** local, all run by **systemd**.

Architecture on the server:

```
internet ──▶ Caddy :443 (your domain, auto-HTTPS)
              ├── static files  → /var/www/skool/dist   (built client)
              └── /api/*        → uvicorn 127.0.0.1:3001 (FastAPI)
                                     └── PostgreSQL localhost:5432
```

The client talks to `/api/...` relative — same origin in production, no CORS,
no proxy config changes needed in the app code.

---

## 1. What changes in the repo (nothing structural)

- Client: `npm run build` → `client/dist/`. The `vite.config.js` dev proxy is
  dev-only; production uses Caddy's path routing instead.
- Backend: no code changes. Only `.env` values differ (below).
- `client/src/lib/auth.js`, `api/client.js`: already use relative paths — work as-is.

## 2. Server prep (Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
# Python 3.11+, Node for the build (or build locally and rsync dist/)
sudo apt install -y python3.11 python3.11-venv postgresql caddy git
```

Create DB + user:

```bash
sudo -u postgres psql <<'SQL'
CREATE USER skool WITH PASSWORD 'CHANGE_ME_STRONG';
CREATE DATABASE skool OWNER skool;
SQL
```

Restore your data dump (from your machine):

```bash
# on your PC first:
pg_dump -U pouri -d pouri -n skool -Fc -f skool.dump
scp skool.dump user@SERVER:/tmp/
# on the server:
sudo -u postgres pg_restore -d skool --no-owner --role=skool /tmp/skool.dump
```

## 3. Backend on the server

```bash
sudo mkdir -p /opt/skool && sudo chown $USER /opt/skool
git clone <your-repo> /opt/skool/app        # or rsync server-fastapi/
cd /opt/skool/app/server-fastapi            # adjust to your layout
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt gunicorn
```

**/opt/skool/app/server-fastapi/.env** (values CHANGE from local):
```
PGHOST=localhost
PGPORT=5432
PGUSER=skool
PGPASSWORD=CHANGE_ME_STRONG
PGDATABASE=skool
PORT=3001
AUTH_JWT_SECRET=<generate: python -c "import secrets;print(secrets.token_urlsafe(48))">
AUTH_TOKEN_DAYS=7
META_CACHE_TTL_S=300
ANALYTICS_CACHE_TTL_S=120
ANALYTICS_CACHE_MAX=50
CORS_ORIGINS=                              # empty = closed; same-origin via Caddy
```
(Setting names follow app/core/config.py — check the file if any differ.)

**systemd unit** — `/etc/systemd/system/skool-api.service`:
```ini
[Unit]
Description=Skool Explorer API (FastAPI)
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/skool/app/server-fastapi
EnvironmentFile=/opt/skool/app/server-fastapi/.env
ExecStart=/opt/skool/app/server-fastapi/venv/bin/gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker -w 2 --bind 127.0.0.1:3001 --timeout 30
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/skool
sudo systemctl daemon-reload
sudo systemctl enable --now skool-api
curl http://127.0.0.1:3001/api/health     # → {"status":"ok","db":"up"}
```

## 4. Client build + deploy

On your PC:

```bash
cd "Skool Front/client" && npm ci && npm run build
rsync -avz --delete dist/ user@SERVER:/tmp/skool-dist/
```

On the server:

```bash
sudo mkdir -p /var/www/skool
sudo rsync -a --delete /tmp/skool-dist/ /var/www/skool/dist/
sudo chown -R www-data:www-data /var/www/skool
```

(Repeat these two steps for every release.)

## 5. Caddyfile — HTTPS + routing

**/etc/caddy/Caddyfile**:
```
skool.yourdomain.com {
    root * /var/www/skool/dist
    encode gzip

    # SPA fallback: unknown paths that aren't files → index.html
    try_files {path} /index.html

    # API → FastAPI
    handle /api/* {
        reverse_proxy 127.0.0.1:3001
    }

    # Static assets are content-hashed → cache hard
    @assets path /assets/*
    header @assets Cache-Control "public, max-age=31536000, immutable"

    file_server
}
```

```bash
sudo systemctl reload caddy
```

DNS: point an A record of `skool.yourdomain.com` at the VPS IP **before**
starting Caddy — it fetches Let's Encrypt certificates automatically on first
request. Verify: `curl -I https://skool.yourdomain.com/api/health`.

## 6. First-run checklist

1. `https://skool.yourdomain.com` → redirected to `/login`; sign in works.
2. Admin panel reachable; change the seeded admin password immediately
   (`POST /api/admin/accounts/{id}/password`) or delete+recreate it.
3. Browse/filters/analytics/metrics charts load (spot-check counts vs local).
4. `sudo journalctl -u skool-api -f` shows request logs, no tracebacks.
5. Usage rows appear in `app.usage_log` as you click around.

## 7. Updates (per release)

```bash
# backend
cd /opt/skool/app && git pull
sudo systemctl restart skool-api
# frontend (build locally, then)
sudo rsync -a --delete /tmp/skool-dist/ /var/www/skool/dist/
```

## 8. Security notes (do not skip)

- `.env` never enters git; generate a fresh `AUTH_JWT_SECRET` per environment.
- PostgreSQL listens on localhost only (default) — never open 5432 publicly.
- Keep `CORS_ORIGINS` empty while frontend and API share the domain.
- `ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable` — block everything else.
- Backups: `pg_dump -Fc` nightly cron to off-server storage; the whole product
  is the database.
