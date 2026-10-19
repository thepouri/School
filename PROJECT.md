# Project: Skool Explorer Refactoring, Automation & AWS Deployment

## Architecture
- **Backend Architecture**: FastAPI Hexagonal (Ports & Adapters) architecture located in `backend/`.
  - Driving Adapters: `app/api/` (HTTP route controllers translating requests to domain models). Zero direct SQL queries or connection pool acquisitions.
  - Domain Core: `app/domain/services/` (`GroupService`, `UserService`, `UsageService`, `MetricsService`). Pure business logic.
  - Ports: `app/ports/repositories.py` (Protocol interfaces defining data access contracts).
  - Driven Adapters: `app/adapters/db/` (`PgGroupRepository`, `PgUserRepository`, `PgUsageRepository`). All SQL execution and asyncpg connection management.
  - Middleware: `app/main.py` request latency elimination via `starlette.background.BackgroundTask`.
- **Harvester Subsystem**: Python data scraper located in `harvester/skool`.
  - 3-day stale group refresh (`--mode refresh --refresh-days 3 --no-users`) with time-series snapshots to `skool.group_metrics`.
  - Weekly deep discovery (`--mode all --no-users`) traversing 9 categories, 48 languages, and 1,354 query seeds, with zero-redundancy skipping of already-fetched groups.
  - Scheduler runner executing crontab jobs inside a containerized service.
- **Frontend Subsystem**: React 19 + Tailwind CSS in `frontend/`.
  - Multi-stage Docker build (`node:22-alpine` builder -> `nginx:1.27-alpine` runner).
  - Production static serving with gzip, SPA client routing (`try_files $uri $uri/ /index.html`), and immutable 1-year asset caching.
  - Relative `/api/...` reverse proxying to backend on port 3001, providing same-origin access with zero CORS overhead.
- **Deployment & Orchestration**:
  - Root `docker-compose.yml` orchestrating 4 services (`web`, `api`, `db`, `scheduler`).
  - `.env.production` template for production secrets.
  - `AWS_DEPLOY.md` guide for turnkey EC2/Lightsail deployment.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Clean direct SQL from `app/api/` | Remove `_group_exists` and `_user_exists` SQL queries from `app/api/metrics.py` | M1 | ORIGINAL_REQUEST §R1 |
| F2 | Port & Adapter `exists()` queries | Add `exists(id: str) -> bool` to `GroupRepository` and `UserRepository` ports and DB adapters | M1 | ORIGINAL_REQUEST §R1 |
| F3 | Domain service `exists()` methods | Expose `exists()` in `GroupService` and `UserService` and route API controllers through them | M1 | ORIGINAL_REQUEST §R1 |
| F4 | Clean healthcheck direct pool usage | Refactor `app/api/health.py` to decouple from raw `request.app.state.pool` | M1 | ORIGINAL_REQUEST §R1 |
| F5 | Usage service encapsulation | Add `record()` method to `UsageService` to prevent direct adapter calls from middleware | M1 | ORIGINAL_REQUEST §R1 |
| F6 | Non-blocking usage logging | Offload `usage.record(...)` in `app/main.py` HTTP middleware to `BackgroundTask` | M1 | ORIGINAL_REQUEST §R1 |
| F7 | Repository archive & artifact cleanup | Delete `Skool Backend/server-fastapi.zip` (24.9 MB) and update `.gitignore` with `*.zip` | M1 | ORIGINAL_REQUEST §R1 |
| F8 | 3-Day metrics refresh pipeline | Implement and verify `--mode refresh --refresh-days 3 --no-users` stale group scanning and metrics snapshotting | M2 | ORIGINAL_REQUEST §R2 |
| F9 | Staleness null-safety & time-series | Ensure `repo.all_groups` staleness filter is null-safe and writes records to `skool.group_metrics` | M2 | ORIGINAL_REQUEST §R2 |
| F10 | Weekly deep discovery pipeline | Implement and verify `--mode all --no-users` deep discovery across categories, languages, and query seeds | M2 | ORIGINAL_REQUEST §R3 |
| F11 | Zero-redundant group skipping | Enforce that previously indexed groups (`detail_fetched == True`) skip detail fetches with zero network calls | M2 | ORIGINAL_REQUEST §R3 |
| F12 | Standalone scheduler runner | Provide a containerized scheduler runner (e.g. `skool.scheduler` or crontab) running refresh and discovery jobs | M2 | ORIGINAL_REQUEST §R2, §R3 |
| F13 | Frontend multi-stage Dockerfile | Multi-stage Node 22 + Nginx Alpine Dockerfile with gzip, SPA fallback, immutable asset caching, and `/api/` reverse proxy | M3 | ORIGINAL_REQUEST §R4 |
| F14 | Backend lean non-root Dockerfile | Multi-stage `python:3.11-slim` non-root container with health check probe | M3 | ORIGINAL_REQUEST §R4 |
| F15 | Scheduler container Dockerfile | Lean container for running the harvester scheduler service | M3 | ORIGINAL_REQUEST §R4 |
| F16 | Root `docker-compose.yml` | 4-service compose stack (`web`, `api`, `db`, `scheduler`) with persistent volume, health checks, and network bridge | M3 | ORIGINAL_REQUEST §R4 |
| F17 | Production environment template | `.env.production` containing all necessary database, security, and API configurations | M3 | ORIGINAL_REQUEST §R4 |
| F18 | AWS deployment playbook | `AWS_DEPLOY.md` detailing EC2/Lightsail setup, Docker Compose deployment, SSL, swap, and maintenance | M3 | ORIGINAL_REQUEST §R4 |
| F19 | Full E2E & Domain verification | 100% pass across domain tests (`test_domain.py`), contract tests (`test_contract.py`), `npm run build`, and `docker compose config` | M4 | ORIGINAL_REQUEST Verification |
| F20 | Adversarial coverage hardening | Adversarial verification of boundary cases, database failures, and zero-leakage security | M4 | Project Pattern Phase 2 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Hexagonal Architecture Refactoring & Codebase Cleanup | F1, F2, F3, F4, F5, F6, F7 | none | DONE |
| M2 | Automated 3-Day Metrics Refresh & Weekly Discovery | F8, F9, F10, F11, F12 | none | DONE |
| M3 | Turnkey Dockerization & AWS Deployment Configuration | F13, F14, F15, F16, F17, F18 | M1, M2 | DONE |
| M4 | Full Verification & Adversarial Hardening | F19, F20 | M1, M2, M3 | DONE |
| M5 | Scraper Admin Management & Control API (Hexagonal) | F21, F22, F23, F24 | none | DONE |
| M6 | Harvester Scheduler DB Integration & Missing Owners | F25, F26 | M5 | DONE |
| M7 | Scraper Dashboard UI & MetricsChart Enhancements | F27, F28 | M5 | DONE |
| M8 | Full Verification & Non-Regression Hardening | F29 | M5, M6, M7 | IN_PROGRESS |

## Interface Contracts

### API Router ↔ Domain Services
- `group_service.exists(group_id: str) -> bool`
  - Returns `True` if group exists in `skool.groups`, otherwise `False`.
- `user_service.exists(user_id: str) -> bool`
  - Returns `True` if user exists in `skool.users`, otherwise `False`.
- `usage_service.record(account_id: int, endpoint: str, status_code: int, latency_ms: int) -> None`
  - Records usage log in background without blocking response.
- `health_service.check_db(pool) -> bool` / `is_up(pool) -> bool`
  - Checks if DB pool is healthy and responsive.

### Domain Services ↔ Repository Adapters
- `GroupRepository.exists(group_id: str) -> bool`:
  - `PgGroupRepository.exists(group_id: str) -> bool`: executes `SELECT 1 FROM skool.groups WHERE id = $1`.
- `UserRepository.exists(user_id: str) -> bool`:
  - `PgUserRepository.exists(user_id: str) -> bool`: executes `SELECT 1 FROM skool.users WHERE id = $1`.
- `UsageRepository.record(account_id: int, endpoint: str, status_code: int, latency_ms: int) -> None`:
  - `PgUsageRepository.record(...)`: executes `INSERT INTO app.usage_log ...`.

### Scraper Pipeline ↔ Scheduler
- Refresh Job Command: `python -m skool.main --mode refresh --refresh-days 3 --no-users`
  - Cron schedule: `0 2 */3 * *`
- Discovery Job Command: `python -m skool.main --mode all --no-users`
  - Cron schedule: `0 3 * * 0`

### Nginx ↔ Backend API
- `location /api/` -> `proxy_pass http://backend:3001;`
- Headers: `Host $host`, `X-Real-IP $remote_addr`, `X-Forwarded-For $proxy_add_x_forwarded_for`, `X-Forwarded-Proto $scheme`.

## Code Layout
- Backend Source: `backend/`
  - `app/api/` (metrics.py, health.py, etc.)
  - `app/ports/` (repositories.py)
  - `app/adapters/db/` (group_repository.py, user_repository.py, usage_repository.py)
  - `app/domain/services/` (group_service.py, user_service.py, usage_service.py)
  - `app/main.py` (FastAPI app & middleware)
  - `Dockerfile` (Backend container)
- Harvester Source: `harvester/skool/`
  - `main.py`, `pipeline.py`, `constants.py`
  - `db/models.py`, `db/repository.py`
  - `scheduler.py` (Recurring job scheduler)
  - `Dockerfile` (Scheduler container)
- Frontend Source: `frontend/`
  - `src/` (React components, API client, router)
  - `Dockerfile` (Multi-stage build)
  - `nginx.conf` (Nginx configuration)
- Root Deployment Files: `c:\Users\Pouri\Desktop\Coding\Projects\School\`
  - `docker-compose.yml`
  - `.env.production`
  - `AWS_DEPLOY.md`
