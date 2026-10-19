"""Account + usage schema bootstrap.

The skool schema is read-only for the API; auth state lives in its own
`app` schema (accounts, usage_log). Idempotent — safe to run at startup.
"""
import logging

logger = logging.getLogger("skool")

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.accounts (
    id            serial PRIMARY KEY,
    email         varchar(255) NOT NULL UNIQUE,
    password_hash varchar(255) NOT NULL,
    label         varchar(255),
    is_admin      boolean NOT NULL DEFAULT false,
    is_active     boolean NOT NULL DEFAULT true,
    expires_at    timestamptz NOT NULL DEFAULT now() + interval '30 days',
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.usage_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
    path        varchar(255) NOT NULL,
    status      integer NOT NULL,
    duration_ms integer,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_usage_log_account_time
    ON app.usage_log (account_id, created_at);
CREATE INDEX IF NOT EXISTS ix_usage_log_time
    ON app.usage_log (created_at);
"""

SCRAPER_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS skool;

CREATE TABLE IF NOT EXISTS skool.scraper_settings (
    id                      integer PRIMARY KEY DEFAULT 1,
    refresh_interval_days   integer NOT NULL DEFAULT 3,
    discovery_interval_days integer NOT NULL DEFAULT 7,
    refresh_cron            varchar(64) NOT NULL DEFAULT '0 2 */3 * *',
    discovery_cron          varchar(64) NOT NULL DEFAULT '0 3 * * 0',
    is_paused               boolean NOT NULL DEFAULT false,
    daemon_heartbeat_at     timestamptz,
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT single_scraper_settings CHECK (id = 1)
);

INSERT INTO skool.scraper_settings (id, refresh_interval_days, discovery_interval_days, refresh_cron, discovery_cron, is_paused)
VALUES (1, 3, 7, '0 2 */3 * *', '0 3 * * 0', false)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS skool.scraper_jobs (
    id            bigserial PRIMARY KEY,
    job_type      varchar(32) NOT NULL,
    trigger_type  varchar(16) NOT NULL DEFAULT 'manual',
    status        varchar(16) NOT NULL DEFAULT 'PENDING',
    started_at    timestamptz,
    finished_at   timestamptz,
    exit_code     integer,
    error_message text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_scraper_jobs_status
    ON skool.scraper_jobs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_scraper_jobs_type
    ON skool.scraper_jobs (job_type, created_at DESC);

CREATE TABLE IF NOT EXISTS skool.scraper_logs (
    id         bigserial PRIMARY KEY,
    job_id     bigint REFERENCES skool.scraper_jobs(id) ON DELETE CASCADE,
    level      varchar(10) NOT NULL DEFAULT 'INFO',
    message    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_scraper_logs_job_id
    ON skool.scraper_logs (job_id, id);
"""


async def ensure_scraper_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCRAPER_SCHEMA_SQL)
    logger.info("[scraper] schema ready")


async def ensure_auth_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        # One-off backfills for pre-existing installs (no-ops on fresh DBs).
        await conn.execute("""
            ALTER TABLE app.accounts
            ADD COLUMN IF NOT EXISTS label varchar(255),
            ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false
        """)
        await conn.execute(SCRAPER_SCHEMA_SQL)
    logger.info("[auth+scraper] schema ready")

