"""Revenue estimation + price-bucket inference (R1, R5).

Pure functions — the single source of truth for the Python side. The SQL
sort expressions in adapters/db/sql/groups_sql.py mirror this formula
exactly; keep them in sync.
"""
import math


def effective_price(row) -> float | None:
    """price_usd falling back to price_amount_cents / 100 (R1 amount source)."""
    if row.get("price_usd") is not None:
        return float(row["price_usd"])
    cents = row.get("price_amount_cents")
    if cents is not None:
        return float(cents) / 100.0
    return None


def infer_bucket(row) -> str:
    """R1: null bucket with an amount → paid; null with no amount → free."""
    raw = row.get("price_bucket")
    if raw:
        return raw
    price = effective_price(row)
    return "paid" if price is not None and price > 0 else "free"


def estimate_revenue(row) -> dict | None:
    """R5 revenue block; spread into card/detail responses when monetized.

    Mirrors serialize.estimateRevenue in the Express reference:
      month → total · year → /12 · week → ×4.33 · one_time → total/months_age
    months_age clamped 0.5..120 via 30.44-day months, default 12.
    """
    price = effective_price(row)
    members = row.get("total_members")
    if members is not None:
        members = int(members)
    bucket = row.get("price_bucket") or (
        "paid" if price is not None and price > 0 else None
    )
    if (
        price is None or not members or price <= 0
        or not bucket or bucket in ("free", "unknown")
    ):
        return None

    total = price * members
    interval = row.get("price_interval") or "month"

    if row.get("created_at") is not None:
        age_s = _now_ms() - _to_ms(row["created_at"])
        months_age = min(max(age_s / (1000 * 60 * 60 * 24 * 30.44), 0.5), 120)
    else:
        months_age = 12.0

    monthly: float | None
    one_time: float | None = None
    if interval == "year":
        monthly = total / 12.0
    elif interval == "week":
        monthly = total * 4.33
    elif interval == "one_time":
        one_time = round(total)
        monthly = total / months_age
    else:
        monthly = total  # 'month' or missing

    return {
        "estimated_monthly_revenue_usd": round(monthly) if monthly is not None and math.isfinite(monthly) else None,
        "estimated_one_time_revenue_usd": one_time,
        "estimated_rev_period": interval,
    }


def _now_ms() -> float:
    import time
    return time.time() * 1000


def _to_ms(dt) -> float:
    if isinstance(dt, (int, float)):
        return float(dt)
    try:
        return dt.timestamp() * 1000
    except AttributeError:
        # ISO string fallback
        from datetime import datetime, timezone
        s = str(dt).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp() * 1000
