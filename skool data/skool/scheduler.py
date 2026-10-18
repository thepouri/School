"""Automated scheduler runner for Skool harvesting pipeline.

Executes recurring jobs:
  1. 3-day metrics refresh:
     `python -m skool.main --mode refresh --refresh-days 3 --no-users`
     Schedule: `0 2 */3 * *` (Every 3 days at 02:00 UTC)
  2. Weekly deep discovery:
     `python -m skool.main --mode all --no-users`
     Schedule: `0 3 * * 0` (Every Sunday at 03:00 UTC)

CLI Usage:
  # Run continuous daemon
  python -m skool.scheduler --daemon

  # Execute 3-day refresh immediately
  python -m skool.scheduler --run-now refresh

  # Execute weekly discovery immediately
  python -m skool.scheduler --run-now discovery
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("skool.scheduler")


def configure_logging(level: str = "INFO") -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def parse_cron_field(
    field_str: str, min_val: int, max_val: int, is_dow: bool = False
) -> set[int]:
    """Parse a single cron field into matching integer values."""
    field_str = field_str.strip()
    if field_str == "*":
        return set(range(min_val, max_val + 1))

    matches: set[int] = set()
    for part in field_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            matches.update(range(min_val, max_val + 1, step))
        elif "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
            if "-" in range_part:
                start, end = map(int, range_part.split("-", 1))
            else:
                start, end = int(range_part), max_val
            matches.update(range(start, end + 1, step))
        elif "-" in part:
            start, end = map(int, part.split("-", 1))
            matches.update(range(start, end + 1))
        else:
            val = int(part)
            if is_dow and val == 7:
                val = 0
            matches.add(val)

    if is_dow and 7 in matches:
        matches.remove(7)
        matches.add(0)
    return matches


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime (UTC) matches a standard 5-field cron expression."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (must have 5 fields): {cron_expr}")
    min_expr, hr_expr, dom_expr, mon_expr, dow_expr = parts

    # Python weekday(): Monday=0 ... Sunday=6
    # Cron DOW: Sunday=0, Monday=1 ... Saturday=6
    cron_dow = (dt.weekday() + 1) % 7

    if dt.minute not in parse_cron_field(min_expr, 0, 59):
        return False
    if dt.hour not in parse_cron_field(hr_expr, 0, 23):
        return False
    if dt.day not in parse_cron_field(dom_expr, 1, 31):
        return False
    if dt.month not in parse_cron_field(mon_expr, 1, 12):
        return False
    if cron_dow not in parse_cron_field(dow_expr, 0, 6, is_dow=True):
        return False
    return True


@dataclass
class ScheduledJob:
    name: str
    cron: str
    description: str
    command: list[str]
    last_run_time: datetime | None = None
    last_status: str | None = None  # "SUCCESS", "FAILED", "RUNNING", "IDLE"
    last_duration_s: float | None = None
    last_error: str | None = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cron": self.cron,
            "description": self.description,
            "command": self.command,
            "last_run": self.last_run_time.isoformat() if self.last_run_time else None,
            "last_status": self.last_status,
            "last_duration_s": self.last_duration_s,
            "last_error": self.last_error,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


def build_default_jobs(
    refresh_days: float = 3.0, python_bin: str | None = None
) -> list[ScheduledJob]:
    py = python_bin or sys.executable
    refresh_days_str = str(int(refresh_days) if refresh_days.is_integer() else refresh_days)
    return [
        ScheduledJob(
            name="refresh",
            cron="0 2 */3 * *",
            description="3-day group metrics refresh (stale groups re-fetch & time-series snapshots)",
            command=[
                py,
                "-m",
                "skool.main",
                "--mode",
                "refresh",
                "--refresh-days",
                refresh_days_str,
                "--no-users",
            ],
        ),
        ScheduledJob(
            name="discovery",
            cron="0 3 * * 0",
            description="Weekly deep group discovery (categories, languages, seeds; zero-redundancy skipping)",
            command=[
                py,
                "-m",
                "skool.main",
                "--mode",
                "all",
                "--no-users",
            ],
        ),
    ]


class HarvesterScheduler:
    """Manages scheduling and execution of recurring harvester pipelines."""

    def __init__(
        self,
        jobs: list[ScheduledJob] | None = None,
        check_interval: float = 30.0,
        dry_run: bool = False,
    ) -> None:
        self.jobs: list[ScheduledJob] = jobs or build_default_jobs()
        self.check_interval = check_interval
        self.dry_run = dry_run
        self._stop_event = threading.Event()
        self._last_run_keys: dict[str, tuple[int, int, int, int, int]] = {}

    def get_job(self, name: str) -> ScheduledJob | None:
        for j in self.jobs:
            if j.name == name:
                return j
        return None

    def status(self) -> list[dict[str, Any]]:
        return [job.as_dict() for job in self.jobs]

    def stop(self) -> None:
        self._stop_event.set()

    def run_job(self, job: ScheduledJob) -> bool:
        job.run_count += 1
        job.last_run_time = datetime.now(timezone.utc)
        job.last_status = "RUNNING"
        job.last_error = None
        start_time = time.monotonic()

        cmd_display = " ".join(job.command)
        log.info("Starting job [%s]: %s (Command: %s)", job.name, job.description, cmd_display)

        if self.dry_run:
            duration = time.monotonic() - start_time
            job.last_duration_s = duration
            job.last_status = "SUCCESS"
            job.success_count += 1
            log.info("[DRY RUN] Job [%s] simulated success in %.4fs", job.name, duration)
            return True

        try:
            process = subprocess.Popen(
                job.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            if process.stdout:
                for line in process.stdout:
                    line_clean = line.rstrip()
                    if line_clean:
                        log.info("[%s] %s", job.name, line_clean)
            process.wait()
            duration = time.monotonic() - start_time
            job.last_duration_s = duration

            if process.returncode == 0:
                job.last_status = "SUCCESS"
                job.success_count += 1
                log.info("Job [%s] finished successfully in %.2fs (exit code 0)", job.name, duration)
                return True
            else:
                job.last_status = "FAILED"
                job.failure_count += 1
                job.last_error = f"Process exited with non-zero code {process.returncode}"
                log.error("Job [%s] failed with exit code %s in %.2fs", job.name, process.returncode, duration)
                return False

        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start_time
            job.last_duration_s = duration
            job.last_status = "FAILED"
            job.failure_count += 1
            job.last_error = str(exc)
            log.exception("Job [%s] crashed with exception: %s", job.name, exc)
            return False

    def tick(self, now: datetime | None = None) -> list[str]:
        """Evaluate all jobs against the given or current timestamp.
        Returns names of jobs triggered during this tick.
        """
        now = now or datetime.now(timezone.utc)
        minute_key = (now.year, now.month, now.day, now.hour, now.minute)
        triggered: list[str] = []

        for job in self.jobs:
            if cron_matches(job.cron, now):
                if self._last_run_keys.get(job.name) != minute_key:
                    self._last_run_keys[job.name] = minute_key
                    triggered.append(job.name)
                    log.info("Job [%s] triggered by cron match '%s' at %s", job.name, job.cron, now.isoformat())
                    self.run_job(job)
        return triggered

    def run_daemon(self, single_tick: bool = False) -> None:
        log.info(
            "Starting Harvester Scheduler Daemon (check interval: %.1fs, dry_run: %s)",
            self.check_interval,
            self.dry_run,
        )
        for job in self.jobs:
            log.info("  * Job [%s]: '%s' -> %s", job.name, job.cron, job.description)

        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            self.tick(now)
            if single_tick:
                break
            self._stop_event.wait(timeout=self.check_interval)

        log.info("Harvester Scheduler Daemon stopped.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skool Data Harvester Recurring Job Scheduler")
    parser.add_argument(
        "--daemon",
        action="store_true",
        default=False,
        help="Run continuous scheduler loop (default when --run-now is not specified)",
    )
    parser.add_argument(
        "--run-now",
        choices=("refresh", "discovery", "all"),
        default=None,
        help="Execute specified job immediately and exit",
    )
    parser.add_argument(
        "--refresh-days",
        type=float,
        default=3.0,
        help="Age threshold in days for 3-day refresh job (default: 3)",
    )
    parser.add_argument(
        "--check-interval",
        type=float,
        default=30.0,
        help="Seconds between schedule evaluations in daemon mode (default: 30)",
    )
    parser.add_argument(
        "--single-tick",
        action="store_true",
        help="Evaluate schedule once and exit (useful for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without launching actual worker processes",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    scheduler = HarvesterScheduler(
        jobs=build_default_jobs(refresh_days=args.refresh_days),
        check_interval=args.check_interval,
        dry_run=args.dry_run,
    )

    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("Received termination signal %s; stopping scheduler daemon...", signum)
        scheduler.stop()

    try:
        signal.signal(signal.SIGINT, _handle_signal)
    except Exception:
        pass
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _handle_signal)
        except Exception:
            pass

    if args.run_now:
        if args.run_now == "all":
            job1 = scheduler.get_job("refresh")
            job2 = scheduler.get_job("discovery")
            ok1 = scheduler.run_job(job1) if job1 else False
            ok2 = scheduler.run_job(job2) if job2 else False
            return 0 if (ok1 and ok2) else 1
        else:
            job = scheduler.get_job(args.run_now)
            if not job:
                log.error("Unknown job name: %s", args.run_now)
                return 1
            ok = scheduler.run_job(job)
            return 0 if ok else 1

    # Default to daemon mode
    scheduler.run_daemon(single_tick=args.single_tick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
