"""Loading data and building derived columns (feature engineering).

Two data sources:

1. postgres — `load_from_db()` (same `DATABASE_URL` as the project)
2. CSV — `load_from_csv(dir)` for offline analysis on a snapshot
   previously captured with `--dump-csv`

`prepare()` runs on both and builds the analytical columns:
price bucket, size bucket, normalized monthly price, estimated revenue,
group age, posts-per-member ratio, number of owner social links, and similar.

Important note about price: a missing price has two different meanings — either
the group is free, or its `about.json` has not been fetched yet. These are
separated by the `price_known` column so averages are not misleading.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

log = logging.getLogger("skool.analyze.loader")

# ───────────── buckets ─────────────

PRICE_EDGES = [0.01, 10, 20, 30, 50, 100, 200, 500, 1000, np.inf]
PRICE_LABELS = [
    "$1-9",
    "$10-19",
    "$20-29",
    "$30-49",
    "$50-99",
    "$100-199",
    "$200-499",
    "$500-999",
    "$1000+",
]
PRICE_TIERS = ["Free"] + PRICE_LABELS

SIZE_EDGES = [-1, 10, 50, 100, 500, 1000, 5000, 10000, np.inf]
SIZE_LABELS = [
    "0-10",
    "11-50",
    "51-100",
    "101-500",
    "501-1k",
    "1k-5k",
    "5k-10k",
    "10k+",
]

# billing interval → how many months (for normalizing price)
INTERVAL_MONTHS = {
    "day": 1 / 30.44,
    "daily": 1 / 30.44,
    "week": 1 / 4.345,
    "weekly": 1 / 4.345,
    "month": 1.0,
    "monthly": 1.0,
    "quarter": 3.0,
    "quarterly": 3.0,
    "semiannual": 6.0,
    "year": 12.0,
    "yearly": 12.0,
    "annual": 12.0,
}

SOCIAL_COLUMNS = [
    "link_facebook",
    "link_instagram",
    "link_linkedin",
    "link_twitter",
    "link_website",
    "link_youtube",
]

GROUP_NUMERIC = [
    "price_usd",
    "price_monthly_usd",
    "total_members",
    "total_online_members",
    "total_posts",
    "total_admins",
    "total_rules",
    "num_courses",
    "num_modules",
    "afl_percent",
    "posts_per_member",
    "online_ratio",
    "desc_len",
    "link_count",
    "age_days",
]

USER_NUMERIC = [
    "total_followers",
    "total_following",
    "total_contributions",
    "social_count",
    "owned_groups",
    "owned_members",
    "account_age_days",
]


# ──────────── small helpers ────────────


def series(frame: pd.DataFrame, name: str, default: Any = np.nan) -> pd.Series:
    """Returns the column, or if absent a same-length series filled with the default."""
    if name in frame.columns:
        return frame[name]
    return pd.Series(default, index=frame.index)


def as_float(values: Any) -> pd.Series:
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    if s.dtype == bool:
        return s.astype("float64")
    return pd.to_numeric(s, errors="coerce").astype("float64")


_TRUE = {"true", "t", "1", "yes", "y"}
_FALSE = {"false", "f", "0", "no", "n", ""}


def as_bool(values: Any) -> pd.Series:
    """Three-state boolean (True/False/NA) — robust against CSV and None."""
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    if s.dtype == bool:
        return s.astype("boolean")

    def convert(value: Any) -> Any:
        if value is None or value is pd.NA:
            return pd.NA
        if isinstance(value, float) and math.isnan(value):
            return pd.NA
        if isinstance(value, str):
            text = value.strip().lower()
            if text in _TRUE:
                return True
            if text in _FALSE:
                return pd.NA if text == "" else False
            return pd.NA
        return bool(value)

    return s.map(convert).astype("boolean")


def as_datetime(values: Any) -> pd.Series:
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    try:
        return pd.to_datetime(s, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return pd.to_datetime(pd.Series(pd.NaT, index=s.index), utc=True)


def _text(values: Any) -> pd.Series:
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    return s.astype("object").where(s.notna(), None)


def _link_count(raw: Any) -> float:
    """The links column is a JSON string (list or dictionary)."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return 0.0
    if isinstance(raw, (list, dict)):
        return float(len(raw))
    text = str(raw).strip()
    if not text or text in ("[]", "{}", "null"):
        return 0.0
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return 1.0
    if isinstance(parsed, (list, dict)):
        return float(len(parsed))
    return 1.0 if parsed else 0.0


# ─────────────── data model ───────────────


@dataclass
class Dataset:
    groups: pd.DataFrame
    users: pd.DataFrame
    user_groups: pd.DataFrame
    source: str = "postgres"
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filters: list[str] = field(default_factory=list)

    @property
    def paid(self) -> pd.DataFrame:
        """Only paid groups with a known price."""
        if self.groups.empty or "is_paid" not in self.groups.columns:
            return self.groups.iloc[0:0]
        mask = self.groups["is_paid"].fillna(False).astype(bool)
        return self.groups[mask]

    @property
    def free(self) -> pd.DataFrame:
        if self.groups.empty or "is_paid" not in self.groups.columns:
            return self.groups.iloc[0:0]
        known = self.groups["price_known"].fillna(False).astype(bool)
        paid = self.groups["is_paid"].fillna(False).astype(bool)
        return self.groups[known & ~paid]

    @property
    def detailed(self) -> pd.DataFrame:
        if self.groups.empty or "detail_fetched" not in self.groups.columns:
            return self.groups
        return self.groups[self.groups["detail_fetched"].fillna(False).astype(bool)]

    def info(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "loaded_at": self.loaded_at.isoformat(timespec="seconds"),
            "groups": int(len(self.groups)),
            "users": int(len(self.users)),
            "user_groups": int(len(self.user_groups)),
            "paid_groups": int(len(self.paid)),
            "filters": list(self.filters),
        }


# ──────────────── SQL ─────────────────


def group_sql(schema: str, limit: int | None = None) -> str:
    tail = f" LIMIT {int(limit)}" if limit else ""
    return f"""
        SELECT id, name, display_name,
               left(description, 400) AS description,
               (lp_description IS NOT NULL AND lp_description <> '') AS has_landing_page,
               (cover_url IS NOT NULL) AS has_cover,
               (logo_url IS NOT NULL) AS has_logo,
               price_amount_cents, price_usd, price_currency, price_interval,
               membership_model, privacy, is_public,
               total_members, total_online_members, total_posts,
               total_admins, total_rules, num_courses, num_modules,
               afl_percent, links, owner_id, owner_name,
               category_slug, language, price_bucket, sort_seen,
               discovered_via, detail_fetched,
               created_at, updated_at, scraped_at
        FROM "{schema}".groups
        ORDER BY total_members DESC NULLS LAST{tail}
    """


def user_sql(schema: str, limit: int | None = None) -> str:
    tail = f" LIMIT {int(limit)}" if limit else ""
    columns = ", ".join(SOCIAL_COLUMNS)
    return f"""
        SELECT id, name, first_name, last_name, full_name,
               left(bio, 400) AS bio,
               location, location_source, timezone,
               (avatar_url IS NOT NULL) AS has_avatar,
               {columns},
               last_offline, total_followers, total_following,
               total_contributions,
               groups_fetched, created_at, updated_at, scraped_at
        FROM "{schema}".users
        ORDER BY total_followers DESC NULLS LAST{tail}
    """


def link_sql(schema: str, limit: int | None = None) -> str:
    tail = f" LIMIT {int(limit)}" if limit else ""
    return f'SELECT user_id, group_id FROM "{schema}".user_groups{tail}'


async def load_from_db(limit: int | None = None) -> Dataset:
    """Read the three tables from postgres (lazy imports so the module is importable without SQLAlchemy)."""
    from sqlalchemy import text

    from ..db.db import SCHEMA, dispose_db, session_scope

    frames: dict[str, pd.DataFrame] = {}
    try:
        async with session_scope() as session:
            for key, statement in (
                ("groups", group_sql(SCHEMA, limit)),
                ("users", user_sql(SCHEMA, limit)),
                ("user_groups", link_sql(SCHEMA, None)),
            ):
                result = await session.execute(text(statement))
                columns = list(result.keys())
                rows = result.mappings().all()
                frames[key] = pd.DataFrame([dict(row) for row in rows], columns=columns)
                log.info("%s: %s rows read", key, len(frames[key]))
    finally:
        await dispose_db()

    return prepare(
        Dataset(
            groups=frames.get("groups", pd.DataFrame()),
            users=frames.get("users", pd.DataFrame()),
            user_groups=frames.get("user_groups", pd.DataFrame()),
            source="postgres",
        )
    )


# ──────────────── CSV ─────────────────

CSV_FILES = {"groups": "groups.csv", "users": "users.csv", "user_groups": "user_groups.csv"}
DERIVED_PREFIXES = (
    "is_paid",
    "price_known",
    "price_tier",
    "price_monthly_usd",
    "size_tier",
    "est_mrr_usd",
    "posts_per_member",
    "online_ratio",
    "desc_len",
    "link_count",
    "age_days",
    "created_year",
    "created_month",
    "updated_days_ago",
    "visibility",
    "has_courses",
    "content_units",
    "social_count",
    "has_any_social",
    "owned_groups",
    "owned_members",
    "owned_est_mrr",
    "linked_groups",
    "account_age_days",
    "last_seen_days",
    "one_time_payment",
)


def dump_csv(data: Dataset, out_dir: str | Path) -> list[Path]:
    """Raw snapshot (without derived columns) for later analysis without the database."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for key, filename in CSV_FILES.items():
        frame: pd.DataFrame = getattr(data, key)
        if frame is None:
            continue
        keep = [c for c in frame.columns if c not in DERIVED_PREFIXES]
        path = target / filename
        frame[keep].to_csv(path, index=False)
        written.append(path)
    return written


def load_from_csv(in_dir: str | Path) -> Dataset:
    source = Path(in_dir)
    frames: dict[str, pd.DataFrame] = {}
    for key, filename in CSV_FILES.items():
        path = source / filename
        if path.exists():
            frames[key] = pd.read_csv(path, low_memory=False)
        else:
            log.warning("File %s is missing — table %s treated as empty", path, key)
            frames[key] = pd.DataFrame()
    return prepare(
        Dataset(
            groups=frames["groups"],
            users=frames["users"],
            user_groups=frames["user_groups"],
            source=f"csv:{source}",
        )
    )


def from_frames(
    groups: pd.DataFrame,
    users: pd.DataFrame | None = None,
    user_groups: pd.DataFrame | None = None,
    source: str = "memory",
) -> Dataset:
    """Test/notebook path: build a Dataset from ready-made DataFrames."""
    return prepare(
        Dataset(
            groups=groups.copy(),
            users=(users if users is not None else pd.DataFrame()).copy(),
            user_groups=(user_groups if user_groups is not None else pd.DataFrame()).copy(),
            source=source,
        )
    )


# ─────────── derived columns ───────────


def _price_tier(price: pd.Series, is_paid: pd.Series, free_known: pd.Series) -> pd.Series:
    paid_tier = pd.cut(
        price.where(is_paid),
        bins=PRICE_EDGES,
        labels=PRICE_LABELS,
        right=False,
        ordered=True,
    ).astype("object")
    labels = np.where(is_paid, paid_tier, np.where(free_known, "Free", None))
    return pd.Series(
        pd.Categorical(labels, categories=PRICE_TIERS, ordered=True),
        index=price.index,
    )


def prepare_groups(frame: pd.DataFrame, reference: pd.Timestamp) -> pd.DataFrame:
    if frame.empty:
        return frame
    g = frame.copy()

    for column in (
        "price_usd",
        "price_amount_cents",
        "total_members",
        "total_online_members",
        "total_posts",
        "total_admins",
        "total_rules",
        "num_courses",
        "num_modules",
        "afl_percent",
        "membership_model",
        "privacy",
    ):
        g[column] = as_float(series(g, column))

    for column in ("detail_fetched", "is_public", "has_landing_page", "has_cover", "has_logo"):
        g[column] = as_bool(series(g, column, default=None))

    for column in ("created_at", "updated_at", "scraped_at"):
        g[column] = as_datetime(series(g, column, default=pd.NaT))

    # price
    price = g["price_usd"].where(g["price_usd"].notna(), g["price_amount_cents"] / 100.0)
    g["price_usd"] = price
    g["is_paid"] = (price > 0).fillna(False)
    bucket = _text(series(g, "price_bucket")).astype("object")
    free_bucket = bucket.isin(["free", "free-trial"])
    g["price_known"] = (
        g["is_paid"] | free_bucket | g["detail_fetched"].fillna(False).astype(bool)
    )
    g["price_tier"] = _price_tier(price, g["is_paid"], g["price_known"] & ~g["is_paid"])

    interval = _text(series(g, "price_interval")).map(
        lambda v: str(v).strip().lower() if isinstance(v, str) and v.strip() else None
    )
    g["price_interval"] = interval
    months = interval.map(lambda v: INTERVAL_MONTHS.get(v) if v else None)
    g["price_monthly_usd"] = price / as_float(months)
    g["one_time_payment"] = g["is_paid"] & interval.isna()

    # size and engagement
    members = g["total_members"]
    g["size_tier"] = pd.cut(members, bins=SIZE_EDGES, labels=SIZE_LABELS, right=True, ordered=True)
    g["est_mrr_usd"] = g["price_monthly_usd"] * members
    safe_members = members.where(members > 0)
    g["posts_per_member"] = g["total_posts"] / safe_members
    g["online_ratio"] = g["total_online_members"] / safe_members
    g["content_units"] = g["num_courses"].fillna(0) + g["num_modules"].fillna(0)
    g["has_courses"] = g["num_courses"] > 0

    # text and links
    description = _text(series(g, "description"))
    g["desc_len"] = description.map(lambda v: len(str(v)) if isinstance(v, str) else np.nan)
    g["link_count"] = series(g, "links").map(_link_count)

    # time
    g["age_days"] = (reference - g["created_at"]).dt.total_seconds() / 86400.0
    g["updated_days_ago"] = (reference - g["updated_at"]).dt.total_seconds() / 86400.0
    g["created_year"] = g["created_at"].dt.year.astype("Float64")
    g["created_month"] = g["created_at"].dt.strftime("%Y-%m")

    # visibility
    g["visibility"] = g["is_public"].map({True: "public", False: "private"}).astype("object")
    g["visibility"] = g["visibility"].where(g["visibility"].notna(), "unknown")

    return g


def prepare_users(
    frame: pd.DataFrame,
    groups: pd.DataFrame,
    links: pd.DataFrame,
    reference: pd.Timestamp,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    u = frame.copy()

    for column in ("total_followers", "total_following", "total_contributions"):
        u[column] = as_float(series(u, column))
    for column in ("groups_fetched", "has_avatar"):
        u[column] = as_bool(series(u, column, default=None))
    for column in ("created_at", "updated_at", "scraped_at", "last_offline"):
        u[column] = as_datetime(series(u, column, default=pd.NaT))

    present = [c for c in SOCIAL_COLUMNS if c in u.columns]
    if present:
        filled = u[present].apply(
            lambda col: col.map(lambda v: bool(isinstance(v, str) and v.strip()))
        )
        u["social_count"] = filled.sum(axis=1).astype("float64")
    else:
        u["social_count"] = np.nan
    u["has_any_social"] = u["social_count"] > 0

    u["bio_len"] = _text(series(u, "bio")).map(
        lambda v: len(str(v)) if isinstance(v, str) else np.nan
    )
    u["account_age_days"] = (reference - u["created_at"]).dt.total_seconds() / 86400.0
    u["last_seen_days"] = (reference - u["last_offline"]).dt.total_seconds() / 86400.0

    # ownership portfolio: only from groups.owner_id (not membership)
    if not groups.empty and "owner_id" in groups.columns:
        owned = groups.groupby("owner_id", dropna=True)
        u["owned_groups"] = as_float(u["id"].map(owned.size()))
        u["owned_members"] = as_float(u["id"].map(owned["total_members"].sum(min_count=1)))
        if "est_mrr_usd" in groups.columns:
            u["owned_est_mrr"] = as_float(u["id"].map(owned["est_mrr_usd"].sum(min_count=1)))
    else:
        u["owned_groups"] = np.nan
        u["owned_members"] = np.nan

    if not links.empty and {"user_id", "group_id"} <= set(links.columns):
        u["linked_groups"] = as_float(u["id"].map(links.groupby("user_id").size()))
    else:
        u["linked_groups"] = np.nan

    u["owned_groups"] = u["owned_groups"].fillna(0.0)
    return u


def prepare(data: Dataset) -> Dataset:
    """Builds all analytical columns."""
    reference = pd.Timestamp.now(tz="UTC")
    groups = prepare_groups(data.groups, reference)
    if not groups.empty and "scraped_at" in groups.columns:
        newest = groups["scraped_at"].max()
        if pd.notna(newest):
            reference = max(reference, newest)
    users = prepare_users(data.users, groups, data.user_groups, reference)
    return Dataset(
        groups=groups,
        users=users,
        user_groups=data.user_groups,
        source=data.source,
        loaded_at=data.loaded_at,
        filters=list(data.filters),
    )


# ────────────── filters ──────────────


def apply_filters(
    data: Dataset,
    detailed_only: bool = False,
    paid_only: bool = False,
    public_only: bool = False,
    min_members: int | None = None,
    categories: Sequence[str] | None = None,
    languages: Sequence[str] | None = None,
    since: str | None = None,
) -> Dataset:
    """Filters the groups table (users are left untouched)."""
    groups = data.groups
    notes: list[str] = list(data.filters)
    if groups.empty:
        return data

    if detailed_only and "detail_fetched" in groups.columns:
        groups = groups[groups["detail_fetched"].fillna(False).astype(bool)]
        notes.append("detail_fetched=true")
    if paid_only and "is_paid" in groups.columns:
        groups = groups[groups["is_paid"].fillna(False).astype(bool)]
        notes.append("paid only")
    if public_only and "is_public" in groups.columns:
        groups = groups[groups["is_public"].fillna(False).astype(bool)]
        notes.append("public only")
    if min_members is not None and "total_members" in groups.columns:
        groups = groups[groups["total_members"].fillna(0) >= min_members]
        notes.append(f"members >= {min_members}")
    if categories and "category_slug" in groups.columns:
        wanted = {c.lower() for c in categories}
        groups = groups[groups["category_slug"].astype("object").str.lower().isin(wanted)]
        notes.append(f"categories={sorted(wanted)}")
    if languages and "language" in groups.columns:
        wanted = {c.lower() for c in languages}
        groups = groups[groups["language"].astype("object").str.lower().isin(wanted)]
        notes.append(f"languages={sorted(wanted)}")
    if since and "created_at" in groups.columns:
        moment = pd.to_datetime(since, utc=True, errors="coerce")
        if pd.notna(moment):
            groups = groups[groups["created_at"] >= moment]
            notes.append(f"created_at >= {since}")

    keep_owners = set(groups["owner_id"].dropna()) if "owner_id" in groups.columns else set()
    users = data.users
    if notes and not users.empty and keep_owners and "id" in users.columns:
        users = users[users["id"].isin(keep_owners)]

    links = data.user_groups
    if notes and not links.empty and "group_id" in links.columns:
        links = links[links["group_id"].isin(set(groups["id"]))]

    return Dataset(
        groups=groups,
        users=users,
        user_groups=links,
        source=data.source,
        loaded_at=data.loaded_at,
        filters=notes,
    )
