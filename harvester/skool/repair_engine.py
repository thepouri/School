"""Self-Healing Audit and Repair Engine for Skool Harvester.

Queries the real database for missing owners, orphans, and incomplete records,
repairs relationships immediately, and re-enqueues repair tasks into fetch_tasks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import repository as repo
from .db.models import FetchTask, Group, User, UserGroup

log = logging.getLogger("skool.repair_engine")


@dataclass
class AuditReport:
    incomplete_groups: int
    groups_missing_owner: int
    owners_missing_in_users: int
    incomplete_users: int
    orphan_user_groups: int
    missing_owner_links: int

    @property
    def is_healthy(self) -> bool:
        return (
            self.incomplete_groups == 0
            and self.owners_missing_in_users == 0
            and self.orphan_user_groups == 0
            and self.missing_owner_links == 0
        )


class RepairEngine:
    """Self-healing auditor and repair orchestrator."""

    @staticmethod
    async def run_audit(session: AsyncSession) -> AuditReport:
        """Run all 6 completeness audit queries and return metrics summary."""
        # 1. Incomplete groups
        q1 = await session.execute(
            text("""
                SELECT count(*) FROM skool.groups
                WHERE detail_status IN ('pending', 'partial', 'failed')
                  AND detail_attempts < 6
            """)
        )
        c1 = int(q1.scalar() or 0)

        # 2. Groups without owner after detail fetch ok
        q2 = await session.execute(
            text("""
                SELECT count(*) FROM skool.groups
                WHERE detail_status = 'ok' AND owner_id IS NULL
            """)
        )
        c2 = int(q2.scalar() or 0)

        # 3. Owners missing in users table
        q3 = await session.execute(
            text("""
                SELECT count(DISTINCT g.owner_id) FROM skool.groups g
                LEFT JOIN skool.users u ON u.id = g.owner_id
                WHERE g.owner_id IS NOT NULL AND u.id IS NULL
            """)
        )
        c3 = int(q3.scalar() or 0)

        # 4. Stub / incomplete users
        q4 = await session.execute(
            text("""
                SELECT count(*) FROM skool.users
                WHERE profile_status IN ('pending', 'stub', 'partial', 'failed')
                  AND profile_attempts < 6
            """)
        )
        c4 = int(q4.scalar() or 0)

        # 5. Orphan user_groups
        q5 = await session.execute(
            text("""
                SELECT count(*) FROM skool.user_groups ug
                LEFT JOIN skool.users u ON u.id = ug.user_id
                LEFT JOIN skool.groups g ON g.id = ug.group_id
                WHERE u.id IS NULL OR g.id IS NULL
            """)
        )
        c5 = int(q5.scalar() or 0)

        # 6. Owners without role='owner' in user_groups
        q6 = await session.execute(
            text("""
                SELECT count(*) FROM skool.groups g
                LEFT JOIN skool.user_groups ug ON ug.group_id = g.id
                     AND ug.user_id = g.owner_id AND ug.role = 'owner'
                WHERE g.owner_id IS NOT NULL AND ug.group_id IS NULL
            """)
        )
        c6 = int(q6.scalar() or 0)

        report = AuditReport(
            incomplete_groups=c1,
            groups_missing_owner=c2,
            owners_missing_in_users=c3,
            incomplete_users=c4,
            orphan_user_groups=c5,
            missing_owner_links=c6,
        )

        log.info(
            "Audit Report: incomplete_groups=%d, missing_owners=%d, unlinked_owners=%d, "
            "stub_users=%d, orphan_user_groups=%d, missing_owner_links=%d",
            report.incomplete_groups,
            report.groups_missing_owner,
            report.owners_missing_in_users,
            report.incomplete_users,
            report.orphan_user_groups,
            report.missing_owner_links,
        )
        return report

    @staticmethod
    async def repair_and_enqueue(session: AsyncSession, max_enqueue: int = 1000) -> dict[str, int]:
        """Perform zero-request repair where possible and re-enqueue repair tasks."""
        stats = {
            "groups_enqueued": 0,
            "stub_users_created": 0,
            "users_enqueued": 0,
            "owner_links_healed": 0,
        }

        # 1. Zero-request internal healing
        healed_count = await repo.heal_missing_owners_internally(session)
        stats["owner_links_healed"] += healed_count

        # 2. Repair missing owner users: insert stub user immediately
        missing_owners_res = await session.execute(
            text("""
                SELECT DISTINCT g.owner_id, g.owner_name FROM skool.groups g
                LEFT JOIN skool.users u ON u.id = g.owner_id
                WHERE g.owner_id IS NOT NULL AND g.owner_name IS NOT NULL AND u.id IS NULL
                LIMIT 500
            """)
        )
        for oid, oname in missing_owners_res.all():
            await repo.upsert_stub_user(session, user_id=oid, user_name=oname)
            stats["stub_users_created"] += 1

            # Enqueue user_profile task
            await repo.enqueue_task(
                session=session,
                task_type="user_profile",
                dedupe_key=f"user_profile:{oname}",
                payload={"handle": oname, "user_id": oid},
                priority=1,
            )
            stats["users_enqueued"] += 1

        # 3. Re-link owner relations
        await session.execute(
            text("""
                INSERT INTO skool.user_groups (user_id, group_id, role, source, last_seen_at)
                SELECT g.owner_id, g.id, 'owner', 'repair', NOW()
                FROM skool.groups g
                LEFT JOIN skool.user_groups ug ON ug.group_id = g.id
                     AND ug.user_id = g.owner_id AND ug.role = 'owner'
                WHERE g.owner_id IS NOT NULL AND ug.group_id IS NULL
                ON CONFLICT (user_id, group_id) DO UPDATE SET
                   role = 'owner',
                   last_seen_at = NOW()
            """)
        )

        # 4. Re-enqueue incomplete groups for about.json
        incomplete_groups_res = await session.execute(
            text("""
                SELECT id, name FROM skool.groups
                WHERE detail_status IN ('pending', 'partial', 'failed')
                  AND detail_attempts < 6
                  AND name IS NOT NULL
                ORDER BY completeness ASC, id ASC
                LIMIT :limit
            """),
            {"limit": max_enqueue},
        )
        for gid, gname in incomplete_groups_res.all():
            enqueued = await repo.enqueue_task(
                session=session,
                task_type="group_about",
                dedupe_key=f"group_about:{gname}",
                payload={"name": gname, "group_id": gid},
                priority=1,
            )
            if enqueued:
                stats["groups_enqueued"] += 1

        # 5. Re-enqueue stub users
        stub_users_res = await session.execute(
            text("""
                SELECT id, name FROM skool.users
                WHERE profile_status IN ('pending', 'stub', 'partial', 'failed')
                  AND profile_attempts < 6
                  AND name IS NOT NULL
                LIMIT :limit
            """),
            {"limit": max_enqueue // 2},
        )
        for uid, uname in stub_users_res.all():
            enqueued = await repo.enqueue_task(
                session=session,
                task_type="user_profile",
                dedupe_key=f"user_profile:{uname}",
                payload={"handle": uname, "user_id": uid},
                priority=3,
            )
            if enqueued:
                stats["users_enqueued"] += 1

        log.info("Repair and enqueue completed: %s", stats)
        return stats
