# Content analysis: description text, course depth, and market segmentation.

from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from .. import stats as st
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "7. Content, text, and market segmentation"

STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "that", "this", "from", "are", "our", "was",
    "how", "who", "what", "will", "can", "all", "get", "out", "about", "into", "more", "any",
    "but", "not", "have", "has", "had", "they", "their", "them", "his", "her", "its", "one",
    "two", "new", "other", "than", "then", "there", "here", "where", "when", "just", "also",
    "like", "want", "need", "make", "made", "only", "over", "per", "via", "use", "using",
    "join", "group", "groups", "community", "skool", "free", "inside", "every", "day", "days",
    "week", "month", "year", "help", "learn", "best", "good", "great", "start", "started",
    "place", "people", "you’re", "don’t", "let’s", "it’s", "i’m",
}
WORD_RE = re.compile(r"[a-zà-ÿ']{3,}")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]",
    flags=re.UNICODE,
)


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


def _keywords(values: pd.Series, top: int) -> pd.DataFrame:
    counter: Counter[str] = Counter()
    for text in values.dropna().astype("object"):
        for word in WORD_RE.findall(str(text).lower()):
            if word not in STOPWORDS:
                counter[word] += 1
    if not counter:
        return pd.DataFrame()
    rows = [{"keyword": word, "count": count} for word, count in counter.most_common(top)]
    return pd.DataFrame(rows)


@analysis("text_stats", "Group name and description text", group=GROUP)
def text_stats(ctx: Context) -> Result | None:
    out = _out("text_stats")
    g = ctx.groups
    if "desc_len" not in g.columns and "name" not in g.columns:
        return None

    if "desc_len" in g.columns:
        summary = st.describe(g["desc_len"])
        out.line(
            f"Median description length: **{st.fmt_int(summary.get('median'))}** characters "
            f"(empty or zero: {st.fmt_int(summary.get('zeros'))} groups)."
        )
        out.table("Text and links summary", st.describe_table(g, [c for c in ("desc_len", "link_count", "total_rules") if c in g.columns]))
        out.chart(
            ctx.charts.hist(
                g["desc_len"].tolist(),
                name="desc_len_hist",
                title="Description length distribution",
                xlabel="characters",
                bins=30,
                color="#9C755F",
            )
        )
        if "total_members" in g.columns:
            pair = st.correlate(g["desc_len"], g["total_members"], "Description length", "Member count")
            if pair.best is not None:
                out.bullet(pair.summary_fa())
                out.metric("desc_len_vs_members", pair.spearman)
        out.metric("median_desc_len", summary.get("median"))

    presence = []
    for column, label in (("has_landing_page", "Landing page"), ("has_cover", "Cover image"), ("has_logo", "Logo"), ("has_courses", "Courses")):
        if column in g.columns:
            share = st.share_of(g[column])
            presence.append({"asset": label, "share": share})
            out.metric(f"{column}_share", share)
    if presence:
        table = pd.DataFrame(presence)
        out.table("What share of groups have each asset?", table)
        out.chart(
            ctx.charts.barh(
                table["asset"].tolist(),
                table["share"].tolist(),
                name="asset_coverage",
                title="Share of groups with each asset",
                xlabel="share of groups",
                percent=True,
                color="#8CD17D",
            )
        )

    if "name" in g.columns:
        keywords = _keywords(g["name"], ctx.top)
        if not keywords.empty:
            out.blank()
            out.line("Most common words in group names:")
            out.line(", ".join(f"{r.keyword} ({r.count})" for r in keywords.head(15).itertuples()))
            out.table("Most common words in group names", keywords)
            out.chart(
                ctx.charts.barh(
                    keywords["keyword"].head(15).tolist(),
                    keywords["count"].head(15).tolist(),
                    name="name_keywords",
                    title="Most common words in group names",
                    xlabel="occurrences",
                )
            )
        emoji_share = st.share_of(g["name"].dropna().astype("object").apply(lambda v: bool(EMOJI_RE.search(str(v)))))
        out.bullet(f"Groups with an emoji in their name: **{st.fmt_pct(emoji_share)}**")
        out.metric("emoji_name_share", emoji_share)

    if "description" in g.columns:
        keywords = _keywords(g["description"], ctx.top)
        if not keywords.empty:
            out.table("Most common words in descriptions", keywords)
    return out


@analysis("content_depth", "Content depth: courses and modules", group=GROUP)
def content_depth(ctx: Context) -> Result | None:
    out = _out("content_depth")
    g = ctx.groups
    if "num_courses" not in g.columns or g["num_courses"].notna().sum() == 0:
        return None

    has_courses = st.share_of(g["has_courses"]) if "has_courses" in g.columns else None
    out.line(f"Share of groups with at least one course: **{st.fmt_pct(has_courses)}**")
    out.table(
        "Content summary",
        st.describe_table(g, [c for c in ("num_courses", "num_modules", "content_units", "total_admins") if c in g.columns]),
    )
    counts = st.value_counts_table(g["num_courses"].astype("Int64"), top=12, label="num_courses")
    out.table("Distribution of course count", counts)
    out.chart(
        ctx.charts.bar(
            [str(v) for v in counts["num_courses"]],
            counts["count"].tolist(),
            name="courses_counts",
            title="Number of courses per group",
            xlabel="courses",
            ylabel="groups",
        )
    )

    if "num_modules" in g.columns:
        with_courses = g[g["num_courses"].fillna(0) > 0]
        if not with_courses.empty:
            per_course = with_courses["num_modules"] / with_courses["num_courses"]
            out.bullet(f"Median modules per course: {st.fmt_num(per_course.median(), 1)}")

    for column, label in (("price_usd", "Price"), ("total_members", "Member count"), ("posts_per_member", "Posts per member")):
        if column not in g.columns:
            continue
        pair = st.correlate(g["num_courses"], g[column], "Number of courses", label)
        if pair.best is not None:
            out.bullet(pair.summary_fa())
            out.metric(f"courses_vs_{column}", pair.spearman)

    paid = ctx.paid
    if not paid.empty and "has_courses" in paid.columns and "price_usd" in paid.columns:
        mask = paid["has_courses"].fillna(False).astype(bool)
        test = st.mann_whitney(paid.loc[~mask, "price_usd"], paid.loc[mask, "price_usd"])
        if test:
            out.blank()
            out.line("Paid group price — " + st.mann_whitney_fa(test, "no courses", "with courses"))
    if "content_units" in g.columns:
        columns = [c for c in ("name", "num_courses", "num_modules", "total_members", "price_usd") if c in g.columns]
        out.table("Groups with the most content", g.nlargest(min(ctx.top, 15), "content_units")[columns])
    out.metric("has_courses_share", has_courses)
    return out


@analysis("market_segments", "Market segmentation: size × price", group=GROUP)
def market_segments(ctx: Context) -> Result | None:
    out = _out("market_segments")
    g = ctx.groups
    if not {"size_tier", "price_tier"} <= set(g.columns):
        return None
    known = g[g["price_known"].fillna(False).astype(bool) & g["size_tier"].notna()]
    if known.empty:
        return None

    matrix = pd.crosstab(known["size_tier"], known["price_tier"])
    out.table("Number of groups in each size × price cell", matrix.reset_index())
    out.chart(
        ctx.charts.heatmap(
            matrix,
            name="size_x_price",
            title="Groups by size tier and price tier",
            fmt="{:.0f}",
            cmap="YlGnBu",
            vmin=0,
            cbar_label="groups",
        )
    )

    total = float(matrix.to_numpy().sum())
    flat = (
        matrix.stack(future_stack=True)
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    flat.columns = ["size_tier", "price_tier", "count"]
    flat["share"] = flat["count"] / total if total else 0.0
    out.line("Most populated market segments:")
    for record in flat.head(8).itertuples():
        out.bullet(
            f"Size {record.size_tier} and price {record.price_tier}: "
            f"{st.fmt_int(record.count)} groups ({st.fmt_pct(record.share)})"
        )

    quadrants = {}
    big = known["total_members"].fillna(0) >= known["total_members"].median()
    paid_mask = known["is_paid"].fillna(False).astype(bool)
    quadrants["Big and paid (revenue engine)"] = int((big & paid_mask).sum())
    quadrants["Big and free (acquisition funnel)"] = int((big & ~paid_mask).sum())
    quadrants["Small and paid (niche premium)"] = int((~big & paid_mask).sum())
    quadrants["Small and free (newcomers)"] = int((~big & ~paid_mask).sum())
    out.blank()
    out.line("The four market quadrants (size boundary = median members):")
    for label, value in quadrants.items():
        out.bullet(f"{label}: {st.fmt_int(value)} groups ({st.fmt_pct(value / len(known) if len(known) else None)})")
    out.chart(
        ctx.charts.bar(
            ["big+paid", "big+free", "small+paid", "small+free"],
            list(quadrants.values()),
            name="market_quadrants",
            title="Market quadrants (size vs monetization)",
            ylabel="groups",
        )
    )

    if "est_mrr_usd" in known.columns:
        revenue_segment = st.group_summary(
            known[known["is_paid"].fillna(False).astype(bool)],
            "size_tier",
            {"est_mrr_usd": ["sum", "median"], "price_usd": ["median"]},
            sort_by=None,
        )
        if not revenue_segment.empty:
            out.table("Estimated revenue by group size", revenue_segment)
            out.chart(
                ctx.charts.bar(
                    [str(v) for v in revenue_segment["size_tier"]],
                    revenue_segment["est_mrr_usd_sum"].tolist(),
                    name="revenue_by_size",
                    title="Estimated revenue by size tier",
                    ylabel="estimated MRR (USD)",
                    rotate=20,
                )
            )
    out.metric("top_segment", f"{flat.iloc[0]['size_tier']} / {flat.iloc[0]['price_tier']}")
    return out
