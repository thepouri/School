"""Tests for DiscoveryPlanner (faceting, splitting, keyword harvesting)."""

import pytest
from skool.db.db import session_scope
from skool.db.models import DiscoveryQuery
from skool.discovery_planner import DiscoveryPlanner, hash_params


def test_hash_params_determinism():
    p1 = {"c": "business", "lang": "english", "pr": None}
    p2 = {"lang": "english", "c": "business"}

    assert hash_params(p1) == hash_params(p2)
    assert len(hash_params(p1)) == 40


def test_should_split_and_generate_children():
    # When total_hint > received, should split
    assert DiscoveryPlanner.should_split(total_hint=500, received_count=200, hit_cap=False, depth=0) is True

    # Depth 5 should not split (safeguard)
    assert DiscoveryPlanner.should_split(total_hint=500, received_count=200, hit_cap=True, depth=5) is False

    # Generation of price children from depth 0
    params = {"c": "crypto", "lang": "english"}
    children = DiscoveryPlanner.generate_children(params, depth=0)

    assert len(children) == 2
    assert {"c": "crypto", "lang": "english", "pr": "free"} in children
    assert {"c": "crypto", "lang": "english", "pr": "paid"} in children


@pytest.mark.asyncio
async def test_seed_and_query_flow():
    async with session_scope() as session:
        seeded = await DiscoveryPlanner.seed_root_queries(
            session=session,
            categories=["crypto"],
            languages=["english"],
            prices=["none"],
            sorts=["rank"],
        )
        assert seeded >= 1

        next_q = await DiscoveryPlanner.get_next_query(session)
        assert next_q is not None
        assert next_q.params.get("c") == "crypto"

        # Record result with hit_cap -> triggers automatic splitting into children
        await DiscoveryPlanner.record_query_result(
            session=session,
            query_id=next_q.id,
            pages_done=34,
            new_groups=50,
            seen_groups=1000,
            total_hint=3000,
            hit_cap=True,
        )

        updated_q = await session.get(DiscoveryQuery, next_q.id)
        assert updated_q.status == "split"
        assert updated_q.hit_cap is True

        # Clean up created query and children
        await session.delete(updated_q)
