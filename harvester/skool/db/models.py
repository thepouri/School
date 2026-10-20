"""Database models (the `skool` schema).

Two kinds of fields with different update behavior:

1. Content fields (name, member count, price…) → the latest value wins each time.
2. Parametric fields (category, language, price_bucket, sort_seen)
   → record which slice found the group; filled only if NULL.

The plans table was removed: Skool no longer returns public data for
`plans.json`, and all price information comes from the group's own metadata
(`displayPrice` or `currentMBp`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    lp_description: Mapped[str | None] = mapped_column(Text)

    color: Mapped[str | None] = mapped_column(String(16))
    initials: Mapped[str | None] = mapped_column(String(16))
    cover_url: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
    logo_big_url: Mapped[str | None] = mapped_column(Text)
    favicon_url: Mapped[str | None] = mapped_column(Text)

    # price: discovery → displayPrice, about.json → currentMBp
    price_amount_cents: Mapped[int | None] = mapped_column(Integer)
    price_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_currency: Mapped[str | None] = mapped_column(String(8))
    price_interval: Mapped[str | None] = mapped_column(String(24))

    # numeric in JSON (membership / membershipModel and privacy)
    membership_model: Mapped[int | None] = mapped_column(Integer)
    privacy: Mapped[int | None] = mapped_column(Integer)
    # readable meaning of privacy: 1 → True (public), 2 and above → False (private)
    # if absent from JSON, stays NULL (i.e. unknown)
    is_public: Mapped[bool | None] = mapped_column(Boolean, index=True)

    total_members: Mapped[int | None] = mapped_column(Integer)
    total_online_members: Mapped[int | None] = mapped_column(Integer)
    total_posts: Mapped[int | None] = mapped_column(Integer)
    total_admins: Mapped[int | None] = mapped_column(Integer)
    total_rules: Mapped[int | None] = mapped_column(Integer)
    num_courses: Mapped[int | None] = mapped_column(Integer)
    num_modules: Mapped[int | None] = mapped_column(Integer)

    afl_percent: Mapped[int | None] = mapped_column(Integer)
    src_group: Mapped[str | None] = mapped_column(String(64))
    links: Mapped[str | None] = mapped_column(Text)

    owner_id: Mapped[str | None] = mapped_column(String(64), index=True)
    owner_name: Mapped[str | None] = mapped_column(String(255), index=True)

    # ─── parametric fields (fill-if-null) ───
    category_id: Mapped[str | None] = mapped_column(String(64), index=True)
    category_slug: Mapped[str | None] = mapped_column(String(64), index=True)
    language: Mapped[str | None] = mapped_column(String(32), index=True)
    price_bucket: Mapped[str | None] = mapped_column(String(16), index=True)
    sort_seen: Mapped[str | None] = mapped_column(String(16))

    # browse | search | snowball
    discovered_via: Mapped[str | None] = mapped_column(String(16))
    # whether full details were fetched from about.json
    detail_fetched: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # the real handle in the URL (like kane-kallaway-5536)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(512))

    bio: Mapped[str | None] = mapped_column(Text)

    # if location is empty it is filled from the timezone (location_source says which)
    location: Mapped[str | None] = mapped_column(String(255))
    location_source: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str | None] = mapped_column(String(64))

    avatar_url: Mapped[str | None] = mapped_column(Text)
    avatar_bubble_url: Mapped[str | None] = mapped_column(Text)

    # ─── social networks ───
    link_facebook: Mapped[str | None] = mapped_column(Text)
    link_instagram: Mapped[str | None] = mapped_column(Text)
    link_linkedin: Mapped[str | None] = mapped_column(Text)
    link_twitter: Mapped[str | None] = mapped_column(Text)
    link_website: Mapped[str | None] = mapped_column(Text)
    link_youtube: Mapped[str | None] = mapped_column(Text)

    last_offline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # removed: email (always empty), myers_briggs, disc_top,
    # total_groups (the site's `totalGroups` includes memberships and was
    # wrong; the right count is SELECT count(*) FROM groups WHERE owner_id = users.id),
    # and total_posts (the site has no such stat for users)
    total_followers: Mapped[int | None] = mapped_column(Integer)
    total_following: Mapped[int | None] = mapped_column(Integer)
    total_contributions: Mapped[int | None] = mapped_column(Integer)

    # whether the full profile (and group list) has been fetched
    groups_fetched: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserGroup(Base):
    """User-group link.

    Deliberately no ForeignKey — in a parallel crawl insertion order is not
    guaranteed. `role` says whether the user owns the group ("owner") or is
    merely a member of it ("member").
    """

    __tablename__ = "user_groups"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index("ix_groups_category_language", Group.category_slug, Group.language)
Index("ix_groups_detail_pending", Group.detail_fetched)
Index("ix_user_groups_group", UserGroup.group_id)


class GroupMetric(Base):
    """Point-in-time metrics of a group (time-series history).

    One row per snapshot — append-only, never updated. `captured_at` is the
    wall-clock time the snapshot was taken; the numeric columns are copies of
    the live values at that moment, so charts can show how members / price /
    posts evolve over the long run.
    """

    __tablename__ = "group_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    price_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_members: Mapped[int | None] = mapped_column(Integer)
    total_online_members: Mapped[int | None] = mapped_column(Integer)
    total_posts: Mapped[int | None] = mapped_column(Integer)
    total_admins: Mapped[int | None] = mapped_column(Integer)
    total_rules: Mapped[int | None] = mapped_column(Integer)
    num_courses: Mapped[int | None] = mapped_column(Integer)
    num_modules: Mapped[int | None] = mapped_column(Integer)
    afl_percent: Mapped[int | None] = mapped_column(Integer)


class UserMetric(Base):
    """Point-in-time metrics of a user (time-series history)."""

    __tablename__ = "user_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    total_followers: Mapped[int | None] = mapped_column(Integer)
    total_following: Mapped[int | None] = mapped_column(Integer)
    total_contributions: Mapped[int | None] = mapped_column(Integer)
    owned_groups: Mapped[int | None] = mapped_column(Integer)


Index("ix_group_metrics_group_time", GroupMetric.group_id, GroupMetric.captured_at)
Index("ix_user_metrics_user_time", UserMetric.user_id, UserMetric.captured_at)


class ScraperSettings(Base):
    """Scraper settings and heartbeat tracking."""

    __tablename__ = "scraper_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_interval_days: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3")
    )
    discovery_interval_days: Mapped[int] = mapped_column(
        Integer, default=7, server_default=text("7")
    )
    refresh_cron: Mapped[str] = mapped_column(
        String(64), default="0 2 */3 * *", server_default=text("'0 2 */3 * *'")
    )
    discovery_cron: Mapped[str] = mapped_column(
        String(64), default="0 3 * * 0", server_default=text("'0 3 * * 0'")
    )
    is_paused: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    discovery_mode: Mapped[str] = mapped_column(
        String(32), default="all", server_default=text("'all'")
    )
    page_concurrency: Mapped[int] = mapped_column(
        Integer, default=4, server_default=text("4")
    )
    detail_concurrency: Mapped[int] = mapped_column(
        Integer, default=8, server_default=text("8")
    )
    request_delay_ms: Mapped[int] = mapped_column(
        Integer, default=300, server_default=text("300")
    )
    include_bigrams: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    daemon_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScraperJob(Base):
    """Manual and scheduled scraper job execution records."""

    __tablename__ = "scraper_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(32))
    trigger_type: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScraperLog(Base):
    """Streaming log output from scraper job executions."""

    __tablename__ = "scraper_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scraper_jobs.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
