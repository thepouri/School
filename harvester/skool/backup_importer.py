"""Backup Importer for Skool Harvester.

Reads PostgreSQL pg_dump tar archives (.backup / .tar), extracts user records,
filters out all duplicates against the current database, and safely inserts
the new non-duplicate users as stubs (profile_status='stub', groups_fetched=False).

Zero data overwrite: Existing groups and users are completely untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db.db import dispose_db, session_scope
from .db.models import User

log = logging.getLogger("skool.backup_importer")


@dataclass
class ImportStats:
    total_in_backup: int = 0
    already_in_db: int = 0
    duplicate_in_file: int = 0
    new_users_found: int = 0
    inserted: int = 0
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_in_backup": self.total_in_backup,
            "already_in_db": self.already_in_db,
            "duplicate_in_file": self.duplicate_in_file,
            "new_users_found": self.new_users_found,
            "inserted": self.inserted,
            "dry_run": self.dry_run,
        }


def _find_user_table_info(tar: tarfile.TarFile) -> tuple[str, list[str]]:
    """Inspect restore.sql or toc.dat in the tar archive to locate the users data file and columns."""
    names = tar.getnames()
    
    # 1. Try restore.sql
    if "restore.sql" in names:
        f = tar.extractfile("restore.sql")
        if f:
            sql = f.read().decode("utf-8", errors="ignore")
            for line in sql.splitlines():
                if "COPY skool.users " in line and "$$PATH$$" in line:
                    parts = line.split(" FROM ")
                    table_part = parts[0].replace("COPY skool.users", "").strip()
                    cols = [c.strip() for c in table_part.strip("()").split(",")]
                    file_name = parts[1].split("$$PATH$$/")[1].split("'")[0].strip(" ;")
                    return file_name, cols

    # 2. Check for standard 5103.dat or similar dat files
    for dat_candidate in ("5103.dat", "users.dat"):
        if dat_candidate in names:
            return dat_candidate, [
                "id", "name", "first_name", "last_name", "full_name",
                "bio", "location", "location_source", "timezone",
                "avatar_url", "avatar_bubble_url", "link_facebook",
                "link_instagram", "link_linkedin", "link_twitter",
                "link_website", "link_youtube", "last_offline",
                "total_followers", "total_following", "total_contributions",
                "groups_fetched", "created_at", "updated_at", "scraped_at",
            ]

    raise ValueError("Could not find skool.users table data in the provided backup archive.")


async def _load_existing_identifiers() -> tuple[set[str], set[str]]:
    """Load existing user IDs and usernames from the database into memory."""
    log.info("Querying existing user identifiers from database...")
    existing_ids: set[str] = set()
    existing_names: set[str] = set()

    async with session_scope() as session:
        # Load in chunks to manage memory
        chunk_size = 50_000
        offset = 0
        while True:
            stmt = select(User.id, User.name).order_by(User.id).limit(chunk_size).offset(offset)
            result = await session.execute(stmt)
            rows = result.all()
            if not rows:
                break
            for uid, uname in rows:
                if uid:
                    existing_ids.add(str(uid).strip())
                if uname:
                    existing_names.add(str(uname).strip().lower())
            offset += len(rows)
            log.info("Loaded %d existing users from DB...", len(existing_ids))

    log.info("Total existing users in DB: %d IDs, %d unique names", len(existing_ids), len(existing_names))
    return existing_ids, existing_names


async def import_backup_users(
    backup_path: str | Path,
    dry_run: bool = False,
    batch_size: int = 1000,
) -> ImportStats:
    """Read a pg_dump tar backup and insert non-duplicate users as stubs."""
    path = Path(backup_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Backup file not found at: {path}")

    stats = ImportStats(dry_run=dry_run)
    log.info("Opening backup archive: %s (%.1f MB)", path.name, path.stat().st_size / (1024 * 1024))

    # 1. Load existing DB identifiers
    existing_ids, existing_names = await _load_existing_identifiers()

    # 2. Open tar archive and locate users file
    with tarfile.open(path, "r") as tar:
        dat_filename, columns = _find_user_table_info(tar)
        log.info("Found users data in archive: '%s' with %d columns", dat_filename, len(columns))

        try:
            id_idx = columns.index("id")
            name_idx = columns.index("name")
            fullname_idx = columns.index("full_name") if "full_name" in columns else -1
        except ValueError as err:
            raise ValueError(f"Required columns 'id' or 'name' missing from backup schema: {err}") from err

        dat_file = tar.extractfile(dat_filename)
        if not dat_file:
            raise ValueError(f"Could not read member '{dat_filename}' from tar archive.")

        # In-memory tracking for duplicates within the file itself
        seen_in_file_ids: set[str] = set()
        seen_in_file_names: set[str] = set()
        pending_inserts: list[dict[str, Any]] = []

        log.info("Scanning users data from archive...")
        line_num = 0

        for raw_line in dat_file:
            if not raw_line or raw_line.startswith(b"\\."):
                continue

            line = raw_line.decode("utf-8", errors="ignore").rstrip("\r\n")
            if not line:
                continue

            line_num += 1
            stats.total_in_backup += 1

            fields = line.split("\t")
            if len(fields) <= max(id_idx, name_idx):
                continue

            raw_id = fields[id_idx].strip()
            raw_name = fields[name_idx].strip()
            full_name = fields[fullname_idx].strip() if fullname_idx >= 0 and fullname_idx < len(fields) else raw_name

            # Skip Postgres COPY NULL markers (\N) or empty values
            if not raw_id or raw_id == "\\N" or not raw_name or raw_name == "\\N":
                continue

            norm_name = raw_name.lower()

            # Check if user already exists in DB
            if raw_id in existing_ids or norm_name in existing_names:
                stats.already_in_db += 1
                continue

            # Check if user is duplicate within this file
            if raw_id in seen_in_file_ids or norm_name in seen_in_file_names:
                stats.duplicate_in_file += 1
                continue

            seen_in_file_ids.add(raw_id)
            seen_in_file_names.add(norm_name)
            stats.new_users_found += 1

            clean_full_name = None if full_name == "\\N" else full_name

            pending_inserts.append({
                "id": raw_id,
                "name": raw_name,
                "full_name": clean_full_name or raw_name,
                "groups_fetched": False,
                "profile_status": "stub",
            })

            # Batch insert
            if len(pending_inserts) >= batch_size:
                if not dry_run:
                    await _insert_stub_batch(pending_inserts)
                    stats.inserted += len(pending_inserts)
                log.info(
                    "Processed %d lines | New users: %d (in batch: %d)",
                    line_num, stats.new_users_found, len(pending_inserts),
                )
                pending_inserts.clear()

        # Insert remaining
        if pending_inserts:
            if not dry_run:
                await _insert_stub_batch(pending_inserts)
                stats.inserted += len(pending_inserts)
            pending_inserts.clear()

    log.info("==========================================")
    log.info("Backup Import Finished:")
    log.info("  Total users in backup:     %d", stats.total_in_backup)
    log.info("  Already in database:       %d", stats.already_in_db)
    log.info("  Duplicates within backup:  %d", stats.duplicate_in_file)
    log.info("  New unique users found:    %d", stats.new_users_found)
    log.info("  Inserted into DB:          %d %s", stats.inserted, "(DRY RUN - 0 written)" if dry_run else "")
    log.info("==========================================")

    return stats


async def _insert_stub_batch(rows: list[dict[str, Any]]) -> None:
    """Insert a chunk of stub users using ON CONFLICT DO NOTHING."""
    if not rows:
        return

    # Deterministic sort prevents deadlocks
    rows.sort(key=lambda r: str(r["id"]))

    async with session_scope() as session:
        stmt = (
            pg_insert(User)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        await session.execute(stmt)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import non-duplicate users from Skool database backup (.tar / .backup)")
    parser.add_argument("backup_path", help="Path to the .backup or .tar file")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and report without writing to database")
    parser.add_argument("--batch-size", type=int, default=1000, help="Insert batch size (default: 1000)")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    return parser


async def _run_cli(args: argparse.Namespace) -> None:
    try:
        await import_backup_users(
            backup_path=args.backup_path,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    finally:
        await dispose_db()


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    try:
        asyncio.run(_run_cli(args))
    except KeyboardInterrupt:
        log.warning("Import cancelled by user.")
    except Exception as exc:
        log.error("Import failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
