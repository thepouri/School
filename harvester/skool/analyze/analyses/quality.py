"""Analyses of data coverage and health.

Before drawing any conclusions we need to know how much of the data is
actually filled in and which fields are only filled after `--mode details`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import stats as st
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "1. Data coverage and health"


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


# fields that only come from about.json (i.e. require the details stage)
DETAIL_ONLY = [
    "price_usd",
    "price_interval",
    "total_posts",
    "total_admins",
    "total_rules",
    "num_courses",
    "num_modules",
    "afl_percent",
    "owner_id",
    "is_public",
]

COVERAGE_FIELDS = [
    ("name", "Group slug"),
    ("description", "Description"),
    ("total_members", "Member count"),
    ("total_posts", "Post count"),
    ("price_usd", "Price"),
    ("price_interval", "Billing interval"),
    ("is_public", "public/private"),
    ("owner_id", "Owner"),
    ("category_slug", "Category"),
    ("language", "Language"),
    ("num_courses", "Course count"),
    ("created_at", "Creation date"),
]


@analysis("overview", "Dataset overview", group=GROUP)
def overview(ctx: Context) -> Result:
    out = _out("overview")
    g, u, links = ctx.groups, ctx.users, ctx.links

    detail_share = st.share_of(g["detail_fetched"]) if "detail_fetched" in g else None
    price_share = st.share_of(g["price_known"]) if "price_known" in g else None
    paid_share = st.share_of(ctx.data.groups.loc[g["price_known"], "is_paid"]) if "price_known" in g else None

    out.line(f"Data source: `{ctx.data.source}`")
    out.bullet(f"Groups: **{st.fmt_int(len(g))}** rows")
    out.bullet(f"Users (owners): **{st.fmt_int(len(u))}** rows")
    out.bullet(f"User–group links: **{st.fmt_int(len(links))}** rows")
    out.bullet(f"Details fetched (about.json): **{st.fmt_pct(detail_share)}** of groups")
    out.bullet(f"Price known (free or paid): **{st.fmt_pct(price_share)}**")
    out.bullet(f"Of the groups with a known price, **{st.fmt_pct(paid_share)}** are paid")

    if "created_at" in g.columns and g["created_at"].notna().any():
        out.bullet(
            "Group creation date range: "
            f"{g['created_at'].min():%Y-%m-%d} to {g['created_at'].max():%Y-%m-%d}"
        )
    if "scraped_at" in g.columns and g["scraped_at"].notna().any():
        out.bullet(f"Last database update: {g['scraped_at'].max():%Y-%m-%d %H:%M} UTC")

    rows = []
    for column, label in COVERAGE_FIELDS:
        if column not in g.columns:
            continue
        filled = int(g[column].notna().sum())
        rows.append(
            {
                "field": label,
                "column": column,
                "filled": filled,
                "missing": int(len(g) - filled),
                "fill_share": filled / len(g) if len(g) else np.nan,
            }
        )
    coverage = pd.DataFrame(rows).sort_values("fill_share")
    out.table("Coverage of key group fields", coverage)
    out.chart(
        ctx.charts.barh(
            coverage["column"].tolist(),
            coverage["fill_share"].tolist(),
            name="field_coverage",
            title="Field coverage (share of rows filled)",
            xlabel="share filled",
            percent=True,
        )
    )

    funnel_labels = ["discovered", "detail fetched", "price known", "paid", "owners saved"]
    funnel_values = [
        len(g),
        int(g["detail_fetched"].fillna(False).sum()) if "detail_fetched" in g else 0,
        int(g["price_known"].fillna(False).sum()) if "price_known" in g else 0,
        len(ctx.paid),
        len(u),
    ]
    out.chart(
        ctx.charts.bar(
            funnel_labels,
            funnel_values,
            name="pipeline_funnel",
            title="Scraping funnel",
            ylabel="rows",
            rotate=20,
        )
    )

    out.metric("groups", len(g))
    out.metric("users", len(u))
    out.metric("user_groups", len(links))
    out.metric("detail_coverage", detail_share)
    out.metric("price_coverage", price_share)
    out.metric("paid_share", paid_share)
    return out


@analysis("missingness", "Gaps in the data", group=GROUP)
def missingness(ctx: Context) -> Result:
    out = _out("missingness")

    def table_for(frame: pd.DataFrame, name: str) -> pd.DataFrame:
        rows = []
        for column in frame.columns:
            filled = int(frame[column].notna().sum())
            rows.append(
                {
                    "table": name,
                    "column": column,
                    "filled": filled,
                    "missing_share": 1 - (filled / len(frame)) if len(frame) else np.nan,
                }
            )
        return pd.DataFrame(rows)

    frames = [table_for(ctx.groups, "groups")]
    if len(ctx.users):
        frames.append(table_for(ctx.users, "users"))
    everything = pd.concat(frames, ignore_index=True)
    worst = everything[everything["missing_share"] > 0].sort_values("missing_share", ascending=False)

    if worst.empty:
        out.line("No column is empty — this is very rare, re-check the data.")
        return out

    out.line("Columns left empty (by missing percentage):")
    out.table("Missing share per column", worst.head(30))
    out.chart(
        ctx.charts.barh(
            (worst["table"] + "." + worst["column"]).head(20).tolist(),
            worst["missing_share"].head(20).tolist(),
            name="missing_share",
            title="Most incomplete columns",
            xlabel="missing share",
            percent=True,
        )
    )

    detail_gap = [
        c
        for c in DETAIL_ONLY
        if c in ctx.groups.columns and ctx.groups[c].isna().mean() > 0.2
    ]
    if detail_gap:
        out.blank()
        out.line(
            "These columns are only filled from `about.json`; to fill them "
            "run `python -m skool.main --mode details` more: "
            + ", ".join(f"`{c}`" for c in detail_gap)
        )
    out.metric("columns_with_gaps", int(len(worst)))
    return out


@analysis("integrity", "Data health checklist (text)", group=GROUP)
def integrity(ctx: Context) -> Result:
    """Fully textual analysis — looks for suspicious rows."""
    out = _out("integrity")
    g, u, links = ctx.groups, ctx.users, ctx.links
    total = len(g)
    checks: list[dict] = []

    def add(label: str, mask, frame_len: int | None = None, hint: str = "") -> None:
        try:
            count = int(pd.Series(mask).fillna(False).astype(bool).sum())
        except Exception:  # noqa: BLE001
            return
        base = frame_len if frame_len is not None else total
        checks.append(
            {
                "check": label,
                "rows": count,
                "share": count / base if base else np.nan,
                "note": hint,
            }
        )

    if "id" in g.columns:
        add("Duplicate id", g["id"].duplicated(), hint="should be zero (primary key)")
    if "name" in g.columns:
        add("Duplicate slug", g["name"].duplicated() & g["name"].notna(), hint="slug must be unique")
    if "is_paid" in g.columns and "price_interval" in g.columns:
        add(
            "Paid but no billing interval",
            g["is_paid"] & g["price_interval"].isna(),
            hint="possibly a one-time payment",
        )
    if "price_bucket" in g.columns and "is_paid" in g.columns:
        add(
            "Paid at discovery but no price",
            (g["price_bucket"] == "paid") & ~g["is_paid"],
            hint="either details were not fetched or the price lives elsewhere",
        )
    if {"total_online_members", "total_members"} <= set(g.columns):
        add(
            "Online > total members",
            g["total_online_members"] > g["total_members"],
            hint="inconsistent Skool counters",
        )
    if "total_members" in g.columns:
        add("Zero members", g["total_members"].fillna(-1) == 0, hint="empty/newly created group")
        add("Unknown member count", g["total_members"].isna())
    if {"total_posts", "total_members"} <= set(g.columns):
        add(
            "Over 100 members but zero posts",
            (g["total_members"] > 100) & (g["total_posts"].fillna(0) == 0),
            hint="dead group or content outside the feed",
        )
    if "owner_id" in g.columns:
        add("No owner", g["owner_id"].isna(), hint="owner is not captured at discovery")
    if "is_public" in g.columns:
        add("Unknown public/private", g["is_public"].isna())
    if "created_at" in g.columns:
        add(
            "Creation date in the future",
            g["created_at"] > pd.Timestamp.now(tz="UTC"),
            hint="timestamp parsing issue",
        )
    if "price_usd" in g.columns:
        add(
            "Price over $5000",
            g["price_usd"] > 5000,
            hint="a real outlier or a wrong unit (cents instead of dollars)",
        )
    if len(u) and "id" in u.columns and "owner_id" in g.columns:
        known_owners = set(g["owner_id"].dropna())
        add(
            "Registered user but owns no group",
            ~u["id"].isin(known_owners),
            frame_len=len(u),
            hint="their groups have not been scraped yet",
        )
    if len(links) and "group_id" in links.columns and "id" in g.columns:
        add(
            "User–group link to a group not in the table",
            ~links["group_id"].isin(set(g["id"])),
            frame_len=len(links),
            hint="group later deleted or filtered",
        )

    frame = pd.DataFrame(checks)
    problems = frame[frame["rows"] > 0]
    out.line(f"Checks performed: **{len(frame)}** — with findings: **{len(problems)}**")
    out.blank()
    for record in problems.sort_values("rows", ascending=False).itertuples():
        hint = f" — {record.note}" if record.note else ""
        out.bullet(f"{record.check}: **{st.fmt_int(record.rows)}** rows ({st.fmt_pct(record.share)}){hint}")
    if problems.empty:
        out.bullet("No problems found.")
    out.table("Full checks table", frame)
    out.metric("failed_checks", int(len(problems)))
    return out
