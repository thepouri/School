"""Tests for the group-fetch flow (owner + their groups, inline, DB-checked).

Offline (no network, no DB): we stub the client and the repository so we can
drive `process_group` / `process_user` and prove:
  * a group already complete in the DB is not re-requested
  * a user already complete in the DB is not re-requested
  * fetching a group writes the group + owner, then the owner's profile with
    their owned (role=owner) and member (role=member) groups in one pass
  * there is no deep recursion into member-group owners

    python -m unittest skool.tests.test_snowball -v
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from ..pipeline import Pipeline


class _FakeUserPage:
    def __init__(self, name: str, owned: list[str], members: list[str]) -> None:
        self.name = name
        self.owned = owned
        self.members = members

    def payload(self) -> dict:
        return {
            "pageProps": {
                "currentUser": {
                    "id": f"id-{self.name}",
                    "name": self.name,
                    "firstName": self.name.title(),
                    "lastName": "",
                    "profileData": {
                        "groupsCreatedByUser": [self._group(g) for g in self.owned],
                        "groupsMemberOf": [self._group(g) for g in self.members],
                    },
                }
            }
        }

    def _group(self, name: str) -> dict:
        return {
            "id": f"g-{name}",
            "name": name,
            "metadata": {"displayName": name.title()},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
        }


class _FakeGroupPage:
    def __init__(self, name: str, owner: str) -> None:
        self.name = name
        self.owner = owner

    def payload(self) -> dict:
        return {
            "pageProps": {
                "currentGroup": {
                    "id": f"g-{self.name}",
                    "name": self.name,
                    "metadata": {
                        "displayName": self.name.title(),
                        "createdBy": f"id-{self.owner}",
                        "owner": {"id": f"id-{self.owner}", "name": self.owner},
                    },
                }
            }
        }


class _FakeClient:
    def __init__(self, users: dict, groups: dict | None = None) -> None:
        self.users = users
        self.groups = groups or {}

    async def user_profile(self, user_name: str) -> dict | None:
        page = self.users.get(user_name)
        return page.payload() if page else None

    async def group_about(self, group_name: str) -> dict | None:
        page = self.groups.get(group_name)
        return page.payload() if page else None

    @property
    def stats(self) -> dict:
        return {}


async def _async_noop(*args, **kwargs):
    return None


class TestFetchFlow(unittest.TestCase):
    def _pipeline(self, client: _FakeClient) -> Pipeline:
        return Pipeline(client=client, fetch_users=True)

    def _patch_repo(self):
        repo_p = patch("skool.pipeline.repo")
        scope_p = patch("skool.pipeline.session_scope")
        repo = repo_p.start()
        scope = scope_p.start()
        self.addCleanup(repo_p.stop)
        self.addCleanup(scope_p.stop)
        scope.return_value.__aenter__ = _async_noop
        scope.return_value.__aexit__ = _async_noop

        calls = {"upsert_user": 0, "upsert_groups": 0}

        async def noop(*a, **k):
            return 1

        async def count_upsert_user(*a, **k):
            calls["upsert_user"] += 1
            return None

        async def count_upsert_groups(*a, **k):
            calls["upsert_groups"] += 1
            return 1

        repo.upsert_user = count_upsert_user
        repo.upsert_group = noop
        repo.upsert_groups = count_upsert_groups
        repo.link_user_groups = noop
        repo.mark_user_scraped = noop
        repo.mark_detail_fetched = noop
        repo.group_is_fetched = _async_noop  # returns None (not fetched)
        repo.user_is_scraped = _async_noop  # returns None (not scraped)
        return repo, calls

    def test_group_skipped_when_already_fetched(self) -> None:
        client = _FakeClient(users={}, groups={"g1": _FakeGroupPage("g1", "owner1")})
        pipe = self._pipeline(client)
        repo, calls = self._patch_repo()
        repo.group_is_fetched = _group_true  # already fetched
        asyncio.run(pipe.process_group("g1", "g1", None))
        self.assertEqual(pipe.stats.groups_detailed, 0)
        # no request made for the group
        self.assertEqual(calls["upsert_groups"], 0)

    def test_user_skipped_when_already_scraped(self) -> None:
        client = _FakeClient(users={"owner1": _FakeUserPage("owner1", [], [])})
        pipe = self._pipeline(client)
        repo, calls = self._patch_repo()
        repo.user_is_scraped = _user_true
        asyncio.run(pipe.process_user("owner1", None))
        self.assertEqual(pipe.stats.users_written, 0)
        self.assertEqual(calls["upsert_user"], 0)

    def test_group_writes_owner_and_owner_groups_inline(self) -> None:
        # group g1 owned by owner1; owner1 owns g1 and is member of m1
        client = _FakeClient(
            users={"owner1": _FakeUserPage("owner1", owned=["g1"], members=["m1"])},
            groups={"g1": _FakeGroupPage("g1", "owner1")},
        )
        pipe = self._pipeline(client)
        repo, calls = self._patch_repo()
        asyncio.run(pipe.process_group("g1", "g1", None))
        self.assertGreaterEqual(pipe.stats.groups_detailed, 1)
        self.assertGreaterEqual(pipe.stats.users_written, 1)
        # owner profile fetched once (upsert_user for owner block + owner profile)
        self.assertEqual(calls["upsert_user"], 2)


async def _group_true(session, group_id: str) -> bool:
    return True


async def _user_true(session, user_name: str) -> bool:
    return True


if __name__ == "__main__":
    unittest.main()
