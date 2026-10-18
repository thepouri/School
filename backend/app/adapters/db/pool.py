"""asyncpg pool lifecycle (mirrors server/src/db.js settings)."""
from decimal import Decimal

import asyncpg

from app.core.config import settings


async def _init_conn(conn):
    # node-pg returns int8 (bigint) as a *string*; replicate so JSON shapes
    # match the Express reference byte-for-byte (::bigint sums → "12345").
    await conn.set_type_codec(
        "int8", encoder=str, decoder=str, format="text", schema="pg_catalog"
    )


async def create_pool() -> asyncpg.Pool:
    # Pass host/port/user/... explicitly instead of a URL DSN: some hosts
    # (e.g. alwaysdata) resolve their public DB name to loopback from inside
    # the app process, and DSN parsing also auto-enables SSL "prefer" which
    # changes the connect path. Explicit params = exactly what we tested.
    import logging
    logging.getLogger("skool").info(
        "[db] connecting to %s:%s db=%s user=%s",
        settings.pg_host, settings.pg_port, settings.pg_database, settings.pg_user,
    )
    if settings.db_ssl:
        ssl_ctx = _ssl_context()
        return await asyncpg.create_pool(
            host=settings.pg_host,
            port=settings.pg_port,
            user=settings.pg_user,
            password=settings.pg_password,
            database=settings.pg_database,
            min_size=1,
            max_size=settings.pool_max,
            command_timeout=settings.statement_timeout_ms / 1000.0,
            ssl=ssl_ctx,
            init=_init_conn,
        )
    return await asyncpg.create_pool(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        database=settings.pg_database,
        min_size=1,
        max_size=settings.pool_max,
        command_timeout=settings.statement_timeout_ms / 1000.0,
        init=_init_conn,
    )


def _ssl_context():
    """Trust-system default context for managed PG providers."""
    import ssl
    ctx = ssl.create_default_context()
    return ctx


def record_to_dict(row) -> dict:
    """Row → dict with node-pg semantics: NUMERIC comes back as a *string*
    (that is what the Express API serialized), everything else native."""
    if row is None:
        return {}
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dict(row).items()}


async def is_up(pool: asyncpg.Pool) -> bool:
    try:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except (asyncpg.PostgresError, ConnectionError, OSError):
        return False
