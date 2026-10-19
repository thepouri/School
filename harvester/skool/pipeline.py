"""Two-path pipeline.

Path A (browse):  category × language × price × sort × type, without query.
Path B (search):  search terms × language. Deliberately without c and srt,
                 because Skool itself drops sort when q is present.

Per-group chain (requests sequential, then on to the next group):

    discovery → about.json (details + price + owner) → owner profile
              → owner's other groups (insert + link user_groups)

The plans stage was removed: `plans.json` no longer returns public data. The
price is taken from the group's own metadata: `displayPrice` (discovery) or
`currentMBp` (about.json).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import parser as skool_parser
from .constants import (
    CATEGORIES,
    LANGUAGES,
    MAX_PAGES,
    PAGE_SIZE,
    PRICES,
    SORTS,
    default_query_plan,
)
from .db import repository as repo
from .db.db import session_scope
from .scraper import SkoolClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Slice:
    """One parametric slice of discovery."""

    discovered_via: str
    category_slug: str | None = None
    category_id: str | None = None
    language: str | None = None
    price_bucket: str | None = None
    group_type: str | None = None
    sort: str | None = None
    query: str | None = None

    def label(self) -> str:
        parts = [self.discovered_via]
        if self.query:
            parts.append(f"q={self.query}")
        if self.category_slug:
            parts.append(f"c={self.category_slug}")
        if self.language:
            parts.append(f"lang={self.language}")
        if self.price_bucket:
            parts.append(f"pr={self.price_bucket}")
        if self.group_type:
            parts.append(f"ty={self.group_type}")
        if self.sort:
            parts.append(f"srt={self.sort}")
        return " | ".join(parts)

    def stamp(self, row: dict[str, Any]) -> dict[str, Any]:
        """Stamp the parametric fields onto the record.

        These are written with coalesce(current, new) in the database, so if
        the record already existed without a category, it gets filled here.
        """
        stamped = dict(row)
        stamped["category_id"] = self.category_id
        stamped["category_slug"] = self.category_slug
        stamped["language"] = self.language
        stamped["price_bucket"] = self.price_bucket
        stamped["sort_seen"] = self.sort
        stamped["discovered_via"] = self.discovered_via
        return stamped


@dataclass
class Stats:
    slices: int = 0
    pages: int = 0
    groups_seen: int = 0
    groups_written: int = 0
    groups_detailed: int = 0
    groups_priced: int = 0
    users_written: int = 0
    owner_groups: int = 0
    groups_skipped: int = 0
    users_skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


@dataclass
class Pipeline:
    client: SkoolClient
    page_concurrency: int = 4
    detail_concurrency: int = 8
    max_pages: int = MAX_PAGES
    # whether the owner/user (snowball) stage is enabled
    fetch_users: bool = True
    stats: Stats = field(default_factory=Stats)

    def __post_init__(self) -> None:
        self._page_sem = asyncio.Semaphore(self.page_concurrency)
        self._detail_sem = asyncio.Semaphore(self.detail_concurrency)
        # lock is only for in-memory sets, not the database
        self._lock = asyncio.Lock()
        self._seen_users: set[str] = set()
        self._seen_detail_groups: set[str] = set()
        self._dumped = False

    # ─────────── helpers ───────────

    async def _claim(self, bucket: set[str], key: str) -> bool:
        """Return True if not already claimed this run (atomic)."""
        async with self._lock:
            if key in bucket:
                return False
            bucket.add(key)
            return True

    @staticmethod
    def _page_count(total: int, cap: int) -> int:
        if total <= 0:
            return 0
        return max(1, min(math.ceil(total / PAGE_SIZE), cap))

    async def _fetch_page(self, slice_: Slice, page: int) -> dict[str, Any] | None:
        async with self._page_sem:
            return await self.client.discovery(
                page=page,
                category_id=slice_.category_id,
                language=slice_.language,
                price=slice_.price_bucket,
                sort=slice_.sort,
                group_type=slice_.group_type,
                query=slice_.query,
            )

    # ─────────── harvesting one slice ───────────

    async def harvest_slice(self, slice_: Slice) -> list[tuple[str, str]]:
        """Read one slice and write the base records.

        Output: list of (group_id, group_name) for the enrichment stage.

        Note: the discovery response is intentionally lean — only name,
        description, cover, price and member count. Owner, post count,
        privacy etc. live only in about.json.
        """
        first = await self._fetch_page(slice_, 1)
        if not first:
            log.info("Slice empty/error: %s", slice_.label())
            return []

        parsed = skool_parser.parse_discovery(first)
        total = parsed["total"]
        pages = self._page_count(total, self.max_pages)
        self.stats.slices += 1
        log.info(
            "▸ %s | numGroups=%s | pages=%s%s",
            slice_.label(),
            total,
            pages,
            " (capped)" if total > pages * PAGE_SIZE else "",
        )
        if pages == 0:
            return []

        payloads: list[dict[str, Any]] = [first]
        if pages > 1:
            others = await asyncio.gather(
                *(self._fetch_page(slice_, p) for p in range(2, pages + 1)),
                return_exceptions=True,
            )
            for item in others:
                if isinstance(item, BaseException):
                    log.warning("Error on page of slice %s: %s", slice_.label(), item)
                elif item:
                    payloads.append(item)

        rows: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            self.stats.pages += 1
            for raw in skool_parser.parse_discovery(payload)["groups"]:
                self.stats.groups_seen += 1
                row = skool_parser.parse_group(raw)
                if not row:
                    continue
                rows[row["id"]] = slice_.stamp(row)

        if not rows:
            # Important: this state used to pass silently and leave the DB empty.
            self._dump_debug(first, parsed)
            log.error(
                "No groups parsed from response but numGroups=%s | pageProps keys: %s",
                total,
                parsed.get("prop_keys"),
            )
            return []

        async with session_scope() as session:
            written = await repo.upsert_groups(session, list(rows.values()))
        self.stats.groups_written += written
        log.info("  ✓ %s base groups written/updated", written)
        return [(row["id"], row["name"]) for row in rows.values()]

    # ─────────── enriching each group ───────────

    async def process_group(
        self,
        group_id: str,
        group_name: str,
        slice_: Slice | None,
        force: bool = False,
    ) -> None:
        """Full chain for one group: details → owner → owner's groups.

        Order (all inline, no deep nesting):
          1. if the group's details are already complete in the DB → skip
             (unless `force=True` — the full-refresh pass re-fetches everything)
          2. fetch `about.json` → write the group + the owner block
          3. if the owner's profile isn't already complete in the DB → fetch it
             and write their owned + member groups, then mark them scraped
        """
        if not await self._claim(self._seen_detail_groups, group_id):
            return

        # Skip groups whose details are already complete in the database.
        if not force:
            async with session_scope() as session:
                already = await repo.group_is_fetched(session, group_id)
            if already:
                self.stats.groups_skipped += 1
                log.debug("Group already fetched, skipping request: %s", group_name)
                return

        async with self._detail_sem:
            payload = await self.client.group_about(group_name)

        detail = skool_parser.parse_group_detail(payload) if payload else None
        # The owner block inside about.json is itself a complete user record
        owner = skool_parser.group_owner(payload) if payload else None

        had_payload = bool(payload)
        async with session_scope() as session:
            if detail:
                await repo.upsert_group(
                    session, slice_.stamp(detail) if slice_ else detail
                )
            if owner:
                await repo.upsert_user(session, owner)
                await repo.link_user_groups(
                    session, owner["id"], [group_id], role="owner"
                )
            elif detail and detail.get("owner_id") and detail.get("owner_name"):
                # Fallback stub user so user record is always present in skool.users
                owner_stub = {
                    "id": detail["owner_id"],
                    "name": detail["owner_name"],
                    "full_name": detail.get("owner_name"),
                }
                await repo.upsert_user(session, owner_stub)
                await repo.link_user_groups(
                    session, detail["owner_id"], [group_id], role="owner"
                )
            # Only flag when about.json actually came back; otherwise the
            # run_details pass retries and the group is not permanently burnt.
            if had_payload:
                await repo.mark_detail_fetched(session, [group_id])

        if not detail:
            log.debug("Group details did not come through: %s", group_name)
            return

        self.stats.groups_detailed += 1
        if detail.get("price_amount_cents"):
            self.stats.groups_priced += 1

        log.info(
            "  ✓ %s | price=%s %s | members=%s | owner=@%s",
            group_name,
            detail.get("price_usd"),
            (detail.get("price_currency") or "").upper(),
            detail.get("total_members"),
            detail.get("owner_name"),
        )

        # Owner and their other groups — inline, not nested. Fetch the owner's
        # profile only if they aren't already complete in the database.
        owner_name = detail.get("owner_name") or (owner or {}).get("name")
        if owner_name and self.fetch_users:
            async with session_scope() as session:
                already_scraped = await repo.user_is_scraped(session, owner_name)
            if already_scraped:
                self.stats.users_skipped += 1
                log.debug("Owner already scraped, skipping request: @%s", owner_name)
            else:
                await self.process_user(
                    owner_name, slice_, skip_group_id=group_id, depth=0
                )

    async def enrich_groups(
        self,
        groups: Sequence[tuple[str, str]],
        slice_: Slice | None,
        force: bool = False,
    ) -> None:
        tasks = [
            asyncio.create_task(self.process_group(gid, name, slice_, force=force))
            for gid, name in groups
            if gid and name
        ]
        if not tasks:
            return
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except Exception as exc:  # noqa: BLE001
                log.warning("Error enriching group: %s", exc)
        log.info(
            "  ✓ Enriched: %s complete groups | %s users | %s owner groups",
            self.stats.groups_detailed,
            self.stats.users_written,
            self.stats.owner_groups,
        )

    def _dump_debug(self, payload: dict[str, Any], parsed: dict[str, Any]) -> None:
        """Dump the raw response once to disk to see the real JSON shape."""
        if self._dumped:
            return
        self._dumped = True
        try:
            path = pathlib.Path("debug_discovery.json")
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            log.error("Raw response dumped to %s", path.resolve())
        except OSError as exc:
            log.warning("Writing debug_discovery.json failed: %s", exc)

    # ─────────── user snowball ───────────

    async def process_user(
        self,
        user_name: str,
        inherit: Slice | None,
        skip_group_id: str | None = None,
        depth: int = 0,
        force: bool = False,
    ) -> None:
        """One user's profile + all their groups (owned and member).

        Flat, not recursive: this fetches the user's profile once and writes
        their owned groups (role=owner) and joined groups (role=member) in the
        same pass. There is no deep walk into member-group owners.

        inherit brings the parent slice's category. We only carry the category;
        language/price/type are each group's own attribute and we must not guess.

        skip_group_id: the group we just processed (only for counting).

        depth: kept for API compatibility; no longer used for recursion.
        force: re-fetch even if the DB says this user is complete (refresh).
        """
        if not await self._claim(self._seen_users, user_name):
            return

        # Skip users whose profile + groups are already complete in the DB.
        if not force:
            async with session_scope() as session:
                already = await repo.user_is_scraped(session, user_name)
            if already:
                self.stats.users_skipped += 1
                log.debug("User already scraped, skipping request: @%s", user_name)
                return

        async with self._detail_sem:
            payload = await self.client.user_profile(user_name)
        if not payload:
            return

        parsed = skool_parser.parse_user_page(payload)
        if not parsed:
            log.debug("Profile could not be parsed: %s", user_name)
            return

        user = parsed["user"]
        snow = Slice(
            discovered_via="snowball",
            category_slug=inherit.category_slug if inherit else None,
            category_id=inherit.category_id if inherit else None,
        )
        # owned: groups the user created (role "owner")
        # member: groups the user merely joined (role "member")
        owned_rows: dict[str, dict[str, Any]] = {}
        member_rows: dict[str, dict[str, Any]] = {}
        for raw in parsed.get("owned", []):
            row = skool_parser.parse_group(raw)
            if row:
                owned_rows[row["id"]] = snow.stamp(row)
        for raw in parsed.get("member", []):
            row = skool_parser.parse_group(raw)
            if row:
                member_rows[row["id"]] = snow.stamp(row)

        async with session_scope() as session:
            await repo.upsert_user(session, user)
            # All groups first (both owned and member), then links with roles.
            if owned_rows:
                await repo.upsert_groups(session, list(owned_rows.values()))
                await repo.link_user_groups(
                    session, user["id"], list(owned_rows.keys()), role="owner"
                )
            if member_rows:
                await repo.upsert_groups(session, list(member_rows.values()))
                await repo.link_user_groups(
                    session, user["id"], list(member_rows.keys()), role="member"
                )
            await repo.mark_user_scraped(session, [user["id"]])

        self.stats.users_written += 1
        others = [gid for gid in owned_rows if gid != skip_group_id]
        self.stats.owner_groups += len(others)
        log.info(
            "  ✓ user @%s | %s %s | location=%s (%s) | tz=%s | owned=%s member=%s",
            user["name"],
            user.get("first_name") or "",
            user.get("last_name") or "",
            user.get("location"),
            user.get("location_source"),
            user.get("timezone"),
            len(others),
            len(member_rows),
        )

    async def process_users(
        self,
        user_names: Iterable[str],
        inherit: Slice | None,
        force: bool = False,
    ) -> None:
        tasks = [
            asyncio.create_task(self.process_user(name, inherit, force=force))
            for name in dict.fromkeys(user_names)
        ]
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except Exception as exc:  # noqa: BLE001
                log.warning("Error processing user: %s", exc)

    # ─────────── Path A ───────────

    async def run_browse(
        self,
        categories: Sequence[str] | None = None,
        languages: Sequence[str | None] | None = None,
        prices: Sequence[str | None] = PRICES,
        sorts: Sequence[str | None] = SORTS,
        types: Sequence[str | None] = (None,),
        with_details: bool = True,
    ) -> None:
        category_slugs = list(categories or CATEGORIES.keys())
        language_list = list(languages if languages is not None else LANGUAGES)

        for slug in category_slugs:
            category_id = CATEGORIES.get(slug)
            if not category_id:
                log.warning("Unknown category: %s", slug)
                continue
            for language in language_list:
                for price in prices:
                    for sort in sorts:
                        for group_type in types:
                            slice_ = Slice(
                                discovered_via="browse",
                                category_slug=slug,
                                category_id=category_id,
                                language=language,
                                price_bucket=price,
                                group_type=group_type,
                                sort=sort,
                            )
                            groups = await self.harvest_slice(slice_)
                            if with_details and groups:
                                await self.enrich_groups(groups, slice_)

    # ─────────── Path B ───────────

    async def run_search(
        self,
        queries: Sequence[str] | None = None,
        languages: Sequence[str | None] = (None,),
        prices: Sequence[str | None] = (None,),
        types: Sequence[str | None] = (None,),
        with_details: bool = True,
        language_queries: bool = True,
    ) -> None:
        """Query-driven discovery.

        When `queries` is given, it is the query list for every language
        (cross product). When it is not, `language_queries=True` picks per-
        language keyword sets (`LANGUAGE_QUERIES`) so a German search actually
        uses German words, Japanese uses Japanese, etc. Languages without a
        dedicated set fall back to the generic keyword plan.
        """
        from .constants import LANGUAGE_QUERIES

        explicit = queries is not None
        query_list = list(queries or default_query_plan())

        for language in languages:
            if explicit or not language_queries:
                terms = query_list
            else:
                terms = list(LANGUAGE_QUERIES.get(language) or query_list)
                log.info(
                    "Search language=%s | %s native queries", language, len(terms)
                )
            for term in terms:
                for price in prices:
                    for group_type in types:
                        slice_ = Slice(
                            discovered_via="search",
                            language=language,
                            price_bucket=price,
                            group_type=group_type,
                            query=term,
                            # deliberately no category or sort
                        )
                        groups = await self.harvest_slice(slice_)
                        if with_details and groups:
                            await self.enrich_groups(groups, slice_)

    # ─────────── member search (authenticated user harvest) ───────────

    async def run_member_search(
        self,
        queries: Sequence[str] | None = None,
        group_name: str = "skoolers",
        max_pages: int | None = None,
        concurrency: int = 8,
    ) -> int:
        """Authenticated member search: add matching users to the DB.

        Hits `{group}/-/search.json?q=<query>&t=members&p=<page>` for each query
        and inserts only users who aren't already in the `users` table
        (`ON CONFLICT DO NOTHING`). No group fetching here — this pass only
        registers users; a later pass walks their groups.

        Default query plan is **only the alphabet + digits** — 36 short queries.
        Each page returns ~10 members, so single chars return the most matches
        with the fewest requests; bigrams/keywords are NOT run by default to
        keep the harvest fast. Pass `queries=` to override.

        Pages of a query are fetched concurrently (`concurrency`, default 8),
        so a query's pages run in parallel instead of one-by-one.
        Returns the number of users processed.
        """
        from .constants import alphabet_queries

        query_list = list(queries) if queries else alphabet_queries()
        sem = asyncio.Semaphore(max(1, concurrency))
        inserted = 0

        for term in query_list:
            # Discover the page count from page 1, then blast the rest in
            # parallel. Skool returns ~10 members/page, capped at 1000.
            first = await self.client.member_search(
                query=term, page=1, group_name=group_name
            )
            if first:
                parsed_first = skool_parser.parse_member_search(first)
            else:
                parsed_first = None
            if not parsed_first or not parsed_first["users"]:
                continue

            total = parsed_first["total"]
            # page size from what we actually got
            page_size = max(1, len(parsed_first["users"]))
            pages = (
                (total + page_size - 1) // page_size
                if total and total > page_size
                else 1
            )
            if max_pages is not None:
                pages = min(pages, max(1, max_pages))

            async with session_scope() as session:
                await repo.insert_missing_users(session, parsed_first["users"])
            inserted += len(parsed_first["users"])
            self.stats.users_written += len(parsed_first["users"])
            log.info(
                "  member search q=%r | total=%s | pages=%s | page_size=%s",
                term,
                total,
                pages,
                page_size,
            )

            if pages > 1:
                state = {"pages": 0, "users": 0}

                async def fetch_page(p: int) -> int:
                    async with sem:
                        payload = await self.client.member_search(
                            query=term, page=p, group_name=group_name
                        )
                    parsed = (
                        skool_parser.parse_member_search(payload) if payload else None
                    )
                    users = len(parsed["users"]) if parsed and parsed["users"] else 0
                    state["pages"] += 1
                    state["users"] += users
                    # progress line every 5 completed pages
                    if (state["pages"] % 5) == 0:
                        log.info(
                            "  q=%r | %s/%s pages | %s users",
                            term,
                            state["pages"],
                            pages - 1,
                            inserted + state["users"],
                        )
                    if users:
                        async with session_scope() as session:
                            await repo.insert_missing_users(session, parsed["users"])
                    return users

                results = await asyncio.gather(
                    *(fetch_page(p) for p in range(2, pages + 1))
                )
                page_total = sum(results)
                inserted += page_total
                self.stats.users_written += page_total
                log.info(
                    "  ✓ q=%r done | %s pages | %s users | total so far %s",
                    term,
                    pages - 1,
                    page_total,
                    inserted,
                )

        log.info("Member search done: %s users processed", inserted)
        return inserted

    # ─────────── backlog catch-up ───────────

    async def run_details(
        self, batch: int = 200, max_groups: int | None = None
    ) -> None:
        """Complete any group whose details have not been fetched."""
        processed = 0
        while True:
            async with session_scope() as session:
                pending = await repo.pending_detail_groups(session, limit=batch)
            pending = [
                item for item in pending if item[0] not in self._seen_detail_groups
            ]
            if not pending:
                return
            if max_groups is not None:
                pending = pending[: max(0, max_groups - processed)]
                if not pending:
                    return
            await self.enrich_groups(pending, None)
            processed += len(pending)

    async def run_users(self, batch: int = 200, max_users: int | None = None) -> None:
        """Read owners whose profiles have not been fetched."""
        processed = 0
        while True:
            async with session_scope() as session:
                pending = await repo.pending_owner_users(session, limit=batch)
            names = [
                name for _uid, name in pending if name and name not in self._seen_users
            ]
            if not names:
                return
            if max_users is not None:
                names = names[: max(0, max_users - processed)]
                if not names:
                    return
            await self.process_users(names, None)
            processed += len(names)

    async def run_refresh(
        self,
        batch: int = 200,
        max_groups: int | None = None,
        max_users: int | None = None,
        skip_users: bool = False,
        older_than_days: float | None = None,
    ) -> None:
        """Re-fetch groups and users already in the database.

        Walks `groups` then `users` (keyset pagination), hits about.json /
        @handle.json for each, updates the live rows AND appends a metric-
        history row — inline snapshots fire on every write, so one pass
        refreshes data and extends the timeline at once. No cookies needed.

        `older_than_days`: only re-fetch entities whose latest metric snapshot
        (or scraped_at) is older than N days. Entities refreshed within the
        window are skipped before any request is made. None = refresh
        everything regardless of age.

        This is the heavy "keep everything current" pass — schedule it (e.g.
        nightly) rather than running it ad hoc.
        """
        log.info(
            "=== Full refresh of all groups%s ===",
            f" (older than {older_than_days}d)" if older_than_days else "",
        )
        processed_groups = 0
        last_id = ""
        while True:
            async with session_scope() as session:
                chunk = await repo.all_groups(
                    session,
                    after_id=last_id,
                    limit=batch,
                    older_than_days=older_than_days,
                )
            if not chunk:
                break
            last_id = chunk[-1][0]
            # force=True: re-fetch even groups marked complete — that is the
            # whole point of the refresh pass (and each write snapshots metrics)
            await self.enrich_groups(chunk, None, force=True)
            processed_groups += len(chunk)
            log.info(
                "refresh groups: %s done (%s detailed, %s skipped)",
                processed_groups,
                self.stats.groups_detailed,
                self.stats.groups_skipped,
            )
            if max_groups is not None and processed_groups >= max_groups:
                break
        log.info("Groups refreshed: %s", processed_groups)

        if skip_users:
            log.info("Skipping user refresh (--skip-users)")
            return

        log.info(
            "=== Full refresh of all users%s ===",
            f" (older than {older_than_days}d)" if older_than_days else "",
        )
        processed_users = 0
        last_id = ""
        while True:
            async with session_scope() as session:
                chunk = await repo.all_users(
                    session,
                    after_id=last_id,
                    limit=batch,
                    older_than_days=older_than_days,
                )
            if not chunk:
                break
            last_id = chunk[-1][0]
            names = [name for _uid, name in chunk if name]
            await self.process_users(names, None, force=True)
            processed_users += len(names)
            log.info(
                "refresh users: %s done (%s written, %s skipped)",
                processed_users,
                self.stats.users_written,
                self.stats.users_skipped,
            )
            if max_users is not None and processed_users >= max_users:
                break
        log.info("Users refreshed: %s", processed_users)

    async def run_complete_users(
        self,
        batch: int = 100,
        max_users: int | None = None,
        with_group_details: bool = True,
    ) -> int:
        """Complete registered-but-incomplete users, then their groups.

        For every user with `groups_fetched=False` (including users added by
        the member-search harvest):

          1. `process_user` — fetch the user's profile, write it, write their
             owned groups (`role='owner'`) and joined groups (`role='member'`)
             into `user_groups`, then mark the user scraped.
          2. For each of their owned groups, `process_group` — fetch the
             group's `about.json` and write its details (DB-completeness check
             skips groups already fetched).

        Returns the number of users completed.
        """
        processed = 0
        while True:
            async with session_scope() as session:
                pending = await repo.pending_unscraped_users(session, limit=batch)
            names = [
                name for _uid, name in pending if name and name not in self._seen_users
            ]
            if not names:
                break
            if max_users is not None:
                names = names[: max(0, max_users - processed)]
                if not names:
                    break
            await self.process_users(names, None)

            # For each just-completed user, walk their owned groups' details.
            if with_group_details:
                group_tasks: list[tuple[str, str]] = []
                for user_id, user_name in pending:
                    if user_name not in names:
                        continue
                    async with session_scope() as session:
                        owned = await repo.user_group_ids(session, user_id)
                    group_tasks.extend(owned)
                group_tasks = list(dict.fromkeys(group_tasks))
                for gid, gname in group_tasks:
                    await self.process_group(gid, gname, None)

            processed += len(names)
            if max_users is not None and processed >= max_users:
                break
        log.info("Complete-users pass done: %s users processed", processed)
        return processed

    async def run_missing_owners(
        self, batch: int = 200, max_groups: int | None = None
    ) -> dict[str, int]:
        """Execute 2-tier recovery for groups with missing owners.

        Tier 1: Internal zero-request healing via skool.user_groups WHERE role = 'owner'.
        Tier 2: Targeted about.json fetch for groups still missing owners.
        """
        log.info("=== Missing owners recovery: Tier 1 internal healing ===")
        async with session_scope() as session:
            healed_internal = await repo.heal_missing_owners_internally(session)
        log.info(
            "Tier 1 complete: %d groups healed internally via user_groups",
            healed_internal,
        )

        log.info("=== Missing owners recovery: Tier 2 targeted about.json fetch ===")
        processed_external = 0
        while True:
            async with session_scope() as session:
                pending = await repo.pending_missing_owner_groups(session, limit=batch)
            if not pending:
                break
            pending = [
                item for item in pending if item[0] not in self._seen_detail_groups
            ]
            if not pending:
                break
            if max_groups is not None:
                pending = pending[: max(0, max_groups - processed_external)]
                if not pending:
                    break
            # force=True re-fetches details even though detail_fetched=True
            await self.enrich_groups(pending, None, force=True)
            processed_external += len(pending)
            if max_groups is not None and processed_external >= max_groups:
                break

        if processed_external > 0:
            async with session_scope() as session:
                extra_healed = await repo.heal_missing_owners_internally(session)
                if extra_healed:
                    healed_internal += extra_healed
                    log.info(
                        "Post-enrichment internal healing linked %d additional groups",
                        extra_healed,
                    )

        log.info(
            "Missing owners pipeline finished: %d healed internally, %d re-fetched via network",
            healed_internal,
            processed_external,
        )
        return {
            "healed_internal": healed_internal,
            "processed_external": processed_external,
        }
