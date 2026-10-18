"""Tests for the analyze module on synthetic, predictable data.

If pandas/numpy are not installed, the tests are skipped (like test_db_smoke).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:  # pragma: no cover - depends on the environment
    import numpy as np
    import pandas as pd

    from skool.analyze import charts as charts_module
    from skool.analyze import loader, report, stats as st
    from skool.analyze.analyses import members as members_module  # noqa: F401
    from skool.analyze.cli import run_analysis
    from skool.analyze.registry import REGISTRY, Context, resolve, run_analyses

    DEPS_OK = True
except ImportError:  # pragma: no cover
    DEPS_OK = False

PRICES = [9.0, 19.0, 49.0, 97.0, 297.0]
CATEGORIES = ["business", "money", "tech", "health"]
LANGUAGES = ["en", "es", "fr"]
OWNERS = [f"u{index}" for index in range(6)]


def build_groups(count: int = 120) -> "pd.DataFrame":
    """Half paid, half free; members are inverse to price so the negative correlation is deterministic."""
    rows = []
    for index in range(count):
        paid = index % 2 == 0
        price = PRICES[(index // 2) % len(PRICES)] if paid else None
        members = int(5000 / price) if paid else 100 + index
        interval = ("month" if index % 4 == 0 else "year") if paid else None
        rows.append(
            {
                "id": f"g{index:04d}",
                "name": f"group-{index}",
                "display_name": f"Ultimate Academy {index}",
                "description": "learn trading and grow together" * (1 + index % 4),
                "price_usd": price,
                "price_amount_cents": None if price is None else price * 100,
                "price_currency": "usd" if paid else None,
                "price_interval": interval,
                "membership_model": "paid" if paid else "free",
                "privacy": 1 if index % 3 else 2,
                "is_public": bool(index % 3),
                "total_members": members,
                "total_online_members": max(0, members // 25),
                "total_posts": members * 2,
                "total_admins": 1 + index % 4,
                "total_rules": index % 6,
                "num_courses": index % 9,
                "num_modules": index % 20,
                "afl_percent": 10.0 if index % 5 == 0 else None,
                "links": None,
                "owner_id": OWNERS[index % len(OWNERS)],
                "owner_name": "owner",
                "category_slug": CATEGORIES[index % len(CATEGORIES)],
                "language": LANGUAGES[index % len(LANGUAGES)],
                "price_bucket": "paid" if paid else "free",
                "sort_seen": "trending",
                "discovered_via": "browse" if index % 2 else "search",
                "detail_fetched": index % 10 != 0,
                "created_at": pd.Timestamp("2022-01-01", tz="UTC") + pd.Timedelta(days=index * 7),
                "updated_at": pd.Timestamp("2025-06-01", tz="UTC") + pd.Timedelta(days=index),
                "scraped_at": pd.Timestamp("2026-08-01", tz="UTC"),
                "has_landing_page": index % 2 == 0,
                "has_cover": True,
                "has_logo": index % 4 != 0,
            }
        )
    return pd.DataFrame(rows)


def build_users() -> "pd.DataFrame":
    rows = []
    for index, user_id in enumerate(OWNERS):
        rows.append(
            {
                "id": user_id,
                "name": f"handle-{index}",
                "first_name": f"First{index}",
                "last_name": f"Last{index}",
                "full_name": f"First{index} Last{index}",
                "bio": "coach and builder",
                "location": ["New York, NY", "London, UK", "Dubai, UAE", None][index % 4],
                "location_source": "profile",
                "timezone": ["America/New_York", "Europe/London", "Asia/Dubai", None][index % 4],
                "has_avatar": True,
                "link_facebook": None,
                "link_instagram": "https://instagram.com/x" if index % 2 == 0 else None,
                "link_linkedin": "https://linkedin.com/in/x" if index % 3 == 0 else None,
                "link_twitter": "https://x.com/x",
                "link_website": None,
                "link_youtube": "https://youtube.com/@x" if index % 2 else None,
                "last_offline": pd.Timestamp("2026-07-01", tz="UTC"),
                "total_followers": 100 * (index + 1),
                "total_following": 10,
                "total_posts": 20 * index,
                "total_contributions": 50 * index,
                "groups_fetched": True,
                "created_at": pd.Timestamp("2021-01-01", tz="UTC"),
                "updated_at": pd.Timestamp("2026-08-01", tz="UTC"),
                "scraped_at": pd.Timestamp("2026-08-01", tz="UTC"),
            }
        )
    return pd.DataFrame(rows)


def build_dataset():
    groups = build_groups()
    users = build_users()
    links = groups[["owner_id", "id"]].rename(columns={"owner_id": "user_id", "id": "group_id"})
    return loader.from_frames(groups, users, links, source="test")


@unittest.skipUnless(DEPS_OK, "pandas/numpy not installed")
class DerivedColumnsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = build_dataset()

    def test_price_flags(self) -> None:
        g = self.data.groups
        self.assertEqual(int(g["is_paid"].sum()), 60)
        self.assertTrue(g["price_known"].all())
        paid = g[g["is_paid"]]
        self.assertTrue((paid["price_usd"] > 0).all())

    def test_price_tier_edges(self) -> None:
        g = self.data.groups.set_index("price_usd")
        self.assertEqual(str(g.loc[9.0, "price_tier"].iloc[0]), "$1-9")
        self.assertEqual(str(g.loc[19.0, "price_tier"].iloc[0]), "$10-19")
        self.assertEqual(str(g.loc[49.0, "price_tier"].iloc[0]), "$30-49")
        self.assertEqual(str(g.loc[97.0, "price_tier"].iloc[0]), "$50-99")
        self.assertEqual(str(g.loc[297.0, "price_tier"].iloc[0]), "$200-499")
        free = self.data.free
        self.assertEqual(set(free["price_tier"].astype(str)), {"Free"})

    def test_monthly_price_and_mrr(self) -> None:
        g = self.data.groups
        yearly = g[(g["price_interval"] == "year") & (g["price_usd"] == 19.0)].iloc[0]
        self.assertAlmostEqual(float(yearly["price_monthly_usd"]), 19.0 / 12.0, places=6)
        monthly = g[(g["price_interval"] == "month") & (g["price_usd"] == 9.0)].iloc[0]
        self.assertAlmostEqual(float(monthly["price_monthly_usd"]), 9.0, places=6)
        self.assertAlmostEqual(
            float(monthly["est_mrr_usd"]), 9.0 * float(monthly["total_members"]), places=4
        )

    def test_size_tier_and_visibility(self) -> None:
        g = self.data.groups
        self.assertIn("size_tier", g.columns)
        self.assertTrue(set(g["visibility"]) <= {"public", "private", "unknown"})
        self.assertAlmostEqual(float((g["visibility"] == "public").mean()), 2 / 3, places=2)

    def test_owner_portfolio(self) -> None:
        users = self.data.users
        self.assertEqual(sorted(users["owned_groups"].tolist()), [20.0] * 6)
        self.assertTrue((users["social_count"] >= 1).all())
        self.assertTrue((users["owned_members"] > 0).all())

    def test_filters(self) -> None:
        paid_only = loader.apply_filters(self.data, paid_only=True)
        self.assertEqual(len(paid_only.groups), 60)
        big = loader.apply_filters(self.data, min_members=200)
        self.assertTrue((big.groups["total_members"] >= 200).all())
        public = loader.apply_filters(self.data, public_only=True)
        self.assertTrue(public.groups["is_public"].all())


@unittest.skipUnless(DEPS_OK, "pandas/numpy not installed")
class StatsTest(unittest.TestCase):
    def test_gini_bounds(self) -> None:
        self.assertAlmostEqual(st.gini(pd.Series([5, 5, 5, 5])), 0.0, places=6)
        self.assertGreater(st.gini(pd.Series([0, 0, 0, 100])), 0.6)

    def test_negative_correlation_detected(self) -> None:
        prices = pd.Series([9, 19, 49, 97, 297] * 6, dtype="float64")
        members = 5000 / prices
        corr = st.correlate(prices, members, "price", "members")
        self.assertIsNotNone(corr.spearman)
        self.assertLess(corr.spearman, -0.9)
        self.assertIn("inverse", corr.direction_fa())

    def test_top_share_and_buckets(self) -> None:
        shares = st.top_share(pd.Series(list(range(1, 101))))
        self.assertGreater(shares["top_10pct"], shares["top_1pct"])
        self.assertLessEqual(shares["top_20pct"], 1.0)


@unittest.skipUnless(DEPS_OK, "pandas/numpy not installed")
class RunAllTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = build_dataset()
        cls.tmp = tempfile.TemporaryDirectory()
        maker = charts_module.ChartMaker(Path(cls.tmp.name) / "charts", enabled=False)
        cls.results = run_analyses(Context(data=cls.data, charts=maker))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_registry_size(self) -> None:
        self.assertGreaterEqual(len(REGISTRY), 31)
        for key in ("price_distribution", "price_vs_members", "members_distribution", "outliers"):
            self.assertIn(key, REGISTRY)

    def test_no_analysis_raises(self) -> None:
        failed = {result.key: result.error for result in self.results if result.error}
        self.assertEqual(failed, {})

    def test_every_analysis_produces_output(self) -> None:
        silent = [
            result.key
            for result in self.results
            if not result.lines and not result.tables and not result.notes
        ]
        self.assertEqual(silent, [])

    def test_price_vs_members_is_negative(self) -> None:
        found = {result.key: result for result in self.results}["price_vs_members"]
        self.assertLess(found.metrics["spearman"], 0.0)

    def test_highlight_metrics_exist(self) -> None:
        merged = {
            f"{result.key}.{name}": value
            for result in self.results
            for name, value in result.metrics.items()
        }
        wanted = [
            item[0] if isinstance(item, (tuple, list)) else item for item in report.HIGHLIGHTS
        ]
        missing = [key for key in wanted if key not in merged]
        self.assertEqual(missing, [])
        self.assertGreaterEqual(len(wanted), 13)

    def test_selection_helpers(self) -> None:
        self.assertEqual([spec.key for spec in resolve(only=["outliers"])], ["outliers"])
        self.assertNotIn("outliers", [spec.key for spec in resolve(skip=["outliers"])])
        self.assertTrue(resolve(only_groups=["price"]))
        with self.assertRaises(KeyError):
            resolve(only=["no_such_analysis"])

    def test_console_report_renders(self) -> None:
        text = report.render_console(self.results, self.data.info())
        self.assertIn("data analysis", text)
        self.assertGreater(len(text.splitlines()), 100)


@unittest.skipUnless(DEPS_OK, "pandas/numpy not installed")
class EndToEndTest(unittest.TestCase):
    def test_run_analysis_writes_files(self) -> None:
        data = build_dataset()
        with tempfile.TemporaryDirectory() as tmp:
            outcome = run_analysis(
                data=data,
                out_dir=tmp,
                charts=charts_module.MATPLOTLIB_OK,
                only=["price_distribution", "members_distribution", "integrity"],
                progress=False,
                csv_tables=True,
            )
            self.assertEqual(outcome["failed"], [])
            self.assertEqual(len(outcome["results"]), 3)
            self.assertTrue(Path(tmp, "report.md").exists())
            self.assertTrue(Path(tmp, "report.json").exists())
            self.assertTrue(any(Path(tmp, "tables").glob("*.csv")))
            self.assertIn("price_distribution.free_share", outcome["metrics"])
            if charts_module.MATPLOTLIB_OK:
                self.assertTrue(any(Path(tmp, "charts").glob("*.png")))

    def test_text_only_analysis_has_no_charts(self) -> None:
        data = build_dataset()
        with tempfile.TemporaryDirectory() as tmp:
            outcome = run_analysis(
                data=data,
                out_dir=tmp,
                charts=False,
                only=["integrity", "currency_mix", "outliers", "discovery_bias"],
                progress=False,
                write_reports=False,
            )
            for result in outcome["results"]:
                self.assertEqual(result.charts, [])
                self.assertTrue(result.lines or result.tables)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
