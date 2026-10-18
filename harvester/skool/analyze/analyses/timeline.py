# Time analyses: cohort growth, activity recency, and the effect of group age.

from __future__ import annotations

import pandas as pd

from .. import stats as st
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "5. Time, growth, and recency"

STALE_STEPS = ((30, "one month"), (90, "three months"), (180, "six months"), (365, "one year"))


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


def _year_label(value) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


@analysis("growth", "Group creation trend over time", group=GROUP)
def growth(ctx: Context) -> Result | None:
    out = _out("growth")
    g = ctx.groups
    if "created_year" not in g.columns or g["created_year"].notna().sum() == 0:
        return None

    per_year = st.group_summary(
        g,
        "created_year",
        {
            "total_members": ["median", "sum"],
            "is_paid": ["mean"],
            "price_usd": ["median"],
            "posts_per_member": ["median"],
        },
        sort_by=None,
    ).rename(columns={"is_paid_mean": "paid_share"})
    if per_year.empty:
        return None
    per_year = per_year.sort_values("created_year")
    per_year["year"] = [_year_label(v) for v in per_year["created_year"]]
    display = per_year[[c for c in per_year.columns if c != "created_year"]]
    out.table("Creation-year cohort", display)

    out.chart(
        ctx.charts.bar(
            per_year["year"].tolist(),
            per_year["count"].tolist(),
            name="groups_per_year",
            title="Groups created per year",
            ylabel="groups",
        )
    )
    if "paid_share" in per_year.columns:
        out.chart(
            ctx.charts.line(
                per_year["year"].tolist(),
                {"paid share": per_year["paid_share"].tolist()},
                name="paid_share_by_year",
                title="Share of paid groups by creation year",
                ylabel="paid share",
            )
        )

    busiest = per_year.loc[per_year["count"].idxmax()]
    out.line(f"Busiest year for group creation: **{busiest['year']}** with {st.fmt_int(busiest['count'])} groups.")
    first_year = per_year.iloc[0]
    last_year = per_year.iloc[-1]
    if "paid_share" in per_year.columns and pd.notna(first_year.get("paid_share")) and pd.notna(last_year.get("paid_share")):
        out.bullet(
            f"Share of paid groups went from {st.fmt_pct(first_year['paid_share'])} in {first_year['year']} to "
            f"{st.fmt_pct(last_year['paid_share'])} in {last_year['year']}."
        )
    out.bullet(
        "Note: older groups have had more time to grow, so higher member medians "
        "in older cohorts are natural."
    )

    if "created_month" in g.columns and g["created_month"].notna().sum() > 5:
        monthly = (
            g.dropna(subset=["created_month"])
            .groupby("created_month", observed=True)
            .size()
            .sort_index()
        )
        if len(monthly) > 2:
            cumulative = monthly.cumsum()
            out.chart(
                ctx.charts.line(
                    [str(v) for v in monthly.index],
                    {"new groups": monthly.tolist(), "cumulative": cumulative.tolist()},
                    name="groups_cumulative",
                    title="New and cumulative groups per month",
                    ylabel="groups",
                    rotate=60,
                    marker="",
                )
            )
            out.table(
                "Last 12 months of group creation",
                monthly.tail(12).reset_index(name="new_groups"),
            )

    out.metric("busiest_year", busiest["year"])
    out.metric("years_covered", int(len(per_year)))
    return out


@analysis("recency", "Activity recency and dead groups", group=GROUP)
def recency(ctx: Context) -> Result | None:
    out = _out("recency")
    g = ctx.groups
    if "updated_days_ago" not in g.columns or g["updated_days_ago"].notna().sum() == 0:
        return None

    days = st.clean(g["updated_days_ago"])
    if days.empty:
        return None
    summary = st.describe(days)
    out.line(
        f"Median days since last update: **{st.fmt_num(summary.get('median'), 1)} days** "
        f"(third quartile {st.fmt_num(summary.get('p75'), 1)} days)."
    )
    for threshold, label in STALE_STEPS:
        share = st.share_of(days > threshold)
        out.bullet(f"Inactive for over {label}: **{st.fmt_pct(share)}** of groups with a date")
        out.metric(f"stale_over_{threshold}d", share)

    buckets = st.bucket(
        g["updated_days_ago"],
        [-1, 7, 30, 90, 180, 365, float("inf")],
        ["0-7d", "8-30d", "31-90d", "91-180d", "181-365d", "1y+"],
        right=True,
    )
    counts = st.ordered_counts_table(buckets, label="recency")
    out.table("Activity recency distribution", counts)
    out.chart(
        ctx.charts.bar(
            counts["recency"].tolist(),
            counts["count"].tolist(),
            name="recency_buckets",
            title="Time since last update",
            ylabel="groups",
        )
    )

    columns = [c for c in ("name", "total_members", "price_usd", "updated_days_ago", "category_slug") if c in g.columns]
    zombies = g[(g["updated_days_ago"] > 180) & (g["total_members"].fillna(0) >= 500)]
    if not zombies.empty and columns:
        out.blank()
        out.line(
            f"**{st.fmt_int(len(zombies))}** groups with at least 500 members have not been updated "
            "for over six months — large population but stagnant."
        )
        out.table("Large but stagnant groups", zombies.nlargest(min(ctx.top, 15), "total_members")[columns])
        out.metric("large_stale_groups", int(len(zombies)))

    out.metric("median_days_since_update", summary.get("median"))
    return out


@analysis("age_effects", "Effect of group age on growth and price", group=GROUP)
def age_effects(ctx: Context) -> Result | None:
    out = _out("age_effects")
    g = ctx.groups
    if "age_days" not in g.columns or g["age_days"].notna().sum() < 10:
        return None

    pairs = [
        ("total_members", "Member count"),
        ("total_posts", "Post count"),
        ("posts_per_member", "Posts per member"),
        ("price_usd", "Price"),
        ("num_courses", "Course count"),
    ]
    rows = []
    for column, label in pairs:
        if column not in g.columns:
            continue
        corr = st.correlate(g["age_days"], g[column], "Group age (days)", label)
        if corr.best is None:
            continue
        out.bullet(corr.summary_fa())
        rows.append({"variable": label, "n": corr.n, "spearman": corr.spearman, "p_value": corr.p_value})
        out.metric(f"age_vs_{column}", corr.spearman)
    if rows:
        out.table("Correlation of group age with other variables", pd.DataFrame(rows))

    out.chart(
        ctx.charts.scatter(
            g["age_days"].tolist(),
            g["total_members"].tolist(),
            name="age_vs_members",
            title="Group age vs members",
            xlabel="age (days)",
            ylabel="members (log)",
            log_y=True,
        )
    )

    growth_frame = g.dropna(subset=["age_days", "total_members"]).copy()
    growth_frame = growth_frame[growth_frame["age_days"] > 30]
    if not growth_frame.empty:
        growth_frame["members_per_month"] = growth_frame["total_members"] / (growth_frame["age_days"] / 30.44)
        speed = st.describe(growth_frame["members_per_month"])
        out.blank()
        out.line(
            f"Median member acquisition speed: **{st.fmt_num(speed.get('median'), 2)} members/month** "
            f"(95th percentile: {st.fmt_num(speed.get('p95'), 1)})."
        )
        columns = [c for c in ("name", "total_members", "age_days", "members_per_month", "price_usd") if c in growth_frame.columns]
        out.table(
            "Fastest-growing groups (member acquisition)",
            growth_frame.nlargest(min(ctx.top, 15), "members_per_month")[columns],
        )
        out.metric("median_members_per_month", speed.get("median"))

        if "is_paid" in growth_frame.columns:
            test = st.mann_whitney(
                growth_frame.loc[~growth_frame["is_paid"].fillna(False).astype(bool), "members_per_month"],
                growth_frame.loc[growth_frame["is_paid"].fillna(False).astype(bool), "members_per_month"],
            )
            if test:
                out.line("Member acquisition speed — " + st.mann_whitney_fa(test, "free", "paid"))
    return out
