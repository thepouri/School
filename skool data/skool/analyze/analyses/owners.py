# Group owner analyses: portfolio, social links, geography, and influence.

from __future__ import annotations

import pandas as pd

from .. import stats as st
from ..loader import SOCIAL_COLUMNS
from ..registry import REGISTRY, Context, Result, analysis

GROUP = "6. Owners and social links"

PLATFORM_LABELS = {
    "link_youtube": "YouTube",
    "link_instagram": "Instagram",
    "link_twitter": "X / Twitter",
    "link_linkedin": "LinkedIn",
    "link_facebook": "Facebook",
    "link_website": "Website",
}


def _out(key: str) -> Result:
    spec = REGISTRY[key]
    return Result(key=spec.key, title=spec.title, group=spec.group)


def _owner_columns(frame: pd.DataFrame) -> list[str]:
    preferred = (
        "name",
        "full_name",
        "owned_groups",
        "owned_members",
        "owned_est_mrr",
        "total_followers",
        "social_count",
        "timezone",
    )
    return [c for c in preferred if c in frame.columns]


@analysis("owner_portfolio", "Owner portfolios (multi-group ownership)", group=GROUP, needs=("users",))
def owner_portfolio(ctx: Context) -> Result | None:
    out = _out("owner_portfolio")
    users = ctx.users
    if "owned_groups" not in users.columns:
        return None
    owners = users[users["owned_groups"].fillna(0) > 0]
    if owners.empty:
        out.note("No user in the users table was identified as a group owner.")
        return out

    counts = st.value_counts_table(owners["owned_groups"].astype("Int64"), label="owned_groups")
    multi_share = st.share_of(owners["owned_groups"] > 1)
    out.line(
        f"Of the {st.fmt_int(len(owners))} identified owners, **{st.fmt_pct(multi_share)}** own more than one group."
    )
    out.bullet(f"Median groups per owner: {st.fmt_num(owners['owned_groups'].median(), 1)}")
    out.bullet(f"Most groups owned by a single owner: {st.fmt_int(owners['owned_groups'].max())}")
    out.table("How many groups does each owner have?", counts)
    out.chart(
        ctx.charts.bar(
            [str(v) for v in counts["owned_groups"]],
            counts["count"].tolist(),
            name="groups_per_owner",
            title="Groups owned per owner",
            xlabel="groups owned",
            ylabel="owners",
        )
    )

    columns = _owner_columns(owners)
    out.table(
        "Owners with the most groups",
        owners.nlargest(min(ctx.top, 15), "owned_groups")[columns],
    )
    if "owned_members" in owners.columns:
        out.table(
            "Owners with the most members under control",
            owners.nlargest(min(ctx.top, 15), "owned_members")[columns],
        )
        gini_value = st.gini(owners["owned_members"])
        shares = st.top_share(owners["owned_members"])
        out.blank()
        out.line(
            f"Gini of member distribution across owners: **{st.fmt_num(gini_value)}** — "
            f"the top 10% of owners control {st.fmt_pct(shares.get('top_10pct'))} of all members."
        )
        out.metric("owner_members_gini", gini_value)
        pair = st.correlate(owners["owned_groups"], owners["owned_members"], "Number of groups", "Total members")
        if pair.best is not None:
            out.line(pair.summary_fa())

        multi = owners[owners["owned_groups"] > 1]
        single = owners[owners["owned_groups"] == 1]
        test = st.mann_whitney(single["owned_members"], multi["owned_members"])
        if test:
            out.line("Members under control — " + st.mann_whitney_fa(test, "single-group owner", "multi-group owner"))

    out.metric("owner_count", int(len(owners)))
    out.metric("multi_group_share", multi_share)
    out.metric("max_groups_per_owner", float(owners["owned_groups"].max()))
    return out


@analysis("owner_socials", "Owners' presence on social platforms", group=GROUP, needs=("users",))
def owner_socials(ctx: Context) -> Result | None:
    out = _out("owner_socials")
    users = ctx.users
    available = [c for c in SOCIAL_COLUMNS if c in users.columns]
    if not available:
        return None

    rows = []
    for column in available:
        share = st.share_of(users[column].notna() & (users[column].astype("object") != ""))
        rows.append({"platform": PLATFORM_LABELS.get(column, column), "share": share, "count": int(users[column].notna().sum())})
    table = pd.DataFrame(rows).sort_values("count", ascending=False)
    out.table("Coverage per platform", table)
    out.chart(
        ctx.charts.barh(
            table["platform"].tolist(),
            table["share"].tolist(),
            name="social_coverage",
            title="Owners with each social link",
            xlabel="share of users",
            percent=True,
            color="#F28E2B",
        )
    )
    top_platform = table.iloc[0]
    out.line(
        f"Most used platform: **{top_platform['platform']}** ({st.fmt_pct(top_platform['share'])} of users)."
    )

    if "social_count" in users.columns:
        counts = st.value_counts_table(users["social_count"].astype("Int64"), label="social_count")
        out.table("Number of social links per user", counts)
        none_share = st.share_of(users["social_count"].fillna(0) == 0)
        out.bullet(f"No social links at all: **{st.fmt_pct(none_share)}**")
        out.bullet(f"Mean number of links: {st.fmt_num(users['social_count'].mean(), 2)}")
        out.metric("no_social_share", none_share)
        out.metric("mean_social_count", float(users["social_count"].mean()))

        for column, label in (("total_followers", "Followers"), ("owned_members", "Total members"), ("owned_groups", "Number of groups")):
            if column not in users.columns:
                continue
            pair = st.correlate(users["social_count"], users[column], "Number of social links", label)
            if pair.best is not None:
                out.line(pair.summary_fa())
                out.metric(f"social_vs_{column}", pair.spearman)

        if "owned_members" in users.columns:
            with_social = users.loc[users["social_count"].fillna(0) > 0, "owned_members"]
            without = users.loc[users["social_count"].fillna(0) == 0, "owned_members"]
            test = st.mann_whitney(without, with_social)
            if test:
                out.blank()
                out.line(
                    "Members under control — "
                    + st.mann_whitney_fa(test, "no social links", "with social links")
                )
    return out


@analysis("owner_geography", "Owner geography and timezone (text)", group=GROUP, needs=("users",))
def owner_geography(ctx: Context) -> Result | None:
    out = _out("owner_geography")
    users = ctx.users
    used = False

    if "timezone" in users.columns and users["timezone"].notna().sum() > 0:
        used = True
        counts = st.value_counts_table(users["timezone"], top=15, label="timezone")
        out.line("**Most common timezones**")
        for record in counts.itertuples():
            out.bullet(f"{record.timezone}: {st.fmt_int(record.count)} ({st.fmt_pct(record.share)})")
        out.table("Timezone table", counts)
        regions = users["timezone"].astype("object").str.split("/").str[0]
        region_counts = st.value_counts_table(regions, top=10, label="region")
        out.chart(
            ctx.charts.barh(
                region_counts["region"].tolist(),
                region_counts["count"].tolist(),
                name="owner_regions",
                title="Owners per timezone region",
                xlabel="users",
                color="#4E79A7",
            )
        )
        out.metric("timezone_coverage", st.share_of(users["timezone"].notna()))

    if "location" in users.columns and users["location"].notna().sum() > 0:
        used = True
        counts = st.value_counts_table(users["location"], top=15, label="location")
        out.blank()
        out.line("**Most common recorded locations**")
        for record in counts.itertuples():
            out.bullet(f"{record.location}: {st.fmt_int(record.count)}")
        out.metric("location_coverage", st.share_of(users["location"].notna()))

    if "location_source" in users.columns and users["location_source"].notna().sum() > 0:
        used = True
        counts = st.value_counts_table(users["location_source"], label="location_source")
        out.blank()
        out.line("Location field source:")
        for record in counts.itertuples():
            out.bullet(f"{record.location_source}: {st.fmt_int(record.count)} ({st.fmt_pct(record.share)})")

    if not used:
        return None
    out.note(
        "Timezone is usually more reliable than the location field, because users write the location "
        "themselves and it is sometimes empty or a joke."
    )
    return out


@analysis("owner_influence", "Owner influence: followers vs group success", group=GROUP, needs=("users",))
def owner_influence(ctx: Context) -> Result | None:
    out = _out("owner_influence")
    users = ctx.users
    if "total_followers" not in users.columns or users["total_followers"].notna().sum() < 5:
        return None

    out.table(
        "Numeric user summary",
        st.describe_table(
            users,
            [c for c in ("total_followers", "total_following", "total_posts", "total_contributions", "owned_members", "bio_len") if c in users.columns],
        ),
    )
    followers = st.clean(users["total_followers"])
    gini_value = st.gini(followers)
    out.line(
        f"Median followers: **{st.fmt_int(followers.median())}**, mean: {st.fmt_int(followers.mean())}, "
        f"Gini: **{st.fmt_num(gini_value)}**"
    )
    out.chart(
        ctx.charts.hist(
            users["total_followers"].tolist(),
            name="followers_hist",
            title="Owner follower distribution (log scale)",
            xlabel="followers (log)",
            log_x=True,
            color="#59A14F",
        )
    )

    for column, label in (("owned_members", "Total members of owned groups"), ("owned_groups", "Number of groups"), ("owned_est_mrr", "Estimated revenue")):
        if column not in users.columns:
            continue
        pair = st.correlate(users["total_followers"], users[column], "Followers", label)
        if pair.best is None:
            continue
        out.bullet(pair.summary_fa())
        out.metric(f"followers_vs_{column}", pair.spearman)
        if column == "owned_members":
            out.chart(
                ctx.charts.scatter(
                    users["total_followers"].tolist(),
                    users[column].tolist(),
                    name="followers_vs_members",
                    title="Owner followers vs total members owned (log-log)",
                    xlabel="followers (log)",
                    ylabel="members owned (log)",
                    log_x=True,
                    log_y=True,
                )
            )

    columns = _owner_columns(users)
    out.table(
        "Users with the most followers",
        users.nlargest(min(ctx.top, 15), "total_followers")[columns],
    )
    if "total_following" in users.columns:
        ratio = users["total_followers"] / users["total_following"].replace(0, pd.NA)
        out.blank()
        out.line(
            f"Median followers-to-following ratio: **{st.fmt_num(ratio.median(), 1)}** "
            "(a high number means owners are typically in celebrity mode, not two-way networking)."
        )
    if "last_seen_days" in users.columns and users["last_seen_days"].notna().sum() > 0:
        out.bullet(
            f"Median days since last online: {st.fmt_num(users['last_seen_days'].median(), 1)} days"
        )
    out.metric("median_followers", float(followers.median()))
    out.metric("followers_gini", gini_value)
    return out
