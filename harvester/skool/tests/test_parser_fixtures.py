"""Fixture tests and completeness evaluation tests for Parser."""

import json
from pathlib import Path

import pytest
from skool.parser import (
    dig,
    evaluate_group_completeness,
    evaluate_user_completeness,
    group_owner,
    parse_discovery,
    parse_group_detail,
    parse_user_page,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_dig_utility():
    data = {
        "pageProps": {
            "currentGroup": {
                "metadata": {
                    "owner": {"id": "usr_123", "name": "john"}
                },
                "tags": ["python", "ai"]
            }
        }
    }

    # Successful deep access via string
    assert dig(data, "pageProps.currentGroup.metadata.owner.id") == "usr_123"
    assert dig(data, "pageProps.currentGroup.tags.1") == "ai"

    # Sequence access
    assert dig(data, ["pageProps", "currentGroup", "tags", 0]) == "python"

    # Safe defaults on non-existing paths
    assert dig(data, "pageProps.missing.key", default="fallback") == "fallback"
    assert dig(None, "any.path", default="none") == "none"
    assert dig(data, "pageProps.currentGroup.tags.99", default=None) is None


def test_fixture_group_about_paid():
    fixture = load_fixture("group_about_paid.json")
    group = parse_group_detail(fixture)

    assert group is not None
    assert group["id"] == "grp_paid_123"
    assert group["name"] == "copywriting-mastery"
    assert group["price_amount_cents"] == 4900
    assert group["price_usd"] == 49.00
    assert group["total_members"] == 1250
    assert group["owner_id"] == "usr_owner_999"
    assert group["owner_name"] == "john-copywriter"

    # Status & Completeness
    assert group["detail_status"] == "ok"
    assert group["completeness"] == 100
    assert group["detail_fetched"] is True

    # Owner parsing
    owner = group_owner(fixture)
    assert owner is not None
    assert owner["id"] == "usr_owner_999"
    assert owner["name"] == "john-copywriter"
    assert owner["first_name"] == "John"
    assert owner["timezone"] == "America/New_York"


def test_fixture_group_about_free():
    fixture = load_fixture("group_about_free.json")
    group = parse_group_detail(fixture)

    assert group is not None
    assert group["id"] == "grp_free_456"
    assert group["membership_model"] == 0  # free
    assert group["total_members"] == 8500
    assert group["detail_status"] == "ok"
    assert group["completeness"] == 100


def test_fixture_group_about_no_owner_partial():
    fixture = load_fixture("group_about_no_owner.json")
    group = parse_group_detail(fixture)

    assert group is not None
    assert group["id"] == "grp_orphan_789"
    assert group["owner_id"] is None
    # Lacks owner and price info -> should be marked partial
    assert group["detail_status"] == "partial"
    assert group["completeness"] < 100


def test_fixture_user_profile_full():
    fixture = load_fixture("user_profile_full.json")
    parsed = parse_user_page(fixture)

    assert parsed is not None
    user = parsed["user"]
    assert user["id"] == "usr_owner_999"
    assert user["full_name"] == "John Doe"
    assert user["total_followers"] == 450
    assert user["profile_status"] == "ok"
    assert user["groups_fetched"] is True

    # Owned & Member communities
    assert len(parsed["owned"]) == 2
    assert parsed["owned"][0]["id"] == "grp_paid_123"
    assert parsed["owned"][1]["id"] == "grp_extra_444"

    assert len(parsed["member"]) == 1
    assert parsed["member"][0]["id"] == "grp_free_456"


def test_fixture_user_profile_minimal_stub():
    fixture = load_fixture("user_profile_minimal.json")
    parsed = parse_user_page(fixture)

    assert parsed is not None
    user = parsed["user"]
    assert user["id"] == "usr_minimal_333"
    # Lacks first/last name, bio, etc -> stub
    assert user["profile_status"] == "stub"
