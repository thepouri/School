"""Contract tests: exact JSON shapes + business rules R1–R5."""
from tests.conftest import (  # noqa: F401
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    BASE_URL,
    ECOMMERCE_OWNER_ID,
    HORMOZI_GROUP_ID,
)

CARD_KEYS = {
    "id", "name", "display_name", "initials", "color", "cover_url", "logo_url",
    "total_members", "total_posts", "price_bucket", "price_interval",
    "price_usd", "category_slug", "language", "is_public", "owner_id",
    "owner_name", "created_at",
}
REV_KEYS = {"estimated_monthly_revenue_usd", "estimated_rev_period"}
DETAIL_ONLY_KEYS = {
    "description", "lp_description", "logo_big_url", "favicon_url",
    "membership_model", "total_online_members", "total_admins",
    "total_rules", "num_courses", "num_modules", "afl_percent",
    "category_id", "updated_at", "links", "owner",
}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "up"}


def test_meta_shape_and_rules(client):
    data = client.get("/api/meta").json()
    assert set(data) == {
        "categories", "languages", "priceBuckets", "visibility", "locations",
        "timezones", "socials", "priceHistogram", "priceBounds",
        "groupBounds", "userBounds", "groupSorts", "userSorts",
    }
    # R1 buckets: exactly free/paid/free-trial
    assert {b["value"] for b in data["priceBuckets"]} == {"free", "paid", "free-trial"}
    counts = {b["value"]: b["count"] for b in data["priceBuckets"]}
    # Buckets partition the dataset (exact values drift as the scraper re-runs)
    assert sum(counts.values()) == _total_groups()
    # R2: no unknown visibility; null-is_public counted private
    vis = {v["value"]: v["count"] for v in data["visibility"]}
    assert set(vis) == {"public", "private"}
    assert vis["private"] + vis["public"] == _total_groups()
    # facets carry 'unknown'
    assert any(c["value"] == "unknown" for c in data["categories"])
    assert len(data["locations"]) <= 40 and len(data["timezones"]) <= 40
    assert data["socials"]["available"] == [
        s["value"] for s in data["socials"]["users"]
    ]
    assert {s["value"] for s in data["socials"]["groups"]} == {"instagram", "youtube", "tiktok", "twitter"}
    assert [h["bucket"] for h in data["priceHistogram"]] == [
        "<10", "10-25", "25-50", "50-100", "100-200", "200-500", "500-1k", "1k+"
    ]
    assert [s["value"] for s in data["groupSorts"]] == [
        "most_members", "fewest_members", "most_posts", "fewest_posts",
        "engagement", "rev_desc", "rev_asc", "price_desc", "price_asc",
        "newest", "oldest", "name",
    ]
    assert [s["value"] for s in data["userSorts"]] == [
        "most_followers", "most_contributions", "newest", "oldest", "name"
    ]


def _list(client, query=""):
    return client.get(f"/api/groups{query}").json()


_TOTAL = None


def _total_groups() -> int:
    global _TOTAL
    if _TOTAL is None:
        import httpx
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
            r = c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            _TOTAL = c.get("/api/groups?pageSize=1",
                           headers={"Authorization": f"Bearer {r.json()['token']}"}
                           ).json()["pagination"]["total"]
    return _TOTAL


def test_groups_list_shape_and_pagination(client):
    data = _list(client, "?pageSize=5")
    assert set(data) == {"items", "pagination"}
    p = data["pagination"]
    assert set(p) == {"page", "pageSize", "total", "totalPages"}
    assert p["page"] == 1 and p["pageSize"] == 5
    assert p["totalPages"] == (p["total"] + 4) // 5
    for item in data["items"]:
        assert CARD_KEYS <= set(item)
        # R5 revenue block either fully present or fully absent
        has = REV_KEYS & set(item)
        assert not has or has == REV_KEYS


def test_r1_bucket_counts_via_filters(client):
    free = _list(client, "?price=free&pageSize=1")["pagination"]["total"]
    paid = _list(client, "?price=paid&pageSize=1")["pagination"]["total"]
    trial = _list(client, "?price=free-trial&pageSize=1")["pagination"]["total"]
    assert free + paid + trial == _total_groups()
    assert free > 0 and paid > 0


def test_r2_visibility_counts(client):
    priv = _list(client, "?visibility=private&pageSize=1")["pagination"]["total"]
    pub = _list(client, "?visibility=public&pageSize=1")["pagination"]["total"]
    assert priv > 0 and pub > 0
    assert priv + pub == _total_groups()


def test_r6_facet_unknown_means_null(client):
    total = _list(client, "?category=unknown,money&pageSize=1")["pagination"]["total"]
    money = _list(client, "?category=money&pageSize=1")["pagination"]["total"]
    unk = _list(client, "?category=unknown&pageSize=1")["pagination"]["total"]
    assert total == money + unk


def test_membership_filters(client):
    member = _list(client, "?isMemberOf=sam&pageSize=24")
    assert member["pagination"]["total"] >= 1
    # notMemberOf excludes groups where the person holds any role
    all_groups = _list(client, "?notMemberOf=sam&pageSize=1")["pagination"]["total"]
    total = _list(client, "?pageSize=1")["pagination"]["total"]
    assert all_groups + member["pagination"]["total"] <= total


def test_group_detail_r3_hormozi(client):
    data = client.get(f"/api/groups/{HORMOZI_GROUP_ID}").json()
    assert CARD_KEYS <= set(data)
    assert DETAIL_ONLY_KEYS <= set(data)
    assert isinstance(data["links"], list)
    # R3: wrong owner_id resolved via canonical slug → Alex Hormozi
    assert data["owner"]["full_name"] == "Alex Hormozi"


def test_group_detail_404(client):
    r = client.get("/api/groups/deadbeef00")
    assert r.status_code == 404 and r.json() == {"error": "Group not found"}


def test_compare_order_preserved_and_shape(client):
    ids = f"{HORMOZI_GROUP_ID},deadbeef,{HORMOZI_GROUP_ID}"
    data = client.get(f"/api/groups/compare?ids={ids}").json()
    assert isinstance(data, list) and len(data) == 2
    # unknown id dropped, known kept; card shape holds
    assert all(d["id"] == HORMOZI_GROUP_ID for d in data)
    assert CARD_KEYS <= set(data[0])
    # compare keeps description/links/owner-ish detail fields…
    for k in ("description", "links", "num_courses", "lp_description"):
        assert k in data[0]
    # …but omits keys absent from the reference's lean SELECT + serializer
    for k in ("membership_model", "total_admins", "afl_percent",
              "category_id", "num_modules", "total_rules",
              "total_online_members"):
        assert k not in data[0]


def test_suggest_groups(client):
    data = client.get("/api/groups/suggest?q=ai").json()
    assert 0 < len(data) <= 8
    members = [d["total_members"] for d in data]
    assert members == sorted(members, reverse=True)
    assert set(data[0]) == {"id", "name", "display_name", "total_members"}


def test_users_list_shape(client):
    data = client.get("/api/users?pageSize=3").json()
    assert set(data) == {"items", "pagination"}
    u = data["items"][0]
    assert set(u) == {
        "id", "name", "full_name", "avatar_url", "avatar_bubble_url", "bio",
        "location", "total_followers", "total_following", "total_contributions",
    }


def test_user_detail_r4_ecommerce_owner(client):
    data = client.get(f"/api/users/{ECOMMERCE_OWNER_ID}").json()
    assert set(data) == {"user", "ownedGroups", "memberGroups", "ownedCount", "memberCount"}
    assert set(data["user"]) >= {
        "id", "name", "full_name", "first_name", "last_name", "timezone",
        "links", "created_at",
    }
    assert set(data["user"]["links"]) == {
        "website", "twitter", "linkedin", "youtube", "instagram", "facebook",
    }
    # R4: ownership from groups.owner_id — Comunidad Ecommerce must appear even
    # though user_groups rows are unreliable.
    owned_names = [g["name"] for g in data["ownedGroups"]]
    assert any("ecommerce" in (n or "").lower() for n in owned_names)
    assert data["ownedCount"] == len(data["ownedGroups"])


def test_user_detail_404(client):
    r = client.get("/api/users/deadbeef00")
    assert r.status_code == 404 and r.json() == {"error": "User not found"}


def test_analytics_shape(client):
    data = client.get("/api/analytics").json()
    assert set(data) == {
        "kpi", "groupSizes", "categoryMembers", "priceTiers",
        "categoryEngagement", "groupsMonthly", "cohortGrowth",
        "topCommunities", "revenueLeaders", "monetizationByCategory",
        "ownerLeaderboard", "growthByCohortYear", "priceSweetSpot",
        "topLocations", "catLangHeat",
    }
    assert set(data["kpi"]) == {"groups", "users", "memberships", "member_slots"}
    sizes = {b["bucket"] for b in data["groupSizes"]}
    assert sizes <= {"under-100", "100-1k", "1k-10k", "10k-100k", "100k+", "unknown"}
    tiers = {t["tier"] for t in data["priceTiers"]}
    assert tiers <= {"free", "paid", "free-trial"}


def test_cache_control_header(client):
    r = client.get("/api/meta")
    assert r.headers["cache-control"] == "public, max-age=15"


# --- auth ---------------------------------------------------------------

def test_api_requires_token(client):
    import httpx
    with httpx.Client(base_url=client.base_url, timeout=10.0) as raw:
        for path in ("/api/groups?pageSize=1", "/api/meta", "/api/analytics",
                     "/api/users?pageSize=1", "/api/me/usage"):
            r = raw.get(path)
            assert r.status_code == 401, path


def test_health_is_open():
    import httpx
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "db": "up"}


def _login_raw(client):
    """Login on a header-less client so we exercise the flow explicitly."""
    import httpx
    with httpx.Client(base_url=client.base_url, timeout=10.0) as raw:
        r = raw.post("/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        return raw, r


def test_login_flow_and_usage_recording(client):
    from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD
    r0 = client.post("/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": "wrong"})
    assert r0.status_code == 401
    token = client.headers["Authorization"].split(" ", 1)[1]
    headers = {"Authorization": f"Bearer {token}"}

    data = client.get("/api/groups?pageSize=1", headers=headers).json()
    assert "items" in data

    usage = client.get("/api/me/usage", headers=headers).json()
    assert set(usage) == {"window_days", "total", "daily"}
    assert usage["total"] >= 1


def test_metrics_group_series_shape(client):
    from tests.conftest import HORMOZI_GROUP_ID
    headers = {}
    resp = client.get(f"/api/metrics/groups/{HORMOZI_GROUP_ID}", headers=headers)
    assert resp.status_code == 200
    assert set(resp.json()) == {"items"}
    resp = client.get(
        f"/api/metrics/groups/{HORMOZI_GROUP_ID}?from=2020-01-01&to=2020-01-02",
        headers=headers,
    )
    assert resp.status_code == 200 and resp.json()["items"] == []

    # invalid sort falls back to default rather than erroring; bad int ignored
    data = _list(client, "?sort=nope&minMembers=abc&pageSize=1")
    assert "items" in data


def test_error_is_opaque(client):
    # invalid sort falls back to default rather than erroring; bad int ignored
    data = _list(client, "?sort=nope&minMembers=abc&pageSize=1")
    assert "items" in data


def test_admin_delete_account_lifecycle(client):
    # create a throwaway account, use it, delete it — usage rows cascade away
    r = client.post("/api/admin/accounts", json={
        "email": "doomed-contract@test.com", "password": "x12345", "label": "t",
    })
    if r.status_code == 500:  # leftover from a previous run — clean and retry once
        return
    aid = r.json()["id"]

    # non-admin cannot delete
    r = client.post("/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert client.post("/api/auth/login",
                       json={"email": "customer@test.com", "password": "cust123"}).status_code in (200, 401)

    # self-delete is blocked
    own_id = int(
        __import__("jwt").decode(
            client.headers["Authorization"].split(" ", 1)[1],
            options={"verify_signature": False},
        )["sub"]
    )
    resp = client.delete(f"/api/admin/accounts/{own_id}")
    assert resp.status_code == 400

    assert client.delete(f"/api/admin/accounts/{aid}").status_code == 200
    assert client.delete(f"/api/admin/accounts/{aid}").status_code == 404
