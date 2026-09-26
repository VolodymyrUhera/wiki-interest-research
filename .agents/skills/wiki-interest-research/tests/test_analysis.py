"""Offline checks of the metrics.

Run from the skill dir: uv run --with "matplotlib>=3.8,<4" python -m unittest discover -s tests
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import analysis  # noqa: E402

START, END = date(2024, 1, 1), date(2025, 12, 31)
DAYS = analysis.days_between(START, END)
MONTHS = analysis.month_list(START, END)
FLAT_WIKI = {m: 1_000_000 for m in MONTHS}


def series(fn):
    return {d: fn(i) for i, d in enumerate(DAYS)}


class AnalyzeTest(unittest.TestCase):
    def test_steady_growth_is_high_confidence(self):
        m = analysis.analyze(series(lambda i: 100 + i // 5), FLAT_WIKI, START, END)
        self.assertEqual(m["direction"], "growing")
        self.assertEqual(m["confidence"], "high")
        self.assertLess(m["mann_kendall_p"], 0.01)
        self.assertAlmostEqual(m["growth_normalized"], m["growth_robust"])

    def test_single_spike_is_flagged_and_not_growth(self):
        m = analysis.analyze(series(lambda i: 5000 if i == len(DAYS) - 40 else 100), FLAT_WIKI, START, END)
        self.assertEqual(m["direction"], "flat")
        self.assertGreater(m["growth_total"], 0.1)  # the naive number looks like growth...
        self.assertTrue(any("spike-driven" in f for f in m["flags"]))  # ...but it is flagged
        self.assertEqual(m["spike_days"][0]["views"], 5000)

    def test_growth_near_cutoff_is_not_called_spike_driven(self):
        # typical day ~+9%, total ~+10%: verdict words differ but the numbers agree
        m = analysis.analyze(series(lambda i: 100 if i < len(DAYS) // 2 else 109 + i % 3), FLAT_WIKI, START, END)
        self.assertFalse(any("spike-driven" in f for f in m["flags"]), m["flags"])

    def test_new_article_gets_no_growth_number_and_low_confidence(self):
        m = analysis.analyze(series(lambda i: 0 if i < len(DAYS) // 2 else 100), FLAT_WIKI, START, END)
        self.assertIsNone(m["growth_robust"])
        self.assertEqual(m["confidence"], "low")

    def test_article_created_mid_period_is_flagged(self):
        m = analysis.analyze(series(lambda i: 0 if i < 60 else 100), FLAT_WIKI, START, END)
        self.assertTrue(any("created or renamed" in f for f in m["flags"]), m["flags"])

    def test_growth_that_only_follows_wiki_traffic_is_flagged(self):
        wiki = {m: 1_000_000 * (2 if i >= 12 else 1) for i, m in enumerate(MONTHS)}
        m = analysis.analyze(series(lambda i: 100 + i // 10), wiki, START, END)
        self.assertEqual(m["direction"], "growing")
        self.assertLess(m["growth_normalized"], 0)
        self.assertTrue(any("reverses" in f for f in m["flags"]))

    def test_low_volume_is_low_confidence(self):
        m = analysis.analyze(series(lambda i: i % 3), FLAT_WIKI, START, END)
        self.assertEqual(m["confidence"], "low")

    def test_short_period_warns_about_seasonality(self):
        end = date(2024, 6, 30)
        m = analysis.analyze({d: 100 for d in analysis.days_between(START, end)}, FLAT_WIKI, START, end)
        self.assertEqual(m["window"], "last 3 vs first 3 months")
        self.assertTrue(any("seasonality" in f for f in m["flags"]))

    def test_unpublished_wiki_month_is_flagged_not_counted_as_zero(self):
        wiki = dict(FLAT_WIKI)
        del wiki["2025-12"]  # last month's whole-wiki total not published yet
        m = analysis.analyze(series(lambda i: 100), wiki, START, END)
        self.assertIsNone(m["growth_project"])
        self.assertIsNone(m["growth_normalized"])
        self.assertTrue(any("2025-12" in f for f in m["flags"]))

    def test_missing_days_count_as_zero(self):
        m = analysis.analyze({}, FLAT_WIKI, START, END)
        self.assertEqual(m["total_views"], 0)
        self.assertEqual(m["direction"], "insufficient data")


if __name__ == "__main__":
    unittest.main()
