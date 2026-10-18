"""Shared fixtures: live client against a running server (contract tests hit
the same queries as prod per spec §7)."""
import os

import httpx
import pytest

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:3001")

HORMOZI_GROUP_ID = "e0f76dfe658a4d3ea142b8936e472b68"
ECOMMERCE_OWNER_ID = "be59d6d34a884a3999e6d9adb18d3f42"
ADMIN_EMAIL = os.environ.get("API_ADMIN_EMAIL", "admin@skool.local")
ADMIN_PASSWORD = os.environ.get("API_ADMIN_PASSWORD", "admin123")


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        c.get("/api/health")  # fail fast if server down
        # Auth is mandatory on /api now — log in once for the whole session.
        r = c.post("/api/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        r.raise_for_status()
        token = r.json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
