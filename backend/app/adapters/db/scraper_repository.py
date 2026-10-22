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
                daemon_status = "RUNNING" if delta_s <= 120.0 else "STOPPED"
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
                       refresh_cron, discovery_cron, is_paused,
                       discovery_mode, page_concurrency, detail_concurrency,
                       request_delay_ms, include_bigrams
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
                    "discovery_mode": "all",
                    "page_concurrency": 4,
                    "detail_concurrency": 8,
                    "request_delay_ms": 300,
                    "include_bigrams": False,
                }
            return {
                "refresh_interval_days": row["refresh_interval_days"],
                "discovery_interval_days": row["discovery_interval_days"],
                "refresh_cron": row["refresh_cron"],
                "discovery_cron": row["discovery_cron"],
                "is_paused": row["is_paused"],
                "discovery_mode": row["discovery_mode"] or "all",
                "page_concurrency": row["page_concurrency"] if row["page_concurrency"] is not None else 4,
                "detail_concurrency": row["detail_concurrency"] if row["detail_concurrency"] is not None else 8,
                "request_delay_ms": row["request_delay_ms"] if row["request_delay_ms"] is not None else 300,
                "include_bigrams": bool(row["include_bigrams"]),
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
                    discovery_mode = COALESCE($6, discovery_mode),
                    page_concurrency = COALESCE($7, page_concurrency),
                    detail_concurrency = COALESCE($8, detail_concurrency),
                    request_delay_ms = COALESCE($9, request_delay_ms),
                    include_bigrams = COALESCE($10, include_bigrams),
                    updated_at = NOW()
                WHERE id = 1
                RETURNING refresh_interval_days, discovery_interval_days,
                          refresh_cron, discovery_cron, is_paused,
                          discovery_mode, page_concurrency, detail_concurrency,
                          request_delay_ms, include_bigrams
                """,
                settings_data.get("refresh_interval_days"),
                settings_data.get("discovery_interval_days"),
                settings_data.get("is_paused"),
                settings_data.get("refresh_cron"),
                settings_data.get("discovery_cron"),
                settings_data.get("discovery_mode"),
                settings_data.get("page_concurrency"),
                settings_data.get("detail_concurrency"),
                settings_data.get("request_delay_ms"),
                settings_data.get("include_bigrams"),
            )
            if not row:
                return await self.get_settings()
            return {
                "refresh_interval_days": row["refresh_interval_days"],
                "discovery_interval_days": row["discovery_interval_days"],
                "refresh_cron": row["refresh_cron"],
                "discovery_cron": row["discovery_cron"],
                "is_paused": row["is_paused"],
                "discovery_mode": row["discovery_mode"] or "all",
                "page_concurrency": row["page_concurrency"] if row["page_concurrency"] is not None else 4,
                "detail_concurrency": row["detail_concurrency"] if row["detail_concurrency"] is not None else 8,
                "request_delay_ms": row["request_delay_ms"] if row["request_delay_ms"] is not None else 300,
                "include_bigrams": bool(row["include_bigrams"]),
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
                FROM (
                    SELECT id, job_id, level, message, created_at
                    FROM skool.scraper_logs
                    WHERE job_id = ANY($1::bigint[])
                    ORDER BY id DESC
                    LIMIT 2000
                ) sub
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

    async def cancel_job(self, job_id: int) -> bool:
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE skool.scraper_jobs
                SET status = 'CANCELLED',
                    finished_at = NOW(),
                    error_message = 'Cancelled by administrator'
                WHERE id = $1 AND status IN ('PENDING', 'RUNNING')
                """,
                job_id,
            )
            if "UPDATE 1" in res:
                await conn.execute(
                    """
                    INSERT INTO skool.scraper_logs (job_id, level, message, created_at)
                    VALUES ($1, 'WARNING', 'Job was cancelled by administrator', NOW())
                    """,
                    job_id,
                )
                return True
            return False

    async def export_data(self, include_metrics: bool = True) -> dict:
        async with self._pool.acquire() as conn:
            groups_rows = await conn.fetch("SELECT * FROM skool.groups ORDER BY id ASC")
            users_rows = await conn.fetch("SELECT * FROM skool.users ORDER BY id ASC")
            ug_rows = await conn.fetch("SELECT * FROM skool.user_groups ORDER BY user_id, group_id ASC")

            groups = [record_to_dict(r) for r in groups_rows]
            users = [record_to_dict(r) for r in users_rows]
            user_groups = [record_to_dict(r) for r in ug_rows]

            group_metrics = []
            user_metrics = []
            if include_metrics:
                gm_rows = await conn.fetch("SELECT * FROM skool.group_metrics ORDER BY group_id, captured_at ASC")
                um_rows = await conn.fetch("SELECT * FROM skool.user_metrics ORDER BY user_id, captured_at ASC")
                group_metrics = [record_to_dict(r) for r in gm_rows]
                user_metrics = [record_to_dict(r) for r in um_rows]

            return {
                "version": "1.0",
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "counts": {
                    "groups": len(groups),
                    "users": len(users),
                    "user_groups": len(user_groups),
                    "group_metrics": len(group_metrics),
                    "user_metrics": len(user_metrics),
                },
                "data": {
                    "groups": groups,
                    "users": users,
                    "user_groups": user_groups,
                    "group_metrics": group_metrics,
                    "user_metrics": user_metrics,
                },
            }

    async def import_data(self, payload: dict) -> dict:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        raw_groups = data.get("groups") or []
        raw_users = data.get("users") or []
        raw_user_groups = data.get("user_groups") or []
        raw_group_metrics = data.get("group_metrics") or []
        raw_user_metrics = data.get("user_metrics") or []

        imported_counts = {
            "groups": 0,
            "users": 0,
            "user_groups": 0,
            "group_metrics": 0,
            "user_metrics": 0,
        }

        def _to_dt(val: Any) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    d = datetime.fromisoformat(val)
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    return d
                except Exception:
                    return None
            return None

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. Users
                sorted_users = [u for u in raw_users if isinstance(u, dict) and u.get("id") and u.get("name")]
                sorted_users.sort(key=lambda u: str(u["id"]))
                if sorted_users:
                    user_records = [
                        (
                            str(u["id"]),
                            str(u["name"]),
                            u.get("full_name") or u.get("display_name") or str(u["name"]),
                            u.get("first_name"),
                            u.get("last_name"),
                            u.get("bio"),
                            u.get("location"),
                            u.get("location_source"),
                            u.get("timezone"),
                            u.get("avatar_url") or u.get("picture_url"),
                            u.get("avatar_bubble_url"),
                            u.get("link_facebook"),
                            u.get("link_instagram"),
                            u.get("link_linkedin"),
                            u.get("link_twitter"),
                            u.get("link_website"),
                            u.get("link_youtube"),
                            int(u["total_followers"]) if u.get("total_followers") is not None else None,
                            int(u["total_following"]) if u.get("total_following") is not None else None,
                            int(u["total_contributions"]) if u.get("total_contributions") is not None else None,
                            bool(u.get("groups_fetched", False)),
                            _to_dt(u.get("created_at")),
                            _to_dt(u.get("updated_at")),
                        )
                        for u in sorted_users
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO skool.users (
                            id, name, full_name, first_name, last_name, bio, location, location_source, timezone,
                            avatar_url, avatar_bubble_url, link_facebook, link_instagram, link_linkedin,
                            link_twitter, link_website, link_youtube, total_followers,
                            total_following, total_contributions, groups_fetched, created_at, updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                            $16, $17, $18, $19, $20, $21, COALESCE($22, NOW()), COALESCE($23, NOW())
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            name = COALESCE(EXCLUDED.name, skool.users.name),
                            full_name = COALESCE(EXCLUDED.full_name, skool.users.full_name),
                            first_name = COALESCE(EXCLUDED.first_name, skool.users.first_name),
                            last_name = COALESCE(EXCLUDED.last_name, skool.users.last_name),
                            bio = COALESCE(EXCLUDED.bio, skool.users.bio),
                            location = COALESCE(EXCLUDED.location, skool.users.location),
                            location_source = COALESCE(EXCLUDED.location_source, skool.users.location_source),
                            timezone = COALESCE(EXCLUDED.timezone, skool.users.timezone),
                            avatar_url = COALESCE(EXCLUDED.avatar_url, skool.users.avatar_url),
                            avatar_bubble_url = COALESCE(EXCLUDED.avatar_bubble_url, skool.users.avatar_bubble_url),
                            link_facebook = COALESCE(EXCLUDED.link_facebook, skool.users.link_facebook),
                            link_instagram = COALESCE(EXCLUDED.link_instagram, skool.users.link_instagram),
                            link_linkedin = COALESCE(EXCLUDED.link_linkedin, skool.users.link_linkedin),
                            link_twitter = COALESCE(EXCLUDED.link_twitter, skool.users.link_twitter),
                            link_website = COALESCE(EXCLUDED.link_website, skool.users.link_website),
                            link_youtube = COALESCE(EXCLUDED.link_youtube, skool.users.link_youtube),
                            total_followers = COALESCE(EXCLUDED.total_followers, skool.users.total_followers),
                            total_following = COALESCE(EXCLUDED.total_following, skool.users.total_following),
                            total_contributions = COALESCE(EXCLUDED.total_contributions, skool.users.total_contributions),
                            groups_fetched = COALESCE(EXCLUDED.groups_fetched, skool.users.groups_fetched),
                            updated_at = NOW()
                        """,
                        user_records,
                    )
                    imported_counts["users"] = len(user_records)

                # 2. Groups
                sorted_groups = [g for g in raw_groups if isinstance(g, dict) and g.get("id") and g.get("name")]
                sorted_groups.sort(key=lambda g: str(g["id"]))
                if sorted_groups:
                    group_records = [
                        (
                            str(g["id"]),
                            str(g["name"]),
                            g.get("display_name"),
                            g.get("description"),
                            g.get("lp_description"),
                            g.get("color"),
                            g.get("initials"),
                            g.get("cover_url"),
                            g.get("logo_url"),
                            g.get("logo_big_url"),
                            g.get("favicon_url"),
                            int(g["price_amount_cents"]) if g.get("price_amount_cents") is not None else None,
                            float(g["price_usd"]) if g.get("price_usd") is not None else None,
                            g.get("price_currency"),
                            g.get("price_interval"),
                            int(g["membership_model"]) if g.get("membership_model") is not None else None,
                            int(g["privacy"]) if g.get("privacy") is not None else None,
                            bool(g["is_public"]) if g.get("is_public") is not None else None,
                            int(g["total_members"]) if g.get("total_members") is not None else None,
                            int(g["total_online_members"]) if g.get("total_online_members") is not None else None,
                            int(g["total_posts"]) if g.get("total_posts") is not None else None,
                            int(g["total_admins"]) if g.get("total_admins") is not None else None,
                            int(g["total_rules"]) if g.get("total_rules") is not None else None,
                            int(g["num_courses"]) if g.get("num_courses") is not None else None,
                            int(g["num_modules"]) if g.get("num_modules") is not None else None,
                            int(g["afl_percent"]) if g.get("afl_percent") is not None else None,
                            g.get("src_group"),
                            g.get("links"),
                            g.get("owner_id"),
                            g.get("owner_name"),
                            g.get("category_id"),
                            g.get("category_slug"),
                            g.get("language"),
                            g.get("price_bucket"),
                            g.get("sort_seen"),
                            g.get("discovered_via"),
                            bool(g.get("detail_fetched", False)),
                            _to_dt(g.get("created_at")),
                            _to_dt(g.get("updated_at")),
                        )
                        for g in sorted_groups
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO skool.groups (
                            id, name, display_name, description, lp_description, color,
                            initials, cover_url, logo_url, logo_big_url, favicon_url,
                            price_amount_cents, price_usd, price_currency, price_interval,
                            membership_model, privacy, is_public, total_members,
                            total_online_members, total_posts, total_admins, total_rules,
                            num_courses, num_modules, afl_percent, src_group, links,
                            owner_id, owner_name, category_id, category_slug, language,
                            price_bucket, sort_seen, discovered_via, detail_fetched,
                            created_at, updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                            $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28,
                            $29, $30, $31, $32, $33, $34, $35, $36, $37,
                            COALESCE($38, NOW()), COALESCE($39, NOW())
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            display_name = COALESCE(EXCLUDED.display_name, skool.groups.display_name),
                            description = COALESCE(EXCLUDED.description, skool.groups.description),
                            lp_description = COALESCE(EXCLUDED.lp_description, skool.groups.lp_description),
                            cover_url = COALESCE(EXCLUDED.cover_url, skool.groups.cover_url),
                            logo_url = COALESCE(EXCLUDED.logo_url, skool.groups.logo_url),
                            price_amount_cents = COALESCE(EXCLUDED.price_amount_cents, skool.groups.price_amount_cents),
                            price_usd = COALESCE(EXCLUDED.price_usd, skool.groups.price_usd),
                            price_currency = COALESCE(EXCLUDED.price_currency, skool.groups.price_currency),
                            price_interval = COALESCE(EXCLUDED.price_interval, skool.groups.price_interval),
                            membership_model = COALESCE(EXCLUDED.membership_model, skool.groups.membership_model),
                            privacy = COALESCE(EXCLUDED.privacy, skool.groups.privacy),
                            is_public = COALESCE(EXCLUDED.is_public, skool.groups.is_public),
                            total_members = COALESCE(EXCLUDED.total_members, skool.groups.total_members),
                            total_online_members = COALESCE(EXCLUDED.total_online_members, skool.groups.total_online_members),
                            total_posts = COALESCE(EXCLUDED.total_posts, skool.groups.total_posts),
                            total_admins = COALESCE(EXCLUDED.total_admins, skool.groups.total_admins),
                            total_rules = COALESCE(EXCLUDED.total_rules, skool.groups.total_rules),
                            num_courses = COALESCE(EXCLUDED.num_courses, skool.groups.num_courses),
                            num_modules = COALESCE(EXCLUDED.num_modules, skool.groups.num_modules),
                            afl_percent = COALESCE(EXCLUDED.afl_percent, skool.groups.afl_percent),
                            links = COALESCE(EXCLUDED.links, skool.groups.links),
                            owner_id = COALESCE(EXCLUDED.owner_id, skool.groups.owner_id),
                            owner_name = COALESCE(EXCLUDED.owner_name, skool.groups.owner_name),
                            category_id = COALESCE(skool.groups.category_id, EXCLUDED.category_id),
                            category_slug = COALESCE(skool.groups.category_slug, EXCLUDED.category_slug),
                            language = COALESCE(skool.groups.language, EXCLUDED.language),
                            detail_fetched = COALESCE(EXCLUDED.detail_fetched, skool.groups.detail_fetched),
                            updated_at = NOW()
                        """,
                        group_records,
                    )
                    imported_counts["groups"] = len(group_records)

                # 3. User Groups
                sorted_ugs = [
                    ug for ug in raw_user_groups
                    if isinstance(ug, dict) and ug.get("user_id") and ug.get("group_id")
                ]
                sorted_ugs.sort(key=lambda x: (str(x["user_id"]), str(x["group_id"])))
                if sorted_ugs:
                    ug_records = [
                        (
                            str(ug["user_id"]),
                            str(ug["group_id"]),
                            str(ug.get("role", "member")),
                            _to_dt(ug.get("created_at")),
                        )
                        for ug in sorted_ugs
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO skool.user_groups (user_id, group_id, role, scraped_at)
                        VALUES ($1, $2, $3, COALESCE($4, NOW()))
                        ON CONFLICT (user_id, group_id) DO UPDATE SET
                            role = EXCLUDED.role
                        """,
                        ug_records,
                    )
                    imported_counts["user_groups"] = len(ug_records)

                # 4. Group Metrics (idempotent / deduplicated)
                if raw_group_metrics:
                    gm_records = [
                        (
                            str(m["group_id"]),
                            float(m["price_usd"]) if m.get("price_usd") is not None else None,
                            int(m["total_members"]) if m.get("total_members") is not None else None,
                            int(m["total_online_members"]) if m.get("total_online_members") is not None else None,
                            int(m["total_posts"]) if m.get("total_posts") is not None else None,
                            int(m["total_admins"]) if m.get("total_admins") is not None else None,
                            int(m["total_rules"]) if m.get("total_rules") is not None else None,
                            int(m["num_courses"]) if m.get("num_courses") is not None else None,
                            int(m["num_modules"]) if m.get("num_modules") is not None else None,
                            int(m["afl_percent"]) if m.get("afl_percent") is not None else None,
                            _to_dt(m.get("captured_at")) or datetime.now(timezone.utc),
                        )
                        for m in raw_group_metrics
                        if isinstance(m, dict) and m.get("group_id")
                    ]
                    if gm_records:
                        await conn.executemany(
                            """
                            INSERT INTO skool.group_metrics (
                                group_id, price_usd, total_members, total_online_members, total_posts,
                                total_admins, total_rules, num_courses, num_modules, afl_percent, captured_at
                            )
                            SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
                            WHERE NOT EXISTS (
                                SELECT 1 FROM skool.group_metrics
                                WHERE group_id = $1 AND captured_at = $11
                            )
                            """,
                            gm_records,
                        )
                        imported_counts["group_metrics"] = len(gm_records)

                # 5. User Metrics
                if raw_user_metrics:
                    um_records = [
                        (
                            str(m["user_id"]),
                            int(m["total_followers"]) if m.get("total_followers") is not None else None,
                            int(m["total_following"]) if m.get("total_following") is not None else None,
                            int(m["total_contributions"]) if m.get("total_contributions") is not None else None,
                            int(m["owned_groups"]) if m.get("owned_groups") is not None else None,
                            _to_dt(m.get("captured_at")) or datetime.now(timezone.utc),
                        )
                        for m in raw_user_metrics
                        if isinstance(m, dict) and m.get("user_id")
                    ]
                    if um_records:
                        await conn.executemany(
                            """
                            INSERT INTO skool.user_metrics (
                                user_id, total_followers, total_following, total_contributions, owned_groups, captured_at
                            )
                            SELECT $1, $2, $3, $4, $5, $6
                            WHERE NOT EXISTS (
                                SELECT 1 FROM skool.user_metrics
                                WHERE user_id = $1 AND captured_at = $6
                            )
                            """,
                            um_records,
                        )
                        imported_counts["user_metrics"] = len(um_records)

                # 6. Run bidirectional healing to guarantee full consistency
                await conn.execute(
                    """
                    INSERT INTO skool.users (id, name, full_name, created_at, updated_at)
                    SELECT DISTINCT g.owner_id, g.owner_name, g.owner_name, NOW(), NOW()
                    FROM skool.groups g
                    WHERE g.owner_id IS NOT NULL 
                      AND g.owner_name IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM skool.users u WHERE u.id = g.owner_id)
                    ON CONFLICT (id) DO NOTHING;

                    INSERT INTO skool.user_groups (user_id, group_id, role, scraped_at)
                    SELECT DISTINCT g.owner_id, g.id, 'owner', NOW()
                    FROM skool.groups g
                    WHERE g.owner_id IS NOT NULL
                      AND EXISTS (SELECT 1 FROM skool.users u WHERE u.id = g.owner_id)
                    ON CONFLICT (user_id, group_id) DO NOTHING;
                    """
                )

        return imported_counts

