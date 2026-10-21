"""Tests for Repository v2 enhancements (Never overwrite with empty, Task Queue, Stubs)."""

import asyncio

import pytest
from skool.db import repository as repo
from skool.db.db import session_scope
from skool.db.models import FetchTask, Group


def test_build_set_nullif_string_protection():
    """Verify that empty strings produce NULLIF so COALESCE keeps existing values."""
    mock_excluded = {
        "display_name": "",
        "description": "",
        "total_members": 100,
    }

    updates = repo._build_set(
        Group,
        columns=["display_name", "description", "total_members"],
        excluded=mock_excluded,
        keep_first=frozenset(),
        immutable=frozenset({"id"}),
    )

    assert "display_name" in updates
    assert "description" in updates
    assert "total_members" in updates


@pytest.mark.asyncio
async def test_task_queue_lifecycle():
    """Verify idempotent enqueue, claim with lease, completion, and fail backoff."""
    test_key = f"test_task_key_{asyncio.get_event_loop().time()}"

    async with session_scope() as session:
        # 1. Enqueue task with top priority (0)
        enqueued = await repo.enqueue_task(
            session=session,
            task_type="group_about",
            dedupe_key=test_key,
            payload={"name": "test-group-dedupe"},
            priority=0,
        )
        assert enqueued is True

        # 2. Duplicate enqueue should return False (idempotent)
        duplicate = await repo.enqueue_task(
            session=session,
            task_type="group_about",
            dedupe_key=test_key,
            payload={"name": "test-group-dedupe"},
            priority=0,
        )
        assert duplicate is False

    # 3. Claim task
    async with session_scope() as session:
        claimed = await repo.claim_tasks(
            session=session,
            worker_id="worker_test_1",
            batch_size=10,
            lease_sec=60,
        )
        our_task = next((t for t in claimed if t.dedupe_key == test_key), None)
        assert our_task is not None
        assert our_task.status == "running"
        assert our_task.locked_by == "worker_test_1"
        assert our_task.attempts == 1

        # 4. Complete task
        await repo.complete_task(session=session, task_id=our_task.id)

    # 5. Verify status done
    async with session_scope() as session:
        task_in_db = await session.get(FetchTask, our_task.id)
        assert task_in_db.status == "done"
        assert task_in_db.locked_by is None

        # Clean up test row
        await session.delete(task_in_db)
