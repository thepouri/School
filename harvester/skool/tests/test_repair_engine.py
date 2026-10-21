"""Tests for RepairEngine (Self-healing audit and repair queries)."""

import pytest
from skool.db.db import session_scope
from skool.repair_engine import AuditReport, RepairEngine


@pytest.mark.asyncio
async def test_repair_engine_audit_live():
    async with session_scope() as session:
        report = await RepairEngine.run_audit(session)
        assert isinstance(report, AuditReport)
        assert isinstance(report.incomplete_groups, int)
        assert isinstance(report.owners_missing_in_users, int)
        assert isinstance(report.orphan_user_groups, int)


@pytest.mark.asyncio
async def test_repair_engine_repair_enqueue():
    async with session_scope() as session:
        stats = await RepairEngine.repair_and_enqueue(session, max_enqueue=10)
        assert isinstance(stats, dict)
        assert "groups_enqueued" in stats
        assert "stub_users_created" in stats
        assert "owner_links_healed" in stats
