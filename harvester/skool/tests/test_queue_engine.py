"""Tests for TaskWorkerPool and Task Handlers."""

import asyncio

import pytest
from skool.db import repository as repo
from skool.db.db import session_scope
from skool.db.models import FetchTask, Group, User
from skool.http_gateway import ClassifiedResponse, HttpGateway, ResponseClass
from skool.limiter import AdaptiveLimiter, CircuitBreaker
from skool.queue_engine import TaskWorkerPool
from skool.token_manager import BuildIdManager, WafTokenManager


@pytest.mark.asyncio
async def test_worker_pool_start_stop():
    gw = HttpGateway()
    waf = WafTokenManager(gateway=gw)
    build_id_mgr = BuildIdManager(gateway=gw, initial_build_id="bld_test")
    limiter = AdaptiveLimiter()
    breaker = CircuitBreaker()

    pool = TaskWorkerPool(
        gateway=gw,
        waf_manager=waf,
        build_id_manager=build_id_mgr,
        limiter=limiter,
        circuit_breaker=breaker,
        concurrency=2,
    )

    await pool.start()
    assert pool._running is True
    assert len(pool._workers) == 2

    await pool.stop()
    assert pool._running is False
    assert len(pool._workers) == 0

    await waf.aclose()
    await gw.aclose()


@pytest.mark.asyncio
async def test_worker_handle_group_about_flow():
    gw = HttpGateway()
    waf = WafTokenManager(gateway=gw)
    build_id_mgr = BuildIdManager(gateway=gw, initial_build_id="bld_test")
    limiter = AdaptiveLimiter()
    breaker = CircuitBreaker()

    pool = TaskWorkerPool(
        gateway=gw,
        waf_manager=waf,
        build_id_manager=build_id_mgr,
        limiter=limiter,
        circuit_breaker=breaker,
        concurrency=1,
    )

    # Mock gateway execute for group about response
    async def mock_execute(url, *args, **kwargs):
        return ClassifiedResponse(
            status_class=ResponseClass.OK,
            http_status=200,
            data={
                "pageProps": {
                    "currentGroup": {
                        "id": "grp_worker_test",
                        "name": "worker-test-group",
                        "displayName": "Worker Test Group",
                        "metadata": {
                            "description": "Test group description",
                            "membership": 0,
                            "privacy": 1,
                            "totalMembers": 50,
                            "owner": {
                                "id": "usr_worker_owner",
                                "name": "owner-worker",
                                "firstName": "Alice",
                            },
                        },
                    }
                }
            },
            raw_text="{}",
            url=url,
        )

    gw.execute = mock_execute

    # Enqueue group_about task with priority 0
    test_key = f"group_about:worker-test-group_{asyncio.get_event_loop().time()}"
    async with session_scope() as session:
        await repo.enqueue_task(
            session=session,
            task_type="group_about",
            dedupe_key=test_key,
            payload={"name": "worker-test-group", "group_id": "grp_worker_test"},
            priority=0,
        )

    # Start pool to process
    await pool.start()
    for _ in range(10):
        await asyncio.sleep(0.1)
        async with session_scope() as session:
            t = await session.execute(
                FetchTask.__table__.select().where(FetchTask.dedupe_key == test_key)
            )
            row = t.fetchone()
            if row and row.status == "done":
                break
    await pool.stop()

    # Verify database state
    async with session_scope() as session:
        group = await session.get(Group, "grp_worker_test")
        assert group is not None
        assert group.name == "worker-test-group"
        assert group.detail_status == "ok"
        assert group.completeness == 100

        owner = await session.get(User, "usr_worker_owner")
        assert owner is not None
        assert owner.name == "owner-worker"

        # Clean up
        await session.delete(group)
        await session.delete(owner)

    await waf.aclose()
    await gw.aclose()
