# Price analyses: distribution, psychological price points, billing interval, market size.

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import stats as st
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "2. Price and money"


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


@analysis("price_distribution", "Distribution of groups across price ranges", group=GROUP)
def price_distribution(ctx: Context) -> Result | None:
    out = _out("price_distribution")
    g = ctx.groups
    if "price_tier" not in g.columns:
        return None

    known = g[g["price_known"].fillna(False).astype(bool)]
    paid = ctx.paid
    free_share = 1 - (len(paid) / len(known)) if len(known) else None

    out.line(
        f"Of the **{st.fmt_int(len(known))}** groups whose price status is known, "
        f"**{st.fmt_int(len(known) - len(paid))}** are free ({st.fmt_pct(free_share)}) and "
        f"**{st.fmt_int(len(paid))}** are paid."
    )
    unknown = len(g) - len(known)
    if unknown > 0:
        out.line(
            f"Note: **{st.fmt_int(unknown)}** groups have not had their about.json fetched yet "
            "and are excluded from the price calculations "
            "(counting them as zero would falsely inflate the free share)."
        )

    tiers = st.ordered_counts_table(known["price_tier"], label="price_tier")
    out.table("Number of groups per price range (free + paid)", tiers)
    out.chart(
        ctx.charts.bar(
            tiers["price_tier"].tolist(),
            tiers["count"].tolist(),
            name="tier_counts",
            title="Groups per price range",
            xlabel="price range (USD)",
            ylabel="groups",
            rotate=30,
        )
    )
    out.chart(
        ctx.charts.bar(
            tiers["price_tier"].tolist(),
            tiers["share"].tolist(),
            name="tier_share",
            title="Share of groups per price range",
            ylabel="share of groups",
            rotate=30,
            percent=True,
            color="#4E79A7",
        )
    )

    if paid.empty:
        out.note("No paid groups with a known price in the data.")
        out.metric("free_share", free_share)
        return out

    paid_tiers = st.ordered_counts_table(paid["price_tier"], label="price_tier")
    paid_tiers = paid_tiers[paid_tiers["price_tier"] != "Free"].reset_index(drop=True)
    out.table("Paid groups only, per range", paid_tiers)

    summary = st.describe(paid["price_usd"])
    out.blank()
    out.line("Price statistics for paid groups:")
    out.bullet(
        f"Median **{st.fmt_money(summary.get('median'))}** and mean "
        f"**{st.fmt_money(summary.get('mean'))}** (a mean above the median means a heavy right tail)"
    )
    out.bullet(
        f"First quartile {st.fmt_money(summary.get('p25'))} | Third quartile {st.fmt_money(summary.get('p75'))} | "
        f"90th percentile {st.fmt_money(summary.get('p90'))} | 99th percentile {st.fmt_money(summary.get('p99'))}"
    )
    out.bullet(f"Most expensive group: {st.fmt_money(summary.get('max'))}")
    out.table("Numeric price summary", st.describe_table(paid, ["price_usd", "price_monthly_usd"]))

    out.chart(
        ctx.charts.hist(
            paid["price_usd"].tolist(),
            name="paid_price_hist",
            title="Price distribution of paid groups (log scale)",
            xlabel="price (USD, log)",
            log_x=True,
            bins=32,
        )
    )

    top_tier = None
    if not paid_tiers.empty and paid_tiers["count"].max() > 0:
        top_tier = paid_tiers.loc[paid_tiers["count"].idxmax(), "price_tier"]
    out.metric("free_share", free_share)
    out.metric("paid_count", int(len(paid)))
    out.metric("median_paid_price", summary.get("median"))
    out.metric("mean_paid_price", summary.get("mean"))
    out.metric("p90_paid_price", summary.get("p90"))
    out.metric("top_tier", top_tier)
    return out


@analysis("price_points", "Price points and psychological pricing", group=GROUP)
def price_points(ctx: Context) -> Result | None:
    out = _out("price_points")
    paid = ctx.paid
    if paid.empty or "price_usd" not in paid.columns:
        return None

    prices = st.clean(paid["price_usd"], positive=True)
    if prices.empty:
        return None

    counts = st.value_counts_table(prices.round(2), top=20, label="price_usd")
    out.line(
        f"Number of unique prices: **{st.fmt_int(prices.nunique())}** across "
        f"{st.fmt_int(len(prices))} paid groups."
    )
    out.line(
        f"Most popular price: **{st.fmt_money(counts.iloc[0]['price_usd'])}** in "
        f"{st.fmt_int(counts.iloc[0]['count'])} groups ({st.fmt_pct(counts.iloc[0]['share'])} of paid)."
    )
    out.line(
        f"The top 5 prices together cover **{st.fmt_pct(counts['share'].head(5).sum())}** of the market."
    )
    out.table("Most frequent price points", counts)
    out.chart(
        ctx.charts.bar(
            [f"${v:,.0f}" for v in counts["price_usd"].head(15)],
            counts["count"].head(15).tolist(),
            name="popular_price_points",
            title="Most common price points",
            ylabel="groups",
            rotate=35,
        )
    )

    cents = (prices * 100).round().astype("int64")
    dollars = cents // 100
    ends_99 = st.share_of(cents % 100 == 99)
    whole = st.share_of(cents % 100 == 0)
    round_ten = st.share_of(cents % 1000 == 0)
    last_digit = dollars % 10
    digits = st.value_counts_table(last_digit, label="last_digit").sort_values("last_digit")

    out.blank()
    out.line("Pricing pattern:")
    out.bullet(f"Prices ending in .99: **{st.fmt_pct(ends_99)}**")
    out.bullet(f"Round dollar prices (no cents): **{st.fmt_pct(whole)}**")
    out.bullet(f"Multiples of $10 (e.g. 10, 20, 50): **{st.fmt_pct(round_ten)}**")
    for digit in (7, 9):
        share = st.share_of(last_digit == digit)
        out.bullet(f"Last dollar digit = {digit}: **{st.fmt_pct(share)}**")
    out.table("Distribution of price last digit", digits)
    out.chart(
        ctx.charts.bar(
            digits["last_digit"].tolist(),
            digits["share"].tolist(),
            name="last_digit",
            title="Last digit of price (charm pricing)",
            xlabel="last digit of dollar amount",
            ylabel="share of paid groups",
            percent=True,
        )
    )

    out.metric("unique_prices", int(prices.nunique()))
    out.metric("modal_price", float(counts.iloc[0]["price_usd"]))
    out.metric("charm_99_share", ends_99)
    out.metric("round_ten_share", round_ten)
    return out


@analysis("price_by_interval", "Billing interval (monthly / yearly / one-time)", group=GROUP)
def price_by_interval(ctx: Context) -> Result | None:
    out = _out("price_by_interval")
    paid = ctx.paid
    if paid.empty or "price_interval" not in paid.columns:
        return None

    frame = paid.copy()
    frame["interval_label"] = frame["price_interval"].fillna("one-time / unknown")
    counts = st.value_counts_table(frame["interval_label"], label="interval")
    out.table("Number of groups by billing interval", counts)
    for record in counts.itertuples():
        out.bullet(
            f"{record.interval}: {st.fmt_int(record.count)} groups ({st.fmt_pct(record.share)} of paid)"
        )

    summary = st.group_summary(
        frame,
        "interval_label",
        {
            "price_usd": ["median", "mean", "max"],
            "price_monthly_usd": ["median"],
            "total_members": ["median"],
        },
        sort_by="count",
    )
    out.table("Billing interval comparison", summary)
    out.blank()
    out.line(
        "The price_monthly_usd column normalizes the price to a monthly basis (yearly divided by 12, "
        "weekly multiplied by 4.3) so comparisons are meaningful."
    )

    groups_for_box = {
        str(label): sub["price_usd"].tolist()
        for label, sub in frame.groupby("interval_label", observed=True)
        if len(sub) >= 3
    }
    out.chart(
        ctx.charts.box(
            groups_for_box,
            name="price_by_interval",
            title="Price by billing interval (log scale)",
            ylabel="price (USD, log)",
            log_y=True,
            rotate=15,
        )
    )

    monthly = frame.loc[frame["price_interval"] == "month", "price_monthly_usd"]
    yearly = frame.loc[
        frame["price_interval"].isin(["year", "annual", "yearly"]), "price_monthly_usd"
    ]
    test = st.mann_whitney(monthly, yearly)
    if test:
        out.blank()
        out.line(
            "Equivalent monthly price comparison between monthly and yearly plans: "
            + st.mann_whitney_fa(test, "monthly plan", "yearly plan")
        )
        if test["median1"] and test["median2"] < test["median1"]:
            saving = 1 - (test["median2"] / test["median1"])
            out.bullet(f"So the yearly plan is about **{st.fmt_pct(saving)}** cheaper.")
        out.metric("monthly_vs_yearly_p", test["p_value"])

    if "one_time_payment" in paid.columns:
        out.metric("one_time_share", st.share_of(paid["one_time_payment"]))
    out.metric("interval_variants", int(len(counts)))
    return out


@analysis("price_by_category", "Price by category", group=GROUP)
def price_by_category(ctx: Context) -> Result | None:
    out = _out("price_by_category")
    g = ctx.groups
    if "category_slug" not in g.columns:
        return None
    known = g[g["price_known"].fillna(False).astype(bool)]
    if known.empty:
        return None

    summary = st.group_summary(
        known,
        "category_slug",
        {
            "is_paid": ["mean"],
            "price_usd": ["median", "mean", "max"],
            "total_members": ["median"],
            "est_mrr_usd": ["sum"],
        },
        min_count=ctx.min_group,
        sort_by="count",
    )
    if summary.empty:
        return None
    summary = summary.rename(columns={"is_paid_mean": "paid_share"})
    out.line("Only groups with a known price status are counted in this table.")
    out.table("Categories from a price perspective", summary)

    by_share = summary.sort_values("paid_share", ascending=False)
    out.chart(
        ctx.charts.barh(
            by_share["category_slug"].tolist(),
            by_share["paid_share"].tolist(),
            name="paid_share_by_category",
            title="Share of paid groups by category",
            xlabel="paid share",
            percent=True,
        )
    )
    by_price = summary.dropna(subset=["price_usd_median"]).sort_values(
        "price_usd_median", ascending=False
    )
    out.chart(
        ctx.charts.barh(
            by_price["category_slug"].tolist(),
            by_price["price_usd_median"].tolist(),
            name="median_price_by_category",
            title="Median price by category (paid groups)",
            xlabel="median price (USD)",
            color="#59A14F",
        )
    )

    if not by_share.empty:
        top = by_share.iloc[0]
        bottom = by_share.iloc[-1]
        out.bullet(
            f"Most paid category: **{top['category_slug']}** with {st.fmt_pct(top['paid_share'])} paid groups"
        )
        out.bullet(
            f"Most free category: **{bottom['category_slug']}** with {st.fmt_pct(bottom['paid_share'])}"
        )
    if not by_price.empty:
        out.bullet(
            f"Most expensive category (median price): **{by_price.iloc[0]['category_slug']}** — "
            f"{st.fmt_money(by_price.iloc[0]['price_usd_median'])}"
        )
        out.metric("most_expensive_category", by_price.iloc[0]["category_slug"])
    return out


@analysis("currency_mix", "Currency mix (text)", group=GROUP)
def currency_mix(ctx: Context) -> Result | None:
    out = _out("currency_mix")
    paid = ctx.paid
    if paid.empty or "price_currency" not in paid.columns:
        return None
    currencies = paid["price_currency"].astype("object").str.upper()
    counts = st.value_counts_table(currencies, label="currency")
    if counts.empty:
        return None
    out.line("Currency distribution of paid groups:")
    for record in counts.itertuples():
        out.bullet(f"{record.currency}: {st.fmt_int(record.count)} groups ({st.fmt_pct(record.share)})")
    non_usd = st.share_of(currencies.notna() & (currencies != "USD"))
    out.blank()
    out.line(
        f"Non-USD share: **{st.fmt_pct(non_usd)}** — "
        "if this number is significant, raw price comparisons are flawed because no exchange rate has been applied."
    )
    out.table("Currency table", counts)
    out.metric("non_usd_share", non_usd)
    return out


@analysis("affiliate", "Affiliate commission (affiliate)", group=GROUP)
def affiliate(ctx: Context) -> Result | None:
    out = _out("affiliate")
    g = ctx.groups
    if "afl_percent" not in g.columns or g["afl_percent"].notna().sum() == 0:
        return None

    values = st.clean(g["afl_percent"])
    active = values[values > 0]
    share_active = len(active) / len(values) if len(values) else None
    out.line(
        f"Of the {st.fmt_int(len(values))} groups with this field, **{st.fmt_int(len(active))}** "
        f"({st.fmt_pct(share_active)}) have an active affiliate commission."
    )
    if not active.empty:
        out.bullet(
            f"Median commission: **{st.fmt_num(active.median())}%** "
            f"(lowest {st.fmt_num(active.min())}%, highest {st.fmt_num(active.max())}%)"
        )
        counts = st.value_counts_table(active.round(0), top=12, label="afl_percent")
        out.table("Most frequent commission percentages", counts)
        out.chart(
            ctx.charts.bar(
                [f"{float(v):.0f}%" for v in counts["afl_percent"]],
                counts["count"].tolist(),
                name="affiliate_percent",
                title="Affiliate commission rates",
                ylabel="groups",
            )
        )

    paid = ctx.paid
    if not paid.empty and "price_usd" in paid.columns:
        corr = st.correlate(paid["afl_percent"], paid["price_usd"], "Affiliate commission", "Price")
        out.blank()
        out.line(corr.summary_fa())
        out.metric("affiliate_price_spearman", corr.spearman)

    out.metric("affiliate_active_share", share_active)
    return out


@analysis("market_size", "Market size estimate and revenue concentration", group=GROUP)
def market_size(ctx: Context) -> Result | None:
    out = _out("market_size")
    paid = ctx.paid
    if paid.empty or "est_mrr_usd" not in paid.columns:
        return None
    revenue = paid.dropna(subset=["est_mrr_usd"])
    if revenue.empty:
        return None

    total = float(revenue["est_mrr_usd"].sum())
    out.note(
        "These numbers are very rough estimates: we assume all members of a paid group are active "
        "customers, which is not true in reality (trials, churn, discounts, free members). "
        "They are only good for relative comparison."
    )
    out.line(
        f"Total estimated monthly revenue across {st.fmt_int(len(revenue))} groups: **{st.fmt_money(total, 0)}**"
    )
    out.bullet(
        f"Median monthly revenue of a paid group: **{st.fmt_money(revenue['est_mrr_usd'].median(), 0)}**"
    )
    out.bullet(f"Mean: {st.fmt_money(revenue['est_mrr_usd'].mean(), 0)}")

    shares = st.top_share(revenue["est_mrr_usd"])
    gini_value = st.gini(revenue["est_mrr_usd"])
    concentration = st.hhi(revenue["est_mrr_usd"])
    for key, label in (("top_1pct", "1%"), ("top_5pct", "5%"), ("top_10pct", "10%"), ("top_20pct", "20%")):
        if key in shares:
            out.bullet(f"Share of total estimated revenue held by the top {label} of groups: **{st.fmt_pct(shares[key])}**")
    out.bullet(
        f"Revenue Gini: **{st.fmt_num(gini_value)}** "
        "(the closer to 1, the more the market is held by a few groups)"
    )
    out.bullet(f"HHI concentration index: {st.fmt_num(concentration)}")

    columns = [
        c
        for c in ("name", "price_usd", "price_interval", "total_members", "est_mrr_usd", "category_slug")
        if c in revenue.columns
    ]
    top = revenue.nlargest(min(ctx.top, len(revenue)), "est_mrr_usd")[columns]
    out.table("Top-earning groups (estimated)", top)
    if "name" in top.columns:
        out.chart(
            ctx.charts.barh(
                top["name"].head(15).tolist(),
                top["est_mrr_usd"].head(15).tolist(),
                name="top_est_mrr",
                title="Top groups by estimated monthly revenue",
                xlabel="estimated MRR (USD)",
                color="#E15759",
            )
        )
    curve = st.lorenz(revenue["est_mrr_usd"])
    if curve is not None:
        out.chart(
            ctx.charts.lorenz(
                curve[0],
                curve[1],
                name="revenue_lorenz",
                title="Revenue concentration (Lorenz curve)",
                xlabel="cumulative share of paid groups",
                ylabel="cumulative share of estimated revenue",
                gini_value=gini_value,
            )
        )

    out.metric("total_est_mrr", total)
    out.metric("median_est_mrr", float(revenue["est_mrr_usd"].median()))
    out.metric("revenue_gini", gini_value)
    for key, value in shares.items():
        out.metric(f"revenue_{key}", value)
    return out
