"""Database connection and Base definition.

Important note about race conditions: every task must take its own session.
The SQLAlchemy session is absolutely not thread/task-safe; so always use
session_scope().
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "skool"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://pouri:pouri@localhost:5432/pouri",
)

import asyncio
import logging
import time

log = logging.getLogger("skool.db")

POOL_SIZE = int(os.getenv("HARVESTER_DB_POOL_SIZE", "3"))
MAX_OVERFLOW = int(os.getenv("HARVESTER_DB_MAX_OVERFLOW", "2"))
LONG_TRANSACTION_THRESHOLD_S = float(os.getenv("LONG_TX_THRESHOLD_S", "10.0"))

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "idle_in_transaction_session_timeout": "30000",
            "statement_timeout": "30000",
        }
    },
)

SessionMaker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


# Concurrency semaphore to bound active DB transactions
_DB_CONCURRENCY_LIMIT = int(os.getenv("DB_MAX_CONCURRENT_SESSIONS", "5"))
_db_semaphore = asyncio.Semaphore(_DB_CONCURRENCY_LIMIT)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A short independent session per unit of work with duration monitoring."""
    async with _db_semaphore:
        start_time = time.monotonic()
        session = SessionMaker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            duration = time.monotonic() - start_time
            if duration > LONG_TRANSACTION_THRESHOLD_S:
                log.warning(
                    "Long-running DB transaction detected: %.2fs (threshold: %.1fs)",
                    duration,
                    LONG_TRANSACTION_THRESHOLD_S,
                )
            await session.close()


async def init_db() -> None:
    """Create the schema and tables (only what is missing)."""
    from . import models  # noqa: F401  models must be registered

    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
        await conn.run_sync(Base.metadata.create_all)


async def reset_db() -> None:
    """Drop the whole schema and rebuild.

    Necessary because create_all does not add new columns to an existing
    table, and the previous schema (with the plans table and old columns)
    is incompatible.
    """
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()
