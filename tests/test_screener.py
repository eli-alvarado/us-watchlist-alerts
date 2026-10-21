"""Fixture tests for movers / gappers / plugin schema."""
from __future__ import annotations
import io, json, os, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gappers, movers, quotes as qt, screener, validate_plugin, watchlist as wlm

FX = os.path.join(ROOT, "tests", "fixtures", "quotes.json")
WL = os.path.join(ROOT, "tests", "fixtures", "watchlist.json")
NOW = "2026-10-15T10:00:00-04:00"


def _quotes():
    return {s: qt.get_quote(s, fixture=FX) for s in ("AAPL", "TSLA", "NVDA")}


class ScreenerLib(unittest.TestCase):
    def test_movers_rank_fixture(self):
        wl = wlm.load(WL)
        rows = screener.rank_movers(wl, _quotes())
        self.assertEqual([r["symbol"] for r in rows], ["TSLA", "AAPL", "NVDA"])
        self.assertAlmostEqual(rows[0]["change_pct"], -5.9980334316617565)
        self.assertAlmostEqual(rows[1]["change_pct"], 1.7570471495386117)
        self.assertAlmostEqual(rows[2]["change_pct"], 1.3126491646778145)
        self.assertEqual([r["symbol"] for r in screener.rank_movers(wl, _quotes(), limit=1)], ["TSLA"])

    def test_gappers_threshold(self):
        wl = wlm.load(WL)
        q = _quotes()
        at_2 = screener.rank_gappers(wl, q, threshold=2)
        self.assertEqual([r["symbol"] for r in at_2], ["TSLA"])
        self.assertEqual(at_2[0]["direction"], "down")
        self.assertAlmostEqual(at_2[0]["gap_pct"], (212.55 - 223.74) / 223.74 * 100)
        none = screener.rank_gappers(wl, q, threshold=10)
        self.assertEqual(none, [])
        loose = screener.rank_gappers(wl, q, threshold=0.1)
        self.assertIn("TSLA", [r["symbol"] for r in loose])
        self.assertIn("AAPL", [r["symbol"] for r in loose])
        self.assertNotIn("NVDA", [r["symbol"] for r in loose])  # open == prev_close

    def test_market_status_holiday_and_regular(self):
        closed = screener.market_status("2026-11-26")
        self.assertEqual(closed["session"], "closed")
        self.assertFalse(closed["trading_day"])
        self.assertIn("Thanksgiving", closed["holiday"] or "")
        self.assertEqual(closed["next_session"], "2026-11-27")
        open_ = screener.market_status("2026-10-15T10:00:00-04:00")
        self.assertEqual(open_["session"], "regular")
        self.assertTrue(open_["trading_day"])
        self.assertIsNone(open_["holiday"])
        early = screener.market_status("2026-11-27T10:00:00-05:00")
        self.assertTrue(early["early_close"])


class MoversCli(unittest.TestCase):
    def test_cli_fixture_text_and_json(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            rc = movers.main(["--watchlist", WL, "--fixture", FX, "--now", NOW])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("TSLA", text)
        self.assertIn("-6.00%", text)
        self.assertIn("AAPL", text)
        self.assertIn("NVDA", text)
        self.assertLess(text.index("TSLA"), text.index("AAPL"))
        jout = io.StringIO()
        with mock.patch("sys.stdout", jout):
            rc = movers.main(["--watchlist", WL, "--fixture", FX, "--now", NOW,
                              "--format", "json", "--limit", "1"])
        self.assertEqual(rc, 0)
        payload = json.loads(jout.getvalue())
        self.assertEqual([m["symbol"] for m in payload["movers"]], ["TSLA"])

    def test_empty_and_missing(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        wlm.save({"version": 1, "settings": {}, "tickers": []}, path)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(movers.main(["--watchlist", path, "--fixture", FX]), 0)
        self.assertIn("Watchlist is empty", out.getvalue())
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(movers.main(["--watchlist", os.path.join(d, "missing.json")]), 2)
        self.assertIn("init", err.getvalue())


class GappersCli(unittest.TestCase):
    def test_cli_threshold_flag(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            rc = gappers.main(["--watchlist", WL, "--fixture", FX, "--now", NOW, "--threshold", "2"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("TSLA", text)
        self.assertIn("down", text)
        self.assertFalse(any(line.startswith("AAPL") for line in text.splitlines()))
        high = io.StringIO()
        with mock.patch("sys.stdout", high):
            rc = gappers.main(["--watchlist", WL, "--fixture", FX, "--threshold", "10", "--now", NOW])
        self.assertEqual(rc, 0)
        self.assertIn("No gappers", high.getvalue())
        jout = io.StringIO()
        with mock.patch("sys.stdout", jout):
            rc = gappers.main(["--watchlist", WL, "--fixture", FX, "--threshold", "0.1",
                               "--format", "json", "--now", NOW])
        self.assertEqual(rc, 0)
        payload = json.loads(jout.getvalue())
        self.assertEqual(payload["threshold"], 0.1)
        self.assertEqual({g["symbol"] for g in payload["gappers"]}, {"TSLA", "AAPL"})


class PluginSchema(unittest.TestCase):
    def test_repo_plugin_files_validate(self):
        errors = validate_plugin.validate_tree(ROOT)
        self.assertEqual(errors, [], errors)

    def test_rejects_claude_prefix_and_dotdot_source(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, ".claude-plugin"))
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), "w") as f:
            json.dump({"name": "claude-nope", "version": "1.0.0"}, f)
        with open(os.path.join(d, ".claude-plugin", "marketplace.json"), "w") as f:
            json.dump({
                "name": "claude-nope",
                "owner": {"name": "x"},
                "plugins": [{"name": "claude-nope", "source": "../elsewhere"}],
            }, f)
        errors = validate_plugin.validate_tree(d)
        blob = " ".join(errors)
        self.assertIn("claude-", blob)
        self.assertIn("..", blob)


if __name__ == "__main__":
    unittest.main()
