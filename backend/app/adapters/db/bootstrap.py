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


async def ensure_auth_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        # One-off backfills for pre-existing installs (no-ops on fresh DBs).
        await conn.execute("""
            ALTER TABLE app.accounts
            ADD COLUMN IF NOT EXISTS label varchar(255),
            ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false
        """)
    logger.info("[auth] schema ready")
