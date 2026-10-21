"""Scraper service — scraper admin management and business logic (no SQL, no HTTP)."""
from typing import Any

from app.ports.repositories import ScraperRepository

VALID_MODES = {"refresh", "discovery", "all", "missing_owners", "repair", "audit", "run_all", "run-all"}


class ScraperService:
    def __init__(self, repo: ScraperRepository) -> None:
        self._repo = repo

    async def get_status(self) -> dict:
        """Fetch daemon state, schedules, backlog stats, and active job."""
        return await self._repo.get_status()

    async def trigger_job(self, mode: str) -> dict:
        """Trigger an execution job manually.
        
        Mode must be one of: refresh, discovery, all, missing_owners.
        """
        if not isinstance(mode, str) or mode.strip().lower() not in VALID_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(VALID_MODES))}."
            )
        normalized_mode = mode.strip().lower()
        job_id = await self._repo.enqueue_job(normalized_mode, trigger_type="manual")
        return {
            "status": "queued",
            "job_id": job_id,
            "mode": normalized_mode,
        }

    async def get_logs(self, limit: int = 50, job_id: int | None = None) -> dict:
        """Fetch execution records and logs."""
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 50
        clamped_limit = max(1, min(lim, 200))

        clean_job_id: int | None = None
        if job_id is not None:
            try:
                clean_job_id = int(job_id)
            except (TypeError, ValueError):
                return {"items": []}
            if clean_job_id <= 0 or clean_job_id > 9_223_372_036_854_775_807:
                return {"items": []}

        items = await self._repo.get_logs(limit=clamped_limit, job_id=clean_job_id)
        return {"items": items}

    async def get_settings(self) -> dict:
        """Fetch persistent schedule settings."""
        settings = await self._repo.get_settings()
        return {
            "refresh_interval_days": settings.get("refresh_interval_days", 3),
            "discovery_interval_days": settings.get("discovery_interval_days", 7),
            "is_paused": settings.get("is_paused", False),
            "discovery_mode": settings.get("discovery_mode", "all"),
            "page_concurrency": settings.get("page_concurrency", 4),
            "detail_concurrency": settings.get("detail_concurrency", 8),
            "request_delay_ms": settings.get("request_delay_ms", 300),
            "include_bigrams": settings.get("include_bigrams", False),
        }

    async def update_settings(self, settings_data: dict) -> dict:
        """Update persistent schedule parameters."""
        if not isinstance(settings_data, dict):
            raise ValueError("Settings payload must be a dictionary")

        clean_data: dict[str, Any] = {}

        if "refresh_interval_days" in settings_data:
            val = settings_data["refresh_interval_days"]
            try:
                val_int = int(val)
            except (TypeError, ValueError):
                raise ValueError("refresh_interval_days must be an integer")
            if val_int <= 0:
                raise ValueError("refresh_interval_days must be greater than 0")
            if val_int > 3650:
                raise ValueError("refresh_interval_days must not exceed 3650 days")
            clean_data["refresh_interval_days"] = val_int

        if "discovery_interval_days" in settings_data:
            val = settings_data["discovery_interval_days"]
            try:
                val_int = int(val)
            except (TypeError, ValueError):
                raise ValueError("discovery_interval_days must be an integer")
            if val_int <= 0:
                raise ValueError("discovery_interval_days must be greater than 0")
            if val_int > 3650:
                raise ValueError("discovery_interval_days must not exceed 3650 days")
            clean_data["discovery_interval_days"] = val_int

        if "is_paused" in settings_data:
            clean_data["is_paused"] = bool(settings_data["is_paused"])

        if "discovery_mode" in settings_data and settings_data["discovery_mode"] is not None:
            dm = str(settings_data["discovery_mode"]).lower().strip()
            if dm not in ("all", "browse", "search", "quick", "details"):
                raise ValueError("discovery_mode must be one of: all, browse, search, quick, details")
            clean_data["discovery_mode"] = dm

        if "page_concurrency" in settings_data and settings_data["page_concurrency"] is not None:
            try:
                pc = int(settings_data["page_concurrency"])
            except (TypeError, ValueError):
                raise ValueError("page_concurrency must be an integer")
            if pc < 1 or pc > 16:
                raise ValueError("page_concurrency must be between 1 and 16")
            clean_data["page_concurrency"] = pc

        if "detail_concurrency" in settings_data and settings_data["detail_concurrency"] is not None:
            try:
                dc = int(settings_data["detail_concurrency"])
            except (TypeError, ValueError):
                raise ValueError("detail_concurrency must be an integer")
            if dc < 1 or dc > 24:
                raise ValueError("detail_concurrency must be between 1 and 24")
            clean_data["detail_concurrency"] = dc

        if "request_delay_ms" in settings_data and settings_data["request_delay_ms"] is not None:
            try:
                rd = int(settings_data["request_delay_ms"])
            except (TypeError, ValueError):
                raise ValueError("request_delay_ms must be an integer")
            if rd < 0 or rd > 5000:
                raise ValueError("request_delay_ms must be between 0 and 5000")
            clean_data["request_delay_ms"] = rd

        if "include_bigrams" in settings_data and settings_data["include_bigrams"] is not None:
            clean_data["include_bigrams"] = bool(settings_data["include_bigrams"])

        updated = await self._repo.update_settings(clean_data)
        return {
            "status": "updated",
            "settings": {
                "refresh_interval_days": updated.get("refresh_interval_days", 3),
                "discovery_interval_days": updated.get("discovery_interval_days", 7),
                "is_paused": updated.get("is_paused", False),
                "discovery_mode": updated.get("discovery_mode", "all"),
                "page_concurrency": updated.get("page_concurrency", 4),
                "detail_concurrency": updated.get("detail_concurrency", 8),
                "request_delay_ms": updated.get("request_delay_ms", 300),
                "include_bigrams": updated.get("include_bigrams", False),
            },
        }

    async def cancel_job(self, job_id: int) -> dict:
        """Cancel an active or queued scraper job."""
        try:
            clean_id = int(job_id)
        except (TypeError, ValueError):
            raise ValueError("job_id must be an integer")
        if clean_id <= 0:
            raise ValueError("job_id must be positive")

        success = await self._repo.cancel_job(clean_id)
        return {
            "status": "cancelled" if success else "not_found_or_already_completed",
            "job_id": clean_id,
            "success": success,
        }

    async def export_data(self, include_metrics: bool = True) -> dict:
        """Export all scraped data (groups, users, relationships, and time-series metrics)."""
        return await self._repo.export_data(include_metrics=bool(include_metrics))

    async def import_data(self, payload: dict) -> dict:
        """Import scraped dataset safely and idempotently."""
        if not isinstance(payload, dict):
            raise ValueError("Import payload must be a JSON object")
        counts = await self._repo.import_data(payload)
        return {
            "status": "success",
            "imported": counts,
        }

