"""Discovery Planner: Recursive Faceting, Saturation Tracking, and Keyword Expansion.

Algorithm:
1. Root query (empty or base categories).
2. For each query, fetch pages until empty or page_cap.
3. If hit_cap (total > returned or last page full):
   Split along facet hierarchy: category -> lang -> price -> type -> sort -> keyword.
4. Saturation tracking:
   If 3 consecutive pages yield 0 new groups -> mark exhausted.
5. Keyword expansion:
   Extract high-frequency tokens/bigrams from group descriptions/names to seed new search terms.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .constants import CATEGORIES, LANGUAGES, PRICES, SORTS, TYPES
from .db.models import DiscoveryQuery, Group

log = logging.getLogger("skool.discovery_planner")

TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,20}")
STOP_WORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "you", "your", "all",
    "are", "about", "how", "what", "who", "which", "will", "can", "community",
    "group", "learn", "free", "club", "hub", "school", "online", "official",
})


def hash_params(params: dict[str, Any]) -> str:
    """Deterministic SHA1 hash of normalized query parameters."""
    normalized = {k: v for k, v in sorted(params.items()) if v is not None}
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class DiscoveryPlanner:
    """Manages resumable query generation, recursive splitting, and keyword harvesting."""

    @staticmethod
    async def seed_root_queries(
        session: AsyncSession,
        categories: Sequence[str] | None = None,
        languages: Sequence[str] | None = None,
        prices: Sequence[str] | None = None,
        sorts: Sequence[str] | None = None,
    ) -> int:
        """Seed initial root discovery queries into skool.discovery_queries."""
        cat_list = list(categories) if categories else list(CATEGORIES.keys())
        lang_list = list(languages) if languages else ["english"]
        price_list = list(prices) if prices else ["none"]
        sort_list = list(sorts) if sorts else ["rank"]

        seeded = 0
        for c in cat_list:
            for lang in lang_list:
                for pr in price_list:
                    for srt in sort_list:
                        params: dict[str, Any] = {}
                        if c and c != "none":
                            params["c"] = c
                        if lang and lang != "none":
                            params["lang"] = lang
                        if pr and pr != "none":
                            params["pr"] = pr
                        if srt and srt != "none":
                            params["srt"] = srt

                        qhash = hash_params(params)
                        stmt = (
                            pg_insert(DiscoveryQuery)
                            .values(
                                query_hash=qhash,
                                params=params,
                                depth=0,
                                status="pending",
                            )
                            .on_conflict_do_nothing()
                        )
                        res = await session.execute(stmt)
                        if res.rowcount:
                            seeded += 1

        log.info("Seeded %d new discovery queries into database", seeded)
        return seeded

    @staticmethod
    async def get_next_query(session: AsyncSession) -> DiscoveryQuery | None:
        """Fetch next pending query to execute."""
        stmt = (
            select(DiscoveryQuery)
            .where(DiscoveryQuery.status == "pending")
            .order_by(DiscoveryQuery.depth.asc(), DiscoveryQuery.id.asc())
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    def should_split(total_hint: int | None, received_count: int, hit_cap: bool, depth: int) -> bool:
        """Determine if a query should be partitioned into child facets."""
        if depth >= 5:  # maximum depth safeguard
            return False
        if hit_cap:
            return True
        if total_hint and total_hint > received_count:
            return True
        return False

    @staticmethod
    def generate_children(params: dict[str, Any], depth: int) -> list[dict[str, Any]]:
        """Split parent query along the facet tree:
        depth 0: category
        depth 1: language
        depth 2: price (free vs paid)
        depth 3: type (open vs private)
        depth 4: sort (rank, members_desc, newest)
        """
        children: list[dict[str, Any]] = []

        # If price is missing, split by price
        if "pr" not in params:
            for pr in ("free", "paid"):
                child = dict(params)
                child["pr"] = pr
                children.append(child)
            return children

        # If type is missing, split by type
        if "ty" not in params:
            for ty in ("open", "private"):
                child = dict(params)
                child["ty"] = ty
                children.append(child)
            return children

        # If sort is default, try different slices
        if params.get("srt") == "rank":
            for srt in ("members_desc", "newest"):
                child = dict(params)
                child["srt"] = srt
                children.append(child)
            return children

        return children

    @staticmethod
    async def record_query_result(
        session: AsyncSession,
        query_id: int,
        pages_done: int,
        new_groups: int,
        seen_groups: int,
        total_hint: int | None,
        hit_cap: bool,
    ) -> None:
        """Update query stats and automatically split if hit_cap is True."""
        query = await session.get(DiscoveryQuery, query_id)
        if not query:
            return

        is_exhausted = (new_groups == 0 and pages_done >= 3)
        needs_split = DiscoveryPlanner.should_split(total_hint, query.seen_groups + seen_groups, hit_cap, query.depth)

        new_status = "exhausted" if is_exhausted else ("split" if needs_split else "done")

        query.pages_done = pages_done
        query.new_groups = query.new_groups + new_groups
        query.seen_groups = query.seen_groups + seen_groups
        query.total_hint = total_hint
        query.hit_cap = hit_cap
        query.status = new_status
        query.updated_at = func.now()

        if needs_split and not is_exhausted:
            children_params = DiscoveryPlanner.generate_children(query.params, query.depth)
            for cp in children_params:
                qhash = hash_params(cp)
                stmt = (
                    pg_insert(DiscoveryQuery)
                    .values(
                        query_hash=qhash,
                        params=cp,
                        depth=query.depth + 1,
                        status="pending",
                    )
                    .on_conflict_do_nothing()
                )
                await session.execute(stmt)

    @staticmethod
    async def harvest_keywords_from_db(
        session: AsyncSession,
        min_freq: int = 5,
        limit: int = 30,
    ) -> list[str]:
        """Extract high-frequency keyword tokens from discovered group names/descriptions."""
        stmt = (
            select(Group.display_name, Group.description)
            .where(Group.display_name.is_not(None))
            .order_by(Group.scraped_at.desc())
            .limit(2000)
        )
        res = await session.execute(stmt)
        rows = res.all()

        counts: dict[str, int] = {}
        for display_name, desc in rows:
            text = f"{display_name or ''} {desc or ''}".lower()
            tokens = TOKEN_RE.findall(text)
            for t in set(tokens):
                if t not in STOP_WORDS and len(t) >= 4:
                    counts[t] = counts.get(t, 0) + 1

        sorted_tokens = [
            token for token, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            if count >= min_freq
        ]
        return sorted_tokens[:limit]
