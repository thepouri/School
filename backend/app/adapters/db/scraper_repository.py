"""PostgreSQL ScraperRepository — persistence adapter for scraper admin management."""
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.adapters.db.pool import record_to_dict


class PgScraperRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_status(self) -> dict:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            # 1. Scraper settings & heartbeat
            settings_row = await conn.fetchrow(
                """
                SELECT refresh_interval_days, discovery_interval_days,
                       refresh_cron, discovery_cron, is_paused,
                       daemon_heartbeat_at
                FROM skool.scraper_settings
                WHERE id = 1
                """
            )
            if not settings_row:
                settings_dict = {
                    "refresh_interval_days": 3,
                    "discovery_interval_days": 7,
                    "refresh_cron": "0 2 */3 * *",
                    "discovery_cron": "0 3 * * 0",
                    "is_paused": False,
                    "daemon_heartbeat_at": None,
                }
            else:
                settings_dict = dict(settings_row)

            heartbeat = settings_dict.get("daemon_heartbeat_at")
            if heartbeat is not None:
                if heartbeat.tzinfo is None:
                    heartbeat = heartbeat.replace(tzinfo=timezone.utc)
                delta_s = (now - heartbeat).total_seconds()
                daemon_status = "RUNNING" if delta_s <= 45.0 else "STOPPED"
                last_hb_iso = heartbeat.isoformat()
            else:
                daemon_status = "STOPPED"
                last_hb_iso = None

            # 2. Last runs for schedules
            last_runs_rows = await conn.fetch(
                """
                SELECT job_type, MAX(started_at) AS last_run
                FROM skool.scraper_jobs
                WHERE job_type IN ('refresh', 'discovery')
                  AND status IN ('SUCCESS', 'RUNNING')
                GROUP BY job_type
                """
            )
            last_runs = {r["job_type"]: r["last_run"] for r in last_runs_rows}

            # Refresh schedule
            ref_int = settings_dict.get("refresh_interval_days", 3)
            ref_last = last_runs.get("refresh")
            if ref_last:
                if ref_last.tzinfo is None:
                    ref_last = ref_last.replace(tzinfo=timezone.utc)
                ref_last_iso = ref_last.isoformat()
                ref_next_iso = (ref_last + timedelta(days=ref_int)).isoformat()
            else:
                ref_last_iso = None
                ref_next_iso = (now + timedelta(days=ref_int)).isoformat()

            # Discovery schedule
            disc_int = settings_dict.get("discovery_interval_days", 7)
            disc_last = last_runs.get("discovery")
            if disc_last:
                if disc_last.tzinfo is None:
                    disc_last = disc_last.replace(tzinfo=timezone.utc)
                disc_last_iso = disc_last.isoformat()
                disc_next_iso = (disc_last + timedelta(days=disc_int)).isoformat()
            else:
                disc_last_iso = None
                disc_next_iso = (now + timedelta(days=disc_int)).isoformat()

            # 3. Stats from skool.groups (if table exists)
            stats = {"total_groups": 0, "pending_details": 0, "pending_owners": 0}
            tbl_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'skool' AND table_name = 'groups'
                )
                """
            )
            if tbl_exists:
                stats_row = await conn.fetchrow(
                    """
                    SELECT 
                        count(*)::int AS total_groups,
                        count(*) FILTER (WHERE detail_fetched IS FALSE)::int AS pending_details,
                        count(*) FILTER (WHERE owner_name IS NULL OR owner_id IS NULL)::int AS pending_owners
                    FROM skool.groups
                    """
                )
                if stats_row:
                    stats = {
                        "total_groups": stats_row["total_groups"] or 0,
                        "pending_details": stats_row["pending_details"] or 0,
                        "pending_owners": stats_row["pending_owners"] or 0,
                    }

            # 4. Active job
            active_row = await conn.fetchrow(
                """
                SELECT id, job_type, status, started_at
                FROM skool.scraper_jobs
                WHERE status = 'RUNNING'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            active_job = None
            if active_row:
                started_at = active_row["started_at"]
                if started_at and started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                active_job = {
                    "id": int(active_row["id"]) if active_row["id"] is not None else None,
                    "job_type": active_row["job_type"],
                    "status": active_row["status"],
                    "started_at": started_at.isoformat() if started_at else None,
                }

        return {
            "daemon": {
                "status": daemon_status,
                "last_heartbeat": last_hb_iso,
                "is_paused": settings_dict.get("is_paused", False),
            },
            "schedules": {
                "refresh": {
                    "interval_days": ref_int,
                    "cron": settings_dict.get("refresh_cron", "0 2 */3 * *"),
                    "last_run": ref_last_iso,
                    "next_run": ref_next_iso,
                },
                "discovery": {
                    "interval_days": disc_int,
                    "cron": settings_dict.get("discovery_cron", "0 3 * * 0"),
                    "last_run": disc_last_iso,
                    "next_run": disc_next_iso,
                },
            },
            "stats": stats,
            "active_job": active_job,
        }

    async def get_settings(self) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT refresh_interval_days, discovery_interval_days,
                       refresh_cron, discovery_cron, is_paused
                FROM skool.scraper_settings
                WHERE id = 1
                """
            )
            if not row:
                return {
                    "refresh_interval_days": 3,
                    "discovery_interval_days": 7,
                    "refresh_cron": "0 2 */3 * *",
                    "discovery_cron": "0 3 * * 0",
                    "is_paused": False,
                }
            return {
                "refresh_interval_days": row["refresh_interval_days"],
                "discovery_interval_days": row["discovery_interval_days"],
                "refresh_cron": row["refresh_cron"],
                "discovery_cron": row["discovery_cron"],
                "is_paused": row["is_paused"],
            }

    async def update_settings(self, settings_data: dict) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE skool.scraper_settings
                SET refresh_interval_days = COALESCE($1, refresh_interval_days),
                    discovery_interval_days = COALESCE($2, discovery_interval_days),
                    is_paused = COALESCE($3, is_paused),
                    refresh_cron = COALESCE($4, refresh_cron),
                    discovery_cron = COALESCE($5, discovery_cron),
                    updated_at = NOW()
                WHERE id = 1
                RETURNING refresh_interval_days, discovery_interval_days,
                          refresh_cron, discovery_cron, is_paused
                """,
                settings_data.get("refresh_interval_days"),
                settings_data.get("discovery_interval_days"),
                settings_data.get("is_paused"),
                settings_data.get("refresh_cron"),
                settings_data.get("discovery_cron"),
            )
            if not row:
                return await self.get_settings()
            return {
                "refresh_interval_days": row["refresh_interval_days"],
                "discovery_interval_days": row["discovery_interval_days"],
                "refresh_cron": row["refresh_cron"],
                "discovery_cron": row["discovery_cron"],
                "is_paused": row["is_paused"],
            }

    async def enqueue_job(self, job_type: str, trigger_type: str = "manual") -> int:
        async with self._pool.acquire() as conn:
            job_id = await conn.fetchval(
                """
                INSERT INTO skool.scraper_jobs (job_type, trigger_type, status, created_at)
                VALUES ($1, $2, 'PENDING', NOW())
                RETURNING id
                """,
                job_type,
                trigger_type,
            )
            return int(job_id)

    async def get_logs(self, limit: int = 50, job_id: int | None = None) -> list[dict]:
        async with self._pool.acquire() as conn:
            jobs_rows = await conn.fetch(
                """
                SELECT id, job_type, trigger_type, status, started_at,
                       finished_at, exit_code, error_message, created_at
                FROM skool.scraper_jobs
                WHERE ($1::bigint IS NULL OR id = $1)
                ORDER BY id DESC
                LIMIT $2
                """,
                job_id,
                limit,
            )
            if not jobs_rows:
                return []

            job_ids = [int(r["id"]) for r in jobs_rows]
            logs_rows = await conn.fetch(
                """
                SELECT id, job_id, level, message, created_at
                FROM skool.scraper_logs
                WHERE job_id = ANY($1::bigint[])
                ORDER BY id ASC
                """,
                job_ids,
            )

            job_lines: dict[int, list[dict]] = {jid: [] for jid in job_ids}
            for l in logs_rows:
                cat_at = l["created_at"]
                if cat_at and cat_at.tzinfo is None:
                    cat_at = cat_at.replace(tzinfo=timezone.utc)
                lid = int(l["id"]) if l["id"] is not None else None
                ljid = int(l["job_id"]) if l["job_id"] is not None else None
                line_entry = {
                    "id": lid,
                    "job_id": ljid,
                    "level": l["level"],
                    "message": l["message"],
                    "created_at": cat_at.isoformat() if cat_at else None,
                }
                if ljid in job_lines:
                    job_lines[ljid].append(line_entry)

            items = []
            for j in jobs_rows:
                jid = int(j["id"]) if j["id"] is not None else None
                s_at = j["started_at"]
                if s_at and s_at.tzinfo is None:
                    s_at = s_at.replace(tzinfo=timezone.utc)
                f_at = j["finished_at"]
                if f_at and f_at.tzinfo is None:
                    f_at = f_at.replace(tzinfo=timezone.utc)
                c_at = j["created_at"]
                if c_at and c_at.tzinfo is None:
                    c_at = c_at.replace(tzinfo=timezone.utc)

                items.append({
                    "id": jid,
                    "job_id": jid,
                    "job_type": j["job_type"],
                    "trigger_type": j["trigger_type"],
                    "status": j["status"],
                    "started_at": s_at.isoformat() if s_at else None,
                    "finished_at": f_at.isoformat() if f_at else None,
                    "created_at": c_at.isoformat() if c_at else None,
                    "exit_code": j["exit_code"],
                    "error_message": j["error_message"],
                    "lines": job_lines.get(jid, []),
                })

            return items

    async def get_active_job(self) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, job_type, status, started_at
                FROM skool.scraper_jobs
                WHERE status = 'RUNNING'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            if not row:
                return None
            s_at = row["started_at"]
            if s_at and s_at.tzinfo is None:
                s_at = s_at.replace(tzinfo=timezone.utc)
            return {
                "id": int(row["id"]) if row["id"] is not None else None,
                "job_type": row["job_type"],
                "status": row["status"],
                "started_at": s_at.isoformat() if s_at else None,
            }

    async def update_heartbeat(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE skool.scraper_settings
                SET daemon_heartbeat_at = NOW()
                WHERE id = 1
                """
            )
