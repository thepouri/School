"""Adversarial stress-test suite for the harvester scheduler and cron matching.

Empirically tests edge cases, boundaries, error isolation, and CLI behaviors.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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

        # Non-dry-run where child succeeds -> main must return 0
        code = scheduler_main(["--run-now", "discovery"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
