"""Smoke tests for the database layer — only when Postgres is available.

Warning: this test drops and rebuilds the schema. Run it against a temporary database.

    SKOOL_DB_TESTS=1 python -m unittest skool.tests.test_db_smoke -v

What it guarantees:
  * two records with the same id in one batch do not raise an ON CONFLICT error (_dedupe)
  * KEEP_FIRST fields are not changed by a second run
  * a NULL value does not wipe existing data
  * the detail_fetched flag is not cleared by a later upsert
  * an unknown parser key does not cause an error
  * the user's timezone and social links are saved
  * running link_user_groups twice does not create duplicate records
  * parallel inserts are not lost
  * pending_owner_users is empty after mark_user_scraped
"""

from __future__ import annotations

import asyncio
import os
import unittest

# Database dependencies are optional; without them the whole file must be skipped
# (a module-level import is not prevented by skipUnless, so it goes in a try)
try:
    from sqlalchemy import select

    from ..db import repository as repo
    from ..db.db import dispose_db, reset_db, session_scope
    from ..db.models import Group, User, UserGroup

    DEPS_OK = True
except ModuleNotFoundError:  # sqlalchemy/asyncpg not installed
    DEPS_OK = False

RUN = os.getenv("SKOOL_DB_TESTS") == "1" and DEPS_OK


def _group(gid: str, name: str, **extra) -> dict:
    row = {"id": gid, "name": name, "display_name": name.title()}
    row.update(extra)
    return row


@unittest.skipUnless(RUN, "requires SKOOL_DB_TESTS=1 to run")
class TestRepository(unittest.TestCase):
    def setUp(self) -> None:
        asyncio.run(reset_db())

    def tearDown(self) -> None:
        asyncio.run(dispose_db())

    def test_dedupe_same_id_in_one_batch(self) -> None:
        async def scenario() -> int:
            async with session_scope() as session:
                await repo.upsert_groups(
                    session,
                    [
                        _group("g1", "alpha", total_members=1),
                        _group("g1", "alpha", total_members=2),
                    ],
                )
            async with session_scope() as session:
                return (await repo.counts(session))["groups"]

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_keep_first_and_null_preservation(self) -> None:
        async def scenario():
            async with session_scope() as session:
                await repo.upsert_groups(
                    session,
                    [_group("g1", "alpha", category_slug="tech", total_members=10)],
                )
            async with session_scope() as session:
                await repo.upsert_groups(
                    session,
                    [
                        _group(
                            "g1",
                            "alpha",
                            category_slug="business",
                            total_members=None,
                        )
                    ],
                )
            async with session_scope() as session:
                result = await session.execute(
                    select(Group.category_slug, Group.total_members).where(
                        Group.id == "g1"
                    )
                )
                return result.one()

        category_slug, total_members = asyncio.run(scenario())
        self.assertEqual(category_slug, "tech")
        self.assertEqual(total_members, 10)

    def test_detail_flag_survives_later_upsert(self) -> None:
        async def scenario():
            async with session_scope() as session:
                await repo.upsert_group(session, _group("g1", "alpha"))
                await repo.mark_detail_fetched(session, ["g1"])
            async with session_scope() as session:
                await repo.upsert_group(session, _group("g1", "alpha"))
            async with session_scope() as session:
                return await repo.pending_detail_groups(session)

        self.assertEqual(asyncio.run(scenario()), [])

    def test_unknown_keys_are_dropped(self) -> None:
        async def scenario() -> int:
            async with session_scope() as session:
                return await repo.upsert_groups(
                    session, [_group("g1", "alpha", totally_unknown_column="x")]
                )

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_user_timezone_and_links(self) -> None:
        async def scenario():
            async with session_scope() as session:
                await repo.upsert_user(
                    session,
                    {
                        "id": "u1",
                        "name": "kane-kallaway-5536",
                        "first_name": "Kane",
                        "last_name": "Kallaway",
                        "full_name": "Kane Kallaway",
                        "timezone": "America/Los_Angeles",
                        "link_instagram": "https://www.instagram.com/kallaway",
                        "link_facebook": None,
                    },
                )
            async with session_scope() as session:
                result = await session.execute(
                    select(
                        User.first_name,
                        User.last_name,
                        User.timezone,
                        User.link_instagram,
                        User.link_facebook,
                    ).where(User.id == "u1")
                )
                return result.one()

        first, last, tz, insta, facebook = asyncio.run(scenario())
        self.assertEqual((first, last), ("Kane", "Kallaway"))
        self.assertEqual(tz, "America/Los_Angeles")
        self.assertEqual(insta, "https://www.instagram.com/kallaway")
        self.assertIsNone(facebook)

    def test_link_user_groups_is_idempotent(self) -> None:
        async def scenario() -> int:
            async with session_scope() as session:
                await repo.upsert_groups(
                    session, [_group("g1", "alpha"), _group("g2", "beta")]
                )
                await repo.upsert_user(session, {"id": "u1", "name": "kane"})
                await repo.link_user_groups(session, "u1", ["g1", "g2", "g1"])
            async with session_scope() as session:
                await repo.link_user_groups(session, "u1", ["g1", "g2"])
            async with session_scope() as session:
                return (await repo.counts(session))["user_groups"]

        self.assertEqual(asyncio.run(scenario()), 2)

    def test_link_roles_owner_wins_and_no_duplicates(self) -> None:
        async def scenario() -> list[tuple[str, str]]:
            async with session_scope() as session:
                await repo.upsert_user(session, {"id": "u1", "name": "kane"})
                await repo.upsert_groups(
                    session, [_group("g1", "alpha"), _group("g2", "beta")]
                )
                await repo.link_user_groups(session, "u1", ["g1"], role="owner")
                await repo.link_user_groups(session, "u1", ["g2"], role="member")
            async with session_scope() as session:
                # upgrade member->owner, re-link as member, add duplicate
                await repo.link_user_groups(session, "u1", ["g2"], role="owner")
                await repo.link_user_groups(session, "u1", ["g1", "g1"], role="member")
            async with session_scope() as session:
                result = await session.execute(
                    select(UserGroup.group_id, UserGroup.role).where(
                        UserGroup.user_id == "u1"
                    )
                )
                return [(row[0], row[1]) for row in result.all()]

        rows = asyncio.run(scenario())
        self.assertEqual(len(rows), 2)  # no duplicates
        roles = dict(rows)
        self.assertEqual(roles["g1"], "owner")  # owner never downgraded
        self.assertEqual(roles["g2"], "owner")  # member upgraded to owner

    def test_sparse_rows_batch_does_not_overshoot_bind_cap(self) -> None:
        """Regression: rows carrying fewer keys than table columns must chunk
        against the REAL column count. Previously `_batches` derived the per-row
        param count from the row keys (e.g. 39) while `pg_insert(Group)` binds
        all 41 table columns, so a chunk could reach ~33,600 params and trip the
        Postgres ~32,767 bind-parameter cap on big slices."""
        from ..db.repository import _BIND_LIMIT

        async def scenario() -> int:
            # ~1000 sparse rows (only a handful of keys) — the failing shape
            rows = [
                {
                    "id": f"g{i}",
                    "name": f"group-{i}",
                    "display_name": f"G{i}",
                    "total_members": i,
                }
                for i in range(1000)
            ]
            async with session_scope() as session:
                await repo.upsert_groups(session, rows)
            async with session_scope() as session:
                return (await repo.counts(session))["groups"]

        self.assertEqual(asyncio.run(scenario()), 1000)
        # sanity: the chosen chunk budget really is under the Postgres cap
        self.assertLess(_BIND_LIMIT, 32767)

    def test_concurrent_upserts(self) -> None:
        async def scenario() -> int:
            async def writer(index: int) -> None:
                async with session_scope() as session:
                    await repo.upsert_group(
                        session, _group(f"g{index}", f"group-{index}")
                    )

            await asyncio.gather(*(writer(i) for i in range(7)))
            async with session_scope() as session:
                return (await repo.counts(session))["groups"]

        self.assertEqual(asyncio.run(scenario()), 7)

    def test_pending_owner_users(self) -> None:
        async def scenario():
            async with session_scope() as session:
                await repo.upsert_group(
                    session, _group("g1", "alpha", owner_id="u1", owner_name="kane")
                )
            async with session_scope() as session:
                before = await repo.pending_owner_users(session)
            async with session_scope() as session:
                await repo.upsert_user(session, {"id": "u1", "name": "kane"})
                await repo.mark_user_scraped(session, ["u1"])
            async with session_scope() as session:
                after = await repo.pending_owner_users(session)
            return before, after

        before, after = asyncio.run(scenario())
        self.assertEqual(before, [("u1", "kane")])
        self.assertEqual(after, [])


if __name__ == "__main__":
    unittest.main()
