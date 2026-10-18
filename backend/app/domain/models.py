"""Row → API-shape dicts (port of server/src/serialize.js).

Field names/nesting/casing must stay byte-identical to the Express output.
"""
import json
from typing import Any

from app.domain.pricing import effective_price, estimate_revenue, infer_bucket


def parse_links(raw: str | None) -> list[dict]:
    """Tolerant links JSON parse: invalid/empty → []; http(s)-only urls."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        items = parsed.get("links") if isinstance(parsed, dict) else None
        if not isinstance(items, list):
            return []
        out = []
        for l in items:
            if not isinstance(l, dict):
                continue
            url = l.get("url")
            if not isinstance(url, str) or not url.startswith("http"):
                continue
            label = str(l.get("label") or "").strip() or url
            out.append({"url": url, "label": label, "public": bool(l.get("public"))})
        return out
    except (ValueError, TypeError):
        return []


def serialize_group_card(row: dict) -> dict:
    price_usd = row.get("price_usd")
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "display_name": row.get("display_name") or row.get("name"),
        "initials": row.get("initials") or None,
        "color": row.get("color") or None,
        "cover_url": row.get("cover_url") or None,
        "logo_url": row.get("logo_url") or None,
        "total_members": row.get("total_members"),
        "total_posts": row.get("total_posts"),
        # Express: `row.price_bucket || (Number(row.price_usd) > 0 ? 'paid' : 'free')`
        "price_bucket": row.get("price_bucket")
        or ("paid" if _num(price_usd) is not None and _num(price_usd) > 0 else "free"),
        "price_interval": row.get("price_interval") or None,
        "price_usd": price_usd,
        "category_slug": row.get("category_slug"),
        "language": row.get("language"),
        "is_public": row.get("is_public"),
        "owner_id": row.get("owner_id") or None,
        "owner_name": row.get("owner_name") or None,
        "created_at": _iso(row.get("created_at")),
        **(estimate_revenue(_with_price_fallback(row)) or {}),
    }


def serialize_group_detail(row: dict) -> dict:
    """Full group shape (detail + compare)."""
    has_amount = _has_amount(row)
    bucket = row.get("price_bucket") or ("paid" if has_amount else "free")
    price_usd_val = row.get("price_usd")
    if price_usd_val is not None:
        price_usd_out = float(price_usd_val)
    elif row.get("price_amount_cents") is not None:
        price_usd_out = float(f"{int(row['price_amount_cents']) / 100:.2f}")
    else:
        price_usd_out = None
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "display_name": row.get("display_name") or row.get("name"),
        "description": row.get("description") or None,
        "lp_description": row.get("lp_description") or None,
        "color": row.get("color") or None,
        "initials": row.get("initials") or None,
        "cover_url": row.get("cover_url") or None,
        "logo_url": row.get("logo_url") or None,
        "logo_big_url": row.get("logo_big_url") or None,
        "favicon_url": row.get("favicon_url") or None,
        "price_bucket": bucket,
        "price_interval": row.get("price_interval") or None,
        "price_usd": price_usd_out,
        "is_public": row.get("is_public"),
        "membership_model": row.get("membership_model"),
        "total_members": row.get("total_members"),
        "total_online_members": row.get("total_online_members"),
        "total_posts": row.get("total_posts"),
        "total_admins": row.get("total_admins"),
        "total_rules": row.get("total_rules"),
        "num_courses": row.get("num_courses"),
        "num_modules": row.get("num_modules"),
        "afl_percent": row.get("afl_percent"),
        "category_slug": row.get("category_slug"),
        "category_id": row.get("category_id"),
        "language": row.get("language"),
        "links": parse_links(row.get("links")),
        "owner_id": row.get("owner_id") or None,
        "owner_name": row.get("owner_name") or None,
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        **(estimate_revenue(_with_price_fallback(row)) or {}),
        "owner": serialize_owner(row),
    }


def serialize_owner(row: dict) -> dict | None:
    """Owner object from the R3 three-way LEFT JOIN aliases."""
    u_id = row.get("u_id")
    if not u_id:
        return None

    def pick(key: str) -> Any:
        v = row.get(key)
        return v if v is not None else None

    return {
        "id": u_id,
        "name": pick("u_name"),
        "full_name": pick("u_full_name"),
        "bio": pick("u_bio"),
        "avatar": pick("u_avatar"),
        "total_followers": pick("u_followers"),
        "total_contributions": pick("u_contributions"),
        "location": pick("u_location"),
    }


def serialize_user_card(row: dict) -> dict:
    avatar_bubble = row.get("avatar_bubble_url") or row.get("avatar_url") or None
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "full_name": row.get("full_name") or row.get("name"),
        "avatar_url": row.get("avatar_url") or None,
        "avatar_bubble_url": avatar_bubble,
        "bio": row.get("bio") or None,
        "location": row.get("location") or None,
        "total_followers": row.get("total_followers"),
        "total_following": row.get("total_following"),
        "total_contributions": row.get("total_contributions"),
    }


def serialize_user_full(row: dict) -> dict:
    out = serialize_user_card(row)
    out.update(
        {
            "first_name": row.get("first_name"),
            "last_name": row.get("last_name"),
            "timezone": row.get("timezone"),
            "links": {
                "website": row.get("link_website") or None,
                "twitter": row.get("link_twitter") or None,
                "linkedin": row.get("link_linkedin") or None,
                "youtube": row.get("link_youtube") or None,
                "instagram": row.get("link_instagram") or None,
                "facebook": row.get("link_facebook") or None,
            },
            "created_at": _iso(row.get("created_at")),
        }
    )
    return out


# --- helpers -----------------------------------------------------------

def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _has_amount(row: dict) -> bool:
    """Express: price_usd != null ? Number(price_usd) > 0 : Number(cents) > 0."""
    if row.get("price_usd") is not None:
        n = _num(row["price_usd"])
        return n is not None and n > 0
    cents = _num(row.get("price_amount_cents"))
    return cents is not None and cents > 0


def _with_price_fallback(row: dict) -> dict:
    """Revenue needs price_amount_cents even when the SELECT omitted it —
    cards don't select it, so fall back to the selected price_usd only."""
    return row


def _iso(dt: Any) -> Any:
    if dt is None or isinstance(dt, str):
        return dt
    try:
        return dt.isoformat()
    except AttributeError:
        return dt
