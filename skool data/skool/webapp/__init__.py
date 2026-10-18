"""FastAPI application exposing the read-only API + static frontend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import api as db

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Skool Browser", version="1.0.0")


class Page(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    items: list[dict[str, Any]]


# ─── Static frontend ───


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ─── Facets ───


@app.get("/api/filters/groups")
async def groups_facets() -> dict[str, Any]:
    return await db.get_facets_groups()


@app.get("/api/filters/users")
async def users_facets() -> dict[str, Any]:
    return await db.get_facets_users()


# ─── Groups ───


@app.get("/api/groups", response_model=Page)
async def list_groups(
    page: int = 1,
    per_page: int = 30,
    sort: str = "members_desc",
    q: str | None = None,
    category: str | None = None,
    language: str | None = None,
    price_bucket: str | None = None,
    currency: str | None = None,
    interval: str | None = None,
    is_public: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_members: int | None = None,
    max_members: int | None = None,
    min_courses: int | None = None,
    min_posts: int | None = None,
    detail: str | None = None,
    with_price: str | None = None,
) -> dict[str, Any]:
    return await db.query_groups(
        page=page,
        per_page=per_page,
        sort=sort,
        q=q,
        category=category,
        language=language,
        price_bucket=price_bucket,
        currency=currency,
        interval=interval,
        is_public=is_public,
        min_price=min_price,
        max_price=max_price,
        min_members=min_members,
        max_members=max_members,
        min_courses=min_courses,
        min_posts=min_posts,
        detail=detail,
        with_price=with_price,
    )


@app.get("/api/groups/{group_id}")
async def group_detail(group_id: str) -> dict[str, Any]:
    result = await db.get_group_detail(group_id)
    if not result:
        raise HTTPException(status_code=404, detail="Group not found")
    result["owner"] = await db.get_group_owner(group_id)
    return result


# ─── Users ───


@app.get("/api/users", response_model=Page)
async def list_users(
    page: int = 1,
    per_page: int = 30,
    sort: str = "followers_desc",
    q: str | None = None,
    location_source: str | None = None,
    timezone: str | None = None,
    has_avatar: str | None = None,
    owned: str | None = None,
    scraped: str | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
) -> dict[str, Any]:
    return await db.query_users(
        page=page,
        per_page=per_page,
        sort=sort,
        q=q,
        location_source=location_source,
        timezone=timezone,
        has_avatar=has_avatar,
        owned=owned,
        scraped=scraped,
        min_followers=min_followers,
        max_followers=max_followers,
    )


@app.get("/api/users/{user_id}")
async def user_detail(user_id: str) -> dict[str, Any]:
    result = await db.get_user_detail(user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    result["groups"] = await db.get_user_groups(user_id)
    return result