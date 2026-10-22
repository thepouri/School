"""Account + usage schema bootstrap.

The skool schema is read-only for the API; auth state lives in its own
`app` schema (accounts, usage_log). Idempotent — safe to run at startup.
"""
import logging
import os

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

ALTER TABLE skool.scraper_settings
ADD COLUMN IF NOT EXISTS daemon_heartbeat_at timestamptz,
ADD COLUMN IF NOT EXISTS execution_mode varchar(32) NOT NULL DEFAULT 'parallel',
ADD COLUMN IF NOT EXISTS discovery_mode varchar(32) NOT NULL DEFAULT 'all',
ADD COLUMN IF NOT EXISTS page_concurrency integer NOT NULL DEFAULT 1,
ADD COLUMN IF NOT EXISTS detail_concurrency integer NOT NULL DEFAULT 2,
ADD COLUMN IF NOT EXISTS request_delay_ms integer NOT NULL DEFAULT 800,
ADD COLUMN IF NOT EXISTS include_bigrams boolean NOT NULL DEFAULT false;

ALTER TABLE skool.scraper_settings ALTER COLUMN refresh_interval_days SET DEFAULT 3;
ALTER TABLE skool.scraper_settings ALTER COLUMN discovery_interval_days SET DEFAULT 7;
ALTER TABLE skool.scraper_settings ALTER COLUMN refresh_cron SET DEFAULT '0 2 */3 * *';
ALTER TABLE skool.scraper_settings ALTER COLUMN discovery_cron SET DEFAULT '0 3 * * 0';
ALTER TABLE skool.scraper_settings ALTER COLUMN is_paused SET DEFAULT false;
ALTER TABLE skool.scraper_settings ALTER COLUMN execution_mode SET DEFAULT 'parallel';
ALTER TABLE skool.scraper_settings ALTER COLUMN discovery_mode SET DEFAULT 'all';
ALTER TABLE skool.scraper_settings ALTER COLUMN page_concurrency SET DEFAULT 1;
ALTER TABLE skool.scraper_settings ALTER COLUMN detail_concurrency SET DEFAULT 2;
ALTER TABLE skool.scraper_settings ALTER COLUMN request_delay_ms SET DEFAULT 800;
ALTER TABLE skool.scraper_settings ALTER COLUMN include_bigrams SET DEFAULT false;

INSERT INTO skool.scraper_settings (id, refresh_interval_days, discovery_interval_days, refresh_cron, discovery_cron, is_paused, execution_mode, discovery_mode, page_concurrency, detail_concurrency, request_delay_ms, include_bigrams)
VALUES (1, 3, 7, '0 2 */3 * *', '0 3 * * 0', false, 'parallel', 'all', 1, 2, 800, false)
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


SCHEMA_BOOTSTRAP_LOCK_ID = 74294821


async def _run_scraper_schema_locked(conn) -> None:
    await conn.execute(SCRAPER_SCHEMA_SQL)
    # Safe column type and default normalization for existing and fresh installs
    try:
        await conn.execute("""
            ALTER TABLE skool.scraper_jobs ALTER COLUMN id TYPE bigint;
            ALTER TABLE skool.scraper_logs ALTER COLUMN id TYPE bigint;
            ALTER TABLE skool.scraper_logs ALTER COLUMN job_id TYPE bigint;
            ALTER TABLE skool.scraper_settings
            ADD COLUMN IF NOT EXISTS discovery_mode varchar(32) NOT NULL DEFAULT 'all',
            ADD COLUMN IF NOT EXISTS page_concurrency integer NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS detail_concurrency integer NOT NULL DEFAULT 2,
            ADD COLUMN IF NOT EXISTS request_delay_ms integer NOT NULL DEFAULT 800,
            ADD COLUMN IF NOT EXISTS include_bigrams boolean NOT NULL DEFAULT false;

            ALTER TABLE skool.scraper_settings ALTER COLUMN refresh_interval_days SET DEFAULT 3;
            ALTER TABLE skool.scraper_settings ALTER COLUMN discovery_interval_days SET DEFAULT 7;
            ALTER TABLE skool.scraper_settings ALTER COLUMN refresh_cron SET DEFAULT '0 2 */3 * *';
            ALTER TABLE skool.scraper_settings ALTER COLUMN discovery_cron SET DEFAULT '0 3 * * 0';
            ALTER TABLE skool.scraper_settings ALTER COLUMN is_paused SET DEFAULT false;
            ALTER TABLE skool.scraper_settings ALTER COLUMN discovery_mode SET DEFAULT 'all';
            ALTER TABLE skool.scraper_settings ALTER COLUMN page_concurrency SET DEFAULT 1;
            ALTER TABLE skool.scraper_settings ALTER COLUMN detail_concurrency SET DEFAULT 2;
            ALTER TABLE skool.scraper_settings ALTER COLUMN request_delay_ms SET DEFAULT 800;
            ALTER TABLE skool.scraper_settings ALTER COLUMN include_bigrams SET DEFAULT false;
        """)
    except Exception as exc:
        logger.warning("[scraper] column normalization notice: %s", exc)

    # One-off deduplication of redundant snapshots taken on the same calendar day
    try:
        await conn.execute("""
            DELETE FROM skool.group_metrics m1
            USING skool.group_metrics m2
            WHERE m1.group_id = m2.group_id
              AND m1.id > m2.id
              AND m1.total_members IS NOT DISTINCT FROM m2.total_members
              AND m1.total_online_members IS NOT DISTINCT FROM m2.total_online_members
              AND m1.total_posts IS NOT DISTINCT FROM m2.total_posts
              AND m1.price_usd IS NOT DISTINCT FROM m2.price_usd
              AND m1.captured_at::date = m2.captured_at::date;
        """)
    except Exception as exc:
        logger.warning("[scraper] metric dedup notice: %s", exc)

    # V2 additive columns and persistent queue tables
    try:
        await conn.execute("""
            ALTER TABLE skool.groups
              ADD COLUMN IF NOT EXISTS detail_status      VARCHAR(16) NOT NULL DEFAULT 'pending',
              ADD COLUMN IF NOT EXISTS detail_attempts    INTEGER     NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS detail_last_error  TEXT,
              ADD COLUMN IF NOT EXISTS detail_fetched_at  TIMESTAMPTZ,
              ADD COLUMN IF NOT EXISTS first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              ADD COLUMN IF NOT EXISTS completeness       SMALLINT    NOT NULL DEFAULT 0;

            ALTER TABLE skool.groups ALTER COLUMN detail_fetched SET DEFAULT false;

            ALTER TABLE skool.users
              ADD COLUMN IF NOT EXISTS profile_status     VARCHAR(16) NOT NULL DEFAULT 'pending',
              ADD COLUMN IF NOT EXISTS profile_attempts   INTEGER     NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS profile_last_error TEXT,
              ADD COLUMN IF NOT EXISTS profile_fetched_at TIMESTAMPTZ,
              ADD COLUMN IF NOT EXISTS first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW();

            ALTER TABLE skool.users ALTER COLUMN groups_fetched SET DEFAULT false;

            ALTER TABLE skool.user_groups
              ADD COLUMN IF NOT EXISTS source        VARCHAR(24),
              ADD COLUMN IF NOT EXISTS last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW();

            CREATE TABLE IF NOT EXISTS skool.fetch_tasks (
              id            BIGSERIAL PRIMARY KEY,
              task_type     VARCHAR(32)  NOT NULL,
              dedupe_key    VARCHAR(255) NOT NULL,
              payload       JSONB        NOT NULL DEFAULT '{}',
              status        VARCHAR(12)  NOT NULL DEFAULT 'pending',
              priority      SMALLINT     NOT NULL DEFAULT 5,
              attempts      INTEGER      NOT NULL DEFAULT 0,
              max_attempts  INTEGER      NOT NULL DEFAULT 6,
              not_before    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
              locked_until  TIMESTAMPTZ,
              locked_by     VARCHAR(64),
              last_error    TEXT,
              job_id        BIGINT REFERENCES skool.scraper_jobs(id) ON DELETE SET NULL,
              created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
              updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_fetch_tasks_dedupe_active
              ON skool.fetch_tasks (dedupe_key) WHERE status IN ('pending','running');
            CREATE INDEX IF NOT EXISTS ix_fetch_tasks_claim
              ON skool.fetch_tasks (priority, not_before) WHERE status = 'pending';

            CREATE TABLE IF NOT EXISTS skool.discovery_queries (
              id            BIGSERIAL PRIMARY KEY,
              query_hash    CHAR(40)    NOT NULL UNIQUE,
              params        JSONB       NOT NULL,
              depth         SMALLINT    NOT NULL DEFAULT 0,
              pages_done    INTEGER     NOT NULL DEFAULT 0,
              total_results INTEGER,
              exhausted     BOOLEAN     NOT NULL DEFAULT FALSE,
              last_run_at   TIMESTAMPTZ,
              created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS skool.raw_responses (
              id            BIGSERIAL PRIMARY KEY,
              url           TEXT        NOT NULL,
              status_code   INTEGER     NOT NULL,
              content_type  VARCHAR(64),
              headers       JSONB,
              body          TEXT,
              bytes_size    INTEGER,
              fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
    except Exception as e:
        logger.warning("[scraper] v2 schema bootstrap notice: %s", e)

    # Bidirectional healing for groups with owner info but missing in skool.users
    try:
        await conn.execute("""
            INSERT INTO skool.users (id, name, full_name, created_at, updated_at)
            SELECT DISTINCT g.owner_id, g.owner_name, g.owner_name, NOW(), NOW()
            FROM skool.groups g
            WHERE g.owner_id IS NOT NULL 
              AND g.owner_name IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM skool.users u WHERE u.id = g.owner_id)
            ON CONFLICT (id) DO NOTHING;

            INSERT INTO skool.user_groups (user_id, group_id, role, scraped_at)
            SELECT DISTINCT g.owner_id, g.id, 'owner', NOW()
            FROM skool.groups g
            WHERE g.owner_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM skool.users u WHERE u.id = g.owner_id)
            ON CONFLICT (user_id, group_id) DO NOTHING;
        """)
    except Exception as exc:
        logger.warning("[scraper] owner sync notice: %s", exc)


async def _run_auth_schema_locked(conn) -> None:
    await conn.execute(SCHEMA_SQL)
    # One-off backfills for pre-existing installs (no-ops on fresh DBs).
    await conn.execute("""
        ALTER TABLE app.accounts
        ADD COLUMN IF NOT EXISTS label varchar(255),
        ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false
    """)

    # Seed initial admin account from environment if provided
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if (
        admin_email
        and admin_password
        and admin_password != "REPLACE_WITH_STRONG_ADMIN_PASSWORD"
    ):
        from app.core.security import hash_password

        existing = await conn.fetchval(
            "SELECT id FROM app.accounts WHERE email = $1", admin_email
        )
        if not existing:
            await conn.execute(
                """
                INSERT INTO app.accounts (email, password_hash, label, is_admin, is_active, expires_at)
                VALUES ($1, $2, 'Administrator', true, true, now() + interval '3650 days')
                ON CONFLICT (email) DO NOTHING
                """,
                admin_email,
                hash_password(admin_password),
            )
            logger.info("[auth] Initial admin account created for %s", admin_email)


async def ensure_scraper_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1);", SCHEMA_BOOTSTRAP_LOCK_ID)
        try:
            await _run_scraper_schema_locked(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1);", SCHEMA_BOOTSTRAP_LOCK_ID)
    logger.info("[scraper] schema ready")


async def ensure_auth_schema(pool) -> None:
    async with pool.acquire() as conn:
        logger.info("[bootstrap] Acquiring advisory lock for schema initialization...")
        await conn.execute("SELECT pg_advisory_lock($1);", SCHEMA_BOOTSTRAP_LOCK_ID)
        try:
            await _run_auth_schema_locked(conn)
            await _run_scraper_schema_locked(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1);", SCHEMA_BOOTSTRAP_LOCK_ID)
            logger.info("[bootstrap] Released schema initialization advisory lock.")
    logger.info("[auth+scraper] schema ready")
