"""Adversarial stress-test suite for the harvester scheduler and cron matching.

Empirically tests edge cases, boundaries, error isolation, and CLI behaviors.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from ..scheduler import (
    HarvesterScheduler,
    ScheduledJob,
    build_default_jobs,
    cron_matches,
    main as scheduler_main,
    parse_cron_field,
)


class TestCronFieldAdversarial(unittest.TestCase):
    """Stress-test parse_cron_field and cron_matches boundary conditions."""

    def test_wildcard_all_ranges(self) -> None:
        self.assertEqual(parse_cron_field("*", 0, 59), set(range(0, 60)))
        self.assertEqual(parse_cron_field("*", 0, 23), set(range(0, 24)))
        self.assertEqual(parse_cron_field("*", 1, 31), set(range(1, 32)))
        self.assertEqual(parse_cron_field("*", 1, 12), set(range(1, 13)))
        self.assertEqual(parse_cron_field("*", 0, 6), set(range(0, 7)))

    def test_comma_separated_with_spaces_and_blanks(self) -> None:
        # Handles whitespace and empty segments gracefully
        res = parse_cron_field(" 1 , 5 , , 10 ", 0, 59)
        self.assertEqual(res, {1, 5, 10})

    def test_range_boundaries(self) -> None:
        self.assertEqual(parse_cron_field("0-0", 0, 59), {0})
        self.assertEqual(parse_cron_field("59-59", 0, 59), {59})
        self.assertEqual(parse_cron_field("0-59", 0, 59), set(range(0, 60)))
        self.assertEqual(parse_cron_field("1-31", 1, 31), set(range(1, 32)))

    def test_range_with_step(self) -> None:
        self.assertEqual(parse_cron_field("10-20/2", 0, 59), {10, 12, 14, 16, 18, 20})
        self.assertEqual(parse_cron_field("0-23/6", 0, 23), {0, 6, 12, 18})
        self.assertEqual(parse_cron_field("1-31/3", 1, 31), {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31})

    def test_single_value_with_step(self) -> None:
        # "2/5" over 0-15 should evaluate to 2, 7, 12
        self.assertEqual(parse_cron_field("2/5", 0, 15), {2, 7, 12})

    def test_day_of_week_mapping_sunday_0_and_7(self) -> None:
        # 0 and 7 are both Sunday
        self.assertEqual(parse_cron_field("0", 0, 6, is_dow=True), {0})
        self.assertEqual(parse_cron_field("7", 0, 6, is_dow=True), {0})
        self.assertEqual(parse_cron_field("0,7", 0, 6, is_dow=True), {0})

        # Range ending in 7: 5-7 (Fri, Sat, Sun) -> {5, 6, 0}
        self.assertEqual(parse_cron_field("5-7", 0, 6, is_dow=True), {0, 5, 6})

        # Range 6-7 (Sat, Sun) -> {6, 0}
        self.assertEqual(parse_cron_field("6-7", 0, 6, is_dow=True), {0, 6})

    def test_day_of_week_full_7_day_cycle(self) -> None:
        # 2026-10-12 was Monday (weekday=0, cron_dow=1)
        # 2026-10-13 was Tuesday (weekday=1, cron_dow=2)
        # 2026-10-14 was Wednesday (weekday=2, cron_dow=3)
        # 2026-10-15 was Thursday (weekday=3, cron_dow=4)
        # 2026-10-16 was Friday (weekday=4, cron_dow=5)
        # 2026-10-17 was Saturday (weekday=5, cron_dow=6)
        # 2026-10-18 was Sunday (weekday=6, cron_dow=0)
        expected_dow_mapping = [
            (datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc), "1"),  # Mon
            (datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc), "2"),  # Tue
            (datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc), "3"),  # Wed
            (datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc), "4"),  # Thu
            (datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc), "5"),  # Fri
            (datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc), "6"),  # Sat
            (datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc), "0"),  # Sun
            (datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc), "7"),  # Sun as 7
        ]

        from datetime import timedelta
        for dt, dow_str in expected_dow_mapping:
            cron = f"0 12 * * {dow_str}"
            self.assertTrue(
                cron_matches(cron, dt),
                f"Failed to match {dt.isoformat()} with cron '{cron}'"
            )
            # Verify adjacent day of week does not match
            other_dt = dt + timedelta(days=1)
            self.assertFalse(cron_matches(cron, other_dt))

    def test_leap_year_february_29_matching(self) -> None:
        # Leap year 2024
        leap_dt = datetime(2024, 2, 29, 2, 0, tzinfo=timezone.utc)
        self.assertTrue(cron_matches("0 2 29 2 *", leap_dt))

        # Non-leap year 2025: Feb 28 does not match 29
        non_leap_dt = datetime(2025, 2, 28, 2, 0, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("0 2 29 2 *", non_leap_dt))

    def test_year_transition_boundary(self) -> None:
        dt_end = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
        self.assertTrue(cron_matches("59 23 31 12 *", dt_end))
        self.assertFalse(cron_matches("0 0 1 1 *", dt_end))

        dt_start = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(cron_matches("0 0 1 1 *", dt_start))
        self.assertFalse(cron_matches("59 23 31 12 *", dt_start))

    def test_refresh_schedule_full_month_cadence(self) -> None:
        """Requirement R2: verify '0 2 */3 * *' strictly triggers on 1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31 at 02:00."""
        cron = "0 2 */3 * *"
        expected_days = {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31}

        for day in range(1, 32):
            # Test at 02:00 UTC
            dt_match_time = datetime(2026, 10, day, 2, 0, tzinfo=timezone.utc)
            if day in expected_days:
                self.assertTrue(cron_matches(cron, dt_match_time), f"Day {day} at 02:00 should match")
            else:
                self.assertFalse(cron_matches(cron, dt_match_time), f"Day {day} at 02:00 should not match")

            # Test at 02:01 UTC (should never match any day)
            dt_wrong_time = datetime(2026, 10, day, 2, 1, tzinfo=timezone.utc)
            self.assertFalse(cron_matches(cron, dt_wrong_time))

    def test_discovery_schedule_full_month_cadence(self) -> None:
        """Requirement R3: verify '0 3 * * 0' strictly triggers on Sundays at 03:00 UTC."""
        cron = "0 3 * * 0"
        # October 2026 Sundays: 4, 11, 18, 25
        sundays = {4, 11, 18, 25}

        for day in range(1, 32):
            dt_0300 = datetime(2026, 10, day, 3, 0, tzinfo=timezone.utc)
            if day in sundays:
                self.assertTrue(cron_matches(cron, dt_0300), f"Oct {day} is Sunday and should match")
            else:
                self.assertFalse(cron_matches(cron, dt_0300), f"Oct {day} is not Sunday and must not match")

    def test_invalid_cron_syntax_raises_error(self) -> None:
        now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # Less than 5 fields
        with self.assertRaises(ValueError):
            cron_matches("* * * *", now)
        # More than 5 fields
        with self.assertRaises(ValueError):
            cron_matches("* * * * * *", now)
        # Empty string
        with self.assertRaises(ValueError):
            cron_matches("", now)
        # Non-numeric token
        with self.assertRaises(ValueError):
            cron_matches("abc * * * *", now)
        with self.assertRaises(ValueError):
            cron_matches("* * * * xyz", now)


class TestSchedulerErrorToleranceAndProcessIsolation(unittest.TestCase):
    """Stress-test process isolation, error containment, and child process exits."""

    def test_real_subprocess_non_zero_exit_contained(self) -> None:
        """Empirically test scheduler execution with a real Python child process exiting 42."""
        cmd = [sys.executable, "-c", "import sys; print('failing child process'); sys.exit(42)"]
        job = ScheduledJob(
            name="failing_real_job",
            cron="* * * * *",
            description="Child process exiting 42",
            command=cmd,
        )
        scheduler = HarvesterScheduler(jobs=[job], dry_run=False)

        success = scheduler.run_job(job)
        self.assertFalse(success)
        self.assertEqual(job.last_status, "FAILED")
        self.assertEqual(job.run_count, 1)
        self.assertEqual(job.failure_count, 1)
        self.assertEqual(job.success_count, 0)
        self.assertIn("exited with non-zero code 42", job.last_error or "")

    def test_real_subprocess_success_tracked(self) -> None:
        """Empirically test scheduler execution with a real Python child process exiting 0."""
        cmd = [sys.executable, "-c", "import sys; print('successful child process'); sys.exit(0)"]
        job = ScheduledJob(
            name="successful_real_job",
            cron="* * * * *",
            description="Child process exiting 0",
            command=cmd,
        )
        scheduler = HarvesterScheduler(jobs=[job], dry_run=False)

        success = scheduler.run_job(job)
        self.assertTrue(success)
        self.assertEqual(job.last_status, "SUCCESS")
        self.assertEqual(job.run_count, 1)
        self.assertEqual(job.failure_count, 0)
        self.assertEqual(job.success_count, 1)
        self.assertIsNone(job.last_error)
        self.assertIsNotNone(job.last_duration_s)

    def test_tick_resilience_one_job_fails_other_still_executes(self) -> None:
        """Verify that when one job fails, the scheduler does NOT abort and continues to run other jobs."""
        job_fail = ScheduledJob(
            name="fail_job",
            cron="* * * * *",
            description="Failing job",
            command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        job_succeed = ScheduledJob(
            name="succeed_job",
            cron="* * * * *",
            description="Succeeding job",
            command=[sys.executable, "-c", "import sys; sys.exit(0)"],
        )
        scheduler = HarvesterScheduler(jobs=[job_fail, job_succeed], dry_run=False)

        triggered = scheduler.tick(datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(triggered, ["fail_job", "succeed_job"])

        # First job failed
        self.assertEqual(job_fail.last_status, "FAILED")
        self.assertEqual(job_fail.failure_count, 1)

        # Second job executed and succeeded!
        self.assertEqual(job_succeed.last_status, "SUCCESS")
        self.assertEqual(job_succeed.success_count, 1)

    def test_tick_deduplication_same_minute_and_multi_tick(self) -> None:
        """Ensure multiple ticks in the same minute trigger only once, but a tick in the next minute triggers again."""
        job = ScheduledJob(
            name="dedup_job",
            cron="* * * * *",
            description="Every minute job",
            command=["mock"],
        )
        scheduler = HarvesterScheduler(jobs=[job], dry_run=True)

        t1 = datetime(2026, 10, 18, 12, 0, 10, tzinfo=timezone.utc)
        triggered1 = scheduler.tick(t1)
        self.assertEqual(triggered1, ["dedup_job"])
        self.assertEqual(job.run_count, 1)

        # Second tick 20s later in same minute
        t2 = datetime(2026, 10, 18, 12, 0, 30, tzinfo=timezone.utc)
        triggered2 = scheduler.tick(t2)
        self.assertEqual(triggered2, [])
        self.assertEqual(job.run_count, 1)  # not incremented

        # Third tick in next minute (12:01)
        t3 = datetime(2026, 10, 18, 12, 1, 5, tzinfo=timezone.utc)
        triggered3 = scheduler.tick(t3)
        self.assertEqual(triggered3, ["dedup_job"])
        self.assertEqual(job.run_count, 2)  # incremented


class TestSchedulerCLIEmpirical(unittest.TestCase):
    """Empirically test CLI flags and exit code semantics."""

    def test_cli_dry_run_flags(self) -> None:
        self.assertEqual(scheduler_main(["--run-now", "refresh", "--dry-run"]), 0)
        self.assertEqual(scheduler_main(["--run-now", "discovery", "--dry-run"]), 0)
        self.assertEqual(scheduler_main(["--run-now", "all", "--dry-run"]), 0)
        self.assertEqual(scheduler_main(["--daemon", "--single-tick", "--dry-run"]), 0)
        self.assertEqual(scheduler_main(["--single-tick", "--dry-run"]), 0)

    @patch("subprocess.Popen")
    def test_cli_run_now_exit_code_on_child_failure(self, mock_popen) -> None:
        proc = MagicMock()
        proc.stdout = []
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        # Non-dry-run where child fails -> main must return 1
        code = scheduler_main(["--run-now", "refresh"])
        self.assertEqual(code, 1)

    @patch("subprocess.Popen")
    def test_cli_run_now_exit_code_on_child_success(self, mock_popen) -> None:
        proc = MagicMock()
        proc.stdout = []
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc

        code = scheduler_main(["--run-now", "discovery"])
        self.assertEqual(code, 0)


class TestSchedulerDBIntegrationAdversarial(unittest.TestCase):
    """Empirical challenge suite for HarvesterScheduler dynamic settings, pause, and DB failure resilience."""

    def test_dynamic_interval_reload_changes_timing_without_restart(self) -> None:
        """Requirement: Modifying settings in skool.scraper_settings alters job timing without restarting process."""
        scheduler = HarvesterScheduler(dry_run=True, enable_db=True)

        current_settings = {
            "refresh_interval_days": 3,
            "discovery_interval_days": 7,
            "refresh_cron": "0 2 */3 * *",
            "discovery_cron": "0 3 * * 0",
            "is_paused": False,
        }

        async def _noop(*args, **kwargs):
            return None

        with patch("skool.scheduler.repo") as mock_repo, patch("skool.scheduler.session_scope") as mock_scope:
            mock_scope.return_value.__aenter__ = _noop
            mock_scope.return_value.__aexit__ = _noop
            mock_repo.update_daemon_heartbeat = AsyncMock(return_value=None)
            mock_repo.claim_next_pending_job = AsyncMock(return_value=None)
            mock_repo.get_scraper_settings = AsyncMock(side_effect=lambda session: dict(current_settings))

            # Phase 1: At 2026-10-01 02:00 UTC (day 1), matches default '0 2 */3 * *'
            t1 = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
            triggered1 = scheduler.tick(t1)
            self.assertIn("refresh", triggered1)
            ref_job = scheduler.get_job("refresh")
            self.assertIsNotNone(ref_job)
            self.assertEqual(ref_job.cron, "0 2 */3 * *")
            idx = ref_job.command.index("--refresh-days")
            self.assertEqual(ref_job.command[idx + 1], "3")

            # Phase 2: Modify settings dynamically in PostgreSQL (simulated via DB mock)
            # Change refresh to 10 days, cron "0 8 */10 * *", and discovery to Wednesday 09:00 "0 9 * * 3"
            current_settings["refresh_interval_days"] = 10
            current_settings["refresh_cron"] = "0 8 */10 * *"
            current_settings["discovery_cron"] = "0 9 * * 3"

            # At 2026-10-04 02:00 UTC: under OLD cron (*/3), day 4 would have triggered!
            # Under NEW cron (0 8 */10 * *), 02:00 UTC does NOT match.
            t2 = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)
            triggered2 = scheduler.tick(t2)
            self.assertNotIn("refresh", triggered2)
            # Verify internal scheduler state has dynamically updated
            self.assertEqual(ref_job.cron, "0 8 */10 * *")
            idx = ref_job.command.index("--refresh-days")
            self.assertEqual(ref_job.command[idx + 1], "10")

            # At 2026-10-11 08:00 UTC (day 11 matches */10 starting at 1, hour 8) -> MUST trigger!
            t3 = datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)
            triggered3 = scheduler.tick(t3)
            self.assertIn("refresh", triggered3)

            # At Wednesday 2026-10-14 09:00 UTC (weekday=2, cron_dow=3) -> discovery MUST trigger!
            t4 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
            triggered4 = scheduler.tick(t4)
            self.assertIn("discovery", triggered4)
            disc_job = scheduler.get_job("discovery")
            self.assertIsNotNone(disc_job)
            self.assertEqual(disc_job.cron, "0 9 * * 3")

            # Phase 3: Modify settings AGAIN to daily refresh (1 day, cron "0 0 * * *")
            current_settings["refresh_interval_days"] = 1
            current_settings["refresh_cron"] = "0 0 * * *"
            t5 = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
            triggered5 = scheduler.tick(t5)
            self.assertIn("refresh", triggered5)
            idx = ref_job.command.index("--refresh-days")
            self.assertEqual(ref_job.command[idx + 1], "1")

    def test_dynamic_reload_partial_settings_and_missing_flags_robustness(self) -> None:
        """Verify scheduler handles partial settings payloads without corrupting command state."""
        scheduler = HarvesterScheduler(dry_run=True, enable_db=True)
        async def _noop(*args, **kwargs):
            return None

        with patch("skool.scheduler.repo") as mock_repo, patch("skool.scheduler.session_scope") as mock_scope:
            mock_scope.return_value.__aenter__ = _noop
            mock_scope.return_value.__aexit__ = _noop

            # Setting with missing refresh_cron and discovery_cron
            mock_repo.get_scraper_settings = AsyncMock(
                return_value={"refresh_interval_days": 6, "is_paused": False}
            )
            settings = scheduler.reload_settings()
            self.assertIsNotNone(settings)
            ref_job = scheduler.get_job("refresh")
            self.assertIsNotNone(ref_job)
            # Existing cron is preserved
            self.assertEqual(ref_job.cron, "0 2 */3 * *")
            # Refresh days updated to 6
            idx = ref_job.command.index("--refresh-days")
            self.assertEqual(ref_job.command[idx + 1], "6")

            # If job didn't have --refresh-days originally, it is appended cleanly
            ref_job.command = ["python", "-m", "skool.main", "--mode", "refresh"]
            mock_repo.get_scraper_settings = AsyncMock(
                return_value={"refresh_interval_days": 8}
            )
            scheduler.reload_settings()
            self.assertIn("--refresh-days", ref_job.command)
            idx2 = ref_job.command.index("--refresh-days")
            self.assertEqual(ref_job.command[idx2 + 1], "8")

    def test_pause_behavior_suppresses_cron_while_heartbeat_and_manual_queue_function(self) -> None:
        """Requirement: is_paused = True prevents scheduled runs while heartbeat and manual queue still function."""
        scheduler = HarvesterScheduler(dry_run=True, enable_db=True)

        async def _noop(*args, **kwargs):
            return None

        heartbeat_calls = []
        claimed_jobs = [
            {"id": 201, "job_type": "missing-owners", "trigger_type": "manual"},
            None,
        ]

        with patch("skool.scheduler.repo") as mock_repo, patch("skool.scheduler.session_scope") as mock_scope:
            mock_scope.return_value.__aenter__ = _noop
            mock_scope.return_value.__aexit__ = _noop

            async def _hb(session):
                heartbeat_calls.append(datetime.now(timezone.utc))
                return None

            mock_repo.update_daemon_heartbeat = _hb
            mock_repo.get_scraper_settings = AsyncMock(
                return_value={
                    "is_paused": True,
                    "refresh_interval_days": 3,
                    "refresh_cron": "* * * * *",  # would match every minute!
                    "discovery_cron": "* * * * *",
                }
            )
            mock_repo.claim_next_pending_job = AsyncMock(side_effect=claimed_jobs)
            mock_repo.insert_scraper_log = AsyncMock(return_value=None)
            mock_repo.finish_scraper_job = AsyncMock(return_value=None)

            # Tick at any time
            now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
            triggered = scheduler.tick(now)

            # 1. Scheduled runs are suppressed
            self.assertEqual(triggered, [], "Scheduled runs must NOT execute when paused")
            self.assertTrue(scheduler.is_paused)

            # 2. Heartbeat MUST still function
            self.assertEqual(len(heartbeat_calls), 1, "Heartbeat MUST update even when scheduler is paused")

            # 3. Manual queue MUST still function
            mock_repo.claim_next_pending_job.assert_called()
            mock_repo.finish_scraper_job.assert_called_once()
            call_kwargs = mock_repo.finish_scraper_job.call_args[1] or {}
            call_args = mock_repo.finish_scraper_job.call_args[0]
            self.assertIn(201, list(call_args) + list(call_kwargs.values()))
            self.assertIn("SUCCESS", list(call_args) + list(call_kwargs.values()))

    def test_pause_and_resume_lifecycle(self) -> None:
        """Verify scheduler transitions from paused to resumed cleanly across ticks."""
        scheduler = HarvesterScheduler(dry_run=True, enable_db=True)
        job = ScheduledJob(name="per_minute", cron="* * * * *", description="test", command=["python"])
        scheduler.jobs = [job]

        state = {"is_paused": True}
        async def _noop(*args, **kwargs):
            return None

        with patch("skool.scheduler.repo") as mock_repo, patch("skool.scheduler.session_scope") as mock_scope:
            mock_scope.return_value.__aenter__ = _noop
            mock_scope.return_value.__aexit__ = _noop
            mock_repo.update_daemon_heartbeat = AsyncMock(return_value=None)
            mock_repo.claim_next_pending_job = AsyncMock(return_value=None)
            mock_repo.get_scraper_settings = AsyncMock(side_effect=lambda s: dict(state))

            # Minute 1: Paused
            t1 = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
            res1 = scheduler.tick(t1)
            self.assertEqual(res1, [])
            self.assertTrue(scheduler.is_paused)

            # Minute 2: Resumed by admin
            state["is_paused"] = False
            t2 = datetime(2026, 10, 18, 12, 1, tzinfo=timezone.utc)
            res2 = scheduler.tick(t2)
            self.assertEqual(res2, ["per_minute"])
            self.assertFalse(scheduler.is_paused)

    def test_resilience_when_postgresql_fails_or_is_unreachable(self) -> None:
        """Requirement: Scheduler does NOT crash when PostgreSQL is unreachable or throws errors."""
        scheduler = HarvesterScheduler(dry_run=True, enable_db=True)

        class BrokenScope:
            async def __aenter__(self):
                raise ConnectionRefusedError("PostgreSQL 5432 unreachable or crashed")

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        with patch("skool.scheduler.session_scope", side_effect=lambda *args, **kwargs: BrokenScope()):
            # 1. Heartbeat fails gracefully without crashing
            self.assertFalse(scheduler.update_heartbeat())

            # 2. Settings reload fails gracefully without crashing
            self.assertIsNone(scheduler.reload_settings())

            # 3. Queue polling fails gracefully without crashing
            self.assertEqual(scheduler.poll_and_execute_queued_jobs(), 0)

            # 4. Tick survives complete DB failure and continues running
            t = datetime(2026, 10, 18, 3, 0, tzinfo=timezone.utc)  # Sunday 03:00
            triggered = scheduler.tick(t)
            # Scheduled job (discovery) still executes in dry-run even with DB logging failing!
            self.assertIn("discovery", triggered)

    def test_resilience_intermittent_db_disconnect_and_recovery(self) -> None:
        """Verify scheduler survives intermittent DB dropouts and recovers immediately upon reconnect."""
        scheduler = HarvesterScheduler(dry_run=True, enable_db=True)

        async def _noop(*args, **kwargs):
            return None

        fail_mode = True

        with patch("skool.scheduler.repo") as mock_repo, patch("skool.scheduler.session_scope") as mock_scope:
            def _scope_factory(*args, **kwargs):
                if fail_mode:
                    raise OSError("Network partition to database host")
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = _noop
                mock_ctx.__aexit__ = _noop
                return mock_ctx

            mock_scope.side_effect = _scope_factory
            mock_repo.update_daemon_heartbeat = AsyncMock(return_value=None)
            mock_repo.get_scraper_settings = AsyncMock(
                return_value={"refresh_interval_days": 9, "is_paused": False}
            )
            mock_repo.claim_next_pending_job = AsyncMock(return_value=None)

            # Step 1: Outage tick
            fail_mode = True
            t1 = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
            scheduler.tick(t1)  # must not crash!

            # Step 2: Database recovers
            fail_mode = False
            t2 = datetime(2026, 10, 18, 12, 1, tzinfo=timezone.utc)
            scheduler.tick(t2)
            ref_job = scheduler.get_job("refresh")
            self.assertIsNotNone(ref_job)
            idx = ref_job.command.index("--refresh-days")
            self.assertEqual(ref_job.command[idx + 1], "9", "Should have recovered and reloaded settings")

    def test_manual_job_real_subprocess_streaming_unicode_and_exit_code(self) -> None:
        """Verify manual job runner with real subprocess streams unicode lines and tracks non-zero exits."""
        scheduler = HarvesterScheduler(dry_run=False, enable_db=True)

        # Real script that prints unicode and exits with code 33
        script = (
            "import sys; "
            "print('Starting processing'); "
            "print('Unicode line: alpha & beta'); "
            "print('Complete'); "
            "sys.exit(33)"
        )
        cmd = [sys.executable, "-c", script]

        logs_written = []
        finish_records = []

        async def _noop(*args, **kwargs):
            return None

        with patch("skool.scheduler.repo") as mock_repo, patch("skool.scheduler.session_scope") as mock_scope:
            mock_scope.return_value.__aenter__ = _noop
            mock_scope.return_value.__aexit__ = _noop

            async def _mock_log(session, job_id, level, msg):
                logs_written.append((job_id, level, msg))

            async def _mock_finish(session, job_id, status, exit_code, error_msg):
                finish_records.append((job_id, status, exit_code, error_msg))

            mock_repo.insert_scraper_log = _mock_log
            mock_repo.finish_scraper_job = _mock_finish

            test_job = ScheduledJob(
                name="unicode_exit_test",
                cron="* * * * *",
                description="Test unicode streaming and exit code",
                command=cmd,
            )

            success = scheduler.run_job(test_job, db_job_id=888)
            self.assertFalse(success)
            self.assertEqual(test_job.last_status, "FAILED")

            # Verify log lines streamed
            msg_texts = [msg for (_, _, msg) in logs_written]
            self.assertTrue(any("Starting processing" in m for m in msg_texts))
            self.assertTrue(any("Unicode line" in m for m in msg_texts))
            self.assertTrue(any("Complete" in m for m in msg_texts))

            # Verify finish record
            self.assertEqual(len(finish_records), 1)
            job_id, status, exit_code, error_msg = finish_records[0]
            self.assertEqual(job_id, 888)
            self.assertEqual(status, "FAILED")
            self.assertEqual(exit_code, 33)
            self.assertIn("non-zero code 33", error_msg)


if __name__ == "__main__":
    unittest.main()

