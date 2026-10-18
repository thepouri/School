"""Parser tests on real Skool data (an abridged sample of responses).

Run: python -m unittest discover -s skool/tests -t .
"""

from __future__ import annotations

import copy
import json
import unittest

from skool import parser

OWNER_BLOB = json.dumps(
    {
        "id": "4e276ca370ad4f2698f5af39121f0f57",
        "name": "kane-kallaway-5536",
        "metadata": {
            "bio": "I help business owners grow faster",
            "last_offline": 1755552396968853800,
            "link_facebook": "",
            "link_instagram": "https://www.instagram.com/kallaway",
            "link_linkedin": "",
            "link_twitter": "https://www.twitter.com/kanekallaway",
            "link_website": "https://content.game",
            "link_youtube": "https://www.youtube.com/@kallawaymarketing",
            "location": "New York, NY",
            "myers_briggs": "",
            "online": 1,
            "picture_bubble": "https://assets.skool.com/bubble-sm.jpg",
            "picture_profile": "https://assets.skool.com/profile",
        },
        "created_at": "2023-12-05T21:24:09.587415Z",
        "updated_at": "2025-08-19T01:46:35.678502Z",
        "email": "",
        "first_name": "Kane",
        "last_name": "Kallaway",
    }
)

DISCOVERY = {
    "pageProps": {
        "page": 1,
        "numGroups": 2,
        "groups": [
            {
                "group": {
                    "id": "1a18982c15714b0c97031894dbdb3900",
                    "name": "aivideobootcamp",
                    "metadata": {
                        "color": "#E4A511",
                        "coverSmallUrl": "https://assets.skool.com/cover-md.jpg",
                        "description": "Master AI Video",
                        "displayName": "AI Video Bootcamp",
                        "displayPrice": '{"currency":"usd","amount":900,"recurring_interval":"month"}',
                        "initials": "AV",
                        "logoUrl": "https://assets.skool.com/logo.jpg",
                        "membershipModel": 2,
                        "totalMembers": 26261,
                    },
                    "createdAt": "2025-10-06T19:45:35.441626Z",
                    "updatedAt": "2026-08-04T14:55:53.063009Z",
                },
                "rank": 0,
                "tags": None,
            }
        ],
    }
}

ABOUT_FREE = {
    "pageProps": {
        "currentGroup": {
            "id": "0d961e00a9474daca54de06671bd4a74",
            "name": "wavyworld",
            "metadata": {
                "color": "#272128",
                "coverSmallUrl": "https://assets.skool.com/cover-md.jpg",
                "createdBy": "4e276ca370ad4f2698f5af39121f0f57",
                "description": "A digital world",
                "displayName": "WavyWorld",
                "faviconUrl": "https://assets.skool.com/favicon",
                "initials": "WW",
                "links": '{"links":[{"url":"https://sandcastles.ai","label":"Sandcastles AI","public":true}]}',
                "logoBigUrl": "https://assets.skool.com/big",
                "logoUrl": "https://assets.skool.com/logo",
                "lpDescription": "WavyWorld was designed",
                "membership": 1,
                "numCourses": 19,
                "numModules": 81,
                "owner": OWNER_BLOB,
                "privacy": 1,
                "srcGroup": "b68da5f5f7504b1f83d9c4c664b63c4f",
                "totalAdmins": 3,
                "totalMembers": 50381,
                "totalOnlineMembers": 358,
                "totalPosts": 3252,
                "totalRules": 3,
            },
            "createdAt": "2024-05-04T01:28:38.58324Z",
            "updatedAt": "2026-08-04T15:41:59.126276Z",
            "labels": [],
            "onlineUsers": [],
        },
        "renderData": {"groupMembershipProducts": []},
    }
}

# This group's price is not in displayPrice; it lives in currentMBp
ABOUT_PAID = {
    "pageProps": {
        "currentGroup": {
            "id": "7b4c85a8269d45c193a30bed88f38b74",
            "name": "mindful-muslimahs-coaching-6429",
            "metadata": {
                "aflPercent": 10,
                "createdBy": "8edb3b9811f0433cbed346aaccab1d99",
                "currentMBp": '{"currency":"usd","amount":99700}',
                "displayName": "Marriage Accelerator Pro",
                "links": '{"links":[]}',
                "membership": 1,
                "owner": json.dumps(
                    {
                        "id": "8edb3b9811f0433cbed346aaccab1d99",
                        "name": "mindful-muslimah-6780",
                        "metadata": {
                            "bio": "A thought leader",
                            "disc_top": "star",
                            "last_offline": 1780573209056853356,
                            "location": "",
                        },
                        "created_at": "2024-09-05T11:47:38.059397Z",
                        "updated_at": "2026-06-04T19:11:05.577275Z",
                        "email": "",
                        "first_name": "Mindful",
                        "last_name": "Muslimah",
                    }
                ),
                "privacy": 1,
                "totalMembers": 17,
                "totalPosts": 24,
            },
            "createdAt": "2025-01-20T20:28:29.415683Z",
            "updatedAt": "2026-08-04T01:10:11.525448Z",
        }
    }
}

USER_GROUPS = [
    {
        "id": "0d961e00a9474daca54de06671bd4a74",
        "name": "wavyworld",
        "metadata": {
            "createdBy": "4e276ca370ad4f2698f5af39121f0f57",
            "displayName": "WavyWorld",
            "membership": 1,
            "totalMembers": 50381,
        },
        "createdAt": "2024-05-04T01:28:38.58324Z",
        "updatedAt": "2026-08-04T16:08:27.36426Z",
    },
    {
        "id": "96c35c0d17734d849c48380b74a7cbf1",
        "name": "content-academy-2049",
        "metadata": {
            "createdBy": "4e276ca370ad4f2698f5af39121f0f57",
            "displayName": "Short Form Academy",
            "membership": 1,
            "totalMembers": 12,
        },
        "createdAt": "2024-10-22T01:31:40.334488Z",
        "updatedAt": "2026-08-03T18:25:23.566631Z",
    },
]

USER_PAGE = {
    "pageProps": {
        "totalGroups": 6,
        "currentUser": {
            "id": "4e276ca370ad4f2698f5af39121f0f57",
            "name": "kane-kallaway-5536",
            "metadata": {
                "bio": "I help business owners grow faster",
                "lastOffline": "1784824596716232000",
                "linkFacebook": "",
                "linkInstagram": "https://www.instagram.com/kallaway",
                "linkLinkedin": "",
                "linkTwitter": "https://www.twitter.com/kanekallaway",
                "linkWebsite": "https://content.game",
                "linkYoutube": "https://www.youtube.com/@kallawaymarketing",
                "location": "New York, NY",
                "myersBriggs": "",
                "pictureBubble": "https://assets.skool.com/bubble-sm.jpg",
                "pictureProfile": "https://assets.skool.com/profile",
            },
            "createdAt": "2023-12-05T21:24:09.587415Z",
            "updatedAt": "2026-08-04T09:10:00.215167Z",
            "email": "",
            "firstName": "Kane",
            "lastName": "Kallaway",
            "timeZone": "America/Los_Angeles",
            "profileData": {
                "totalPosts": 294,
                "totalFollowers": 53272,
                "totalFollowing": 4,
                "totalSharedGroups": 0,
                "groupsMemberOf": None,
                "groupsCreatedByUser": USER_GROUPS,
                "totalContributions": 294,
                "totalGroups": 6,
            },
        },
    }
}

USER_PAGE_RENDER_ONLY = {"pageProps": {"renderData": {"user": USER_PAGE["pageProps"]["currentUser"]}}}


class TestDiscovery(unittest.TestCase):
    def test_groups_are_unwrapped(self) -> None:
        parsed = parser.parse_discovery(DISCOVERY)
        self.assertEqual(len(parsed["groups"]), 1)
        self.assertEqual(parsed["total"], 2)

    def test_group_row(self) -> None:
        raw = parser.parse_discovery(DISCOVERY)["groups"][0]
        row = parser.parse_group(raw)
        assert row is not None
        self.assertEqual(row["name"], "aivideobootcamp")
        self.assertEqual(row["display_name"], "AI Video Bootcamp")
        self.assertEqual(row["price_amount_cents"], 900)
        self.assertEqual(row["price_usd"], 9.0)
        self.assertEqual(row["price_currency"], "usd")
        self.assertEqual(row["price_interval"], "month")
        self.assertEqual(row["membership_model"], 2)
        self.assertEqual(row["total_members"], 26261)
        self.assertEqual(row["color"], "#E4A511")
        self.assertEqual(row["initials"], "AV")
        self.assertIsNotNone(row["created_at"])


class TestGroupDetail(unittest.TestCase):
    def test_detail_fields(self) -> None:
        row = parser.parse_group_detail(ABOUT_FREE)
        assert row is not None
        self.assertEqual(row["owner_id"], "4e276ca370ad4f2698f5af39121f0f57")
        self.assertEqual(row["owner_name"], "kane-kallaway-5536")
        self.assertEqual(row["privacy"], 1)
        self.assertIs(row["is_public"], True)
        self.assertEqual(row["membership_model"], 1)
        self.assertEqual(row["total_posts"], 3252)
        self.assertEqual(row["total_admins"], 3)
        self.assertEqual(row["total_online_members"], 358)
        self.assertEqual(row["total_rules"], 3)
        self.assertEqual(row["num_courses"], 19)
        self.assertEqual(row["num_modules"], 81)
        self.assertEqual(row["src_group"], "b68da5f5f7504b1f83d9c4c664b63c4f")
        self.assertIn("sandcastles.ai", row["links"])
        self.assertIsNone(row["price_amount_cents"])

    def test_price_from_current_mbp(self) -> None:
        row = parser.parse_group_detail(ABOUT_PAID)
        assert row is not None
        self.assertEqual(row["price_amount_cents"], 99700)
        self.assertEqual(float(row["price_usd"]), 997.0)
        self.assertEqual(row["price_currency"], "usd")
        self.assertIsNone(row["price_interval"])
        self.assertEqual(row["afl_percent"], 10)

    def test_owner_blob_is_a_full_user(self) -> None:
        owner = parser.group_owner(ABOUT_FREE)
        assert owner is not None
        self.assertEqual(owner["id"], "4e276ca370ad4f2698f5af39121f0f57")
        self.assertEqual(owner["first_name"], "Kane")
        self.assertEqual(owner["last_name"], "Kallaway")
        self.assertEqual(owner["full_name"], "Kane Kallaway")
        # In this blob the keys are snake_case
        self.assertEqual(owner["link_instagram"], "https://www.instagram.com/kallaway")
        self.assertEqual(owner["link_youtube"], "https://www.youtube.com/@kallawaymarketing")
        self.assertIsNone(owner["link_facebook"])  # empty string -> None
        self.assertEqual(owner["location"], "New York, NY")
        self.assertEqual(owner["location_source"], "profile")
        self.assertIsNotNone(owner["last_offline"])

    def test_owner_without_location_has_no_fallback_source(self) -> None:
        owner = parser.group_owner(ABOUT_PAID)
        assert owner is not None
        self.assertEqual(owner["name"], "mindful-muslimah-6780")
        self.assertNotIn("disc_top", owner)
        self.assertNotIn("myers_briggs", owner)
        self.assertIsNone(owner["location"])
        self.assertIsNone(owner["location_source"])


class TestUserPage(unittest.TestCase):
    def test_names_and_timezone(self) -> None:
        parsed = parser.parse_user_page(USER_PAGE)
        assert parsed is not None
        user = parsed["user"]
        self.assertEqual(user["name"], "kane-kallaway-5536")
        self.assertEqual(user["first_name"], "Kane")
        self.assertEqual(user["last_name"], "Kallaway")
        self.assertEqual(user["timezone"], "America/Los_Angeles")
        self.assertEqual(user["location"], "New York, NY")
        self.assertEqual(user["location_source"], "profile")
        # The removed columns are no longer present in the record
        for removed in ("email", "myers_briggs", "disc_top", "total_groups"):
            self.assertNotIn(removed, user)

    def test_social_links(self) -> None:
        user = parser.parse_user_page(USER_PAGE)["user"]
        self.assertEqual(user["link_instagram"], "https://www.instagram.com/kallaway")
        self.assertEqual(user["link_twitter"], "https://www.twitter.com/kanekallaway")
        self.assertEqual(user["link_website"], "https://content.game")
        self.assertEqual(user["link_youtube"], "https://www.youtube.com/@kallawaymarketing")
        self.assertIsNone(user["link_linkedin"])
        self.assertEqual(user["avatar_bubble_url"], "https://assets.skool.com/bubble-sm.jpg")

    def test_counters(self) -> None:
        user = parser.parse_user_page(USER_PAGE)["user"]
        self.assertEqual(user["total_followers"], 53272)
        self.assertEqual(user["total_following"], 4)
        self.assertEqual(user["total_contributions"], 294)

    def test_user_groups(self) -> None:
        parsed = parser.parse_user_page(USER_PAGE)
        rows = [parser.parse_group(raw) for raw in parsed["owned"]]
        names = sorted(row["name"] for row in rows if row)
        self.assertEqual(names, ["content-academy-2049", "wavyworld"])

    def test_member_groups_are_separated(self) -> None:
        """Member-of groups land under `member`, not `owned`."""
        payload = copy.deepcopy(USER_PAGE)
        profile = payload["pageProps"]["currentUser"]["profileData"]
        foreign = {
            "id": "ffffffffffffffffffffffffffffffff",
            "name": "someone-elses-group",
            "metadata": {"displayName": "Not Mine", "privacy": 1},
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        profile["groupsMemberOf"] = [foreign]

        parsed = parser.parse_user_page(payload)
        assert parsed is not None
        owned_names = sorted(
            row["name"]
            for row in (parser.parse_group(raw) for raw in parsed["owned"])
            if row
        )
        member_names = sorted(
            row["name"]
            for row in (parser.parse_group(raw) for raw in parsed["member"])
            if row
        )
        self.assertEqual(owned_names, ["content-academy-2049", "wavyworld"])
        self.assertEqual(member_names, ["someone-elses-group"])

    def test_render_data_fallback(self) -> None:
        parsed = parser.parse_user_page(USER_PAGE_RENDER_ONLY)
        assert parsed is not None
        self.assertEqual(parsed["user"]["first_name"], "Kane")
        self.assertEqual(len(parsed["owned"]), 2)


class TestHelpers(unittest.TestCase):
    def test_nanosecond_timestamp(self) -> None:
        moment = parser._ns_dt("1784824596716232000")
        assert moment is not None
        self.assertEqual(moment.year, 2026)

    def test_key_normalization(self) -> None:
        self.assertEqual(parser._norm_key("first_name"), parser._norm_key("firstName"))
        self.assertEqual(parser._norm_key("link_youtube"), parser._norm_key("linkYoutube"))

    def test_plans_api_is_gone(self) -> None:
        for attribute in ("find_plan_list", "parse_plan"):
            self.assertFalse(hasattr(parser, attribute))

    def test_is_public_detection(self) -> None:
        self.assertIs(parser.parse_is_public({"privacy": 1}), True)
        self.assertIs(parser.parse_is_public({"privacy": 2}), False)
        self.assertIs(parser.parse_is_public({"privacy": 3}), False)
        # If the site ever returns a string
        self.assertIs(parser.parse_is_public({"groupType": "private"}), False)
        self.assertIs(parser.parse_is_public({"visibility": "PUBLIC"}), True)
        # Unknown -> None (not False)
        self.assertIsNone(parser.parse_is_public({}))


if __name__ == "__main__":
    unittest.main()
