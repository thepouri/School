# Analyses for visibility (public/private), categories, language, and discovery path.

from __future__ import annotations

import pandas as pd

from .. import stats as st
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "4. Visibility, categories, and language"


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


@analysis("public_private", "Public vs private groups", group=GROUP)
def public_private(ctx: Context) -> Result | None:
    out = _out("public_private")
    g = ctx.groups
    if "visibility" not in g.columns:
        return None
    counts = st.value_counts_table(g["visibility"], label="visibility")
    if counts.empty:
        return None

    known = g[g["visibility"].isin(["public", "private"])]
    public_share = st.share_of(known["visibility"] == "public") if not known.empty else None
    out.line(
        f"Of the {st.fmt_int(len(known))} groups whose visibility is known, "
        f"**{st.fmt_pct(public_share)}** are public."
    )
    for record in counts.itertuples():
        out.bullet(f"{record.visibility}: {st.fmt_int(record.count)} groups ({st.fmt_pct(record.share)})")
    out.table("Visibility distribution", counts)
    out.chart(
        ctx.charts.bar(
            counts["visibility"].tolist(),
            counts["count"].tolist(),
            name="visibility",
            title="Public vs private groups",
            ylabel="groups",
        )
    )

    if known.empty:
        out.metric("public_share", public_share)
        return out

    summary = st.group_summary(
        known,
        "visibility",
        {
            "is_paid": ["mean"],
            "total_members": ["median", "mean"],
            "price_usd": ["median"],
            "total_posts": ["median"],
            "posts_per_member": ["median"],
        },
        sort_by="count",
    ).rename(columns={"is_paid_mean": "paid_share"})
    out.table("Public vs private comparison", summary)

    public = known[known["visibility"] == "public"]
    private = known[known["visibility"] == "private"]
    for column, label in (("total_members", "Member count"), ("price_usd", "Price"), ("posts_per_member", "Posts per member")):
        if column not in known.columns:
            continue
        test = st.mann_whitney(public[column], private[column])
        if test:
            out.bullet(f"{label} — " + st.mann_whitney_fa(test, "public", "private"))

    if "is_paid" in known.columns and not summary.empty:
        out.chart(
            ctx.charts.bar(
                summary["visibility"].tolist(),
                summary["paid_share"].tolist(),
                name="paid_share_by_visibility",
                title="Paid share: public vs private",
                ylabel="paid share",
                percent=True,
            )
        )
        private_paid = st.share_of(private["is_paid"]) if not private.empty else None
        public_paid = st.share_of(public["is_paid"]) if not public.empty else None
        if private_paid is not None and public_paid is not None:
            out.blank()
            out.line(
                f"Paid share: private groups {st.fmt_pct(private_paid)} vs public {st.fmt_pct(public_paid)}."
            )
            out.metric("private_paid_share", private_paid)
            out.metric("public_paid_share", public_paid)

    out.metric("public_share", public_share)
    out.metric("unknown_visibility", int((g["visibility"] == "unknown").sum()))
    return out


@analysis("category_breakdown", "Category mix", group=GROUP)
def category_breakdown(ctx: Context) -> Result | None:
    out = _out("category_breakdown")
    g = ctx.groups
    if "category_slug" not in g.columns:
        return None
    counts = st.value_counts_table(g["category_slug"], label="category")
    if counts.empty:
        return None

    out.table("Number of groups per category", counts)
    out.chart(
        ctx.charts.barh(
            counts["category"].tolist(),
            counts["count"].tolist(),
            name="category_counts",
            title="Groups per category",
            xlabel="groups",
        )
    )
    top = counts.iloc[0]
    out.line(f"Most populated category: **{top['category']}** with {st.fmt_pct(top['share'])} of all groups.")

    summary = st.group_summary(
        g,
        "category_slug",
        {"total_members": ["sum", "median"], "total_posts": ["median"], "posts_per_member": ["median"]},
        min_count=ctx.min_group,
        sort_by="total_members_sum",
    )
    if not summary.empty:
        out.table("Members and engagement by category", summary)
        out.chart(
            ctx.charts.barh(
                summary["category_slug"].tolist(),
                summary["total_members_sum"].tolist(),
                name="members_by_category",
                title="Total members per category",
                xlabel="members",
                color="#76B7B2",
            )
        )
        out.bullet(
            f"Largest category by total members: **{summary.iloc[0]['category_slug']}**"
        )
        by_engagement = summary.dropna(subset=["posts_per_member_median"]).sort_values(
            "posts_per_member_median", ascending=False
        )
        if not by_engagement.empty:
            out.bullet(
                f"Most engaging category (median posts per member): **{by_engagement.iloc[0]['category_slug']}**"
            )
    out.metric("category_count", int(len(counts)))
    out.metric("largest_category", top["category"])
    return out


@analysis("language_breakdown", "Language distribution", group=GROUP)
def language_breakdown(ctx: Context) -> Result | None:
    out = _out("language_breakdown")
    g = ctx.groups
    if "language" not in g.columns or g["language"].notna().sum() == 0:
        return None
    counts = st.value_counts_table(g["language"], top=15, label="language")
    out.table("Most common languages", counts)
    out.chart(
        ctx.charts.barh(
            counts["language"].tolist(),
            counts["count"].tolist(),
            name="language_counts",
            title="Groups per language (top 15)",
            xlabel="groups",
            color="#B07AA1",
        )
    )
    languages = g["language"].astype("object").str.lower()
    english = languages.isin(["en", "english", "en-us", "en_us"])
    non_english = st.share_of(languages.notna() & ~english)
    out.line(f"Share of non-English groups: **{st.fmt_pct(non_english)}**")

    summary = st.group_summary(
        g,
        "language",
        {"total_members": ["median"], "is_paid": ["mean"], "price_usd": ["median"]},
        min_count=max(ctx.min_group, 5),
        sort_by="count",
        top=15,
    ).rename(columns={"is_paid_mean": "paid_share"})
    if not summary.empty:
        out.table("Language comparison (with minimum group count)", summary)
    out.metric("language_count", int(g["language"].nunique()))
    out.metric("non_english_share", non_english)
    return out


@analysis("category_x_price", "Cross-table of category × price range", group=GROUP)
def category_x_price(ctx: Context) -> Result | None:
    out = _out("category_x_price")
    g = ctx.groups
    if not {"category_slug", "price_tier"} <= set(g.columns):
        return None
    known = g[g["price_known"].fillna(False).astype(bool) & g["category_slug"].notna()]
    if known.empty:
        return None
    keep = known["category_slug"].value_counts()
    keep = keep[keep >= max(ctx.min_group, 5)].index
    known = known[known["category_slug"].isin(keep)]
    if known.empty:
        return None

    matrix = pd.crosstab(known["category_slug"], known["price_tier"])
    matrix = matrix.loc[:, matrix.sum(axis=0) > 0]
    out.table("Number of groups per category and price range", matrix.reset_index())
    shares = pd.crosstab(known["category_slug"], known["price_tier"], normalize="index")
    shares = shares.loc[:, matrix.columns]
    out.chart(
        ctx.charts.heatmap(
            shares,
            name="category_x_price",
            title="Price mix within each category (row shares)",
            fmt="{:.0%}",
            cmap="Blues",
            vmin=0,
            cbar_label="share of category",
        )
    )
    out.chart(
        ctx.charts.stacked_bar(
            [str(v) for v in shares.index],
            {str(col): shares[col].tolist() for col in shares.columns},
            name="category_price_mix",
            title="Price mix per category",
            ylabel="share of groups",
            rotate=30,
            percent=True,
        )
    )
    out.line(
        "Each row shows what share of that category's groups fall in each price range."
    )
    return out


@analysis("discovery_bias", "Data discovery path and sampling bias (text)", group=GROUP)
def discovery_bias(ctx: Context) -> Result | None:
    out = _out("discovery_bias")
    g = ctx.groups
    fields = [
        ("discovered_via", "Discovery path"),
        ("sort_seen", "Sort type when seen"),
        ("price_bucket", "Price filter at discovery"),
        ("membership_model", "Membership model"),
    ]
    used = False
    for column, label in fields:
        if column not in g.columns or g[column].notna().sum() == 0:
            continue
        used = True
        counts = st.value_counts_table(g[column], top=10, label=column)
        out.line(f"**{label}**")
        for record in counts.itertuples():
            value = getattr(record, column)
            out.bullet(f"{value}: {st.fmt_int(record.count)} ({st.fmt_pct(record.share)})")
        out.blank()
    if not used:
        return None

    out.note(
        "These tables are not about the data itself but about the collection method. "
        "If most groups come from one path (e.g. trending), the sample is biased toward "
        "well-known, large groups and medians come out higher than reality."
    )
    if "discovered_via" in g.columns and "total_members" in g.columns:
        summary = st.group_summary(
            g,
            "discovered_via",
            {"total_members": ["median"], "is_paid": ["mean"], "detail_fetched": ["mean"]},
            sort_by="count",
        ).rename(columns={"is_paid_mean": "paid_share", "detail_fetched_mean": "detail_coverage"})
        out.table("Discovery path comparison", summary)
    return out
