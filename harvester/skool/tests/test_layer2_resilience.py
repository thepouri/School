import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from skool.db.db import session_scope, LONG_TRANSACTION_THRESHOLD_S
from skool.db.models import Group
from skool.db.repository import upsert_groups


@pytest.mark.asyncio
async def test_session_scope_duration_tracking(caplog):
    """Test 1: Verify session_scope tracks transaction duration and logs long transactions."""
    with caplog.at_level(logging.WARNING, logger="skool.db"):
        # We patch LONG_TRANSACTION_THRESHOLD_S to a tiny value to test duration alerting
        with patch("skool.db.db.LONG_TRANSACTION_THRESHOLD_S", 0.05):
            async with session_scope() as session:
                assert session is not None
                # Simulate a simulated slow DB operation / sleep inside session
                await asyncio.sleep(0.08)

        # Check that warning was logged
        warning_found = any(
            "Long-running DB transaction detected" in record.message
            for record in caplog.records
        )
        assert warning_found, "Expected long-running transaction warning in logs"


@pytest.mark.asyncio
async def test_session_scope_closed_after_exit():
    """Test 1b: Verify session is strictly committed and closed after context manager exits."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    with patch("skool.db.db.SessionMaker", return_value=mock_session):
        async with session_scope() as s:
            assert s is mock_session
            # During block, close is not called yet
            mock_session.close.assert_not_called()

        # After block, commit and close must have been executed
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_batch_commits_per_chunk():
    """Test 2: Verify that writing a large batch of rows commits per chunk (more than 1 COMMIT)."""
    # Create 1000 dummy group rows
    rows = [
        {
            "id": f"grp_{i:04d}",
            "name": f"group_{i:04d}",
            "display_name": f"Group {i}",
            "total_members": i,
        }
        for i in range(1000)
    ]

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    # Call upsert_groups
    written = await upsert_groups(mock_session, rows, snapshot_mode="none")

    assert written == 1000
    # Because BIND_PARAM_CAP chunks 1000 rows into multiple batches,
    # session.commit() MUST have been called multiple times (once per chunk)
    commit_count = mock_session.commit.call_count
    assert commit_count > 1, f"Expected more than 1 commit for 1000 rows, got {commit_count}"
