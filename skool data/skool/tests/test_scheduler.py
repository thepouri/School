"""Automated tests for the scheduler runner and refresh pipeline."""

from __future__ import annotations

import inspect
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from ..db import repository as repo
from ..scheduler import (
    HarvesterScheduler,
    ScheduledJob,
    build_default_jobs,
    cron_matches,
    main as scheduler_main,
    parse_cron_field,
)


class TestCronEvaluation(unittest.TestCase):
    def test_parse_cron_field_wildcard(self) -> None:
        matches = parse_cron_field("*", 0, 5)
        self.assertEqual(matches, {0, 1, 2, 3, 4, 5})

    def test_parse_cron_field_exact_and_list(self) -> None:
        matches = parse_cron_field("2,5", 0, 10)
        self.assertEqual(matches, {2, 5})

    def test_parse_cron_field_range(self) -> None:
        matches = parse_cron_field("1-4", 0, 10)
        self.assertEqual(matches, {1, 2, 3, 4})

    def test_parse_cron_field_step(self) -> None:
        # Day of month step */3 over 1-31 starts at 1: 1, 4, 7, 10, ...
        matches = parse_cron_field("*/3", 1, 31)
        self.assertIn(1, matches)
        self.assertIn(4, matches)
        self.assertIn(7, matches)
        self.assertIn(10, matches)
        self.assertIn(31, matches)
        self.assertNotIn(2, matches)

    def test_parse_cron_field_day_of_week_sunday(self) -> None:
        # Both 0 and 7 map to Sunday (0)
        matches_0 = parse_cron_field("0", 0, 6, is_dow=True)
        matches_7 = parse_cron_field("7", 0, 6, is_dow=True)
        self.assertEqual(matches_0, {0})
        self.assertEqual(matches_7, {0})

    def test_cron_matches_refresh_job(self) -> None:
        # "0 2 */3 * *" — Day 1, 4, 7, 10, ... at 02:00
        matching_dt = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
        self.assertTrue(cron_matches("0 2 */3 * *", matching_dt))

        # Different hour (03:00) -> False
        wrong_hour = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("0 2 */3 * *", wrong_hour))

        # Different minute (02:15) -> False
        wrong_minute = datetime(2026, 10, 1, 2, 15, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("0 2 */3 * *", wrong_minute))

        # Non-matching day (Day 2) -> False
        wrong_day = datetime(2026, 10, 2, 2, 0, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("0 2 */3 * *", wrong_day))

    def test_cron_matches_discovery_job(self) -> None:
        # "0 3 * * 0" — Every Sunday at 03:00
        # 2026-10-18 was a Sunday! (18 % 7 test: Oct 18, 2026 is Sunday)
        sunday_dt = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(sunday_dt.weekday(), 6)  # Sunday
        self.assertTrue(cron_matches("0 3 * * 0", sunday_dt))

        # Monday at 03:00 -> False
        monday_dt = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("0 3 * * 0", monday_dt))

        # Sunday at 02:00 -> False
        wrong_time = datetime(2026, 10, 18, 2, 0, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("0 3 * * 0", wrong_time))

    def test_invalid_cron_expression_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            cron_matches("0 2 * *", datetime.now(timezone.utc))


class TestSchedulerJobs(unittest.TestCase):
    def test_default_jobs_configuration(self) -> None:
        jobs = build_default_jobs(refresh_days=3.0)
        self.assertEqual(len(jobs), 2)
        names = {j.name for j in jobs}
        self.assertEqual(names, {"refresh", "discovery"})

        refresh = next(j for j in jobs if j.name == "refresh")
        self.assertEqual(refresh.cron, "0 2 */3 * *")
        self.assertIn("--mode", refresh.command)
        self.assertIn("refresh", refresh.command)
        self.assertIn("--refresh-days", refresh.command)
        self.assertIn("3", refresh.command)
        self.assertIn("--no-users", refresh.command)

        discovery = next(j for j in jobs if j.name == "discovery")
        self.assertEqual(discovery.cron, "0 3 * * 0")
        self.assertIn("--mode", discovery.command)
        self.assertIn("all", discovery.command)
        self.assertIn("--no-users", discovery.command)

    def test_job_as_dict(self) -> None:
        job = ScheduledJob(
            name="test",
            cron="* * * * *",
            description="test job",
            command=["python", "test.py"],
        )
        d = job.as_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["cron"], "* * * * *")
        self.assertEqual(d["run_count"], 0)


class TestSchedulerRunner(unittest.TestCase):
    def test_dry_run_job_execution(self) -> None:
        scheduler = HarvesterScheduler(dry_run=True)
        job = scheduler.get_job("refresh")
        self.assertIsNotNone(job)
        success = scheduler.run_job(job)  # type: ignore
        self.assertTrue(success)
        self.assertEqual(job.run_count, 1)  # type: ignore
        self.assertEqual(job.success_count, 1)  # type: ignore
        self.assertEqual(job.last_status, "SUCCESS")  # type: ignore
        self.assertIsNotNone(job.last_run_time)  # type: ignore

    @patch("subprocess.Popen")
    def test_successful_subprocess_execution(self, mock_popen) -> None:
        process_mock = MagicMock()
        process_mock.stdout = ["Processing batch 1\n", "Done\n"]
        process_mock.wait.return_value = None
        process_mock.returncode = 0
        mock_popen.return_value = process_mock

        scheduler = HarvesterScheduler(dry_run=False)
        job = scheduler.get_job("refresh")
        self.assertIsNotNone(job)
        success = scheduler.run_job(job)  # type: ignore

        self.assertTrue(success)
        self.assertEqual(job.last_status, "SUCCESS")  # type: ignore
        self.assertEqual(job.success_count, 1)  # type: ignore
        self.assertIsNone(job.last_error)  # type: ignore

    @patch("subprocess.Popen")
    def test_failed_subprocess_execution(self, mock_popen) -> None:
        process_mock = MagicMock()
        process_mock.stdout = ["Error: rate limited\n"]
        process_mock.wait.return_value = None
        process_mock.returncode = 2
        mock_popen.return_value = process_mock

        scheduler = HarvesterScheduler(dry_run=False)
        job = scheduler.get_job("discovery")
        self.assertIsNotNone(job)
        success = scheduler.run_job(job)  # type: ignore

        self.assertFalse(success)
        self.assertEqual(job.last_status, "FAILED")  # type: ignore
        self.assertEqual(job.failure_count, 1)  # type: ignore
        self.assertIn("exited with non-zero code 2", job.last_error)  # type: ignore

    @patch("subprocess.Popen", side_effect=OSError("Binary not found"))
    def test_exception_in_subprocess_handled_gracefully(self, mock_popen) -> None:
        scheduler = HarvesterScheduler(dry_run=False)
        job = scheduler.get_job("refresh")
        self.assertIsNotNone(job)
        success = scheduler.run_job(job)  # type: ignore

        self.assertFalse(success)
        self.assertEqual(job.last_status, "FAILED")  # type: ignore
        self.assertEqual(job.failure_count, 1)  # type: ignore
        self.assertIn("Binary not found", job.last_error)  # type: ignore

    def test_tick_triggers_and_deduplicates_in_same_minute(self) -> None:
        scheduler = HarvesterScheduler(dry_run=True)
        # Sunday at 03:00 matches "discovery"
        sunday_dt = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)
        triggered_first = scheduler.tick(sunday_dt)
        self.assertIn("discovery", triggered_first)

        # Same minute tick: should not re-trigger
        triggered_second = scheduler.tick(sunday_dt)
        self.assertEqual(triggered_second, [])

    def test_scheduler_status_reporting(self) -> None:
        scheduler = HarvesterScheduler(dry_run=True)
        st = scheduler.status()
        self.assertEqual(len(st), 2)
        self.assertIn("name", st[0])
        self.assertIn("cron", st[0])


class TestSchedulerCLI(unittest.TestCase):
    def test_run_now_refresh_dry_run(self) -> None:
        code = scheduler_main(["--run-now", "refresh", "--dry-run"])
        self.assertEqual(code, 0)

    def test_run_now_discovery_dry_run(self) -> None:
        code = scheduler_main(["--run-now", "discovery", "--dry-run"])
        self.assertEqual(code, 0)

    def test_run_now_all_dry_run(self) -> None:
        code = scheduler_main(["--run-now", "all", "--dry-run"])
        self.assertEqual(code, 0)

    def test_daemon_single_tick_dry_run(self) -> None:
        code = scheduler_main(["--daemon", "--single-tick", "--dry-run"])
        self.assertEqual(code, 0)


class TestRepositoryStalenessNullSafety(unittest.TestCase):
    def test_staleness_query_includes_null_safe_epoch_fallback(self) -> None:
        """Verify repository.all_groups SQL compilation includes coalesce with to_timestamp(0)."""
        source = inspect.getsource(repo.all_groups)
        self.assertIn("func.to_timestamp(0)", source)
        self.assertIn("func.coalesce(last_capture, Group.scraped_at, func.to_timestamp(0))", source)

        user_source = inspect.getsource(repo.all_users)
        self.assertIn("func.to_timestamp(0)", user_source)
        self.assertIn("func.coalesce(last_capture, User.scraped_at, func.to_timestamp(0))", user_source)


class TestDiscoverySkippingAndRefresh(unittest.TestCase):
    def test_deep_discovery_skips_already_indexed_groups(self) -> None:
        """Requirement R3: verify already-indexed groups (detail_fetched=True) skip network requests."""
        import asyncio
        from ..pipeline import Pipeline

        client_mock = MagicMock()
        client_mock.stats = {}
        client_mock.group_about = MagicMock()
        pipe = Pipeline(client=client_mock, fetch_users=False)

        async def _async_noop(*args, **kwargs):
            return None

        async def _run():
            with patch("skool.pipeline.repo") as mock_repo, patch("skool.pipeline.session_scope") as mock_scope:
                mock_scope.return_value.__aenter__ = _async_noop
                mock_scope.return_value.__aexit__ = _async_noop

                # Database reports group as already fetched
                async def _already_fetched(session, gid):
                    return True

                mock_repo.group_is_fetched = _already_fetched
                await pipe.process_group("g123", "cool-group", None, force=False)

        asyncio.run(_run())
        self.assertEqual(pipe.stats.groups_skipped, 1)
        self.assertEqual(pipe.stats.groups_detailed, 0)
        client_mock.group_about.assert_not_called()

    def test_refresh_pipeline_re_fetches_even_when_detail_fetched(self) -> None:
        """Requirement R2: verify refresh mode (force=True) re-fetches details to update stats and snapshots."""
        import asyncio
        from ..pipeline import Pipeline

        client_mock = MagicMock()
        client_mock.stats = {}

        async def _fake_about(name):
            return {
                "pageProps": {
                    "currentGroup": {
                        "id": "g123",
                        "name": "cool-group",
                        "metadata": {"displayName": "Cool Group", "totalMembers": 50},
                    }
                }
            }

        client_mock.group_about = _fake_about
        pipe = Pipeline(client=client_mock, fetch_users=False)

        upsert_called = []

        async def _async_noop(*args, **kwargs):
            return None

        async def _run():
            with patch("skool.pipeline.repo") as mock_repo, patch("skool.pipeline.session_scope") as mock_scope:
                mock_scope.return_value.__aenter__ = _async_noop
                mock_scope.return_value.__aexit__ = _async_noop

                async def _upsert(session, row):
                    upsert_called.append(row)
                    return 1

                async def _mark_fetched(session, ids):
                    return None

                mock_repo.upsert_group = _upsert
                mock_repo.mark_detail_fetched = _mark_fetched
                await pipe.process_group("g123", "cool-group", None, force=True)

        asyncio.run(_run())
        self.assertEqual(pipe.stats.groups_detailed, 1)
        self.assertEqual(len(upsert_called), 1)
        self.assertEqual(upsert_called[0]["id"], "g123")


if __name__ == "__main__":
    unittest.main()

