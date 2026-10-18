# Analysis of size, the price-members relationship, engagement, and correlations.

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import stats as st
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "3. Members, engagement, and relationships"

CORR_COLUMNS = [
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
    "age_days",
    "link_count",
]


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


def _interval_label(value) -> str:
    left = getattr(value, "left", None)
    right = getattr(value, "right", None)
    if left is None or right is None:
        return str(value)
    return f"${float(left):,.0f}-{float(right):,.0f}"


@analysis("members_distribution", "Group size distribution and inequality", group=GROUP)
def members_distribution(ctx: Context) -> Result | None:
    out = _out("members_distribution")
    g = ctx.groups
    if "total_members" not in g.columns:
        return None
    members = st.clean(g["total_members"])
    if members.empty:
        return None

    summary = st.describe(g["total_members"])
    out.line(
        f"The median member count is **{st.fmt_int(summary.get('median'))}** but the mean is "
        f"**{st.fmt_int(summary.get('mean'))}** — this gap signals a heavily skewed distribution "
        "(a few giant groups pull the mean up)."
    )
    out.bullet(
        f"First quartile {st.fmt_int(summary.get('p25'))} | Third quartile {st.fmt_int(summary.get('p75'))} | "
        f"95th percentile {st.fmt_int(summary.get('p95'))} | max {st.fmt_int(summary.get('max'))}"
    )
    out.bullet(f"Groups with zero members: {st.fmt_int(summary.get('zeros'))}")
    out.table(
        "Numeric summary of size and content",
        st.describe_table(g, ["total_members", "total_online_members", "total_posts", "num_courses"]),
    )

    if "size_tier" in g.columns:
        tiers = st.ordered_counts_table(g["size_tier"], label="size_tier")
        out.table("Number of groups per size range", tiers)
        out.chart(
            ctx.charts.bar(
                tiers["size_tier"].tolist(),
                tiers["count"].tolist(),
                name="size_tiers",
                title="Groups per member-count range",
                xlabel="members",
                ylabel="groups",
                rotate=20,
            )
        )
    out.chart(
        ctx.charts.hist(
            g["total_members"].tolist(),
            name="members_hist",
            title="Member count distribution (log scale)",
            xlabel="members (log)",
            log_x=True,
            bins=36,
        )
    )

    gini_value = st.gini(members)
    shares = st.top_share(members)
    out.blank()
    out.line("Population concentration:")
    out.bullet(f"Gini of member distribution: **{st.fmt_num(gini_value)}**")
    for key, label in (("top_1pct", "1%"), ("top_5pct", "5%"), ("top_10pct", "10%"), ("top_20pct", "20%")):
        if key in shares:
            out.bullet(f"The largest {label} of groups hold **{st.fmt_pct(shares[key])}** of all members")
    curve = st.lorenz(members)
    if curve is not None:
        out.chart(
            ctx.charts.lorenz(
                curve[0],
                curve[1],
                name="members_lorenz",
                title="Member concentration (Lorenz curve)",
                gini_value=gini_value,
            )
        )

    out.metric("median_members", summary.get("median"))
    out.metric("mean_members", summary.get("mean"))
    out.metric("max_members", summary.get("max"))
    out.metric("gini", gini_value)
    for key, value in shares.items():
        out.metric(key, value)
    return out


@analysis("price_vs_members", "Correlation between price and member count (paid groups)", group=GROUP)
def price_vs_members(ctx: Context) -> Result | None:
    out = _out("price_vs_members")
    paid = ctx.paid
    if paid.empty or not {"price_usd", "total_members"} <= set(paid.columns):
        return None

    corr = st.correlate(paid["price_usd"], paid["total_members"], "Price (USD)", "Member count")
    out.line(corr.summary_fa())
    out.blank()
    out.line(
        "In plain terms: the Spearman number says whether, when we rank groups by price, "
        "their member-count ranks move in the same direction or not. A negative number means "
        "more expensive groups are generally smaller."
    )
    out.chart(
        ctx.charts.scatter(
            paid["price_usd"].tolist(),
            paid["total_members"].tolist(),
            name="price_vs_members",
            title="Price vs members (paid groups, log-log)",
            xlabel="price (USD, log)",
            ylabel="members (log)",
            log_x=True,
            log_y=True,
        )
    )

    frame = paid.dropna(subset=["price_usd", "total_members"]).copy()
    if len(frame) >= 20:
        quantiles = min(10, max(2, len(frame) // 10))
        try:
            frame["price_decile"] = pd.qcut(frame["price_usd"], q=quantiles, duplicates="drop")
        except ValueError:
            frame["price_decile"] = np.nan
        if frame["price_decile"].notna().any():
            deciles = st.group_summary(
                frame,
                "price_decile",
                {"price_usd": ["median"], "total_members": ["median", "mean"], "total_posts": ["median"]},
            )
            deciles["price_range"] = [_interval_label(v) for v in deciles["price_decile"]]
            display = deciles[[c for c in deciles.columns if c != "price_decile"]]
            out.table("Median members per price decile", display)
            out.chart(
                ctx.charts.bar(
                    deciles["price_range"].tolist(),
                    deciles["total_members_median"].tolist(),
                    name="members_by_price_decile",
                    title="Median members per price decile",
                    xlabel="price decile",
                    ylabel="median members",
                    rotate=40,
                )
            )

    if "price_tier" in paid.columns:
        boxes = {
            str(tier): sub["total_members"].tolist()
            for tier, sub in paid.groupby("price_tier", observed=True)
            if len(sub) >= 5 and str(tier) != "Free"
        }
        out.chart(
            ctx.charts.box(
                boxes,
                name="members_by_price_tier",
                title="Members by price range (log scale)",
                ylabel="members (log)",
                log_y=True,
                rotate=30,
            )
        )

    extras = [
        ("total_posts", "Number of posts"),
        ("num_courses", "Number of courses"),
        ("total_admins", "Number of admins"),
        ("age_days", "Group age (days)"),
        ("posts_per_member", "Posts per member"),
    ]
    out.blank()
    out.line("Price vs the remaining variables (paid groups only):")
    rows = []
    for column, label in extras:
        if column not in paid.columns:
            continue
        pair = st.correlate(paid["price_usd"], paid[column], "Price", label)
        if pair.best is None:
            continue
        out.bullet(pair.summary_fa())
        rows.append(
            {
                "variable": label,
                "n": pair.n,
                "spearman": pair.spearman,
                "pearson": pair.pearson,
                "p_value": pair.p_value,
            }
        )
        out.metric(f"price_vs_{column}", pair.spearman)
    out.table("Correlation of price with other variables", pd.DataFrame(rows))

    out.metric("spearman", corr.spearman)
    out.metric("pearson", corr.pearson)
    out.metric("log_pearson", corr.log_pearson)
    out.metric("n", corr.n)
    out.metric("significant", corr.significant)
    return out


@analysis("free_vs_paid", "Free vs paid groups comparison", group=GROUP)
def free_vs_paid(ctx: Context) -> Result | None:
    out = _out("free_vs_paid")
    free, paid = ctx.free, ctx.paid
    if free.empty or paid.empty:
        return None

    out.line(
        f"**{st.fmt_int(len(free))}** free groups vs **{st.fmt_int(len(paid))}** paid groups with a known price."
    )
    out.line(
        "The Mann–Whitney test is used (it does not require a normal distribution). If p is below 0.05, "
        "the difference between the two groups is not random; Cliff's delta shows the size of the difference."
    )
    out.blank()

    metrics = [
        ("total_members", "Member count"),
        ("total_posts", "Number of posts"),
        ("num_courses", "Number of courses"),
        ("total_admins", "Number of admins"),
        ("posts_per_member", "Posts per member"),
        ("online_ratio", "Online ratio"),
        ("age_days", "Group age (days)"),
        ("desc_len", "Description length"),
    ]
    rows: list[dict] = []
    labels: list[str] = []
    free_medians: list[float] = []
    paid_medians: list[float] = []

    for column, label in metrics:
        if column not in free.columns or column not in paid.columns:
            continue
        left = st.clean(free[column])
        right = st.clean(paid[column])
        if left.empty or right.empty:
            continue
        row = {
            "metric": label,
            "free_median": float(left.median()),
            "paid_median": float(right.median()),
            "free_mean": float(left.mean()),
            "paid_mean": float(right.mean()),
        }
        test = st.mann_whitney(left, right)
        if test is not None:
            row["p_value"] = test["p_value"]
            row["cliffs_delta"] = test["cliffs_delta"]
            out.bullet(f"{label} — " + st.mann_whitney_fa(test, "free", "paid"))
            out.metric(f"{column}_p_value", test["p_value"])
            out.metric(f"{column}_cliffs_delta", test["cliffs_delta"])
        rows.append(row)
        if column in {"total_members", "total_posts", "num_courses"}:
            labels.append(label)
            free_medians.append(float(left.median()))
            paid_medians.append(float(right.median()))
        out.metric(f"{column}_free_median", left.median())
        out.metric(f"{column}_paid_median", right.median())

    table = pd.DataFrame(rows)
    if not table.empty:
        out.table("Free vs paid comparison", table)
    if labels:
        out.chart(
            ctx.charts.grouped_bar(
                labels,
                {"Free": free_medians, "Paid": paid_medians},
                name="free_vs_paid_medians",
                title="Free vs paid groups (median values)",
                ylabel="median (log)",
                rotate=15,
                log_y=True,
            )
        )

    if "total_members" in free.columns and "total_members" in paid.columns:
        free_total = st.clean(free["total_members"]).sum()
        paid_total = st.clean(paid["total_members"]).sum()
        total = free_total + paid_total
        if total:
            out.blank()
            out.bullet(
                f"Member share: free {st.fmt_pct(free_total / total)} vs paid {st.fmt_pct(paid_total / total)}"
            )
            out.metric("free_member_share", free_total / total)
            out.metric("paid_member_share", paid_total / total)
    out.metric("free_groups", len(free))
    out.metric("paid_groups", len(paid))
    return out


@analysis("engagement", "Engagement: posts, online, and ratios", group=GROUP)
def engagement(ctx: Context) -> Result | None:
    out = _out("engagement")
    g = ctx.groups
    available = [c for c in ("posts_per_member", "online_ratio", "total_posts") if c in g.columns]
    if not available:
        return None

    out.table(
        "Engagement indicator summary",
        st.describe_table(g, ["posts_per_member", "online_ratio", "total_posts", "total_online_members"]),
    )
    if "posts_per_member" in g.columns:
        ppm = st.describe(g["posts_per_member"])
        out.line(
            f"Median posts per member is **{st.fmt_num(ppm.get('median'))}** — i.e. in the median group, "
            f"there is one post for every {st.fmt_num(1 / ppm['median']) if ppm.get('median') else '?'} members."
        )
        out.metric("median_posts_per_member", ppm.get("median"))
    if "online_ratio" in g.columns:
        ratio = st.describe(g["online_ratio"])
        out.bullet(f"Median online-member ratio: {st.fmt_pct(ratio.get('median'))}")
        out.metric("median_online_ratio", ratio.get("median"))

    if {"total_members", "total_posts"} <= set(g.columns):
        corr = st.correlate(g["total_members"], g["total_posts"], "Member count", "Post count")
        out.blank()
        out.line(corr.summary_fa())
        out.metric("members_posts_spearman", corr.spearman)
        out.chart(
            ctx.charts.scatter(
                g["total_members"].tolist(),
                g["total_posts"].tolist(),
                name="members_vs_posts",
                title="Members vs posts (log-log)",
                xlabel="members (log)",
                ylabel="posts (log)",
                log_x=True,
                log_y=True,
            )
        )

    if "size_tier" in g.columns and "posts_per_member" in g.columns:
        by_size = st.group_summary(
            g,
            "size_tier",
            {"posts_per_member": ["median"], "online_ratio": ["median"], "total_posts": ["median"]},
            min_count=ctx.min_group,
        )
        if not by_size.empty:
            out.table("Engagement by group size", by_size)
            out.chart(
                ctx.charts.bar(
                    [str(v) for v in by_size["size_tier"]],
                    by_size["posts_per_member_median"].tolist(),
                    name="engagement_by_size",
                    title="Median posts per member by group size",
                    xlabel="members",
                    ylabel="posts / member",
                    rotate=20,
                )
            )
            out.line(
                "If this value drops as groups get bigger, larger groups have more passive members."
            )

    if "is_paid" in g.columns and "posts_per_member" in g.columns:
        paid_ppm = st.clean(ctx.paid.get("posts_per_member", pd.Series(dtype=float)))
        free_ppm = st.clean(ctx.free.get("posts_per_member", pd.Series(dtype=float)))
        test = st.mann_whitney(free_ppm, paid_ppm)
        if test is not None:
            out.blank()
            out.bullet("Posts per member — " + st.mann_whitney_fa(test, "free", "paid"))
            out.metric("ppm_free_vs_paid_p", test["p_value"])
    return out


@analysis("numeric_correlations", "Correlation matrix of numeric variables", group=GROUP)
def numeric_correlations(ctx: Context) -> Result | None:
    out = _out("numeric_correlations")
    g = ctx.groups
    columns = [c for c in CORR_COLUMNS if c in g.columns and st.clean(g[c]).size >= 10]
    if len(columns) < 3:
        return None
    matrix = st.correlation_matrix(g, columns)
    if matrix is None or matrix.empty:
        return None

    out.line(
        "Spearman correlation between all numeric variables. A value near +1 means the two variables "
        "rise together, near −1 means inverse, and near zero means no monotonic relationship."
    )
    display = matrix.round(3).reset_index()
    display = display.rename(columns={display.columns[0]: "variable"})
    out.table("Correlation matrix (Spearman)", display)
    out.chart(
        ctx.charts.heatmap(
            matrix,
            name="correlation_matrix",
            title="Spearman correlation matrix",
            vmin=-1.0,
            vmax=1.0,
            cbar_label="rho",
        )
    )

    stacked = matrix.stack(future_stack=True).reset_index()
    stacked.columns = ["left", "right", "rho"]
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for record in stacked.itertuples(index=False):
        left, right, rho = str(record.left), str(record.right), record.rho
        if left == right or pd.isna(rho):
            continue
        key = tuple(sorted((left, right)))
        if key in seen:
            continue
        seen.add(key)
        rows.append({"pair": f"{key[0]} + {key[1]}", "rho": float(rho), "strength": abs(float(rho))})
    if not rows:
        return out
    pairs = pd.DataFrame(rows).sort_values("strength", ascending=False).head(ctx.top)
    out.table("Strongest relationships", pairs.drop(columns=["strength"]))
    out.blank()
    out.line("The five strongest relationships:")
    for record in pairs.head(5).itertuples(index=False):
        out.bullet(f"{record.pair}: rho = {st.fmt_num(record.rho)} ({st.strength_fa(record.rho)})")
    out.metric("columns", len(columns))
    out.metric("pairs", len(rows))
    out.metric("max_abs_rho", pairs["strength"].max())
    return out


@analysis("outliers", "Outliers and suspicious rows (text)", group=GROUP)
def outliers(ctx: Context) -> Result | None:
    out = _out("outliers")
    g = ctx.groups
    show = [
        c
        for c in ("name", "total_members", "price_usd", "price_interval", "total_posts", "category_slug")
        if c in g.columns
    ]
    limit = min(ctx.top, 15)

    if "total_members" in g.columns and show:
        out.table("Largest groups (members)", g.nlargest(limit, "total_members")[show])
    if "price_usd" in g.columns and show:
        pricey = g.dropna(subset=["price_usd"])
        if not pricey.empty:
            out.table("Most expensive groups", pricey.nlargest(limit, "price_usd")[show])

    out.blank()
    out.line("Outlier fence based on the Q3 + 3×IQR rule (extreme outliers):")
    for column, label in (
        ("total_members", "Member count"),
        ("price_usd", "Price"),
        ("total_posts", "Post count"),
        ("posts_per_member", "Posts per member"),
    ):
        if column not in g.columns:
            continue
        values = st.clean(g[column])
        if values.size < 20:
            continue
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        fence = q3 + 3.0 * (q3 - q1)
        extreme = int((values > fence).sum())
        out.bullet(
            f"{label}: fence {st.fmt_num(fence)} — {st.fmt_int(extreme)} groups above it "
            f"({st.fmt_pct(extreme / values.size)} of known values)"
        )
        out.metric(f"{column}_extreme_count", extreme)
        out.metric(f"{column}_fence", fence)

    out.blank()
    out.line("Suspicious rows (worth checking):")
    checks: list[tuple[str, pd.Series]] = []
    if {"is_paid", "total_members"} <= set(g.columns):
        paid_mask = g["is_paid"].fillna(False).astype(bool)
        checks.append(("Paid group with zero members", paid_mask & (g["total_members"].fillna(0) <= 0)))
    if {"total_members", "total_posts"} <= set(g.columns):
        checks.append(
            (
                "Over 100 members but no posts",
                (g["total_members"].fillna(0) > 100) & (g["total_posts"].fillna(0) <= 0),
            )
        )
    if {"total_online_members", "total_members"} <= set(g.columns):
        checks.append(
            (
                "Online count exceeds total members (inconsistent data)",
                g["total_online_members"].fillna(0) > g["total_members"].fillna(0),
            )
        )
    if {"is_paid", "price_interval"} <= set(g.columns):
        paid_mask = g["is_paid"].fillna(False).astype(bool)
        checks.append(("Paid but no billing interval", paid_mask & g["price_interval"].isna()))
    if "owner_id" in g.columns:
        checks.append(("Group with no identified owner", g["owner_id"].isna()))

    for label, mask in checks:
        count = int(mask.fillna(False).sum())
        out.bullet(f"{label}: {st.fmt_int(count)} groups ({st.fmt_pct(st.share_of(mask))})")
        out.metric(label, count)
    return out
