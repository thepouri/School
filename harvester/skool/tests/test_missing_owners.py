"""Unit and integration tests for missing owners recovery pipeline and repository."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ..db import repository as repo
from ..main import build_parser as build_main_parser, run as main_run
from ..pipeline import Pipeline


class TestMissingOwnersRepository(unittest.TestCase):
    def test_pending_missing_owner_groups_query(self) -> None:
        """Verify pending_missing_owner_groups executes select with detail_fetched=True and null owner."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("g1", "group-1"), ("g2", "group-2")]
        mock_session.execute.return_value = mock_result

        async def _run():
            return await repo.pending_missing_owner_groups(mock_session, limit=10)

        groups = asyncio.run(_run())
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], ("g1", "group-1"))
        self.assertEqual(groups[1], ("g2", "group-2"))
        mock_session.execute.assert_called_once()

    def test_heal_missing_owners_internally(self) -> None:
        """Verify heal_missing_owners_internally executes the bidirectional healing and returns rowcount."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute.return_value = mock_result

        async def _run():
            return await repo.heal_missing_owners_internally(mock_session)

        count = asyncio.run(_run())
        self.assertEqual(count, 10)
        self.assertEqual(mock_session.execute.call_count, 3)
        all_stmts = " ".join(str(call[0][0]) for call in mock_session.execute.call_args_list)
        self.assertIn("skool.groups", all_stmts)
        self.assertIn("skool.user_groups", all_stmts)
        self.assertIn("role = 'owner'", all_stmts)


class TestMissingOwnersPipeline(unittest.TestCase):
    def test_run_missing_owners_zero_external_requests_when_all_healed_tier_1(self) -> None:
        """Verify that when Tier 1 heals all groups, Tier 2 issues zero network requests."""
        client_mock = MagicMock()
        client_mock.stats = {}
        client_mock.group_about = AsyncMock()
        pipe = Pipeline(client=client_mock, fetch_users=False)

        async def _async_noop(*args, **kwargs):
            return None

        async def _run():
            with (
                patch("skool.pipeline.repo") as mock_repo,
                patch("skool.pipeline.session_scope") as mock_scope,
            ):
                mock_scope.return_value.__aenter__ = _async_noop
                mock_scope.return_value.__aexit__ = _async_noop

                # Tier 1 heals 3 groups
                mock_repo.heal_missing_owners_internally = AsyncMock(return_value=3)
                # Tier 2 finds nothing remaining
                mock_repo.pending_missing_owner_groups = AsyncMock(return_value=[])

                return await pipe.run_missing_owners()

        res = asyncio.run(_run())
        self.assertEqual(res["healed_internal"], 3)
        self.assertEqual(res["processed_external"], 0)
        client_mock.group_about.assert_not_called()

    def test_run_missing_owners_2_tier_recovery(self) -> None:
        """Verify Tier 1 heals internally and Tier 2 enriches remaining groups via network."""
        client_mock = MagicMock()
        client_mock.stats = {}

        async def _fake_about(name):
            return {
                "pageProps": {
                    "currentGroup": {
                        "id": "g999",
                        "name": "orphaned-group",
                        "metadata": {
                            "displayName": "Orphaned Group",
                            "createdBy": "u777",
                            "owner": {"id": "u777", "name": "found-owner"},
                        },
                    }
                }
            }

        client_mock.group_about = _fake_about
        pipe = Pipeline(client=client_mock, fetch_users=False)

        upserted_groups = []
        upserted_users = []
        linked_user_groups = []

        async def _async_noop(*args, **kwargs):
            return None

        async def _run():
            with (
                patch("skool.pipeline.repo") as mock_repo,
                patch("skool.pipeline.session_scope") as mock_scope,
            ):
                mock_scope.return_value.__aenter__ = _async_noop
                mock_scope.return_value.__aexit__ = _async_noop

                # Tier 1 heals 1 group internally
                mock_repo.heal_missing_owners_internally = AsyncMock(side_effect=[1, 0])

                # Tier 2 finds 1 group still missing owner
                mock_repo.pending_missing_owner_groups = AsyncMock(
                    side_effect=[[("g999", "orphaned-group")], []]
                )

                async def _upsert_g(session, row, *args, **kwargs):
                    upserted_groups.append(row)
                    return 1

                async def _upsert_u(session, user):
                    upserted_users.append(user)

                async def _link_ug(session, uid, gids, role=None):
                    linked_user_groups.append((uid, gids, role))

                async def _mark_df(session, gids):
                    return None

                mock_repo.upsert_group = _upsert_g
                mock_repo.upsert_user = _upsert_u
                mock_repo.link_user_groups = _link_ug
                mock_repo.mark_detail_fetched = _mark_df

                return await pipe.run_missing_owners(batch=10)

        res = asyncio.run(_run())
        self.assertEqual(res["healed_internal"], 1)
        self.assertEqual(res["processed_external"], 1)
        self.assertEqual(len(upserted_groups), 1)
        self.assertEqual(upserted_groups[0]["owner_name"], "found-owner")
        self.assertEqual(len(linked_user_groups), 1)
        self.assertEqual(linked_user_groups[0], ("u777", ["g999"], "owner"))


class TestMainCliMissingOwners(unittest.TestCase):
    def test_parser_accepts_missing_owners_mode(self) -> None:
        parser = build_main_parser()
        args1 = parser.parse_args(["--mode", "missing-owners"])
        self.assertEqual(args1.mode, "missing-owners")
        self.assertEqual(args1.missing_owners_batch, 200)

        args2 = parser.parse_args(["--mode", "missing_owners", "--missing-owners-batch", "50"])
        self.assertEqual(args2.mode, "missing_owners")
        self.assertEqual(args2.missing_owners_batch, 50)


if __name__ == "__main__":
    unittest.main()
