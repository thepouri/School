"""Parsing of _next/data responses.

Key point: Skool gives one field in two places under two different names:

* User page (`@handle.json`) → camelCase: `firstName`, `linkInstagram`, `timeZone`
* The `owner` block inside `about.json` → snake_case: `first_name`, `link_instagram`

So we normalize every key (lowercase, drop separators) and then read them.
Also some fields are JSON strings (`displayPrice`, `owner`, `links`, …) and
in some places a dict — `_loads` accepts both.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone as _timezone
from typing import Any, Iterator

log = logging.getLogger(__name__)

_FRACTION_RE = re.compile(r"(\.\d{6})\d+")
_KEY_RE = re.compile(r"[^a-z0-9]")


# ────────────────── base helpers ──────────────────


def _loads(value: Any) -> Any:
    """Unwrap a value whether it is a dict/list or a JSON string."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return None


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _dt(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    text = _FRACTION_RE.sub(r"\1", text)  # trim nanoseconds down to microseconds
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _ns_dt(value: Any) -> datetime | None:
    """`lastOffline` is a nanosecond timestamp (sometimes a string, sometimes an int)."""
    number = _int(value)
    if not number or number <= 0:
        return None
    # nano → seconds (if very small it's probably milliseconds)
    for divisor in (1_000_000_000, 1_000_000, 1_000, 1):
        seconds = number / divisor
        if 1_000_000_000 <= seconds <= 4_000_000_000:
            return datetime.fromtimestamp(seconds, tz=_timezone.utc)
    return None


def _norm_key(key: Any) -> str:
    return _KEY_RE.sub("", str(key).lower())


def _flat(source: Any) -> dict[str, Any]:
    """Return a dict with normalized keys (camelCase and snake_case become one)."""
    data = _loads(source)
    if not isinstance(data, dict):
        return {}
    return {_norm_key(key): value for key, value in data.items()}


def _pick(flat: dict[str, Any], *names: str) -> Any:
    """First non-empty value among the given names (names are normalized)."""
    for name in names:
        value = flat.get(_norm_key(name))
        if value not in (None, "", [], {}):
            return value
    return None


def _text(flat: dict[str, Any], *names: str) -> str | None:
    return _clean(_pick(flat, *names))


def _number(flat: dict[str, Any], *names: str) -> int | None:
    return _int(_pick(flat, *names))


def _json_text(value: Any) -> str | None:
    """Normalize structural fields (links, tabs, survey) to a JSON string."""
    data = _loads(value)
    if data in (None, [], {}):
        return None
    return json.dumps(data, ensure_ascii=False)


def _walk(node: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def page_props(payload: dict[str, Any]) -> dict[str, Any]:
    props = payload.get("pageProps")
    if isinstance(props, dict):
        return props
    props = (payload.get("props") or {}).get("pageProps")
    return props if isinstance(props, dict) else {}


# ────────────────── discovery ──────────────────


def _unwrap_group(item: Any) -> dict[str, Any] | None:
    """Pull the group record out of the possible wrappers.

    In discovery each item is `{"group": {...}, "rank": 0, "tags": null}`.
    """
    if not isinstance(item, dict):
        return None
    if _clean(item.get("id")) and _clean(item.get("name")):
        return item
    for key in ("group", "node", "item", "currentGroup"):
        inner = _loads(item.get(key))
        if (
            isinstance(inner, dict)
            and _clean(inner.get("id"))
            and _clean(inner.get("name"))
        ):
            return inner
    return None


def _looks_like_group(item: Any) -> bool:
    group = _unwrap_group(item)
    return bool(group and ("metadata" in group or "displayName" in group))


def discovery_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Defensively find the list of discovery groups."""
    props = page_props(payload)

    for key in ("groups", "discoveryGroups", "results", "items", "hits"):
        value = props.get(key)
        if isinstance(value, list):
            rows = [g for g in (_unwrap_group(i) for i in value) if g]
            if rows:
                return rows

    found: dict[str, dict[str, Any]] = {}
    for _key, value in _walk(props):
        if not isinstance(value, list):
            continue
        for item in value:
            if _looks_like_group(item):
                group = _unwrap_group(item)
                if group:
                    found[str(group["id"])] = group
    return list(found.values())


def parse_discovery(payload: dict[str, Any]) -> dict[str, Any]:
    props = page_props(payload)
    languages = props.get("languages") or []
    return {
        "groups": discovery_groups(payload),
        "prop_keys": sorted(props.keys()),
        "total": _int(props.get("numGroups")) or 0,
        "page": _int(props.get("page")) or 1,
        "categories": props.get("categories") or [],
        "languages": [
            _clean(item.get("name"))
            for item in languages
            if isinstance(item, dict) and _clean(item.get("name"))
        ],
        "language_param": _clean(props.get("languageParam")),
        "category_param": _clean(props.get("categoryParam")),
        "price_param": _clean(props.get("priceParam")),
        "sort_param": _clean(props.get("sortParam")),
        "type_param": _clean(props.get("typeParam")),
        "query_param": _clean(props.get("searchQueryParam")),
    }


# ────────────────── price ──────────────────


def parse_price(metadata: Any) -> tuple[int | None, str | None, str | None]:
    """Group price.

    * discovery → `displayPrice`: {"currency":"usd","amount":900,"recurring_interval":"month"}
    * about.json → `currentMBp`: {"currency":"usd","amount":99700}  (no interval)
    """
    meta = _flat(metadata)
    amount = currency = interval = None

    for key in ("displayPrice", "currentMBp", "price", "displayPriceV2"):
        payload = _flat(_pick(meta, key))
        if not payload:
            continue
        found = _number(payload, "amount", "amountCents", "price")
        if found is None and amount is None:
            # may only have currency
            currency = currency or _text(payload, "currency")
            continue
        if amount is None:
            amount = found
            currency = _text(payload, "currency") or currency
            interval = (
                _text(payload, "recurringInterval", "interval", "recurring_interval")
                or interval
            )

    if interval is None:
        interval = _text(meta, "recurringInterval", "interval")
    if currency is None:
        currency = _text(meta, "currency")

    return amount, (currency.lower() if currency else None), interval


# ────────────────── public / private ──────────────────

# The group metadata carries a numeric `privacy` field: 1 = public, 2 (or more) = private
PRIVACY_PUBLIC = 1


def parse_is_public(metadata: Any) -> bool | None:
    """Determine whether the group is public/private.

    Order of attempts:
    1. A string field (`groupType`/`visibility`/`privacyType` = "public"/"private")
    2. The numeric field `privacy` → 1 means public, 2 and above private

    If neither is present, None is returned (i.e. unknown, not private).
    """
    meta = _flat(metadata)

    text = _text(meta, "groupType", "visibility", "privacyType", "privacyLevel")
    if text:
        lowered = text.lower()
        if "public" in lowered:
            return True
        if "private" in lowered:
            return False

    number = _number(meta, "privacy")
    if number is None:
        return None
    return number == PRIVACY_PUBLIC


# ────────────────── group ──────────────────


def parse_group(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One group record (from discovery, about.json, or a user's group list)."""
    unwrapped = _unwrap_group(raw)
    if unwrapped is None:
        return None
    raw = unwrapped
    group_id = _clean(raw.get("id"))
    name = _clean(raw.get("name"))
    if not group_id or not name:
        return None

    top = _flat(raw)
    meta = _flat(raw.get("metadata"))
    amount, currency, interval = parse_price(raw.get("metadata"))

    owner_blob = _flat(_pick(meta, "owner", "createdByUser", "user"))
    owner_id = _text(meta, "createdBy") or _text(owner_blob, "id") or _text(top, "ownerId")
    owner_name = _text(owner_blob, "name") or _text(top, "ownerName")

    return {
        "id": group_id,
        "name": name,
        "display_name": _text(meta, "displayName") or _text(top, "displayName"),
        "description": _text(meta, "description"),
        "lp_description": _text(meta, "lpDescription"),
        "color": _text(meta, "color"),
        "initials": _text(meta, "initials"),
        "cover_url": _text(meta, "coverSmallUrl", "coverUrl", "coverLargeUrl"),
        "logo_url": _text(meta, "logoUrl", "logoSmallUrl", "picture"),
        "logo_big_url": _text(meta, "logoBigUrl"),
        "favicon_url": _text(meta, "faviconUrl"),
        "price_amount_cents": amount,
        "price_usd": round(amount / 100, 2) if amount is not None else None,
        "price_currency": currency,
        "price_interval": interval,
        # about.json uses key `membership`, discovery uses `membershipModel`
        "membership_model": _number(meta, "membershipModel", "membership"),
        "privacy": _number(meta, "privacy", "groupType", "visibility"),
        "is_public": parse_is_public(raw.get("metadata")),
        "total_members": _number(meta, "totalMembers", "members"),
        "total_online_members": _number(meta, "totalOnlineMembers"),
        "total_posts": _number(meta, "totalPosts"),
        "total_admins": _number(meta, "totalAdmins"),
        "total_rules": _number(meta, "totalRules"),
        "num_courses": _number(meta, "numCourses"),
        "num_modules": _number(meta, "numModules"),
        "afl_percent": _number(meta, "aflPercent"),
        "src_group": _text(meta, "srcGroup"),
        "links": _json_text(_pick(meta, "links")),
        "owner_id": owner_id,
        "owner_name": owner_name,
        "created_at": _dt(raw.get("createdAt") or raw.get("created_at")),
        "updated_at": _dt(raw.get("updatedAt") or raw.get("updated_at")),
    }


def parse_group_detail(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse the group from `about.json` (key `currentGroup`)."""
    props = page_props(payload)
    for key in ("currentGroup", "group"):
        raw = _loads(props.get(key))
        if isinstance(raw, dict):
            row = parse_group(raw)
            if row:
                return row
    return None


def group_owner(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Turn the `owner` block inside about.json into a user record.

    This block has almost everything the user page gives (first/last name,
    bio, links, location) — only the counts and timezone are missing.
    """
    props = page_props(payload)
    for key in ("currentGroup", "group"):
        raw = _loads(props.get(key))
        if not isinstance(raw, dict):
            continue
        meta = _flat(raw.get("metadata"))
        blob = _loads(_pick(meta, "owner", "createdByUser"))
        if isinstance(blob, dict):
            row = parse_user_record(blob)
            if row:
                return row
    return None


# ────────────────── user ──────────────────


def parse_user_record(
    raw: dict[str, Any], profile: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """User record from anywhere: `currentUser`, `renderData.user`, or the `owner` block."""
    if not isinstance(raw, dict):
        return None

    top = _flat(raw)
    user_id = _text(top, "id")
    name = _text(top, "name")
    if not user_id or not name:
        return None

    meta = _flat(raw.get("metadata"))
    stats = _flat(profile if profile is not None else _pick(top, "profileData"))

    # first/last name live on the user itself, not in metadata
    first_name = _text(top, "firstName") or _text(meta, "firstName")
    last_name = _text(top, "lastName") or _text(meta, "lastName")

    timezone_name = _text(top, "timeZone", "timezone") or _text(
        meta, "timezone", "timeZone", "tz"
    )
    location = _text(meta, "location", "city", "country")
    # requested rule: if location is empty, fill it from the timezone
    if location:
        location_source = "profile"
    elif timezone_name:
        location = timezone_name
        location_source = "timezone"
    else:
        location_source = None

    return {
        "id": user_id,
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": " ".join(part for part in (first_name, last_name) if part) or None,
        "bio": _text(meta, "bio", "about"),
        # the email column was removed: the site always returns ""
        "location": location,
        "location_source": location_source,
        "timezone": timezone_name,
        "avatar_url": _text(meta, "pictureProfile", "picture", "avatarUrl"),
        "avatar_bubble_url": _text(meta, "pictureBubble"),
        "link_facebook": _text(meta, "linkFacebook"),
        "link_instagram": _text(meta, "linkInstagram"),
        "link_linkedin": _text(meta, "linkLinkedin", "linkLinkedIn"),
        "link_twitter": _text(meta, "linkTwitter"),
        "link_website": _text(meta, "linkWebsite"),
        "link_youtube": _text(meta, "linkYoutube", "linkYouTube"),
        # myers_briggs / disc_top / email / total_groups / total_posts removed
        "last_offline": _ns_dt(_pick(meta, "lastOffline")),
        "total_followers": _number(stats, "totalFollowers"),
        "total_following": _number(stats, "totalFollowing"),
        "total_contributions": _number(stats, "totalContributions"),
        "created_at": _dt(_pick(top, "createdAt")),
        "updated_at": _dt(_pick(top, "updatedAt")),
    }


def _groups_in(profile: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Read a profile group-list key (`groupsCreatedByUser` / `groupsMemberOf`)."""
    value = _loads(_pick(profile, key))
    if not isinstance(value, list):
        return []
    found: dict[str, dict[str, Any]] = {}
    for item in value:
        if _looks_like_group(item):
            group = _unwrap_group(item)
            if group:
                found[str(group["id"])] = group
    return list(found.values())


def find_group_lists(
    payload: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Groups linked to a user, split by relation.

    Returns {"owned": [...], "member": [...]}:
      * owned  — `profileData.groupsCreatedByUser` (the user created them)
      * member — `profileData.groupsMemberOf` (the user joined them)
    """
    props = page_props(payload)
    render = props.get("renderData") if isinstance(props.get("renderData"), dict) else {}
    user = props.get("currentUser") or (render or {}).get("user") or {}
    profiles = [
        _flat(_pick(_flat(user), "profileData")),
        _flat(props.get("profileData")),
    ]

    owned: dict[str, dict[str, Any]] = {}
    member: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        for item in _groups_in(profile, "groupsCreatedByUser"):
            owned[str(item["id"])] = item
        for item in _groups_in(profile, "groupsMemberOf"):
            member[str(item["id"])] = item

    # a group cannot be both owned and merely member-of; owned wins
    for gid in owned:
        member.pop(gid, None)
    return {"owned": list(owned.values()), "member": list(member.values())}


def parse_user_page(payload: dict[str, Any]) -> dict[str, Any] | None:
    """`@handle.json` page → user record + their groups."""
    props = page_props(payload)
    render = props.get("renderData") or {}
    if not isinstance(render, dict):
        render = {}

    candidates = [props.get("currentUser"), render.get("user")]
    user_row: dict[str, Any] | None = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        profile = _pick(_flat(candidate), "profileData") or props.get("profileData")
        row = parse_user_record(candidate, _loads(profile) or {})
        if row:
            user_row = row
            break
    if not user_row:
        return None

    # the total_groups column was removed: the site's `totalGroups` includes
    # membership groups too and does not match the real count of a user's own
    # groups. Get the right count with
    # SELECT count(*) FROM groups WHERE owner_id = ...
    return {"user": user_row, **find_group_lists(payload)}


def parse_member_search(payload: dict[str, Any]) -> dict[str, Any]:
    """`{group}/-/search.json?t=members` page → member user records.

    The payload has `pageProps.members` — a list of membership entries, each
    carrying the nested `user` object with the full profile fields. Only those
    nested users are returned, as `parse_user_record` rows.

    Returns {"users": [records...], "total": int, "page": int, "has_more": bool}.
    `total` comes from `pageProps.totalMembers`.
    """
    props = page_props(payload)
    members = props.get("members")
    users: list[dict[str, Any]] = []
    if isinstance(members, list):
        for entry in members:
            if not isinstance(entry, dict):
                continue
            user_raw = entry.get("user")
            if isinstance(user_raw, dict):
                row = parse_user_record(user_raw)
                if row:
                    users.append(row)
    total = _int(props.get("totalMembers")) or None
    page = _int(props.get("page")) or 1
    return {
        "users": users,
        "total": total,
        "page": page,
        "has_more": bool(users) and (total is None or (page * 30) < total),
    }


