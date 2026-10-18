"""Filter value objects + JS-lenient parsing.

Parsing must mirror the Express queryBuilder exactly:
- booleans accept true/false/1/0 (anything else = absent)
- ints parse via Number.parseInt semantics ("12abc" → 12, "abc" → absent)
- floats via Number.parseFloat
- csv params split on comma, trimmed, empties dropped, capped at 40 items

These are pure functions — no SQL, no async, trivially unit-testable.
"""
from dataclasses import dataclass, field


def parse_bool(v: str | None) -> bool | None:
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    return None


def parse_int(v: str | None) -> int | None:
    """JS Number.parseInt: leading integer portion or None."""
    if v is None:
        return None
    s = v.strip()
    i = 0
    if s[:1] in ("+", "-"):
        i = 1
    end = i
    while end < len(s) and s[end].isdigit():
        end += 1
    if end == i:
        return None
    return int(s[:end])


def parse_float(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        f = float(v.strip())
    except ValueError:
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None  # NaN/inf guard


def split_list(v: str | None) -> list[str]:
    if not v:
        return []
    return [s.strip() for s in v.split(",") if s.strip()][:40]


@dataclass(frozen=True)
class Pagination:
    page: int = 1
    page_size: int = 24


def pagination_of(params) -> Pagination:
    p = parse_int(params.get("page"))
    page = p if p is not None and p >= 1 else 1
    s = parse_int(params.get("pageSize"))
    page_size = min(max(s, 1), 100) if s is not None else 24
    return Pagination(page=page, page_size=page_size)


GROUP_SORTS = (
    "most_members", "fewest_members", "most_posts", "fewest_posts",
    "engagement", "rev_desc", "rev_asc", "price_desc", "price_asc",
    "newest", "oldest", "name",
)
USER_SORTS = ("most_followers", "most_contributions", "newest", "oldest", "name")
PRICE_INTERVALS = ("month", "year", "week", "one_time")


@dataclass(frozen=True)
class GroupFilter:
    search: str | None = None
    owner: str | None = None
    category: list[str] = field(default_factory=list)
    language: list[str] = field(default_factory=list)
    price: list[str] = field(default_factory=list)
    min_price_usd: float | None = None
    max_price_usd: float | None = None
    price_interval: str | None = None
    visibility: str | None = None
    min_members: int | None = None
    max_members: int | None = None
    min_posts: int | None = None
    max_posts: int | None = None
    has_courses: bool | None = None
    has_posts: bool | None = None
    has_description: bool | None = None
    has_links: bool | None = None
    social: list[str] = field(default_factory=list)
    created_from: str | None = None
    created_to: str | None = None
    is_member_of: list[str] = field(default_factory=list)
    is_owner_of: list[str] = field(default_factory=list)
    not_member_of: list[str] = field(default_factory=list)
    sort: str = "most_members"
    pagination: Pagination = field(default_factory=Pagination)


@dataclass(frozen=True)
class UserFilter:
    search: str | None = None
    location: list[str] = field(default_factory=list)
    timezone: list[str] = field(default_factory=list)
    min_followers: int | None = None
    max_followers: int | None = None
    min_following: int | None = None
    max_following: int | None = None
    min_contributions: int | None = None
    max_contributions: int | None = None
    social: list[str] = field(default_factory=list)
    creators_only: bool | None = None
    created_from: str | None = None
    created_to: str | None = None
    has_bio: bool | None = None
    has_avatar: bool | None = None
    sort: str = "most_followers"
    pagination: Pagination = field(default_factory=Pagination)


@dataclass(frozen=True)
class AnalyticsFilter:
    """Group-sourced analytics filters. Note: the reference applies these to
    most datasets but NOT growthByCohortYear (plain WHERE year >= 2020)."""
    min_members: int | None = None
    max_members: int | None = None
    min_posts: int | None = None
    max_posts: int | None = None
    categories: list[str] = field(default_factory=list)
    created_from: str | None = None
    created_to: str | None = None
    raw_query: str = ""


def group_filter_from_params(params) -> GroupFilter:
    interval = params.get("priceInterval")
    sort = params.get("sort") or "most_members"
    return GroupFilter(
        search=(params.get("search") or "").strip() or None,
        owner=(params.get("owner") or "").strip() or None,
        category=split_list(params.get("category")),
        language=split_list(params.get("language")),
        price=[p for p in split_list(params.get("price"))],
        min_price_usd=_nonneg(parse_float(params.get("minPriceUsd"))),
        max_price_usd=_nonneg(parse_float(params.get("maxPriceUsd"))),
        price_interval=interval if interval in PRICE_INTERVALS else None,
        visibility=params.get("visibility") if params.get("visibility") in ("public", "private") else None,
        min_members=parse_int(params.get("minMembers")),
        max_members=parse_int(params.get("maxMembers")),
        min_posts=parse_int(params.get("minPosts")),
        max_posts=parse_int(params.get("maxPosts")),
        has_courses=parse_bool(params.get("hasCourses")),
        has_posts=parse_bool(params.get("hasPosts")),
        has_description=parse_bool(params.get("hasDescription")),
        has_links=parse_bool(params.get("hasLinks")),
        social=split_list(params.get("social")),
        created_from=params.get("createdFrom") or None,
        created_to=params.get("createdTo") or None,
        is_member_of=split_list(params.get("isMemberOf")),
        is_owner_of=split_list(params.get("isOwnerOf")),
        not_member_of=split_list(params.get("notMemberOf")),
        sort=sort if sort in GROUP_SORTS else "most_members",
        pagination=pagination_of(params),
    )


def user_filter_from_params(params) -> UserFilter:
    sort = params.get("sort") or "most_followers"
    return UserFilter(
        search=(params.get("search") or "").strip() or None,
        location=split_list(params.get("location")),
        timezone=split_list(params.get("timezone")),
        min_followers=parse_int(params.get("minFollowers")),
        max_followers=parse_int(params.get("maxFollowers")),
        min_following=parse_int(params.get("minFollowing")),
        max_following=parse_int(params.get("maxFollowing")),
        min_contributions=parse_int(params.get("minContributions")),
        max_contributions=parse_int(params.get("maxContributions")),
        social=split_list(params.get("social")),
        creators_only=parse_bool(params.get("creatorsOnly")),
        created_from=params.get("createdFrom") or None,
        created_to=params.get("createdTo") or None,
        has_bio=parse_bool(params.get("hasBio")),
        has_avatar=parse_bool(params.get("hasAvatar")),
        sort=sort if sort in USER_SORTS else "most_followers",
        pagination=pagination_of(params),
    )


def analytics_filter_from_params(params) -> AnalyticsFilter:
    return AnalyticsFilter(
        min_members=parse_int(params.get("minMembers")),
        max_members=parse_int(params.get("maxMembers")),
        min_posts=parse_int(params.get("minPosts")),
        max_posts=parse_int(params.get("maxPosts")),
        categories=split_list(params.get("categories")),
        created_from=params.get("createdFrom") or None,
        created_to=params.get("createdTo") or None,
        raw_query=str(params),
    )


def _nonneg(f: float | None) -> float | None:
    """Express guards price bounds with `>= 0`; NaN already filtered."""
    return f if f is not None and f >= 0 else None
