"""DB-Backed Distributed Task Queue Engine and Resilient Workers.

Handlers for the 5 task types:
1. discovery_page: fetch Next.js discovery, bulk upsert, enqueue group_about for new/unfetched.
2. group_about: fetch about.json, atomic upsert (group + metrics + stub owner + user_groups), enqueue owner user_profile.
3. user_profile: fetch @handle.json, atomic upsert (user + metrics + stub groups + user_groups), enqueue unknown group_about.
4. member_page: fetch search.json?t=members, upsert stub members + user_groups.
5. user_groups_expand: expand communities for active members.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .db import repository as repo
from .db.db import session_scope
from .db.models import FetchTask
from .http_gateway import ClassifiedResponse, HttpGateway, ResponseClass
from .limiter import AdaptiveLimiter, CircuitBreaker
from .parser import (
    group_owner,
    parse_discovery,
    parse_group_detail,
    parse_member_search,
    parse_user_page,
)
from .token_manager import BuildIdManager, WafTokenManager

log = logging.getLogger("skool.queue_engine")
BASE_URL = "https://www.skool.com"


class TaskWorkerPool:
    """Async worker pool consuming tasks from PostgreSQL via FOR UPDATE SKIP LOCKED."""

    def __init__(
        self,
        gateway: HttpGateway,
        waf_manager: WafTokenManager,
        build_id_manager: BuildIdManager,
        limiter: AdaptiveLimiter,
        circuit_breaker: CircuitBreaker,
        concurrency: int = 2,
        lease_sec: int = 120,
        worker_prefix: str = "worker",
    ) -> None:
        self.gateway = gateway
        self.waf_manager = waf_manager
        self.build_id_manager = build_id_manager
        self.limiter = limiter
        self.circuit_breaker = circuit_breaker
        self.concurrency = concurrency
        self.lease_sec = lease_sec
        self.worker_prefix = worker_prefix

        self._running = False
        self._workers: list[asyncio.Task[None]] = []
        self._reaper_task: asyncio.Task[None] | None = None
        self._auth_expired_event = asyncio.Event()

    async def start(self) -> None:
        """Start worker pool and background lease reaper."""
        if self._running:
            return
        self._running = True
        log.info("Starting TaskWorkerPool with %d workers (lease=%ds)...", self.concurrency, self.lease_sec)

        # Start Lease Reaper
        self._reaper_task = asyncio.create_task(self._lease_reaper_loop())

        # Start worker loops
        for i in range(self.concurrency):
            worker_id = f"{self.worker_prefix}_{i + 1}"
            task = asyncio.create_task(self._worker_loop(worker_id))
            self._workers.append(task)

    async def stop(self) -> None:
        """Gracefully stop worker pool."""
        self._running = False
        log.info("Stopping TaskWorkerPool...")

        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

        for w in self._workers:
            w.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        log.info("TaskWorkerPool stopped")

    async def _lease_reaper_loop(self) -> None:
        """Periodically recover tasks from dead workers whose lease expired."""
        while self._running:
            try:
                await asyncio.sleep(30.0)
                async with session_scope() as session:
                    reaped = await repo.reap_stale_leases(session)
                    if reaped:
                        log.warning("Lease Reaper restored %d stale running tasks to pending", reaped)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Lease Reaper error: %s", exc)

    async def _worker_loop(self, worker_id: str) -> None:
        """Individual worker loop."""
        while self._running:
            try:
                # 1. Gate on Circuit Breaker (halts claim if circuit is OPEN)
                await self.circuit_breaker.wait_permission()

                # 2. Claim next available task atomically
                async with session_scope() as session:
                    tasks = await repo.claim_tasks(
                        session=session,
                        worker_id=worker_id,
                        batch_size=1,
                        lease_sec=self.lease_sec,
                    )

                if not tasks:
                    await asyncio.sleep(1.0)
                    continue

                task = tasks[0]
                await self._process_task(worker_id, task)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Unhandled error in worker %s: %s", worker_id, exc)
                await asyncio.sleep(2.0)

    async def _process_task(self, worker_id: str, task: FetchTask) -> None:
        """Dispatch task to appropriate handler and record execution."""
        task_type = task.task_type
        payload = task.payload or {}
        task_id = task.id

        try:
            if task_type == "discovery_page":
                await self._handle_discovery_page(task_id, payload)
            elif task_type == "group_about":
                await self._handle_group_about(task_id, payload)
            elif task_type == "user_profile":
                await self._handle_user_profile(task_id, payload)
            elif task_type == "member_page":
                await self._handle_member_page(task_id, payload)
            elif task_type == "user_groups_expand":
                await self._handle_user_groups_expand(task_id, payload)
            else:
                log.error("Unknown task type '%s' (task_id=%d)", task_type, task_id)
                async with session_scope() as session:
                    await repo.fail_task(session, task_id, f"Unknown task type: {task_type}", max_attempts=1)

        except Exception as exc:
            log.warning("Task %d (%s) failed with exception: %s", task_id, task_type, exc)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, str(exc), backoff_sec=min(60 * task.attempts, 600))

    # ────────────────── Task Handlers ──────────────────

    async def _handle_discovery_page(self, task_id: int, payload: dict[str, Any]) -> None:
        params = payload.get("params", {})
        page = payload.get("page", 1)
        build_id = await self.build_id_manager.get_build_id()

        query_str = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if query_str:
            query_str = f"&{query_str}"
        url = f"{BASE_URL}/_next/data/{build_id}/discovery.json?p={page}{query_str}"

        await self.limiter.acquire()
        resp = await self.gateway.execute(url)

        if resp.status_class in (ResponseClass.WAF_BLOCK, ResponseClass.RATE_LIMIT):
            await self.circuit_breaker.record_error(resp.status_class.value, self.limiter)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"WAF/Rate limit: {resp.status_class.value}", backoff_sec=30.0)
            return

        if resp.status_class == ResponseClass.WAF_CHALLENGE or resp.status_class == ResponseClass.WAF_SOFT:
            await self.waf_manager.get_token(force=True)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, "WAF challenge encountered", backoff_sec=10.0)
            return

        if resp.status_class != ResponseClass.OK:
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"HTTP {resp.http_status}: {resp.error_message}")
            return

        self.limiter.record_success()
        self.circuit_breaker.record_success()

        # Parse discovery data
        parsed = parse_discovery(resp.data or {})
        groups = parsed.get("groups", [])

        async with session_scope() as session:
            if groups:
                await repo.upsert_groups(session, groups, snapshot_mode="initial_only", source="discovery")

                # Enqueue group_about for each group needing full details
                for g in groups:
                    gname = g.get("name")
                    gid = g.get("id")
                    if gname and gid:
                        await repo.enqueue_task(
                            session=session,
                            task_type="group_about",
                            dedupe_key=f"group_about:{gname}",
                            payload={"name": gname, "group_id": gid},
                            priority=3,
                        )

            await repo.complete_task(session, task_id)

    async def _handle_group_about(self, task_id: int, payload: dict[str, Any]) -> None:
        group_name = payload.get("name")
        if not group_name:
            async with session_scope() as session:
                await repo.complete_task(session, task_id)
            return

        build_id = await self.build_id_manager.get_build_id()
        url = f"{BASE_URL}/_next/data/{build_id}/{group_name}/about.json?group={group_name}"

        await self.limiter.acquire()
        resp = await self.gateway.execute(url)

        # Disambiguate 404
        if resp.status_class == ResponseClass.NOT_FOUND:
            is_stale, _ = await self.build_id_manager.handle_not_found(url)
            if is_stale:
                # Stale build_id -> Retry task immediately without counting attempt
                async with session_scope() as session:
                    await repo.fail_task(session, task_id, "BuildId was stale, refreshed", backoff_sec=1.0)
                return
            else:
                # Genuine 404 -> GONE
                log.info("Group '%s' is GONE (404 Not Found)", group_name)
                async with session_scope() as session:
                    await repo.upsert_stub_group(session, group_id=payload.get("group_id") or group_name, group_name=group_name)
                    await repo.complete_task(session, task_id)
                return

        if resp.status_class == ResponseClass.GONE:
            log.info("Group '%s' is GONE (%s)", group_name, resp.error_message)
            async with session_scope() as session:
                await repo.complete_task(session, task_id)
            return

        if resp.status_class in (ResponseClass.WAF_BLOCK, ResponseClass.RATE_LIMIT):
            await self.circuit_breaker.record_error(resp.status_class.value, self.limiter)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"WAF/Rate limit: {resp.status_class.value}", backoff_sec=30.0)
            return

        if resp.status_class == ResponseClass.WAF_CHALLENGE or resp.status_class == ResponseClass.WAF_SOFT:
            await self.waf_manager.get_token(force=True)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, "WAF challenge", backoff_sec=10.0)
            return

        if resp.status_class != ResponseClass.OK:
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"HTTP {resp.http_status}: {resp.error_message}")
            return

        self.limiter.record_success()
        self.circuit_breaker.record_success()

        # Parse group and owner
        group_row = parse_group_detail(resp.data or {})
        owner_row = group_owner(resp.data or {})

        if not group_row:
            async with session_scope() as session:
                await repo.fail_task(session, task_id, "Could not parse group from about.json")
            return

        async with session_scope() as session:
            # Atomic write
            await repo.upsert_group_about(session, group_row=group_row, owner_row=owner_row, snapshot_mode="refresh")

            # Snowball: Enqueue user_profile for owner
            owner_handle = (owner_row or {}).get("name") or group_row.get("owner_name")
            owner_id = (owner_row or {}).get("id") or group_row.get("owner_id")
            if owner_handle:
                await repo.enqueue_task(
                    session=session,
                    task_type="user_profile",
                    dedupe_key=f"user_profile:{owner_handle}",
                    payload={"handle": owner_handle, "user_id": owner_id},
                    priority=3,
                )

            await repo.complete_task(session, task_id)

    async def _handle_user_profile(self, task_id: int, payload: dict[str, Any]) -> None:
        handle = payload.get("handle")
        if not handle:
            async with session_scope() as session:
                await repo.complete_task(session, task_id)
            return

        build_id = await self.build_id_manager.get_build_id()
        url = f"{BASE_URL}/_next/data/{build_id}/@{handle}.json"

        await self.limiter.acquire()
        resp = await self.gateway.execute(url)

        if resp.status_class == ResponseClass.NOT_FOUND:
            is_stale, _ = await self.build_id_manager.handle_not_found(url)
            if is_stale:
                async with session_scope() as session:
                    await repo.fail_task(session, task_id, "BuildId stale", backoff_sec=1.0)
                return
            else:
                log.info("User '@%s' is GONE (404 Not Found)", handle)
                async with session_scope() as session:
                    await repo.complete_task(session, task_id)
                return

        if resp.status_class == ResponseClass.GONE:
            async with session_scope() as session:
                await repo.complete_task(session, task_id)
            return

        if resp.status_class in (ResponseClass.WAF_BLOCK, ResponseClass.RATE_LIMIT):
            await self.circuit_breaker.record_error(resp.status_class.value, self.limiter)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"WAF: {resp.status_class.value}", backoff_sec=30.0)
            return

        if resp.status_class == ResponseClass.WAF_CHALLENGE or resp.status_class == ResponseClass.WAF_SOFT:
            await self.waf_manager.get_token(force=True)
            async with session_scope() as session:
                await repo.fail_task(session, task_id, "WAF challenge", backoff_sec=10.0)
            return

        if resp.status_class != ResponseClass.OK:
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"HTTP {resp.http_status}: {resp.error_message}")
            return

        self.limiter.record_success()
        self.circuit_breaker.record_success()

        parsed = parse_user_page(resp.data or {})
        if not parsed:
            async with session_scope() as session:
                await repo.fail_task(session, task_id, "Could not parse user page")
            return

        user_row = parsed["user"]
        owned = parsed.get("owned", [])
        member = parsed.get("member", [])

        async with session_scope() as session:
            await repo.upsert_user_profile(session, user_row=user_row, owned_groups=owned, member_groups=member)

            # Snowball: Enqueue any newly discovered owned/member groups for full details
            for g in owned + member:
                gname = g.get("name")
                gid = g.get("id")
                if gname and gid:
                    await repo.enqueue_task(
                        session=session,
                        task_type="group_about",
                        dedupe_key=f"group_about:{gname}",
                        payload={"name": gname, "group_id": gid},
                        priority=5,
                    )

            await repo.complete_task(session, task_id)

    async def _handle_member_page(self, task_id: int, payload: dict[str, Any]) -> None:
        group = payload.get("group", "skoolers")
        q = payload.get("q", "a")
        page = payload.get("page", 1)

        build_id = await self.build_id_manager.get_build_id()
        url = f"{BASE_URL}/_next/data/{build_id}/{group}/-/search.json?t=members&q={q}&p={page}"

        await self.limiter.acquire()
        resp = await self.gateway.execute(url)

        if resp.status_class == ResponseClass.AUTH_EXPIRED:
            log.error("AUTH_EXPIRED encountered in member_search! Members path paused.")
            self._auth_expired_event.set()
            async with session_scope() as session:
                await repo.fail_task(session, task_id, "Auth token expired", backoff_sec=3600.0)
            return

        if resp.status_class != ResponseClass.OK:
            async with session_scope() as session:
                await repo.fail_task(session, task_id, f"Status: {resp.status_class.value}")
            return

        self.limiter.record_success()
        self.circuit_breaker.record_success()

        parsed = parse_member_search(resp.data or {})
        users = parsed.get("users", [])

        async with session_scope() as session:
            for u in users:
                uid = u.get("id")
                uname = u.get("name")
                if uid and uname:
                    await repo.upsert_stub_user(session, user_id=uid, user_name=uname, full_name=u.get("full_name"))
                    await repo.link_user_groups(
                        session,
                        user_id=uid,
                        group_ids=[payload.get("group_id") or group],
                        role="member",
                        source="member_search",
                    )

            await repo.complete_task(session, task_id)

    async def _handle_user_groups_expand(self, task_id: int, payload: dict[str, Any]) -> None:
        # User profile expansion
        await self._handle_user_profile(task_id, payload)
