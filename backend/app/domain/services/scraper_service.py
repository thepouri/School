"""Scraper service — scraper admin management and business logic (no SQL, no HTTP)."""
from typing import Any

from app.ports.repositories import ScraperRepository

VALID_MODES = {"refresh", "discovery", "all", "missing_owners"}


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

        updated = await self._repo.update_settings(clean_data)
        return {
            "status": "updated",
            "settings": {
                "refresh_interval_days": updated.get("refresh_interval_days", 3),
                "discovery_interval_days": updated.get("discovery_interval_days", 7),
                "is_paused": updated.get("is_paused", False),
            },
        }
