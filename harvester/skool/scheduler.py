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
import asyncio
import concurrent.futures
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

try:
    from .db import repository as repo
    from .db.db import session_scope

    DB_AVAILABLE = True
except Exception:
    repo = None  # type: ignore
    session_scope = None  # type: ignore
    DB_AVAILABLE = False

log = logging.getLogger("skool.scheduler")


class _AsyncWorker:
    """Dedicated background thread hosting a single persistent event loop for async DB calls."""

    _instance: _AsyncWorker | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._target, daemon=True, name="scheduler-db-loop")
        self._thread.start()

    def _target(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    @classmethod
    def get(cls) -> _AsyncWorker:
        with cls._lock:
            if cls._instance is None or not cls._instance._thread.is_alive():
                cls._instance = _AsyncWorker()
            return cls._instance


def _run_coroutine(coro: Any) -> Any:
    """Safely execute an async coroutine from synchronous code on the persistent worker loop."""
    return _AsyncWorker.get().run(coro)


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
    """Manages scheduling and execution of recurring harvester pipelines and queued jobs."""

    def __init__(
        self,
        jobs: list[ScheduledJob] | None = None,
        check_interval: float = 30.0,
        dry_run: bool = False,
        enable_db: bool = True,
    ) -> None:
        self.jobs: list[ScheduledJob] = jobs or build_default_jobs()
        self.check_interval = check_interval
        self.dry_run = dry_run
        self.enable_db = enable_db and DB_AVAILABLE
        self.is_paused: bool = False
        self.settings: dict[str, Any] = {}
        self._stop_event = threading.Event()
        self._last_run_keys: dict[str, tuple[int, int, int, int, int]] = {}
        self._lock = threading.Lock()

    def _db_exec(self, coro: Any) -> Any:
        """Execute a DB coroutine safely, returning None on failure."""
        if not self.enable_db or not DB_AVAILABLE:
            return None
        try:
            return _run_coroutine(coro)
        except Exception as exc:  # noqa: BLE001
            log.debug("Database operation skipped/failed: %s", exc)
            return None

    def _db_write_log(self, job_id: int, level: str, message: str) -> None:
        if not self.enable_db:
            return

        async def _log() -> None:
            async with session_scope() as session:
                await repo.insert_scraper_log(session, job_id, level, message)

        self._db_exec(_log())

    def _db_finish_job(
        self,
        job_id: int,
        status: str,
        exit_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        if not self.enable_db:
            return

        async def _finish() -> None:
            async with session_scope() as session:
                await repo.finish_scraper_job(
                    session, job_id, status, exit_code, error_message
                )

        self._db_exec(_finish())

    def _is_job_cancelled(self, job_id: int) -> bool:
        if not self.enable_db:
            return False

        async def _check() -> bool:
            async with session_scope() as session:
                return await repo.is_scraper_job_cancelled(session, job_id)

        return bool(self._db_exec(_check()))

    def cleanup_dangling_jobs(self) -> int:
        if not self.enable_db:
            return 0

        async def _cleanup() -> int:
            async with session_scope() as session:
                return await repo.cleanup_dangling_running_jobs(session)

        cleaned = self._db_exec(_cleanup())
        if cleaned:
            log.info("Cleaned up %d dangling RUNNING jobs on daemon startup.", cleaned)
        return int(cleaned or 0)

    def update_heartbeat(self) -> bool:
        """Update daemon_heartbeat_at in skool.scraper_settings."""
        if not self.enable_db:
            return False

        async def _update() -> bool:
            async with session_scope() as session:
                await repo.update_daemon_heartbeat(session)
            return True

        res = self._db_exec(_update())
        return bool(res)

    def reload_settings(self) -> dict[str, Any] | None:
        """Read dynamic intervals, cron expressions, pause state, and discovery settings from skool.scraper_settings."""
        if not self.enable_db:
            return None

        async def _read() -> dict[str, Any] | None:
            async with session_scope() as session:
                return await repo.get_scraper_settings(session)

        settings = self._db_exec(_read())
        if not settings:
            return None

        self.settings = settings

        # Update pause state
        if "is_paused" in settings:
            prev_paused = self.is_paused
            self.is_paused = bool(settings["is_paused"])
            if prev_paused != self.is_paused:
                log.info("Scheduler pause state updated: is_paused=%s", self.is_paused)

        # Update refresh job command & cron
        refresh_job = self.get_job("refresh")
        if refresh_job:
            refresh_job.command = self.build_command_for_job_type("refresh")
            ref_cron = settings.get("refresh_cron")
            if ref_cron and refresh_job.cron != ref_cron:
                log.info("Updated refresh job cron from '%s' to '%s'", refresh_job.cron, ref_cron)
                refresh_job.cron = ref_cron

        # Update discovery job command & cron
        disc_job = self.get_job("discovery")
        if disc_job:
            disc_job.command = self.build_command_for_job_type("discovery")
            disc_cron = settings.get("discovery_cron")
            if disc_cron and disc_job.cron != disc_cron:
                log.info("Updated discovery job cron from '%s' to '%s'", disc_job.cron, disc_cron)
                disc_job.cron = disc_cron

        return settings

    def build_command_for_job_type(self, job_type: str) -> list[str]:
        """Construct execution command line for a given job type with active dynamic settings."""
        py = sys.executable
        mode = job_type.lower().strip()

        # Extract active settings with safe defaults
        ref_days = self.settings.get("refresh_interval_days", 3)
        page_conc = self.settings.get("page_concurrency", 4)
        detail_conc = self.settings.get("detail_concurrency", 8)
        delay_ms = self.settings.get("request_delay_ms", 300)
        delay_s = max(0.0, float(delay_ms) / 1000.0)
        include_bigrams = bool(self.settings.get("include_bigrams", False))
        exec_mode = str(self.settings.get("execution_mode", "parallel")).lower()
        if exec_mode == "sequential":
            page_conc = 1
            detail_conc = 1
        disc_mode = str(self.settings.get("discovery_mode", "all")).lower()
        if disc_mode not in ("all", "browse", "search", "quick"):
            disc_mode = "all"

        if mode == "refresh":
            return [
                py,
                "-m",
                "skool.main",
                "--mode",
                "refresh",
                "--refresh-days",
                str(ref_days),
                "--page-concurrency",
                str(page_conc),
                "--detail-concurrency",
                str(detail_conc),
                "--min-delay",
                f"{delay_s:.3f}",
                "--no-users",
            ]
        elif mode == "discovery":
            target_mode = "browse" if disc_mode == "quick" else disc_mode
            cmd = [
                py,
                "-m",
                "skool.main",
                "--mode",
                target_mode,
                "--page-concurrency",
                str(page_conc),
                "--detail-concurrency",
                str(detail_conc),
                "--min-delay",
                f"{delay_s:.3f}",
            ]
            if disc_mode == "quick":
                cmd.extend(["--max-pages", "5"])
            if include_bigrams:
                cmd.append("--include-bigrams")
            if target_mode != "all":
                cmd.append("--no-users")
            return cmd
        elif mode == "all":
            cmd = [
                py,
                "-m",
                "skool.main",
                "--mode",
                "all",
                "--page-concurrency",
                str(page_conc),
                "--detail-concurrency",
                str(detail_conc),
                "--min-delay",
                f"{delay_s:.3f}",
            ]
            if include_bigrams:
                cmd.append("--include-bigrams")
            return cmd
        elif mode in ("missing_owners", "missing-owners"):
            return [
                py,
                "-m",
                "skool.main",
                "--mode",
                "missing-owners",
                "--detail-concurrency",
                str(detail_conc),
                "--min-delay",
                f"{delay_s:.3f}",
            ]
        elif mode == "details":
            return [
                py,
                "-m",
                "skool.main",
                "--mode",
                "details",
                "--detail-concurrency",
                str(detail_conc),
                "--min-delay",
                f"{delay_s:.3f}",
            ]
        elif mode == "users":
            return [
                py,
                "-m",
                "skool.main",
                "--mode",
                "users",
                "--min-delay",
                f"{delay_s:.3f}",
            ]
        else:
            return [
                py,
                "-m",
                "skool.main",
                "--mode",
                mode.replace("_", "-"),
                "--page-concurrency",
                str(page_conc),
                "--detail-concurrency",
                str(detail_conc),
                "--min-delay",
                f"{delay_s:.3f}",
            ]

    def poll_and_execute_queued_jobs(self) -> int:
        """Poll queued manual jobs with status 'PENDING' from skool.scraper_jobs, claim and execute."""
        if not self.enable_db:
            return 0

        async def _claim() -> dict[str, Any] | None:
            async with session_scope() as session:
                return await repo.claim_next_pending_job(session)

        executed_count = 0
        while not self._stop_event.is_set():
            claimed = self._db_exec(_claim())
            if not claimed:
                break

            job_id = claimed["id"]
            job_type = claimed["job_type"]
            trigger_type = claimed.get("trigger_type", "manual")
            log.info("Claimed pending job #%s [%s] (trigger: %s)", job_id, job_type, trigger_type)

            command = self.build_command_for_job_type(job_type)
            queued_job = ScheduledJob(
                name=f"{job_type}_job_{job_id}",
                cron="* * * * *",
                description=f"Manual execution of {job_type} (job #{job_id})",
                command=command,
            )

            self.run_job(queued_job, db_job_id=job_id)
            executed_count += 1
            if self.dry_run:
                break

        return executed_count

    def get_job(self, name: str) -> ScheduledJob | None:
        for j in self.jobs:
            if j.name == name:
                return j
        return None

    def status(self) -> list[dict[str, Any]]:
        return [job.as_dict() for job in self.jobs]

    def stop(self) -> None:
        self._stop_event.set()

    def run_job(self, job: ScheduledJob, db_job_id: int | None = None) -> bool:
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
            if db_job_id is not None:
                self._db_write_log(
                    db_job_id, "INFO", f"[DRY RUN] Job [{job.name}] simulated success in {duration:.4f}s"
                )
                self._db_finish_job(db_job_id, status="SUCCESS", exit_code=0, error_message=None)
            return True

        if db_job_id is not None and self._is_job_cancelled(db_job_id):
            log.warning("Job #%s was cancelled before execution started.", db_job_id)
            job.last_status = "CANCELLED"
            job.last_error = "Cancelled by administrator"
            return False

        try:
            process = subprocess.Popen(
                job.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            cancelled = False
            try:
                if process.stdout:
                    for line in process.stdout:
                        line_clean = line.rstrip() if isinstance(line, str) else str(line).rstrip()
                        if line_clean:
                            log.info("[%s] %s", job.name, line_clean)
                            if db_job_id is not None:
                                self._db_write_log(db_job_id, "INFO", line_clean)
                        if db_job_id is not None and self._is_job_cancelled(db_job_id):
                            log.warning(
                                "Job #%s was cancelled via admin! Terminating process...",
                                db_job_id,
                            )
                            cancelled = True
                            if hasattr(process, "terminate"):
                                process.terminate()
                            if hasattr(process, "wait"):
                                try:
                                    process.wait(timeout=5)
                                except Exception:
                                    if hasattr(process, "kill"):
                                        process.kill()
                            break
                if hasattr(process, "wait"):
                    process.wait()
            finally:
                if process.stdout and hasattr(process.stdout, "close"):
                    try:
                        process.stdout.close()
                    except Exception:
                        pass

            duration = time.monotonic() - start_time
            job.last_duration_s = duration

            if cancelled:
                job.last_status = "CANCELLED"
                job.last_error = "Cancelled by administrator"
                if db_job_id is not None:
                    self._db_finish_job(
                        db_job_id,
                        status="CANCELLED",
                        exit_code=-15,
                        error_message="Cancelled by administrator",
                    )
                return False

            if process.returncode == 0:
                job.last_status = "SUCCESS"
                job.success_count += 1
                log.info("Job [%s] finished successfully in %.2fs (exit code 0)", job.name, duration)
                if db_job_id is not None:
                    self._db_finish_job(db_job_id, status="SUCCESS", exit_code=0, error_message=None)
                return True
            else:
                job.last_status = "FAILED"
                job.failure_count += 1
                job.last_error = f"Process exited with non-zero code {process.returncode}"
                log.error("Job [%s] failed with exit code %s in %.2fs", job.name, process.returncode, duration)
                if db_job_id is not None:
                    self._db_finish_job(
                        db_job_id,
                        status="FAILED",
                        exit_code=process.returncode,
                        error_message=job.last_error,
                    )
                return False

        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start_time
            job.last_duration_s = duration
            job.last_status = "FAILED"
            job.failure_count += 1
            job.last_error = str(exc)
            log.exception("Job [%s] crashed with exception: %s", job.name, exc)
            if db_job_id is not None:
                self._db_write_log(db_job_id, "ERROR", f"Crashed: {exc}")
                self._db_finish_job(db_job_id, status="FAILED", exit_code=1, error_message=str(exc))
            return False

    def tick(self, now: datetime | None = None) -> list[str]:
        """Evaluate all jobs against the given or current timestamp.
        Returns names of jobs triggered during this tick.
        """
        now = now or datetime.now(timezone.utc)
        minute_key = (now.year, now.month, now.day, now.hour, now.minute)
        triggered: list[str] = []

        # 1. Update daemon heartbeat
        self.update_heartbeat()

        # 2. Reload dynamic intervals and pause flag
        self.reload_settings()

        # 3. Poll and execute queued manual jobs
        self.poll_and_execute_queued_jobs()

        # 4. Scheduled cron jobs (if not paused)
        if self.is_paused:
            log.info("Scheduler is paused (is_paused=True); skipping scheduled cron triggers")
            return triggered

        for job in self.jobs:
            if cron_matches(job.cron, now):
                if self._last_run_keys.get(job.name) != minute_key:
                    self._last_run_keys[job.name] = minute_key
                    triggered.append(job.name)
                    log.info("Job [%s] triggered by cron match '%s' at %s", job.name, job.cron, now.isoformat())

                    db_job_id = None
                    if self.enable_db:
                        async def _create_scheduled(jname: str = job.name) -> int:
                            async with session_scope() as session:
                                return await repo.create_scraper_job(
                                    session,
                                    job_type=jname,
                                    trigger_type="scheduled",
                                    status="RUNNING",
                                )
                        db_job_id = self._db_exec(_create_scheduled())

                    self.run_job(job, db_job_id=db_job_id)
        return triggered

    def run_daemon(self, single_tick: bool = False) -> None:
        log.info(
            "Starting Harvester Scheduler Daemon (check interval: %.1fs, dry_run: %s, enable_db: %s)",
            self.check_interval,
            self.dry_run,
            self.enable_db,
        )
        self.cleanup_dangling_jobs()
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
        choices=("refresh", "discovery", "all", "missing-owners", "missing_owners"),
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
        "--no-db",
        action="store_true",
        default=False,
        help="Disable database integration (heartbeat, job queue, settings reload)",
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
        enable_db=not args.no_db,
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
        elif args.run_now in ("missing-owners", "missing_owners"):
            cmd = scheduler.build_command_for_job_type("missing-owners")
            job = ScheduledJob(
                name="missing-owners",
                cron="* * * * *",
                description="Missing owners completion (2-tier recovery)",
                command=cmd,
            )
            ok = scheduler.run_job(job)
            return 0 if ok else 1
        else:
            job = scheduler.get_job(args.run_now)
            if not job:
                cmd = scheduler.build_command_for_job_type(args.run_now)
                job = ScheduledJob(
                    name=args.run_now,
                    cron="* * * * *",
                    description=f"Execution of {args.run_now}",
                    command=cmd,
                )
            ok = scheduler.run_job(job)
            return 0 if ok else 1

    # Default to daemon mode
    scheduler.run_daemon(single_tick=args.single_tick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
