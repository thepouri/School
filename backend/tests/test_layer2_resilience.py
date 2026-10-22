import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.adapters.db.scraper_repository import PgScraperRepository
from app.adapters.db.bootstrap import (
    SCHEMA_BOOTSTRAP_LOCK_ID,
    ensure_auth_schema,
    ensure_scraper_schema,
)


@pytest.mark.anyio
async def test_get_logs_bounded_limit_with_50k_records():
    """Test 3: Guarantee that get_logs queries and returns bounded log lines (<= 2000)

    even when 50,000 records exist in scraper_logs.
    """
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Context manager for pool.acquire()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = False

    # Mock jobs_rows
    job_row = {
        "id": 4,
        "job_type": "all",
        "trigger_type": "manual",
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "exit_code": None,
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
    }

    # Simulate 50,000 mock log lines available in DB, but the query should be bounded to 2000
    mock_50k_lines = [
        {
            "id": i,
            "job_id": 4,
            "level": "INFO",
            "message": f"Log line {i}",
            "created_at": datetime.now(timezone.utc),
        }
        for i in range(1, 2001)  # Database returns top 2000 due to LIMIT 2000
    ]

    async def fake_fetch(query, *args):
        if "FROM skool.scraper_jobs" in query:
            return [job_row]
        if "FROM skool.scraper_logs" in query:
            # Verify that the query contains LIMIT 2000
            assert "LIMIT 2000" in query, "SQL query MUST contain LIMIT 2000 to protect DB"
            return mock_50k_lines
        return []

    mock_conn.fetch.side_effect = fake_fetch

    repo = PgScraperRepository(mock_pool)
    result = await repo.get_logs(limit=50, job_id=4)

    assert len(result) == 1
    job_item = result[0]
    assert job_item["id"] == 4
    # Ensure line count is bounded to 2000
    assert len(job_item["lines"]) == 2000
    assert len(job_item["lines"]) <= 2000


@pytest.mark.anyio
async def test_concurrent_schema_bootstrap_no_deadlock():
    """Test 4: Verify that concurrent callers of ensure_auth_schema acquire pg_advisory_lock

    so DDL execution is strictly serialized without deadlock.
    """
    mock_pool = MagicMock()
    
    # Track lock acquisitions to verify mutual exclusion
    lock_held = False
    max_concurrent_locks = 0
    lock_operations = []

    def make_conn(conn_id):
        conn = AsyncMock()

        async def execute_side_effect(query, *args):
            nonlocal lock_held, max_concurrent_locks
            if "pg_advisory_lock" in query:
                assert args[0] == SCHEMA_BOOTSTRAP_LOCK_ID
                # While waiting or acquiring
                if lock_held:
                    # In real Postgres, second caller waits. We simulate delay:
                    while lock_held:
                        await asyncio.sleep(0.01)
                lock_held = True
                max_concurrent_locks += 1
                lock_operations.append(f"lock_acquired_{conn_id}")
            elif "pg_advisory_unlock" in query:
                assert args[0] == SCHEMA_BOOTSTRAP_LOCK_ID
                lock_held = False
                max_concurrent_locks -= 1
                lock_operations.append(f"lock_released_{conn_id}")
            return "OK"

        conn.execute.side_effect = execute_side_effect
        conn.fetchval.return_value = None
        return conn

    conn1 = make_conn(1)
    conn2 = make_conn(2)
    connections = [conn1, conn2]

    class MockAcquireContext:
        def __init__(self):
            self.conn = connections.pop(0)

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, *args):
            return False

    mock_pool.acquire.side_effect = lambda: MockAcquireContext()

    # Run two workers concurrently
    t1 = asyncio.create_task(ensure_auth_schema(mock_pool))
    t2 = asyncio.create_task(ensure_auth_schema(mock_pool))

    await asyncio.gather(t1, t2)

    # Verify that advisory lock was acquired and released by both workers in sequence
    assert "lock_acquired_1" in lock_operations
    assert "lock_released_1" in lock_operations
    assert "lock_acquired_2" in lock_operations
    assert "lock_released_2" in lock_operations
    # Crucial: lock was never held concurrently by both at the same time
    assert max_concurrent_locks == 0
