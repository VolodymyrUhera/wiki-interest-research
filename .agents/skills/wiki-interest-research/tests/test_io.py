"""Offline checks of the cache, CLI parsing and report rules.

Run from the skill dir: uv run --with "matplotlib>=3.8,<4" python -m unittest discover -s tests
"""
import argparse
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import wiki_interest  # noqa: E402
import wikiapi  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(wikiapi, "CACHE_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = 0

    def fake_urlopen(self, req, timeout):
        self.calls += 1
        return FakeResponse(json.dumps({"n": self.calls}).encode())

    def get(self, ttl):
        with mock.patch("urllib.request.urlopen", self.fake_urlopen):
            return wikiapi.get_json("https://example.org/x", ttl=ttl)

    def test_short_ttl_set_at_write_survives_later_permanent_reads(self):
        self.assertEqual(self.get(ttl=3600), {"n": 1})
        self.assertEqual(self.get(ttl=None), {"n": 1})  # still fresh
        with mock.patch("time.time", return_value=wikiapi.time.time() + 7200):
            # The caller now asks for "forever", but the entry was stored as incomplete: it must be refetched.
            self.assertEqual(self.get(ttl=None), {"n": 2})

    def test_api_error_payload_is_not_cached(self):
        payload = {"error": {"code": "maxlag"}}
        with mock.patch("urllib.request.urlopen", lambda req, timeout: FakeResponse(json.dumps(payload).encode())):
            valid = lambda d: "error" not in d  # noqa: E731
            self.assertEqual(wikiapi.get_json("https://example.org/e", valid=valid), payload)
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_read_timeout_is_retried(self):
        replies = iter([TimeoutError("read timed out"), FakeResponse(b'{"ok": 1}')])

        def flaky(req, timeout):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        with mock.patch("urllib.request.urlopen", flaky), mock.patch("time.sleep"):
            self.assertEqual(wikiapi.get_json("https://example.org/t"), {"ok": 1})

    def test_corrupt_or_old_format_entry_is_refetched(self):
        self.get(ttl=None)
        path = next(Path(self.tmp.name).glob("*.json"))
        for bad in ("", '{"items": [', '{"items": []}'):
            path.write_text(bad)
            calls = self.calls
            self.get(ttl=None)
            self.assertEqual(self.calls, calls + 1)
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])


class CliTest(unittest.TestCase):
    def test_future_or_current_end_month_is_rejected(self):
        args = argparse.Namespace(end=wiki_interest.month_arg("2099-01"), start=None, months=24)
        with self.assertRaises(SystemExit):
            wiki_interest.parse_period(args)

    def test_period_needs_two_months(self):
        args = argparse.Namespace(end=wiki_interest.month_arg("2025-06"), start=wiki_interest.month_arg("2025-06"),
                                  months=24)
        with self.assertRaises(SystemExit):
            wiki_interest.parse_period(args)

    def test_bad_arguments_are_rejected_by_argparse(self):
        for bad in ("2025-13", "2025", "may"):
            with self.assertRaises(argparse.ArgumentTypeError):
                wiki_interest.month_arg(bad)
        for bad in ("0", "-3", "x"):
            with self.assertRaises(argparse.ArgumentTypeError):
                wiki_interest.positive_int(bad)

    def test_article_spec_parsing(self):
        topics = ["Physics", "Mass–energy equivalence"]
        parse = wiki_interest.parse_article
        self.assertEqual(parse("pl:Fizyka", topics), ("Physics", "pl", "Fizyka"))
        self.assertEqual(parse("en:E=mc²", topics), ("Physics", "en", "E=mc²"))
        self.assertEqual(parse("Mass–energy equivalence=en:E=mc²", topics),
                         ("Mass–energy equivalence", "en", "E=mc²"))
        self.assertEqual(parse("pl:Wikipedia:Strona", topics), ("Physics", "pl", "Wikipedia:Strona"))
        for bad in ("Fizyka", "PL:Fizyka", "pl:"):
            with self.assertRaises(ValueError):
                parse(bad, topics)

    def test_wikidata_site_ids(self):
        self.assertEqual(wikiapi.site_id("pl"), "plwiki")
        self.assertEqual(wikiapi.site_id("zh-yue"), "zh_yuewiki")
        self.assertEqual(wikiapi.site_id("be-tarask"), "be_x_oldwiki")



class TiersTest(unittest.TestCase):
    @staticmethod
    def series(lang, ppm, per_day, vs_wiki, confidence="high", proxy=False):
        return {"lang": lang, "proxy": proxy, "metrics": {
            "share_ppm_last": ppm, "avg_daily_last": per_day, "direction_vs_wiki": vs_wiki,
            "growth_normalized": 0.0, "confidence": confidence}}

    def tier_of(self, lines, lang):
        return next(line.split(":")[0].strip(" -") for line in lines[1:]
                    if f" {lang} (" in line or f": {lang} (" in line)

    def test_relative_rule(self):
        import report
        rs = [self.series("uk", 120, 200, "declining"), self.series("tr", 65, 230, "flat"),
              self.series("es", 50, 900, "flat"), self.series("pl", 40, 270, "declining"),
              self.series("cs", 100, 50, "growing", confidence="low"), self.series("sk", 999, 9, "flat", proxy=True)]
        lines = report.tiers(rs, "relative", lambda r: r["lang"])
        self.assertEqual(self.tier_of(lines, "tr"), "explore now")   # top half, not declining
        self.assertEqual(self.tier_of(lines, "uk"), "watch")         # top half but declining
        self.assertEqual(self.tier_of(lines, "es"), "watch")         # bottom half, flat
        self.assertEqual(self.tier_of(lines, "pl"), "skip")          # bottom half, declining
        self.assertEqual(self.tier_of(lines, "cs"), "skip")          # low confidence
        self.assertFalse(any(" sk (" in line for line in lines))           # proxies are not ranked

    def test_audience_rule_ignores_momentum_for_the_largest(self):
        import report
        rs = [self.series("es", 50, 900, "declining"), self.series("uk", 120, 200, "flat"),
              self.series("pl", 40, 270, "declining")]
        lines = report.tiers(rs, "audience", lambda r: r["lang"])
        self.assertEqual(self.tier_of(lines, "es"), "explore now")
        self.assertEqual(self.tier_of(lines, "uk"), "watch")
        self.assertEqual(self.tier_of(lines, "pl"), "skip")


class AnswerTableTest(unittest.TestCase):
    def test_proxy_size_is_hidden_and_confidence_kept(self):
        import report
        m = {"share_ppm_last": 8.0, "avg_daily_last": 50, "growth_robust": -0.2, "direction": "declining",
             "growth_normalized": -0.12, "direction_vs_wiki": "declining", "confidence": "medium"}
        proxy = {"label": "pl:Fasting*", "article": "Post", "proxy": True, "metrics": m}
        real = {"label": "cs:Fasting", "article": "Přerušovaný půst", "proxy": False, "metrics": m}
        rows = report.answer_rows([proxy, real])
        self.assertEqual(rows[0][1:3], [report.PROXY_SIZE, report.PROXY_SIZE])
        self.assertEqual(rows[1][1:3], ["50", "8.0"])
        self.assertEqual([r[-1] for r in rows], ["medium", "medium"])
        self.assertEqual(len(report.ANSWER_HEADER), len(rows[0]))


class RankingsTest(unittest.TestCase):
    @staticmethod
    def series(topic, name, lang, ppm):
        return {"topic": topic, "name": name, "lang": lang, "proxy": False, "metrics": {
            "share_ppm_last": ppm, "avg_daily_last": 30, "direction_vs_wiki": "flat",
            "growth_normalized": 0.0, "confidence": "high"}}

    def test_topics_in_one_language_get_tiers_and_readable_names(self):
        import report
        lines = report.rankings([self.series("Q413", "physics", "uk", 15.4),
                                 self.series("Astronomy", "Astronomy", "uk", 0.45)])
        text = "\n".join(lines)
        self.assertIn("Ranking of topics in uk", text)
        self.assertIn("SUGGESTED TIERS", text)
        self.assertIn("physics (15.4 per 1M", text)
        self.assertIn("Astronomy (0.5 per 1M", text)  # small values keep a decimal, not "0"
        self.assertNotIn("Q413", text)

class StubTest(unittest.TestCase):
    def test_tiny_auto_linked_article_is_flagged_but_proxy_and_small_gaps_are_not(self):
        import report
        def series(lang, ppm, proxy=False, topic="GenAI"):
            return {"label": lang, "article": "A", "topic": topic, "lang": lang, "proxy": proxy,
                    "metrics": {"share_ppm_last": ppm, "avg_daily_last": 10}}
        rs = [series("en", 10.9), series("uk", 7.0), series("pl", 6.6), series("de", 0.2),
              series("cs", 0.1, proxy=True), series("sk", None), series("uk", 2.9, topic="SE"),
              series("pl", 1.2, topic="SE")]
        self.assertEqual([r["lang"] for r, _ in report.stubs(rs)], ["de"])


class InputTest(unittest.TestCase):
    def test_label_keeps_long_single_word_topics_readable(self):
        self.assertEqual(wiki_interest.label("pl", "Artificial_general_intelligence"), "pl:Artificial general intell…")

    def test_repeated_langs_are_merged_lowercased_and_deduplicated(self):
        args = argparse.Namespace()
        p = argparse.ArgumentParser()
        p.add_argument("--langs", nargs="+", action="extend")
        args = p.parse_args(["--langs", "PL,cs", "--langs", "pl"])
        self.assertEqual(wiki_interest.split_langs(args.langs), ["pl", "cs"])


class RankingFiltersTest(unittest.TestCase):
    @staticmethod
    def series(topic, lang, ppm):
        return {"topic": topic, "name": topic, "lang": lang, "label": f"{lang}:{topic}", "article": "A",
                "proxy": False, "metrics": {"share_ppm_last": ppm, "avg_daily_last": 30, "direction_vs_wiki": "flat",
                                            "growth_normalized": 0.0, "confidence": "high"}}

    def test_stub_left_out_of_rankings_and_control_out_of_topic_tiers(self):
        import report
        rs = [self.series("GenAI", "en", 10.9), self.series("GenAI", "pl", 6.6), self.series("GenAI", "de", 0.2),
              self.series("Physics", "en", 50.0), self.series("Physics", "pl", 40.0),
              self.series("Physics", "de", 45.0)]
        text = "\n".join(report.rankings(rs, controls=["Physics"]))
        self.assertNotIn("de 0.2", text)                  # stub is not ranked
        self.assertNotIn("Ranking of topics", text)       # only one candidate topic left
        self.assertIn("Ranking of languages for Physics", text)  # control still compared across languages

    def test_control_check_spells_out_the_gap(self):
        import report
        a = self.series("Astronomy", "uk", 9.9); a["metrics"]["growth_normalized"] = -0.45
        p = self.series("Physics", "uk", 15.4); p["metrics"]["growth_normalized"] = -0.32
        c = self.series("Astronomy", "cs", 8.7); c["metrics"]["growth_normalized"] = -0.27
        q = self.series("Physics", "cs", 15.5); q["metrics"]["growth_normalized"] = -0.20
        text = "\n".join(report.control_checks([a, p, c, q], ["Physics"]))
        self.assertIn("uk: Astronomy -45% vs wiki, Physics (control) -32%: worse than its field by 13 points", text)
        self.assertIn("cs: Astronomy -27% vs wiki, Physics (control) -20%: moves with its field", text)
        for r in (p, a):
            r["metrics"].update(growth_robust=-0.5, direction="declining")
        rows = report.answer_rows([p, a], ["Physics"])
        self.assertTrue(rows[-1][0].startswith("uk:Physics (control)"))

    def test_missing_hint_names_the_topic(self):
        import report
        study = {"title": "t", "start": "2024-01-01", "end": "2025-12-31", "window": "w", "results": [],
                 "missing": [{"label": "pl:SE", "topic": "Software engineering", "lang": "pl"}]}
        self.assertIn('--article "Software engineering=pl:<Title>"', report.markdown(study))


if __name__ == "__main__":
    unittest.main()
