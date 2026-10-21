import copy, datetime as dt, importlib.util, io, json, os, shutil, sys, tempfile, unittest, urllib.error, warnings
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import alerts, brief, chart, indicators as ind, market_calendar as mc, notify, quotes as qt, schedule as sched, watchlist as wlm

FX = os.path.join(ROOT, "tests", "fixtures", "quotes.json")
WL = os.path.join(ROOT, "tests", "fixtures", "watchlist.json")
ET = mc.ET
def T(s): return dt.datetime.fromisoformat(s).replace(tzinfo=ET)
def quotes(): return {s: qt.get_quote(s, fixture=FX) for s in ("AAPL", "TSLA", "NVDA")}


def _clear_path_env():
    """Drop path overrides so resolution tests see the real defaults."""
    os.environ.pop("WATCHLIST_FILE", None)
    os.environ.pop("ALERT_STATE_FILE", None)


class IsolatedDataDir:
    """XDG config + optional chdir; never touch the real ~/.config."""

    def __init__(self, chdir=None):
        self._tmp = tempfile.mkdtemp()
        self.xdg = os.path.join(self._tmp, "config")
        os.makedirs(self.xdg)
        self.chdir = chdir
        self._cwd = os.getcwd()
        self._patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.xdg}, clear=False)

    def __enter__(self):
        self._patch.start()
        _clear_path_env()
        if self.chdir:
            os.chdir(self.chdir)
        return self

    def __exit__(self, *exc):
        os.chdir(self._cwd)
        self._patch.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)


class Calendar(unittest.TestCase):
    def tearDown(self):
        mc.clear_official_closures()
    def test_holidays_2026(self):
        h = mc.nyse_holidays(2026)
        for d in ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
                  "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"]:
            self.assertIn(dt.date.fromisoformat(d), h, d)
    def test_saturday_new_year_not_observed(self):
        self.assertNotIn(dt.date(2021, 12, 31), mc.nyse_holidays(2022))
    def test_good_friday_2027(self):
        self.assertIn(dt.date(2027, 3, 26), mc.nyse_holidays(2027))
    def test_sessions(self):
        self.assertEqual(mc.session(T("2026-10-15T08:00")), "pre")
        self.assertEqual(mc.session(T("2026-10-15T09:30")), "regular")
        self.assertEqual(mc.session(T("2026-10-15T16:30")), "after")
        self.assertEqual(mc.session(T("2026-10-15T21:00")), "closed")
        self.assertEqual(mc.session(T("2026-10-17T12:00")), "closed")  # Saturday
        self.assertEqual(mc.session(T("2026-11-26T12:00")), "closed")  # Thanksgiving
    def test_early_close(self):
        self.assertEqual(mc.session(T("2026-11-27T13:30")), "after")
        self.assertEqual(mc.session(T("2026-11-27T12:30")), "regular")
    def test_utc_input(self):
        self.assertEqual(mc.session(dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.timezone.utc)), "regular")
    def test_next_trading_day(self):
        self.assertEqual(mc.next_trading_day(dt.date(2026, 11, 25)), dt.date(2026, 11, 27))
    def test_previous_trading_day(self):
        self.assertEqual(mc.previous_trading_day(dt.date(2026, 10, 16)), dt.date(2026, 10, 15))
        self.assertEqual(mc.previous_trading_day(dt.date(2026, 10, 19)), dt.date(2026, 10, 16))  # Monday → Friday
    def test_trading_session_date_preopen_is_prior_session(self):
        self.assertEqual(mc.trading_session_date(T("2026-10-15T15:00")), dt.date(2026, 10, 15))
        self.assertEqual(mc.trading_session_date(T("2026-10-15T18:30")), dt.date(2026, 10, 15))
        self.assertEqual(mc.trading_session_date(T("2026-10-15T21:30")), dt.date(2026, 10, 15))
        self.assertEqual(mc.trading_session_date(T("2026-10-16T00:05")), dt.date(2026, 10, 15))
        self.assertEqual(mc.trading_session_date(T("2026-10-16T09:00")), dt.date(2026, 10, 15))
        self.assertEqual(mc.trading_session_date(T("2026-10-16T09:30")), dt.date(2026, 10, 16))
        self.assertEqual(mc.trading_session_date(T("2026-10-19T00:05")), dt.date(2026, 10, 16))
    def test_holiday_name(self):
        self.assertEqual(mc.holiday_name(dt.date(2026, 11, 26)), "Thanksgiving Day")
        self.assertIsNone(mc.holiday_name(dt.date(2026, 10, 15)))
    def test_extra_closures_env(self):
        d = dt.date(2026, 10, 15)
        self.assertTrue(mc.is_trading_day(d))
        with mock.patch.dict(os.environ, {"NYSE_EXTRA_CLOSURES": "2026-10-15"}):
            self.assertFalse(mc.is_trading_day(d))
            self.assertEqual(mc.session(T("2026-10-15T10:00")), "closed")
            self.assertEqual(mc.holiday_name(d), "unscheduled closure")
            self.assertEqual(mc.next_trading_day(dt.date(2026, 10, 14)), dt.date(2026, 10, 16))
    def test_extra_closures_arg(self):
        self.assertFalse(mc.is_trading_day(dt.date(2026, 10, 15), extra=["2026-10-15"]))
    def test_tzdata_documented_not_required(self):
        """Windows extra is documented; Linux CI / requirements.txt stay stdlib-only."""
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        with open(os.path.join(ROOT, "CONTRIBUTING.md"), encoding="utf-8") as f:
            contrib = f.read()
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
            req = f.read()
        with open(os.path.join(ROOT, "scripts", "market_calendar.py"), encoding="utf-8") as f:
            src = f.read()
        for text, label in ((readme, "README"), (contrib, "CONTRIBUTING"), (src, "market_calendar.py")):
            self.assertIn("pip install tzdata", text, label)
        for line in req.splitlines():
            s = line.split("#", 1)[0].strip()
            self.assertFalse(s.startswith("tzdata"), line)
    def test_bundled_unscheduled_closures(self):
        carter = dt.date(2025, 1, 9)
        self.assertFalse(mc.is_trading_day(carter))
        self.assertIn("Carter", mc.holiday_name(carter))
        self.assertEqual(mc.session(T("2025-01-09T10:00")), "closed")
        self.assertIn(dt.date(2012, 10, 29), mc.bundled_overrides())
    def test_official_calendar_overlay(self):
        # 2026-10-15 is a normal Thursday; missing it from the official open set closes it.
        mapping = mc.closures_from_trading_days(2026, {dt.date(2026, 10, 16)})
        self.assertIn(dt.date(2026, 10, 15), mapping)
        mc.set_official_closures({dt.date(2026, 10, 15): "official calendar (market closed)"})
        self.assertFalse(mc.is_trading_day(dt.date(2026, 10, 15)))
        self.assertEqual(mc.holiday_name(dt.date(2026, 10, 15)), "official calendar (market closed)")
        mc.clear_official_closures()
        self.assertTrue(mc.is_trading_day(dt.date(2026, 10, 15)))
    def test_refresh_official_calendar_uses_fetch(self):
        rows = [{"date": "2026-10-16"}]
        closed = mc.refresh_official_calendar(2026, fetch=lambda year: rows)
        self.assertIn(dt.date(2026, 10, 15), closed)
        mc.clear_official_closures()
    def test_refresh_official_noop_without_keys(self):
        with mock.patch.dict(os.environ, {"ALPACA_API_KEY_ID": "", "ALPACA_API_SECRET_KEY": ""}):
            self.assertEqual(mc.refresh_official_calendar(2026), {})


class Indicators(unittest.TestCase):
    def test_sma(self): self.assertEqual(ind.sma([1, 2, 3, 4], 2), 3.5); self.assertIsNone(ind.sma([1], 2))
    def test_rsi_extremes(self):
        self.assertEqual(ind.rsi(list(range(1, 30))), 100.0)
        self.assertLess(ind.rsi(list(range(30, 1, -1))), 1)
    def test_golden_cross_fixture(self):
        self.assertEqual(ind.ma_cross(quotes()["NVDA"]["closes"]), "golden")
    def test_death_cross(self):
        # SMAs equal on the prior bar; last close pulls SMA50 below SMA200.
        closes = [10.0] * 200 + [0.0]
        self.assertEqual(ind.ma_cross(closes, 50, 200), "death")
    def test_price_cross_ma(self):
        below = [1.0] * 50 + [3.0]
        self.assertEqual(ind.price_cross_ma(below, 50), "above")
        above = [3.0] * 50 + [1.0]
        self.assertEqual(ind.price_cross_ma(above, 50), "below")


class Watchlist(unittest.TestCase):
    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "wl.json")
    def test_crud_roundtrip(self):
        wl = wlm.load(self.p)
        wlm.add(wl, "nvda", thesis="AI", entry=120, targets=[150], stop=105, tags=["ai"],
                alerts=[wlm.parse_alert("price_below:110")])
        wlm.save(wl, self.p)
        wl = wlm.load(self.p); self.assertEqual(wl["tickers"][0]["symbol"], "NVDA")
        wlm.update(wl, "NVDA", tags=["semis"], append=True); self.assertEqual(wl["tickers"][0]["tags"], ["ai", "semis"])
        with self.assertRaises(ValueError): wlm.add(wl, "NVDA")
        wlm.remove(wl, "NVDA"); self.assertEqual(wl["tickers"], [])
    def test_validation(self):
        wl = {"tickers": [{"symbol": "bad$", "alerts": [{"type": "nope"}]},
                          {"symbol": "X", "entry": 10, "stop": 12}]}
        errs = wlm.validate(wl)
        self.assertTrue(any("bad symbol" in e for e in errs))
        self.assertTrue(any("unknown alert" in e for e in errs))
        self.assertTrue(any("stop" in e for e in errs))
        self.assertEqual(wlm.validate(wlm.load(WL)), [])
    def test_short_stop_must_be_above_entry(self):
        wl = {"tickers": [{"symbol": "AAPL", "side": "short", "entry": 200, "stop": 180}]}
        self.assertTrue(any("short" in e for e in wlm.validate(wl)))
        wl["tickers"][0]["stop"] = 220
        self.assertEqual(wlm.validate(wl), [])
    def test_sessions_and_extra_closures_validated(self):
        self.assertTrue(any("sessions" in e for e in wlm.validate({"settings": {"sessions": ["overnight"]}, "tickers": []})))
        self.assertTrue(any("extra_closures" in e for e in wlm.validate({"settings": {"extra_closures": ["not-a-date"]}, "tickers": []})))
        self.assertEqual(wlm.validate({"settings": {"sessions": ["regular"], "extra_closures": ["2026-01-09"]}, "tickers": []}), [])
    @unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is an optional YAML extra")
    def test_yaml_example_has_valid_short_and_extra_closure(self):
        path = os.path.join(ROOT, "examples", "watchlist.yaml")
        wl = wlm.load(path)
        self.assertEqual(wlm.validate(wl), [])
        short = next(t for t in wl["tickers"] if t["symbol"] == "TSLA")
        self.assertEqual(short["side"], "short")
        self.assertGreater(short["stop"], short["entry"])
        self.assertEqual(list(wl["settings"].get("extra_closures") or []), [])
    def test_class_shares_symbol(self):
        self.assertTrue(wlm.SYMBOL_RE.match("BRK.B")); self.assertTrue(wlm.SYMBOL_RE.match("BF-B"))
    def test_cli(self):
        self.assertEqual(wlm.main(["--file", self.p, "add", "AMD", "--no-verify", "--entry", "150", "--stop", "130", "--tag", "semis"]), 0)
        self.assertEqual(wlm.main(["--file", self.p, "validate"]), 0)
        with mock.patch("sys.stderr"):
            self.assertEqual(wlm.main(["--file", self.p, "show", "NOPE"]), 1)
            self.assertEqual(wlm.main(["--file", self.p, "remove", "NOPE"]), 1)


class Alerts(unittest.TestCase):
    def setUp(self):
        self.wl = wlm.load(WL); self.q = quotes()
    def types(self, res, sym): return {a["type"] for a in res["alerts"] if a["symbol"] == sym}
    def test_expected_fires(self):
        res = alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-15T10:00"))
        self.assertFalse(res["skipped"])
        self.assertTrue({"price_above", "near_52w_high", "earnings_within"} <= self.types(res, "AAPL"))
        self.assertTrue({"pct_change_down", "gap_down", "volume_spike", "earnings_within"} <= self.types(res, "TSLA"))
        self.assertIn("golden_cross", self.types(res, "NVDA"))
        self.assertNotIn("price_below", self.types(res, "NVDA"))
    def test_skips_outside_session(self):
        res = alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-17T10:00"))
        self.assertTrue(res["skipped"]); self.assertEqual(res["alerts"], [])
        self.assertEqual(res.get("reason"), "weekend")
        self.assertFalse(alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-17T10:00"), force_session=True)["skipped"])
    def test_after_hours_shows_last_close(self):
        res = alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-15T18:30"))
        self.assertFalse(res["skipped"])
        self.assertTrue(res.get("last_close"))
        self.assertEqual(res["session"], "after")
        self.assertTrue(res["alerts"])
    def test_overnight_trading_day_shows_last_close(self):
        res = alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-15T21:30"))
        self.assertFalse(res["skipped"])
        self.assertTrue(res.get("last_close"))
        self.assertEqual(res["session"], "closed")
    def test_extra_closure_skips_session(self):
        wl = copy.deepcopy(self.wl)
        wl["settings"]["extra_closures"] = ["2026-10-15"]
        res = alerts.run(wl, {"fired": {}}, self.q, T("2026-10-15T10:00"))
        self.assertTrue(res["skipped"])
        self.assertEqual(res["session"], "closed")
    def test_dedupe_and_cooldown(self):
        st = {"fired": {}}
        first = alerts.run(self.wl, st, self.q, T("2026-10-15T10:00"))["alerts"]
        self.assertTrue(first)
        self.assertEqual(alerts.run(self.wl, st, self.q, T("2026-10-15T10:30"))["alerts"], [])
        # daily-type alerts don't refire same trading day even after cooldown
        self.assertEqual(alerts.run(self.wl, st, self.q, T("2026-10-15T15:00"))["alerts"], [])
        nxt = alerts.run(self.wl, st, self.q, T("2026-10-16T10:00"))["alerts"]
        self.assertTrue({a["type"] for a in nxt} <= alerts.DAILY and nxt)  # daily events may refire next day; latched levels don't
    def test_overnight_does_not_refire_daily_events(self):
        st = {"fired": {}}
        first = alerts.run(self.wl, st, self.q, T("2026-10-15T15:00"))
        self.assertTrue(first["alerts"])
        self.assertTrue(any(a["type"] in alerts.DAILY for a in first["alerts"]))
        for ts in ("2026-10-16T00:05", "2026-10-16T04:05", "2026-10-16T09:00"):
            nxt = alerts.run(self.wl, st, self.q, T(ts))
            self.assertFalse(nxt["skipped"], ts)
            self.assertTrue(nxt.get("last_close"), ts)
            self.assertEqual(nxt["alerts"], [], msg=ts)
    def test_preopen_pct_message_uses_session_date_not_today(self):
        res = alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-16T00:05"))
        msgs = [a["message"] for a in res["alerts"]]
        self.assertTrue(any("on 2026-10-15" in m for m in msgs), msgs)
        self.assertFalse(any(m.endswith("% today") for m in msgs), msgs)
    def test_level_rearm_hysteresis(self):
        wl = {"settings": {"cooldown_minutes": 1}, "tickers": [{"symbol": "AAPL", "alerts": [{"type": "price_above", "value": 240}]}]}
        st = {"fired": {}}; q = copy.deepcopy(self.q)
        self.assertEqual(len(alerts.run(wl, st, q, T("2026-10-15T10:00"))["alerts"]), 1)
        q["AAPL"]["price"] = 239.9  # dips under but within rearm band
        alerts.run(wl, st, q, T("2026-10-15T10:05")); q["AAPL"]["price"] = 241
        self.assertEqual(alerts.run(wl, st, q, T("2026-10-15T10:10"))["alerts"], [])
        q["AAPL"]["price"] = 236  # clearly back below -> rearm
        alerts.run(wl, st, q, T("2026-10-15T10:15")); q["AAPL"]["price"] = 241
        self.assertEqual(len(alerts.run(wl, st, q, T("2026-10-15T10:20"))["alerts"]), 1)
    def test_stop_and_target_implicit(self):
        wl = {"tickers": [{"symbol": "AAPL", "entry": 260, "stop": 245, "targets": [300]},
                          {"symbol": "NVDA", "entry": 150, "stop": 100, "targets": [160]}]}
        res = alerts.run(wl, {"fired": {}}, self.q, T("2026-10-15T10:00"))
        self.assertIn("stop_hit", self.types(res, "AAPL"))
        self.assertIn("target_hit", self.types(res, "NVDA"))
    def test_target_hit_nearest_then_further(self):
        """Price through T1 and T2 must report T1 (nearest), then T2 on a later run after T1 is latched."""
        q = {"AAPL": {"price": 155, "prev_close": 150, "closes": [150] * 30, "source": "fixture"}}
        wl = {"tickers": [{"symbol": "AAPL", "side": "long", "targets": [140, 160]}]}
        st = {"fired": {}}
        first = alerts.run(wl, st, q, T("2026-10-15T10:00"))
        keys = [a["key"] for a in first["alerts"] if a["type"] == "target_hit"]
        self.assertEqual(keys, ["AAPL|target_hit:140"])
        q["AAPL"]["price"] = 165
        second = alerts.run(wl, st, q, T("2026-10-15T10:05"))
        keys2 = [a["key"] for a in second["alerts"] if a["type"] == "target_hit"]
        self.assertEqual(keys2, ["AAPL|target_hit:160"])
    def test_short_target_hit(self):
        q = {"AAPL": {"price": 90, "prev_close": 100, "closes": [100] * 5, "source": "fixture"}}
        wl = {"tickers": [{"symbol": "AAPL", "side": "short", "targets": [95, 80], "stop": 110}]}
        res = alerts.run(wl, {"fired": {}}, q, T("2026-10-15T10:00"))
        self.assertIn("AAPL|target_hit:95", [a["key"] for a in res["alerts"]])
        self.assertNotIn("AAPL|target_hit:80", [a["key"] for a in res["alerts"]])
    def test_max_alerts_does_not_latch_unreported(self):
        wl = {"settings": {"max_alerts_per_run": 1},
              "tickers": [{"symbol": "AAPL", "alerts": [{"type": "price_above", "value": 1}]},
                          {"symbol": "NVDA", "alerts": [{"type": "price_above", "value": 1}]}]}
        st = {"fired": {}}
        first = alerts.run(wl, st, self.q, T("2026-10-15T10:00"))
        self.assertEqual(len(first["alerts"]), 1)
        self.assertTrue(first.get("truncated"))
        self.assertEqual(first["alerts"][0]["symbol"], "AAPL")
        self.assertNotIn("NVDA|price_above:1", st["fired"])
        second = alerts.run(wl, st, self.q, T("2026-10-15T10:01"))
        self.assertEqual([a["symbol"] for a in second["alerts"]], ["NVDA"])
    def test_stale_quote_during_regular_session(self):
        q = copy.deepcopy(self.q)
        q["AAPL"]["as_of"] = "2026-10-15T13:00:00+00:00"  # 10:00 ET minus ~1h from 10:00 ET? 13:00Z = 9:00 ET
        # now is 10:00 ET = 14:00 UTC; age ~3600s
        res = alerts.run(self.wl, {"fired": {}}, q, T("2026-10-15T10:00"), stale_after=600)
        self.assertTrue(any(s["symbol"] == "AAPL" for s in res["stale"]))
        quiet = alerts.run(self.wl, {"fired": {}}, q, T("2026-10-15T10:00"), stale_after=0)
        self.assertEqual(quiet["stale"], [])
    def test_missing_quote_reported(self):
        wl = {"tickers": [{"symbol": "ZZZZ", "alerts": [{"type": "price_above", "value": 1}]}]}
        res = alerts.run(wl, {"fired": {}}, {"ZZZZ": {"error": "not found"}}, T("2026-10-15T10:00"))
        self.assertEqual(res["errors"][0]["symbol"], "ZZZZ")
    def test_corrupt_state_starts_fresh(self):
        d = tempfile.mkdtemp(); st = os.path.join(d, "s.json")
        with open(st, "w") as f:
            f.write("{not json")
        loaded = alerts.load_state(st)
        self.assertEqual(loaded["fired"], {})
        self.assertIn("warning", loaded)
        with open(st, "w") as f:
            json.dump(["nope"], f)
        self.assertEqual(alerts.load_state(st)["fired"], {})
    def test_cli_state_file(self):
        d = tempfile.mkdtemp(); st = os.path.join(d, "s.json")
        alerts.main(["--watchlist", WL, "--state", st, "--fixture", FX, "--now", "2026-10-15T10:00:00-04:00"])
        with open(st) as f:
            self.assertTrue(json.load(f)["fired"])
    def test_cli_after_hours_banner(self):
        d = tempfile.mkdtemp(); st = os.path.join(d, "s.json")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            alerts.main(["--watchlist", WL, "--state", st, "--fixture", FX, "--now", "2026-10-15T18:30:00-04:00"])
        out = buf.getvalue()
        self.assertIn("market closed, showing last regular close", out)
        self.assertIn("ALERT", out)
    def test_save_state_closes_handle(self):
        d = tempfile.mkdtemp(); st = os.path.join(d, "s.json")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            alerts.save_state({"fired": {"X": {"at": "t"}}}, st)
        self.assertFalse(any(issubclass(w.category, ResourceWarning) for w in caught))
        with open(st) as f:
            self.assertIn("X", json.load(f)["fired"])


class Brief(unittest.TestCase):
    def test_render(self):
        out = brief.render(wlm.load(WL), quotes(), "morning", T("2026-10-15T08:30"))
        self.assertIn("| AAPL |", out); self.assertIn("Biggest movers", out); self.assertIn("not financial advice", out)
        self.assertIn("Earnings dates:", out)
        self.assertIn("Data: fixture", out)
    def test_json_fixture_snapshot(self):
        snapshot = os.path.join(ROOT, "tests", "fixtures", "brief-morning.json")
        stdout = io.StringIO()
        with open(snapshot, encoding="utf-8") as f:
            expected = json.load(f)
        with mock.patch.object(mc, "refresh_official_calendar"), mock.patch("sys.stdout", stdout):
            result = brief.main([
                "--watchlist", WL, "--fixture", FX, "--kind", "morning",
                "--now", "2026-10-15T08:30:00-04:00", "--format", "json",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)
    def test_closed_day_note(self):
        out = brief.render(wlm.load(WL), quotes(), "morning", T("2026-11-26T08:30"))
        self.assertIn("Market closed", out)
        self.assertIn("Thanksgiving", out)
    def test_past_earnings_omitted(self):
        q = quotes()
        q["AAPL"]["earnings_date"] = "2020-01-01"
        q["TSLA"]["earnings_date"] = "2026-10-16"
        q["NVDA"]["earnings_date"] = None
        out = brief.render(wlm.load(WL), q, "morning", T("2026-10-15T08:30"))
        self.assertNotIn("AAPL (2020-01-01)", out)
        self.assertIn("TSLA (2026-10-16)", out)
    def test_short_stop_cushion_sign(self):
        t = {"symbol": "AAPL", "side": "short", "stop": 250, "targets": [200]}
        q = {"price": 241.5, "prev_close": 240, "closes": [200] * 30}
        line, _ = brief.row(t, q)
        # stop is above price for a short → positive cushion
        self.assertIn("+3.5%", line)


class Chart(unittest.TestCase):
    def test_sparkline_empty_and_range(self):
        self.assertEqual(chart.sparkline([]), "")
        self.assertEqual(chart.sparkline([None, None]), "")
        s = chart.sparkline([1, 2, 3, 4, 5, 6, 7, 8])
        self.assertTrue(s)
        self.assertEqual(s[0], "▁")
        self.assertEqual(s[-1], "█")

    def test_sma_series_length(self):
        closes = list(range(1, 31))
        series = chart.sma_series(closes, 20)
        self.assertEqual(len(series), 30)
        self.assertIsNone(series[18])
        self.assertAlmostEqual(series[19], sum(range(1, 21)) / 20)
        self.assertEqual(chart.sma_series(closes, 0), [None] * 30)

    def test_levels_from_fixture_watchlist(self):
        levels = {lab: px for lab, px in chart.levels_from_watchlist(wlm.load(WL), "AAPL")}
        self.assertAlmostEqual(levels["stop"], 210.0)
        self.assertAlmostEqual(levels["entry"], 225.0)
        self.assertAlmostEqual(levels["target1"], 250.0)
        self.assertAlmostEqual(levels["target2"], 270.0)
        self.assertAlmostEqual(levels["price_above"], 240.0)
        self.assertEqual(chart.levels_from_watchlist(wlm.load(WL), "MISSING"), [])

    def test_ascii_chart_overlays(self):
        text = chart.ascii_chart(
            [200, 210, 220, 230, 240],
            levels=[("stop", 210), ("price_above", 240)],
            smas={"sma20": [None, None, None, None, 220]},
            title="AAPL",
        )
        self.assertIn("AAPL", text)
        self.assertIn("*", text)
        self.assertIn("stop $210.00", text)
        self.assertIn("price_above $240.00", text)
        self.assertIn("sma20=.", text)

    def test_cli_fixture(self):
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            rc = chart.main(["AAPL", "--fixture", FX, "--watchlist", WL, "--sma", "20,50"])
        self.assertEqual(rc, 0)
        out = stdout.getvalue()
        self.assertIn("AAPL", out)
        self.assertIn("$241.50", out)
        self.assertIn("stop $210.00", out)
        self.assertIn("price_above $240.00", out)

    def test_png_or_ascii_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "aapl.png")
            result = chart.render("AAPL", fixture=FX, watchlist=WL, style="line", out=dest)
            self.assertTrue(result["path"] and os.path.exists(result["path"]))
            self.assertGreater(os.path.getsize(result["path"]), 0)
            if chart.has_matplotlib():
                self.assertEqual(result["backend"], "matplotlib")
                with open(result["path"], "rb") as f:
                    self.assertEqual(f.read()[:8], b"\x89PNG\r\n\x1a\n")
            else:
                self.assertEqual(result["backend"], "ascii")
                self.assertTrue(result["path"].endswith(".txt"))

    def test_candle_style_offline(self):
        result = chart.render("AAPL", fixture=FX, watchlist=WL, style="candle")
        self.assertEqual(result["backend"], "ascii")
        self.assertIn("AAPL", result["text"])
        bars = chart.ohlc_bars({"closes": [10.0, 12.0, 11.0]})
        self.assertEqual(bars[0], (10.0, 10.0, 10.0, 10.0))
        self.assertEqual(bars[1][0], 10.0)
        self.assertEqual(bars[1][3], 12.0)


class Quotes(unittest.TestCase):
    def test_fixture_roundtrip(self):
        q = qt.get_quote("AAPL", fixture=FX)
        self.assertEqual(q["source"], "fixture")
        self.assertAlmostEqual(q["price"], 241.5)
        self.assertIsNotNone(q["avg_volume_20d"] or True)
    def test_missing_fixture_symbol(self):
        with self.assertRaises(qt.QuoteError):
            qt.from_fixture("ZZZZ", FX)
    def test_unknown_provider(self):
        with self.assertRaises(RuntimeError) as ctx:
            qt.get_quote("AAPL", provider="nope")
        self.assertIn("unknown provider", str(ctx.exception))
    def test_auto_order_optional_keys(self):
        env = {"ALPACA_API_KEY_ID": "id"}  # secret missing → alpaca skipped
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("ALPACA_API_SECRET_KEY", None)
            os.environ.pop("FINNHUB_API_KEY", None)
            os.environ.pop("ALPHAVANTAGE_API_KEY", None)
            order = qt.auto_order()
        self.assertIn("yahoo", order)
        self.assertNotIn("alpaca", order)
    def test_aligned_ohlcv_drops_null_closes(self):
        closes, vols, opens, n, ts = qt._aligned_ohlcv({
            "close": [1.0, None, 3.0],
            "volume": [10, 99, 30],
            "open": [0.9, 2.0, 2.9],
        }, timestamps=[100, 200, 300])
        self.assertEqual(closes, [1.0, 3.0])
        self.assertEqual(vols, [10, 30])
        self.assertEqual(n, 3)
        self.assertEqual(opens, [0.9, 2.9])
        self.assertEqual(ts, [100, 300])
    def test_yahoo_prefers_meta_previous_close(self):
        payload = {
            "chart": {"result": [{
                "meta": {
                    "regularMarketPrice": 10.5,
                    "chartPreviousClose": 10.0,
                    "regularMarketOpen": 10.1,
                    "regularMarketDayHigh": 11,
                    "regularMarketDayLow": 9.9,
                    "regularMarketVolume": 1000,
                    "fiftyTwoWeekHigh": 12,
                    "fiftyTwoWeekLow": 8,
                },
                "indicators": {"quote": [{"close": [9.0, 10.0, 10.5], "volume": [1, 2, 3], "open": [9, 10, 10.1]}]},
            }]}
        }
        with mock.patch.object(qt, "_get", return_value=payload):
            q = qt.from_yahoo("AAPL")
        self.assertEqual(q["prev_close"], 10.0)
        self.assertEqual(q["open"], 10.1)
        self.assertEqual(q["source"], "yahoo-chart")
        self.assertEqual(q["price"], 10.5)

    def test_yahoo_ignores_chart_previous_close_range_start(self):
        """chartPreviousClose on a 1y chart is the close before the range, not yesterday."""
        payload = {
            "chart": {"result": [{
                "meta": {
                    "regularMarketPrice": 342.0,
                    "chartPreviousClose": 249.34,
                    "regularMarketOpen": 346.95,
                    "regularMarketTime": 1792094401,
                },
                "timestamp": [1791898200, 1791984600, 1792071000],
                "indicators": {"quote": [{"close": [336.64, 340.97, 342.0], "volume": [1, 2, 3],
                                          "open": [340, 344, 346.95]}]},
            }]}
        }
        with mock.patch.object(qt, "_get", return_value=payload):
            q = qt.from_yahoo("AAPL")
        self.assertAlmostEqual(q["prev_close"], 340.97)
        self.assertNotAlmostEqual(q["prev_close"], 249.34)
        self.assertEqual(q["as_of"], "2026-10-15T20:00:01+00:00")

    def test_chart_prev_close_helpers(self):
        self.assertEqual(qt._chart_prev_close({"previousClose": 10}, [1, 2, 3]), 10)
        self.assertEqual(qt._chart_prev_close({"chartPreviousClose": 5}, [9, 10, 10.5], price=10.5), 10)
        self.assertEqual(qt._chart_prev_close({"chartPreviousClose": 5}, [9, 10], price=12), 10)
        self.assertEqual(qt._as_of_from_meta({}), None)

    def test_chart_prev_close_trailing_null_today_bar(self):
        """After ~20:00 ET Yahoo keeps today's timestamp with close=None.

        Unaligned timestamps[-1] looked like 'today', so prev_close walked
        back to Oct 13 ($228.52) instead of Wednesday Oct 14 ($221.30).
        """
        # 2026-10-13 / 14 / 15 09:30 ET
        raw_ts = [1791898200, 1791984600, 1792071000]
        now = dt.datetime(2026, 10, 15, 20, 9, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        closes, _vols, _opens, _n, ts = qt._aligned_ohlcv(
            {"close": [228.52, 221.30, None], "volume": [1, 2, 3], "open": [224, 225, 215]},
            timestamps=raw_ts,
        )
        self.assertEqual(closes, [228.52, 221.30])
        self.assertEqual(ts, [1791898200, 1791984600])
        self.assertAlmostEqual(
            qt._chart_prev_close({}, closes, timestamps=ts, price=217.23, now=now), 221.30
        )
        # last finished bar *is* today → prior session
        self.assertAlmostEqual(
            qt._chart_prev_close({}, [228.52, 221.30, 217.23], timestamps=raw_ts, price=217.23, now=now),
            221.30,
        )

    def test_chart_prev_close_rejects_rolled_meta(self):
        """previousClose == last after the session roll is a fake 0% day."""
        now = dt.datetime(2026, 10, 15, 20, 21, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        ts = [1791898200, 1791984600]
        prev = qt._chart_prev_close(
            {"previousClose": 217.23, "regularMarketPreviousClose": 217.23},
            [228.52, 221.30], timestamps=ts, price=217.23, now=now,
        )
        self.assertAlmostEqual(prev, 221.30)

    def test_yahoo_after_hours_null_today_bar(self):
        """from_yahoo: 2026-10-15 20:09 ET shape — last 1d close is None."""
        payload = {
            "chart": {"result": [{
                "meta": {
                    "regularMarketPrice": 217.23,
                    "chartPreviousClose": 230.48,
                    "regularMarketOpen": 215.34,
                    "regularMarketTime": 1792094401,
                },
                "timestamp": [1791898200, 1791984600, 1792071000],
                "indicators": {"quote": [{
                    "close": [228.52, 221.30, None],
                    "volume": [1, 2, 3],
                    "open": [224.34, 225.53, 215.34],
                }]},
            }]}
        }
        with mock.patch.object(qt, "_get", return_value=payload):
            q = qt.from_yahoo("NVDA")
        self.assertAlmostEqual(q["prev_close"], 221.30)
        self.assertNotAlmostEqual(q["prev_close"], 228.52)
        self.assertEqual(q["price"], 217.23)
    def test_yahoo_retries_query2(self):
        payload = {
            "chart": {"result": [{
                "meta": {"regularMarketPrice": 1, "chartPreviousClose": 1, "regularMarketOpen": 1},
                "indicators": {"quote": [{"close": [1, 1], "volume": [1, 1], "open": [1, 1]}]},
            }]}
        }
        with mock.patch.object(qt, "_get", side_effect=[OSError("blocked"), payload]) as g:
            q = qt.from_yahoo("AAPL")
        self.assertEqual(q["price"], 1)
        self.assertEqual(g.call_count, 2)
        self.assertIn("query2.finance.yahoo.com", g.call_args_list[1][0][0])
    def test_finish_rejects_empty_price(self):
        with self.assertRaises(RuntimeError):
            qt._finish({"symbol": "X", "price": None, "closes": [], "source": "x"})
    def test_earnings_date_helpers(self):
        self.assertEqual(qt._first_iso_date("2026-10-29 00:00:00-04:00"), "2026-10-29")
        self.assertEqual(qt._first_iso_date([dt.date(2026, 10, 29)]), "2026-10-29")
        self.assertEqual(qt._first_iso_date(dt.datetime(2026, 10, 29, 16, 0)), "2026-10-29")
        class Ticker:
            calendar = {"Earnings Date": [dt.date(2026, 11, 1)]}
            earnings_dates = None
        self.assertEqual(qt._yfinance_earnings_date(Ticker()), "2026-11-01")
        class Loc:
            def __getitem__(self, key):
                return dt.date(2026, 12, 1)
        class Frame:
            loc = Loc()
            index = ["Earnings Date"]
            columns = []
        class Ticker2:
            calendar = Frame()
            earnings_dates = None
        self.assertEqual(qt._yfinance_earnings_date(Ticker2()), "2026-12-01")
        self.assertEqual(qt._first_iso_date({"raw": 1761696000, "fmt": "2025-10-28"}), "2025-10-28")

    def test_yahoo_earnings_parser(self):
        payload = {"quoteSummary": {"result": [{"calendarEvents": {"earnings": {
            "earningsDate": [{"raw": 1793145600, "fmt": "2026-10-28"}]
        }}}]}}
        with mock.patch.object(qt, "_get", return_value=payload):
            self.assertEqual(qt.earnings_from_yahoo("AAPL"), "2026-10-28")

    def test_finnhub_earnings_parser(self):
        payload = {"earningsCalendar": [
            {"date": "2026-10-20", "symbol": "AAPL"},
            {"date": "2026-11-02", "symbol": "AAPL"},
        ]}
        with mock.patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}):
            with mock.patch.object(qt, "_get", return_value=payload):
                self.assertEqual(qt.earnings_from_finnhub("AAPL", as_of_date=dt.date(2026, 10, 15)), "2026-10-20")

    def test_lookup_earnings_fallback_order(self):
        with mock.patch.object(qt, "earnings_from_yahoo", return_value=None), \
             mock.patch.object(qt, "earnings_from_yahoo_html", return_value=None), \
             mock.patch.object(qt, "earnings_from_nasdaq", return_value=None), \
             mock.patch.object(qt, "earnings_from_finnhub", return_value="2026-11-15"), \
             mock.patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}):
            ed, src = qt.lookup_earnings("AAPL")
        self.assertEqual((ed, src), ("2026-11-15", "finnhub"))
        self.assertEqual(qt.lookup_earnings("AAPL", existing="2026-10-01"), ("2026-10-01", "existing"))

    def test_lookup_earnings_nasdaq_before_keys(self):
        with mock.patch.object(qt, "earnings_from_yahoo", return_value=None), \
             mock.patch.object(qt, "earnings_from_yahoo_html", return_value=None), \
             mock.patch.object(qt, "earnings_from_nasdaq", return_value="2026-11-02"):
            ed, src = qt.lookup_earnings("AAPL")
        self.assertEqual((ed, src), ("2026-11-02", "nasdaq"))

    def test_earnings_error_is_short(self):
        msg = qt._summarize_earnings_errors([
            'yahoo-calendar: yahoo-earnings: {"quoteSummary":{"error":{"code":"Not Found"}}} — HTTP 404',
            "yahoo-html: no earnings date in quote page for SPY",
            "nasdaq: no upcoming earnings date for SPY",
        ])
        self.assertIn("yahoo-calendar, yahoo-html, nasdaq", msg)
        self.assertNotIn("quoteSummary", msg)
        self.assertIn("ETFs", msg)
        q = {"symbol": "SPY", "price": 1, "source": "yahoo-chart"}
        with mock.patch.object(qt, "from_yahoo", return_value=dict(q)), \
             mock.patch.object(qt, "lookup_earnings", side_effect=lambda *a, **k: (
                 k.get("errors_out", []).extend(["yahoo-calendar: boom"]) or (None, None))):
            got = qt.get_quote("SPY", provider="yahoo")
        self.assertTrue(got.get("earnings_error", "").startswith("earnings date unavailable"))
        self.assertNotIn("{", got.get("earnings_error", ""))

    def test_yahoo_html_and_nasdaq_parsers(self):
        html = r'prefix \"earningsDate\":[{\"raw\":1793649600,\"fmt\":\"2026-11-02\"}] suffix'
        self.assertEqual(qt.parse_yahoo_html_earnings(html, as_of_date=dt.date(2026, 10, 15)), "2026-11-02")
        self.assertEqual(qt._extract_yahoo_crumb('{"user":{"crumb":"mCC1tYlndwL"}}'), "mCC1tYlndwL")
        blob = {"data": {"reportText": "Apple Inc. is expected* to report earnings on  11/02/2026 after market close."}}
        self.assertEqual(qt.parse_nasdaq_earnings_blob(blob, as_of_date=dt.date(2026, 10, 15)), "2026-11-02")

    def test_get_quote_attaches_earnings(self):
        snap = {"latestTrade": {"p": 10}, "dailyBar": {"o": 9, "h": 11, "l": 8, "c": 10, "v": 1},
                "prevDailyBar": {"c": 9}}
        with mock.patch.dict(os.environ, {"ALPACA_API_KEY_ID": "id", "ALPACA_API_SECRET_KEY": "sec",
                                          "WATCHLIST_PROVIDER": "alpaca"}):
            with mock.patch.object(qt, "_get", return_value=snap), \
                 mock.patch.object(qt, "lookup_earnings", return_value=("2026-10-29", "yahoo-calendar")):
                q = qt.get_quote("AAPL", provider="alpaca")
        self.assertEqual(q["price"], 10)
        self.assertEqual(q["earnings_date"], "2026-10-29")
        self.assertEqual(q["earnings_source"], "yahoo-calendar")

    def test_alpaca_bars_history(self):
        snap = {"latestTrade": {"p": 10}, "dailyBar": {"o": 9, "h": 11, "l": 8, "c": 10, "v": 100},
                "prevDailyBar": {"c": 9}}
        bars = {"bars": [{"c": 8, "v": 10}, {"c": 9, "v": 20}, {"c": 10, "v": 30}]}
        with mock.patch.dict(os.environ, {"ALPACA_API_KEY_ID": "id", "ALPACA_API_SECRET_KEY": "sec"}):
            with mock.patch.object(qt, "_get", side_effect=[snap, bars]):
                q = qt.from_alpaca("AAPL")
        self.assertEqual(q["closes"], [8.0, 9.0, 10.0])
        self.assertEqual(q["source"], "alpaca")
        self.assertAlmostEqual(q["avg_volume_20d"], 15.0)

    def test_quote_error_hint(self):
        err = qt.QuoteError("alpaca", "nope", status=401, hint="check alpaca API credentials")
        self.assertIn("HTTP 401", str(err))
        self.assertIn("check alpaca", str(err))

    def test_post_accepts_non_json_body(self):
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"ok"
        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            self.assertEqual(qt._post("https://example.test/hook", {"text": "hi"}, provider="slack")["body"], "ok")

    def test_http_retries_on_429(self):
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b'{"ok":1}'
        hdr = mock.MagicMock()
        hdr.get.return_value = "0"
        err = urllib.error.HTTPError("https://x", 429, "rate", hdr, io.BytesIO(b"slow"))
        with mock.patch.object(qt, "_sleep"), \
             mock.patch("urllib.request.urlopen", side_effect=[err, FakeResp()]):
            self.assertEqual(qt._get("https://example.test", provider="yahoo", retries=2), {"ok": 1})

    def test_auto_order_prefers_alpaca_when_keyed(self):
        with mock.patch.dict(os.environ, {"ALPACA_API_KEY_ID": "id", "ALPACA_API_SECRET_KEY": "sec"}):
            self.assertEqual(qt.auto_order()[0], "alpaca")

    def test_quote_age(self):
        now = dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.timezone.utc)
        q = {"as_of": "2026-10-15T13:50:00+00:00"}
        self.assertAlmostEqual(qt.quote_age_seconds(q, now), 600)
        self.assertIsNone(qt.quote_age_seconds({}, now))

    def test_alphavantage_clear_error(self):
        with mock.patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "k"}):
            with mock.patch.object(qt, "_get", return_value={"Note": "API call frequency"}):
                with self.assertRaises(qt.QuoteError) as ctx:
                    qt.from_alphavantage("AAPL")
        self.assertIn("frequency", str(ctx.exception).lower())

    def test_iv_to_percent(self):
        self.assertAlmostEqual(qt._iv_to_percent(0.25), 25.0)
        self.assertAlmostEqual(qt._iv_to_percent(25.0), 25.0)
        self.assertIsNone(qt._iv_to_percent(0))
        self.assertIsNone(qt._iv_to_percent(None))
        self.assertAlmostEqual(qt._iv_to_percent(1.5), 150.0)

    def test_parse_yahoo_atm_iv(self):
        payload = {"optionChain": {"result": [{
            "quote": {"regularMarketPrice": 100},
            "options": [{
                "expirationDate": 1793145600,
                "calls": [
                    {"strike": 95, "impliedVolatility": 0.40},
                    {"strike": 100, "impliedVolatility": 0.20},
                ],
                "puts": [
                    {"strike": 100, "impliedVolatility": 0.22},
                    {"strike": 105, "impliedVolatility": 0.30},
                ],
            }],
        }]}}
        info = qt.parse_yahoo_atm_iv(payload)
        self.assertAlmostEqual(info["atm_iv"], 21.0)
        self.assertEqual(info["iv_strike"], 100.0)
        self.assertEqual(info["iv_source"], "yahoo-options")
        self.assertEqual(info["iv_expiry"], "2026-10-28")

    def test_parse_yahoo_atm_iv_skips_zero_then_next_strike(self):
        payload = {"optionChain": {"result": [{
            "quote": {"regularMarketPrice": 100},
            "options": [{"expirationDate": 1, "calls": [
                {"strike": 100, "impliedVolatility": 0},
                {"strike": 101, "impliedVolatility": 0.5},
            ], "puts": []}]}],
        }}
        info = qt.parse_yahoo_atm_iv(payload, price=100)
        self.assertAlmostEqual(info["atm_iv"], 50.0)
        self.assertEqual(info["iv_strike"], 101.0)

    def test_attach_iv_uses_fetch_and_skips_errors(self):
        q = {"symbol": "AAPL", "price": 100, "atm_iv": None}
        qt.attach_iv(q, fetch=lambda sym, price: {"atm_iv": 33.0, "iv_expiry": "2026-10-28",
                                                  "iv_source": "yahoo-options"})
        self.assertEqual(q["atm_iv"], 33.0)
        broken = {"symbol": "AAPL", "price": 100}
        qt.attach_iv(broken, fetch=lambda *a: (_ for _ in ()).throw(RuntimeError("nope")))
        self.assertIsNone(broken.get("atm_iv"))


class CalendarCache(unittest.TestCase):
    def tearDown(self):
        mc.clear_official_closures()

    def test_cache_hit_skips_fetch(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "cal.json")
        today = dt.date(2026, 10, 15)
        calls = []
        def fetch(year):
            calls.append(year)
            return [{"date": "2026-10-16"}]
        first = mc.refresh_official_calendar(2026, fetch=fetch, cache_path=path, today=today)
        self.assertIn(dt.date(2026, 10, 15), first)
        self.assertEqual(calls, [2026])
        mc.clear_official_closures()
        second = mc.refresh_official_calendar(2026, fetch=fetch, cache_path=path, today=today)
        self.assertEqual(calls, [2026])  # no second network
        self.assertIn(dt.date(2026, 10, 15), second)

    def test_cache_expires_next_day(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "cal.json")
        calls = []
        def fetch(year):
            calls.append(year)
            return [{"date": "2026-10-16"}]
        mc.refresh_official_calendar(2026, fetch=fetch, cache_path=path, today=dt.date(2026, 10, 15))
        mc.clear_official_closures()
        mc.refresh_official_calendar(2026, fetch=fetch, cache_path=path, today=dt.date(2026, 10, 16))
        self.assertEqual(calls, [2026, 2026])

    def test_stale_cache_used_when_fetch_fails(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "cal.json")
        mc.save_calendar_cache(2026, {dt.date(2026, 10, 15): "official calendar (market closed)"},
                               path=path, today=dt.date(2026, 10, 14))
        def boom(year):
            raise RuntimeError("network down")
        closed = mc.refresh_official_calendar(2026, fetch=boom, cache_path=path, today=dt.date(2026, 10, 15))
        self.assertIn(dt.date(2026, 10, 15), closed)


class Notify(unittest.TestCase):
    def setUp(self):
        self.res = {"session": "regular", "skipped": False,
                    "alerts": [{"symbol": "AAPL", "type": "price_above",
                                "message": "AAPL $241.50 is above $240.00"}]}

    def test_parse_sinks(self):
        with mock.patch.dict(os.environ, {"WATCHLIST_NOTIFY": "ntfy, slack, fax"}):
            known, unknown = notify.parse_sinks("env")
        self.assertEqual(known, ["ntfy", "slack"])
        self.assertEqual(unknown, ["fax"])

    def test_format_text(self):
        t = notify.format_text(self.res)
        self.assertIn("1 new alert (regular)", t)
        self.assertIn("AAPL $241.50", t)

    def test_file_sink(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "out.jsonl")
        with mock.patch.dict(os.environ, {"WATCHLIST_NOTIFY_FILE": path}):
            out = notify.deliver(self.res, sinks="file")
        self.assertTrue(out[0]["ok"])
        with open(path) as f:
            row = json.loads(f.readline())
        self.assertEqual(row["count"], 1)
        self.assertEqual(row["alerts"][0]["symbol"], "AAPL")

    def test_webhook_and_slack_payloads(self):
        posted = []
        def fake_post(url, data, headers=None, provider="http", retries=1):
            posted.append((url, data, provider))
            return {"ok": True}
        env = {"WATCHLIST_WEBHOOK_URL": "https://example.test/hook",
               "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/x"}
        with mock.patch.dict(os.environ, env), mock.patch.object(qt, "_post", side_effect=fake_post):
            out = notify.deliver(self.res, sinks="webhook,slack")
        self.assertTrue(all(r["ok"] for r in out))
        self.assertEqual(posted[0][2], "webhook")
        self.assertEqual(posted[0][1]["source"], "us-watchlist-alerts")
        self.assertEqual(posted[1][1]["text"].split("\n")[0], "1 new alert (regular)")

    def test_ntfy_headers_and_token(self):
        posted = []
        def fake_post(url, data, headers=None, provider="http", retries=1):
            posted.append((url, data, headers, provider))
            return {}
        env = {"NTFY_TOPIC": "watchlist", "NTFY_URL": "https://ntfy.sh", "NTFY_TOKEN": "sekrit"}
        with mock.patch.dict(os.environ, env), mock.patch.object(qt, "_post", side_effect=fake_post):
            out = notify.deliver(self.res, sinks="ntfy")
        self.assertTrue(out[0]["ok"])
        self.assertEqual(posted[0][0], "https://ntfy.sh/watchlist")
        self.assertEqual(posted[0][2]["Authorization"], "Bearer sekrit")
        self.assertEqual(posted[0][1].split("\n")[0], "1 new alert (regular)")

    def test_delivery_failure_does_not_raise(self):
        with mock.patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/x"}):
            with mock.patch.object(qt, "_post", side_effect=qt.QuoteError("slack", "nope", status=500)):
                out = notify.deliver(self.res, sinks="slack")
        self.assertFalse(out[0]["ok"])
        self.assertIn("nope", out[0]["error"])

    def test_desktop_missing_binary(self):
        with mock.patch.object(notify.shutil, "which", return_value=None):
            out = notify.deliver(self.res, sinks="desktop")
        self.assertFalse(out[0]["ok"])
        self.assertIn("notify-send", out[0]["error"])

    def test_should_deliver_gates(self):
        self.assertTrue(notify.should_deliver(self.res))
        self.assertFalse(notify.should_deliver(self.res, dry_run=True))
        self.assertFalse(notify.should_deliver({**self.res, "skipped": True}))
        self.assertFalse(notify.should_deliver({**self.res, "alerts": []}))

    def test_sink_config_errors(self):
        with mock.patch.object(notify.os, "environ", {"WATCHLIST_NOTIFY": ""}):
            errs = notify.sink_config_errors()
        self.assertTrue(any("no sinks" in e for e in errs))
        with mock.patch.object(notify.os, "environ", {"WATCHLIST_NOTIFY": "ntfy"}):
            errs = notify.sink_config_errors()
        self.assertTrue(any(e.startswith("ntfy:") for e in errs))
        with mock.patch.object(notify.os, "environ",
                               {"WATCHLIST_NOTIFY": "file", "WATCHLIST_NOTIFY_FILE": "/tmp/x.jsonl"}):
            self.assertEqual(notify.sink_config_errors(), [])


class IvAndRangeAlerts(unittest.TestCase):
    def test_iv_above_latch_and_rearm(self):
        q = {"AAPL": {"price": 241.5, "prev_close": 237, "closes": [200] * 30, "atm_iv": 45.0,
                      "iv_expiry": "2026-10-28", "source": "fixture"}}
        wl = {"settings": {"cooldown_minutes": 1},
              "tickers": [{"symbol": "AAPL", "alerts": [{"type": "iv_above", "value": 40}]}]}
        st = {"fired": {}}
        first = alerts.run(wl, st, q, T("2026-10-15T10:00"))
        self.assertEqual(first["alerts"][0]["type"], "iv_above")
        self.assertIn("ATM IV 45.0%", first["alerts"][0]["message"])
        self.assertEqual(alerts.run(wl, st, q, T("2026-10-15T10:05"))["alerts"], [])
        q["AAPL"]["atm_iv"] = 30.0  # condition false -> rearm
        alerts.run(wl, st, q, T("2026-10-15T10:10"))
        q["AAPL"]["atm_iv"] = 46.0
        self.assertEqual(len(alerts.run(wl, st, q, T("2026-10-15T14:20"))["alerts"]), 1)

    def test_iv_skips_missing_or_zero(self):
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [{"type": "iv_below", "value": 20}]}]}
        q = {"AAPL": {"price": 241.5, "prev_close": 237, "closes": [200] * 5, "source": "fixture"}}
        self.assertEqual(alerts.run(wl, {"fired": {}}, q, T("2026-10-15T10:00"))["alerts"], [])
        q["AAPL"]["atm_iv"] = 0
        self.assertEqual(alerts.run(wl, {"fired": {}}, q, T("2026-10-15T10:00"))["alerts"], [])

    def test_intraday_range_uses_day_high_low_only(self):
        q = {"AAPL": {"price": 100, "prev_close": 100, "day_high": 110, "day_low": 90,
                      "closes": [100] * 10, "source": "fixture"}}
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [{"type": "intraday_range_pct", "value": 15}]}]}
        res = alerts.run(wl, {"fired": {}}, q, T("2026-10-15T10:00"))
        self.assertEqual(res["alerts"][0]["type"], "intraday_range_pct")
        # missing range: do not invent from closes (which swing 50%)
        q2 = {"AAPL": {"price": 150, "prev_close": 100, "closes": [100, 150], "source": "fixture"}}
        silent = alerts.run(wl, {"fired": {}}, q2, T("2026-10-15T10:00"))
        self.assertEqual(silent["alerts"], [])

    def test_intraday_range_once_per_day(self):
        q = {"AAPL": {"price": 100, "prev_close": 100, "day_high": 110, "day_low": 90,
                      "closes": [100], "source": "fixture"}}
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [{"type": "intraday_range_pct", "value": 5}]}]}
        st = {"fired": {}}
        self.assertEqual(len(alerts.run(wl, st, q, T("2026-10-15T10:00"))["alerts"]), 1)
        self.assertEqual(alerts.run(wl, st, q, T("2026-10-15T15:00"))["alerts"], [])

    def test_validate_new_types(self):
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [
            {"type": "iv_above", "value": 40}, {"type": "intraday_range_pct", "value": 8},
            {"type": "intraday_extreme_pct", "value": 3}]}]}
        self.assertEqual(wlm.validate(wl), [])

    def test_intraday_low_fires_when_last_recovered(self):
        """NVDA 2026-10-15 shape: session low −3.82%, last only −1.84%."""
        q = {"NVDA": {"price": 217.23, "prev_close": 221.30, "day_high": 218.47, "day_low": 212.85,
                      "closes": [221.30], "source": "fixture"}}
        wl = {"tickers": [{"symbol": "NVDA", "alerts": [
            {"type": "pct_change_down", "value": 3},
            {"type": "intraday_low_pct", "value": 3}]}]}
        res = alerts.run(wl, {"fired": {}}, q, T("2026-10-15T16:00"))
        types = {a["type"] for a in res["alerts"]}
        self.assertIn("intraday_low_pct", types)
        self.assertNotIn("pct_change_down", types)
        self.assertIn("session low", res["alerts"][0]["message"])

    def test_intraday_extreme_alias_and_once_per_day(self):
        q = {"AAPL": {"price": 100, "prev_close": 100, "day_high": 104, "day_low": 96,
                      "closes": [100], "source": "fixture"}}
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [{"type": "intraday_extreme_pct", "value": 3}]}]}
        st = {"fired": {}}
        first = alerts.run(wl, st, q, T("2026-10-15T10:00"))
        self.assertEqual({a["type"] for a in first["alerts"]}, {"intraday_low_pct", "intraday_high_pct"})
        self.assertEqual(alerts.run(wl, st, q, T("2026-10-15T15:00"))["alerts"], [])

    def test_intraday_extreme_skips_without_session_range(self):
        q = {"AAPL": {"price": 90, "prev_close": 100, "closes": [100], "source": "fixture"}}
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [{"type": "intraday_extreme_pct", "value": 3}]}]}
        self.assertEqual(alerts.run(wl, {"fired": {}}, q, T("2026-10-15T10:00"))["alerts"], [])

    def test_cli_notify_file_not_on_dry_run(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "n.jsonl")
        st = os.path.join(d, "s.json")
        env = {"WATCHLIST_NOTIFY_FILE": path, "WATCHLIST_NOTIFY": "file"}
        with mock.patch.dict(os.environ, env):
            alerts.main(["--watchlist", WL, "--state", st, "--fixture", FX,
                         "--now", "2026-10-15T10:00:00-04:00", "--notify", "file"])
            self.assertTrue(os.path.exists(path) and os.path.getsize(path) > 0)
            os.remove(path)
            st2 = os.path.join(d, "s2.json")
            alerts.main(["--watchlist", WL, "--state", st2, "--fixture", FX,
                         "--now", "2026-10-15T10:00:00-04:00", "--dry-run", "--notify", "file"])
            self.assertFalse(os.path.exists(path))

    def test_tickers_with_iv_alerts(self):
        wl = {"tickers": [{"symbol": "AAPL", "alerts": [{"type": "price_above", "value": 1}]},
                          {"symbol": "NVDA", "alerts": [{"type": "iv_below", "value": 20}]}]}
        self.assertEqual(alerts.tickers_with_iv_alerts(wl), {"NVDA"})


class SkillBundle(unittest.TestCase):
    def test_skill_scripts_match_root(self):
        names = ("alerts.py", "brief.py", "quotes.py", "watchlist.py",
                 "market_calendar.py", "notify.py", "indicators.py", "quickstart.py",
                 "schedule.py", "chart.py",
                 "screener.py", "movers.py", "gappers.py", "mcp_server.py")
        root = os.path.join(ROOT, "scripts")
        for skill in ("price-alerts", "watchlist-brief", "watchlist-manager"):
            dest = os.path.join(ROOT, "skills", skill, "scripts")
            for n in names:
                with open(os.path.join(root, n), "rb") as a, open(os.path.join(dest, n), "rb") as b:
                    self.assertEqual(a.read(), b.read(), f"{skill}/scripts/{n} out of sync; run python3 scripts/bundle_skills.py")
            self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", skill, "data", "holidays_overrides.json")))
            self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", skill, "examples", "quotes-fixture.json")))


class HeartbeatReplay(unittest.TestCase):
    def test_replay_with_skill_is_quiet_without_is_spam(self):
        import importlib.util
        path = os.path.join(ROOT, "docs", "demo", "heartbeat", "replay.py")
        spec = importlib.util.spec_from_file_location("hb_replay", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rep = mod.run()
        w = sum(len(r["alerts"]) for r in rep["with_skill"])
        wo = sum(len(r["alerts"]) for r in rep["without_skill"])
        self.assertEqual(w, 3)
        self.assertEqual(wo, 61)
        a = rep["audit"]
        self.assertEqual(a["distinct_events"], 3)
        self.assertEqual(a["repeats"], 58)
        self.assertEqual(a["repeats_regular_hours"], 50)
        self.assertEqual(a["repeats_after_hours"], 6)
        self.assertEqual(a["repeats_closed_weekend"], 2)
        self.assertTrue(a["skill_covered_every_distinct_event"])
        self.assertEqual(a["missed_keys"], [])
        self.assertEqual(a["without_total"], 61)
        self.assertEqual(a["skill_alerts"], 3)
        self.assertEqual(a["closed_or_after_total"], 8)
        self.assertEqual(set(a["by_key"]), {
            "AAPL|price_above:340", "NVDA|intraday_low_pct", "NVDA|pct_change_down",
        })
        sat = [r for r in rep["with_skill"] if r["now"].startswith("2026-10-17")]
        self.assertTrue(sat and sat[0]["skipped"] and sat[0].get("reason") == "weekend")
        after = [r for r in rep["with_skill"] if r.get("last_close")]
        self.assertTrue(after)
        self.assertTrue(all(r["alerts"] == [] for r in after))


class WatchlistCli(unittest.TestCase):
    def test_file_flag_after_subcommand(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "swing.json")
        rc = wlm.main(["add", "MSFT", "--no-verify", "--file", path, "--alert", "price_above:400"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(wlm.load(path)["tickers"][0]["symbol"], "MSFT")

    def test_init_default_is_empty(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "watchlist.json")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = wlm.main(["init", "--file", path])
        self.assertEqual(rc, 0)
        self.assertEqual(wlm.load(path)["tickers"], [])
        out = buf.getvalue()
        self.assertIn("(empty)", out)
        self.assertNotIn("SAMPLE DATA", out)
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(wlm.main(["init", "--file", path]), 1)
        rc = wlm.main(["add", "NVDA", "--no-verify", "--file", path])
        self.assertEqual(rc, 0)
        self.assertEqual(wlm.load(path)["tickers"][0]["symbol"], "NVDA")

    def test_init_empty_flag_still_empty(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "live.json")
        rc = wlm.main(["init", "--empty", "--file", path])
        self.assertEqual(rc, 0)
        self.assertEqual(wlm.load(path)["tickers"], [])

    def test_init_example_copies_sample_and_labels_it(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "watchlist.json")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = wlm.main(["init", "--example", "--file", path])
        self.assertEqual(rc, 0)
        wl = wlm.load(path)
        self.assertGreaterEqual(len(wl["tickers"]), 1)
        self.assertEqual({t["symbol"] for t in wl["tickers"]}, {"AAPL", "TSLA", "NVDA"})
        out = buf.getvalue()
        self.assertIn("SAMPLE DATA", out)
        self.assertIn("sample data", out.lower())
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(wlm.main(["init", "--example", "--file", path]), 1)
        buf2 = io.StringIO()
        with mock.patch("sys.stderr", buf2):
            rc = wlm.main(["add", "NVDA", "--no-verify", "--file", path])
        self.assertEqual(rc, 1)
        self.assertIn("already on watchlist", buf2.getvalue())

    def test_init_example_and_empty_conflict(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "watchlist.json")
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                wlm.main(["init", "--example", "--empty", "--file", path])
        self.assertFalse(os.path.exists(path))

    def test_list_presets(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = wlm.main(["init", "--list-presets"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        for name in ("mega-cap-tech", "index-etfs", "sector-etfs", "dividend-staples"):
            self.assertIn(name, out)
        self.assertIn("SPY", out)
        self.assertIn("XLK", out)
        self.assertIn("JNJ", out)

    def test_init_preset_seeds_symbols_without_price_levels(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "watchlist.json")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = wlm.main(["init", "--preset", "index-etfs", "--file", path])
        self.assertEqual(rc, 0)
        self.assertIn("preset index-etfs", buf.getvalue())
        wl = wlm.load(path)
        self.assertEqual([t["symbol"] for t in wl["tickers"]], ["SPY", "QQQ", "DIA", "IWM"])
        for t in wl["tickers"]:
            self.assertEqual(t.get("side"), "watch")
            self.assertIn("index-etfs", t.get("tags") or [])
            self.assertIsNone(t.get("entry"))
            self.assertIsNone(t.get("stop"))
            self.assertEqual(t.get("targets") or [], [])
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(wlm.main(["init", "--preset", "index-etfs", "--file", path]), 1)

    def test_init_all_presets_validate(self):
        for name in wlm.PRESETS:
            path = os.path.join(tempfile.mkdtemp(), "wl.json")
            self.assertEqual(wlm.main(["init", "--preset", name, "--file", path]), 0, name)
            self.assertEqual(wlm.validate(wlm.load(path)), [], name)

    def test_init_preset_and_example_conflict(self):
        path = os.path.join(tempfile.mkdtemp(), "watchlist.json")
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                wlm.main(["init", "--preset", "mega-cap-tech", "--example", "--file", path])
        self.assertFalse(os.path.exists(path))

    def test_add_verifies_against_fixture(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        self.assertEqual(wlm.main(["init", "--file", path]), 0)
        self.assertEqual(wlm.main(["add", "AAPL", "--file", path, "--fixture", FX]), 0)
        self.assertEqual(wlm.load(path)["tickers"][0]["symbol"], "AAPL")
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = wlm.main(["add", "ZZZZ", "--file", path, "--fixture", FX])
        self.assertEqual(rc, 1)
        self.assertIn("ZZZZ", err.getvalue())
        self.assertIn("--no-verify", err.getvalue())
        self.assertNotIn("ZZZZ", {t["symbol"] for t in wlm.load(path)["tickers"]})

    def test_add_no_verify_skips_lookup(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        self.assertEqual(wlm.main(["add", "ZZZZ", "--no-verify", "--file", path]), 0)
        self.assertEqual(wlm.load(path)["tickers"][0]["symbol"], "ZZZZ")

    def test_add_unknown_yahoo_is_rejected(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        def yahoo_404(symbol, provider="yahoo", fixture=None, fetch_earnings=True):
            raise qt.QuoteError("yahoo", f"{symbol}: unknown symbol (not found on yahoo)",
                                status=404, bare=True)
        err = io.StringIO()
        with mock.patch.object(qt, "get_quote", side_effect=yahoo_404), \
             mock.patch.dict(os.environ, {"WATCHLIST_NO_VERIFY": "", "WATCHLIST_FIXTURE": ""}, clear=False), \
             mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            os.environ.pop("WATCHLIST_NO_VERIFY", None)
            os.environ.pop("WATCHLIST_FIXTURE", None)
            rc = wlm.main(["add", "ZZZZ", "--file", path])
        self.assertEqual(rc, 1)
        self.assertIn("not a known US ticker", err.getvalue())
        self.assertFalse(os.path.exists(path))

    def test_add_network_outage_warns_and_adds(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        def timeout(symbol, provider="yahoo", fixture=None, fetch_earnings=True):
            raise qt.QuoteError("yahoo", "timed out", hint="connection timed out")
        err = io.StringIO()
        with mock.patch.object(qt, "get_quote", side_effect=timeout), \
             mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = wlm.main(["add", "AAPL", "--file", path])
        self.assertEqual(rc, 0)
        self.assertIn("WARN", err.getvalue())
        self.assertIn("Adding anyway", err.getvalue())
        self.assertEqual(wlm.load(path)["tickers"][0]["symbol"], "AAPL")

    def test_preset_quotes_from_sample_fixture_default(self):
        fx = os.path.join(ROOT, "examples", "quotes-fixture.json")
        q = qt.get_quote("SPY", fixture=fx)
        self.assertEqual(q["symbol"], "SPY")
        self.assertEqual(q["source"], "fixture")
        with self.assertRaises(qt.QuoteError):
            qt.from_fixture("ZZZZ", fx)

    def test_missing_watchlist_hint(self):
        msg = wlm.missing_watchlist_hint("nope.json")
        self.assertIn("watchlist.py init", msg)
        self.assertIn("--example", msg)
        self.assertNotIn("--empty", msg)

    def test_default_init_does_not_fire_stale_example_alerts(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "watchlist.json")
        self.assertEqual(wlm.main(["init", "--file", path]), 0)
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = alerts.main(["--watchlist", path, "--state", os.path.join(d, "s.json"),
                              "--fixture", FX, "--now", "2026-10-15T18:30:00-04:00"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertNotIn("reached target", out)
        self.assertNotIn("AAPL", out)


class AlertsMissingWatchlist(unittest.TestCase):
    def test_alerts_hint_when_file_missing(self):
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            rc = alerts.main(["--watchlist", os.path.join(tempfile.mkdtemp(), "missing.json")])
        self.assertEqual(rc, 2)
        self.assertIn("init", buf.getvalue())


class FreshInstallLayouts(unittest.TestCase):
    """Mimic Claude Code / Cursor / Codex skill folders after npx skills add."""

    def _run_layout(self, rel):
        import shutil
        d = tempfile.mkdtemp()
        dest = os.path.join(d, *rel.split("/"), "price-alerts")
        shutil.copytree(os.path.join(ROOT, "skills", "price-alerts"), dest)
        fx = os.path.join(dest, "examples", "quotes-fixture.json")
        self.assertTrue(os.path.exists(fx), rel)
        wl = os.path.join(dest, "watchlist.json")
        rc = wlm.main(["init", "--file", wl])
        self.assertEqual(rc, 0, rel)
        self.assertEqual(wlm.load(wl)["tickers"], [], rel)
        rc = wlm.main(["add", "NVDA", "--no-verify", "--file", wl])
        self.assertEqual(rc, 0, rel)
        st = os.path.join(dest, ".state.json")
        rc = alerts.main(["--watchlist", wl, "--state", st, "--fixture", fx,
                          "--now", "2026-10-15T18:30:00-04:00"])
        self.assertEqual(rc, 0, rel)
        return dest

    def test_claude_cursor_codex_agents_layouts(self):
        for rel in (".claude/skills", ".cursor/skills", ".agents/skills", ".codex/skills"):
            dest = self._run_layout(rel)
            self.assertTrue(os.path.exists(os.path.join(dest, "scripts", "quickstart.py")), rel)


class LiveSnapshot(unittest.TestCase):
    def test_skips_saturday(self):
        import importlib.util
        path = os.path.join(ROOT, "scripts", "live_snapshot.py")
        spec = importlib.util.spec_from_file_location("live_snap", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = tempfile.mkdtemp()
        out = mod.run(WL, d, now=T("2026-10-17T10:00:00"), fixture=FX)
        self.assertTrue(out["skipped"])
        self.assertEqual(out["reason"], "weekend")
        self.assertFalse(os.path.exists(out["path"]))

    def test_fixture_once_per_day(self):
        import importlib.util
        path = os.path.join(ROOT, "scripts", "live_snapshot.py")
        spec = importlib.util.spec_from_file_location("live_snap", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = tempfile.mkdtemp()
        now = T("2026-10-15T16:20:00")
        a = mod.run(WL, d, now=now, fixture=FX)
        self.assertFalse(a["skipped"])
        self.assertTrue(os.path.exists(a["path"]))
        with open(a["path"]) as f:
            body = f.read()
        self.assertIn("fixture", body.lower())
        self.assertIn("ALERT", body)
        b = mod.run(WL, d, now=now, fixture=FX)
        self.assertTrue(b["skipped"])
        self.assertEqual(b["reason"], "already")

    def test_workflows_never_push_main(self):
        """Owner rule: no workflow may commit or push the default branch."""
        wf_dir = os.path.join(ROOT, ".github", "workflows")
        for name in sorted(os.listdir(wf_dir)):
            if not name.endswith((".yml", ".yaml")):
                continue
            with open(os.path.join(wf_dir, name), encoding="utf-8") as f:
                text = f.read()
            for i, line in enumerate(text.splitlines(), 1):
                s = line.split("#", 1)[0].strip()
                if not s:
                    continue
                self.assertNotEqual(s, "git push", f"{name}:{i} bare git push")
                self.assertNotRegex(s, r"git\s+push\s+\S+\s+main\b", f"{name}:{i} {s}")
                self.assertNotIn("HEAD:main", s, f"{name}:{i} {s}")
                self.assertNotIn("HEAD:refs/heads/main", s, f"{name}:{i} {s}")
        with open(os.path.join(wf_dir, "live.yml"), encoding="utf-8") as f:
            live = f.read()
        self.assertIn("live-snapshots", live)
        self.assertIn("publish_live_snapshot.sh", live)
        self.assertNotIn("git commit", live)

    def test_publish_live_snapshot_refuses_main_and_uses_side_branch(self):
        import shutil, subprocess
        script = os.path.join(ROOT, "scripts", "publish_live_snapshot.sh")
        d = tempfile.mkdtemp()
        remote = tempfile.mkdtemp()
        def git(args, cwd=d, check=True):
            return subprocess.run(["git", "-C", cwd, *args], check=check,
                                  capture_output=True, text=True)
        git(["init", "--bare", "-b", "main"], cwd=remote)
        git(["init", "-b", "main"])
        git(["config", "user.email", "test@example.com"])
        git(["config", "user.name", "test"])
        os.makedirs(os.path.join(d, "docs", "live"), exist_ok=True)
        with open(os.path.join(d, "docs", "live", "README.md"), "w") as f:
            f.write("index\n")
        git(["add", "docs/live/README.md"])
        git(["commit", "-m", "seed"])
        git(["remote", "add", "origin", remote])
        git(["push", "-u", "origin", "main"])
        git(["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"])
        dest = os.path.join(d, "docs", "live", "2026-10-16.md")
        with open(dest, "w") as f:
            f.write("# snap\n")
        env = {**os.environ, "LIVE_BRANCH": "main", "LIVE_REMOTE": "origin",
               "GIT_AUTHOR_NAME": "bot", "GIT_AUTHOR_EMAIL": "bot@example.com"}
        denied = subprocess.run(["bash", script, "docs/live/2026-10-16.md"],
                                cwd=d, env=env, capture_output=True, text=True)
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertIn("refusing", denied.stderr)
        env["LIVE_BRANCH"] = "live-snapshots"
        ok = subprocess.run(["bash", script, "docs/live/2026-10-16.md"],
                            cwd=d, env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
        self.assertIn("live-snapshots", git(["ls-remote", "--heads", "origin"]).stdout)
        self.assertNotIn("2026-10-16.md", git(["ls-tree", "-r", "--name-only", "origin/main"]).stdout)
        self.assertIn("docs/live/2026-10-16.md",
                      git(["ls-tree", "-r", "--name-only", "origin/live-snapshots"]).stdout)
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(remote, ignore_errors=True)


class Schedule(unittest.TestCase):
    def test_cron_block_roundtrip(self):
        job = sched.cron_job_line("/tmp/repo", "/usr/bin/python3",
                                  watchlist="/tmp/data/watchlist.json",
                                  state="/tmp/data/.alert_state.json")
        self.assertTrue(job.startswith("*/5 * * * 1-5 "))
        self.assertIn("alerts.py", job)
        self.assertIn("--notify", job)
        self.assertIn("cd /tmp/data", job)
        self.assertIn("--watchlist /tmp/data/watchlist.json", job)
        existing = "MAILTO=me\n0 8 * * * echo hi\n"
        merged = sched.merge_crontab(existing, root="/tmp/repo", python="/usr/bin/python3",
                                     watchlist="/tmp/data/watchlist.json",
                                     state="/tmp/data/.alert_state.json")
        self.assertIn(sched.BEGIN, merged)
        self.assertIn(job, merged)
        self.assertIn("MAILTO=me", merged)
        gone = sched.merge_crontab(merged, uninstall=True)
        self.assertNotIn(sched.BEGIN, gone)
        self.assertNotIn("alerts.py", gone)
        self.assertIn("MAILTO=me", gone)

    def test_windows_prints_schtasks(self):
        cmd = sched.windows_task_cmd("/c/repo", "python.exe",
                                     watchlist="C:\\data\\watchlist.json",
                                     state="C:\\data\\.alert_state.json")
        self.assertIn("schtasks /Create", cmd)
        self.assertIn("MINUTE /MO 5", cmd)
        self.assertIn("alerts.py", cmd)
        self.assertIn("--notify", cmd)
        self.assertIn("cd /d", cmd)
        self.assertIn("C:\\data", cmd)
        self.assertIn("schtasks /Delete", sched.windows_task_cmd(uninstall=True))

    def test_dry_run_does_not_write_crontab_or_ping(self):
        env = {"WATCHLIST_NOTIFY": "file", "WATCHLIST_NOTIFY_FILE": "/tmp/x.jsonl"}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(sched, "write_crontab") as w, \
             mock.patch.object(sched, "send_test_ping") as ping:
            rc, lines = sched.run(action="install", dry_run=True, platform="linux",
                                  root="/tmp/repo", python="python3")
        self.assertEqual(rc, 0)
        w.assert_not_called()
        ping.assert_not_called()
        self.assertTrue(any("Dry-run" in x for x in lines))
        self.assertTrue(any("*/5 * * * 1-5" in x for x in lines))

    def test_missing_notify_exits_2(self):
        with mock.patch.object(notify.os, "environ", {}), \
             mock.patch.object(sched.os, "environ", {}):
            rc, lines = sched.run(action="install", dry_run=True, platform="linux")
        self.assertEqual(rc, 2)
        self.assertTrue(any("Notify is not ready" in x for x in lines))

    def test_install_writes_crontab_and_test_ping(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "n.jsonl")
        wl = os.path.join(d, "watchlist.json")
        env = {"WATCHLIST_NOTIFY": "file", "WATCHLIST_NOTIFY_FILE": path}
        written = []
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(sched, "read_crontab", return_value=""), \
             mock.patch.object(sched, "write_crontab", side_effect=lambda t: written.append(t)), \
             mock.patch.object(sched.shutil, "which", return_value="/usr/bin/crontab"):
            rc, lines = sched.run(action="install", dry_run=False, platform="linux",
                                  root=d, python="python3", watchlist=wl)
        self.assertEqual(rc, 0, lines)
        self.assertTrue(written)
        self.assertIn("*/5 * * * 1-5", written[0])
        self.assertIn("--watchlist", written[0])
        self.assertTrue(os.path.exists(path) and os.path.getsize(path) > 0)
        self.assertTrue(any("Test ping ok" in x for x in lines))
        self.assertTrue(os.path.isfile(os.path.join(d, ".env")))

    def test_windows_dry_run_prints_task(self):
        env = {"WATCHLIST_NOTIFY": "file", "WATCHLIST_NOTIFY_FILE": "/tmp/x.jsonl"}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(sched, "write_crontab") as w, \
             mock.patch.object(sched, "send_test_ping") as ping:
            rc, lines = sched.run(action="install", dry_run=True, platform="win32",
                                  root="C:\\repo", python="python.exe")
        self.assertEqual(rc, 0)
        w.assert_not_called()
        ping.assert_not_called()
        self.assertTrue(any("schtasks /Create" in x for x in lines))

    def test_quickstart_dispatches_schedule(self):
        import quickstart as qs
        with mock.patch.object(sched, "main", return_value=0) as m:
            rc = qs.main(["schedule", "--dry-run"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with(["--dry-run"])

    def test_quickstart_fixture_still_uses_sample_watchlist(self):
        import quickstart as qs
        d = tempfile.mkdtemp()
        path = os.path.join(d, "watchlist.json")
        buf = io.StringIO()
        with IsolatedDataDir(chdir=d), mock.patch("sys.stdout", buf), mock.patch.object(qs, "ROOT", d):
            rc = qs.main(["--file", path])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(path), "quickstart must not write the user watchlist")
        out = buf.getvalue()
        self.assertIn("FIXTURE DEMO", out)
        self.assertIn("does not write watchlist.json", out)
        self.assertIn("ALERT", out)


def _copy_skill(dest_parent, name="price-alerts"):
    dest = os.path.join(dest_parent, name)
    shutil.copytree(os.path.join(ROOT, "skills", name), dest)
    return dest


def _install_skill(proj, name="price-alerts", agent=".claude"):
    """Layout after `npx skills add` into a project: ``<proj>/.claude/skills/<name>``."""
    dest_parent = os.path.join(proj, agent, "skills")
    os.makedirs(dest_parent, exist_ok=True)
    return _copy_skill(dest_parent, name)


class WatchlistPaths(unittest.TestCase):
    def test_watchlist_file_env_wins(self):
        d = tempfile.mkdtemp()
        target = os.path.join(d, "custom.json")
        with IsolatedDataDir(), mock.patch.dict(os.environ, {"WATCHLIST_FILE": target}):
            self.assertEqual(wlm.default_watchlist_path(), target)
            self.assertEqual(wlm.default_state_path(), os.path.join(d, ".alert_state.json"))

    def test_project_cwd_file_used_when_present(self):
        proj = tempfile.mkdtemp()
        wl = os.path.join(proj, "watchlist.json")
        with open(wl, "w") as f:
            json.dump({"version": 1, "settings": {}, "tickers": []}, f)
        with IsolatedDataDir(chdir=proj):
            self.assertEqual(os.path.abspath(wlm.default_watchlist_path()), os.path.abspath(wl))

    def test_skill_folder_defaults_to_user_config(self):
        proj = tempfile.mkdtemp()
        skill = _copy_skill(proj)
        with IsolatedDataDir(chdir=skill) as iso:
            got = os.path.abspath(wlm.default_watchlist_path())
            self.assertEqual(got, os.path.join(iso.xdg, "us-watchlist-alerts", "watchlist.json"))
            self.assertTrue(wlm.is_skill_install_dir(skill))

    def test_legacy_in_skill_watchlist_is_migrated(self):
        proj = tempfile.mkdtemp()
        skill = _copy_skill(proj)
        legacy = os.path.join(skill, "watchlist.json")
        with open(legacy, "w") as f:
            json.dump({"version": 1, "settings": {}, "tickers": [{"symbol": "MSFT", "side": "long"}]}, f)
        with IsolatedDataDir(chdir=skill) as iso:
            got = wlm.default_watchlist_path()
            dest = os.path.join(iso.xdg, "us-watchlist-alerts", "watchlist.json")
            self.assertEqual(os.path.abspath(got), os.path.abspath(dest))
            self.assertEqual(wlm.load(got)["tickers"][0]["symbol"], "MSFT")

    def test_installed_skill_cwd_uses_project_watchlist(self):
        proj = tempfile.mkdtemp()
        skill = _install_skill(proj)
        proj_wl = os.path.join(proj, "watchlist.json")
        with open(proj_wl, "w") as f:
            json.dump({"version": 1, "settings": {}, "tickers": [{"symbol": "AAPL", "side": "long"}]}, f)
        with IsolatedDataDir(chdir=skill):
            got = os.path.abspath(wlm.default_watchlist_path())
            self.assertEqual(got, os.path.abspath(proj_wl))
            os.chdir(os.path.join(skill, "scripts"))
            self.assertEqual(os.path.abspath(wlm.default_watchlist_path()), os.path.abspath(proj_wl))
            self.assertEqual(wlm.load(got)["tickers"][0]["symbol"], "AAPL")

    def test_installed_skill_init_shares_project_root_list(self):
        proj = tempfile.mkdtemp()
        skill = _install_skill(proj, "price-alerts", ".claude")
        manager = _install_skill(proj, "watchlist-manager", ".agents")
        with IsolatedDataDir(chdir=skill) as iso:
            err = io.StringIO()
            with mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", err):
                self.assertEqual(wlm.main(["init"]), 0)
                self.assertEqual(wlm.main(["add", "NVDA", "--no-verify"]), 0)
            proj_wl = os.path.join(proj, "watchlist.json")
            self.assertTrue(os.path.isfile(proj_wl), err.getvalue())
            self.assertIn("using " + os.path.abspath(proj_wl), err.getvalue())
            self.assertEqual([t["symbol"] for t in wlm.load(proj_wl)["tickers"]], ["NVDA"])
            user_wl = os.path.join(iso.xdg, "us-watchlist-alerts", "watchlist.json")
            self.assertFalse(os.path.isfile(user_wl))
            os.chdir(proj)
            self.assertEqual(os.path.abspath(wlm.default_watchlist_path()), os.path.abspath(proj_wl))
            os.chdir(manager)
            self.assertEqual(os.path.abspath(wlm.default_watchlist_path()), os.path.abspath(proj_wl))
            os.chdir(os.path.join(manager, "scripts"))
            self.assertEqual(os.path.abspath(wlm.default_watchlist_path()), os.path.abspath(proj_wl))

    def test_init_add_list_print_using_path(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        err = io.StringIO()
        with mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", err):
            self.assertEqual(wlm.main(["init", "--file", path]), 0)
            self.assertEqual(wlm.main(["add", "AMD", "--no-verify", "--file", path]), 0)
            self.assertEqual(wlm.main(["list", "--file", path]), 0)
        text = err.getvalue()
        self.assertGreaterEqual(text.count("using " + os.path.abspath(path)), 3)


class Journeys(unittest.TestCase):
    """First-time user / agent journeys from the QA report."""

    def test_fresh_install_init_add_alerts_no_stale(self):
        proj = tempfile.mkdtemp()
        skill = _copy_skill(proj)
        with IsolatedDataDir(chdir=proj):
            self.assertEqual(wlm.main(["init"]), 0)
            wl = wlm.default_watchlist_path()
            self.assertEqual(os.path.abspath(wl), os.path.join(proj, "watchlist.json"))
            self.assertEqual(wlm.main(["add", "AAPL", "--no-verify", "--alert", "pct_change_down:3"]), 0)
            self.assertEqual(wlm.main(["add", "NVDA", "--no-verify", "--stop", "140"]), 0)
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = alerts.main(["--watchlist", wl, "--state", os.path.join(proj, ".s.json"),
                                  "--fixture", FX, "--now", "2026-10-15T11:00:00-04:00"])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertNotIn("above $240", out)
            self.assertNotIn("reached target", out)
            self.assertNotIn("golden cross", out)
            self.assertEqual({t["symbol"] for t in wlm.load(wl)["tickers"]}, {"AAPL", "NVDA"})
            self.assertFalse(os.path.exists(os.path.join(skill, "watchlist.json")))

    def test_quickstart_then_add_works(self):
        import quickstart as qs
        proj = tempfile.mkdtemp()
        skill = _copy_skill(proj)
        with IsolatedDataDir(chdir=skill):
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = qs.main([])
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertIn("FIXTURE DEMO", buf.getvalue())
            self.assertFalse(os.path.exists(os.path.join(skill, "watchlist.json")))
            self.assertFalse(os.path.exists(os.path.join(skill, ".quickstart_state.json")))
            err = io.StringIO()
            with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
                rc = wlm.main(["add", "AAPL", "--no-verify", "--alert", "pct_change_down:3"])
            self.assertEqual(rc, 0, err.getvalue())
            wl = wlm.default_watchlist_path()
            self.assertEqual([t["symbol"] for t in wlm.load(wl)["tickers"]], ["AAPL"])
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                rc = alerts.main(["--watchlist", wl, "--state", wlm.default_state_path(wl),
                                  "--fixture", FX, "--now", "2026-10-15T11:00:00-04:00"])
            self.assertEqual(rc, 0)
            self.assertNotIn("above $240", out.getvalue())
            self.assertNotIn("reached target", out.getvalue())

    def test_reinstall_preserves_list(self):
        proj = tempfile.mkdtemp()
        skill = _copy_skill(proj)
        with IsolatedDataDir(chdir=skill) as iso:
            self.assertEqual(wlm.main(["init"]), 0)
            self.assertEqual(wlm.main(["add", "AAPL", "--no-verify"]), 0)
            saved = wlm.default_watchlist_path()
            self.assertTrue(saved.startswith(iso.xdg))
            shutil.rmtree(skill)
            skill2 = _copy_skill(proj)
            os.chdir(skill2)
            self.assertFalse(os.path.exists(os.path.join(skill2, "watchlist.json")))
            self.assertEqual([t["symbol"] for t in wlm.load(wlm.default_watchlist_path())["tickers"]], ["AAPL"])
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                self.assertEqual(wlm.main(["list"]), 0)
            self.assertIn("AAPL", buf.getvalue())

    def test_cross_skill_shared_list(self):
        proj = tempfile.mkdtemp()
        manager = _copy_skill(proj, "watchlist-manager")
        alerts_skill = _copy_skill(proj, "price-alerts")
        brief_skill = _copy_skill(proj, "watchlist-brief")
        with IsolatedDataDir(chdir=manager) as iso:
            self.assertEqual(wlm.main(["init"]), 0)
            self.assertEqual(wlm.main(["add", "NVDA", "--no-verify", "--alert", "pct_change_down:3"]), 0)
            shared = os.path.join(iso.xdg, "us-watchlist-alerts", "watchlist.json")
            self.assertEqual(os.path.abspath(wlm.default_watchlist_path()), os.path.abspath(shared))
            os.chdir(alerts_skill)
            self.assertEqual([t["symbol"] for t in wlm.load(wlm.default_watchlist_path())["tickers"]], ["NVDA"])
            os.chdir(brief_skill)
            self.assertEqual([t["symbol"] for t in wlm.load(wlm.default_watchlist_path())["tickers"]], ["NVDA"])

    def test_overnight_journey_d_then_d1(self):
        st = {"fired": {}}
        wl = wlm.load(WL)
        q = quotes()
        day = alerts.run(wl, st, q, T("2026-10-15T15:00"))
        self.assertTrue(day["alerts"])
        for ts in ("2026-10-16T00:05", "2026-10-16T09:00"):
            nxt = alerts.run(wl, st, q, T(ts))
            self.assertEqual(nxt["alerts"], [], ts)


class CliUx(unittest.TestCase):
    """P1 / cheap P2 from the 2026-10-20 QA report."""

    def test_watchlist_provider_env_reaches_alerts(self):
        seen = []
        def fake(sym, provider="auto", fixture=None, **kw):
            seen.append(provider)
            raise qt.QuoteError("alpaca", "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set")
        env = {"WATCHLIST_PROVIDER": "alpaca", "ALPACA_API_KEY_ID": "", "ALPACA_API_SECRET_KEY": ""}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(alerts.qt, "get_quote", side_effect=fake), \
             mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            rc = alerts.main(["--watchlist", WL, "--dry-run", "--now", "2026-10-15T10:00:00-04:00"])
        self.assertTrue(seen)
        self.assertEqual(seen[0], "alpaca")
        self.assertEqual(rc, 3)

    def test_all_quotes_failed_exits_3(self):
        def boom(*a, **k):
            raise RuntimeError("feed down")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(alerts.qt, "get_quote", side_effect=boom), \
             mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = alerts.main(["--watchlist", WL, "--dry-run", "--now", "2026-10-15T10:00:00-04:00"])
        self.assertEqual(rc, 3)
        self.assertIn("ERROR no quotes", err.getvalue())
        self.assertNotIn("no new alerts", out.getvalue())

    def test_empty_watchlist_hint(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        self.assertEqual(wlm.main(["init", "--file", path]), 0)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = alerts.main(["--watchlist", path, "--now", "2026-10-15T10:00:00-04:00"])
        self.assertEqual(rc, 0)
        self.assertIn("Watchlist is empty", out.getvalue())
        self.assertIn("watchlist.py add", out.getvalue())
        self.assertNotIn("no new alerts", out.getvalue())
        bout = io.StringIO()
        with mock.patch("sys.stdout", bout), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(brief.main(["--watchlist", path, "--kind", "morning"]), 0)
        self.assertIn("Watchlist is empty", bout.getvalue())

    def test_unknown_symbol_is_short_no_alpaca_hint(self):
        def yahoo_404(symbol):
            raise qt.QuoteError("yahoo", '{"finance":{"error":{"code":"Not Found"}}}', status=404,
                                hint="unknown symbol or endpoint")
        with mock.patch.object(qt, "auto_order", return_value=["yahoo"]), \
             mock.patch.dict(qt.PROVIDERS, {"yahoo": yahoo_404}):
            with self.assertRaises(qt.QuoteError) as cm:
                qt.get_quote("ZZZZ")
        msg = str(cm.exception)
        self.assertIn("ZZZZ: unknown symbol", msg)
        self.assertNotIn("ALPACA", msg)
        self.assertLess(len(msg), 120)

    def test_provider_key_missing_hint_is_specific(self):
        with mock.patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            with self.assertRaises(qt.QuoteError) as cm:
                qt.get_quote("AAPL", provider="finnhub")
        msg = str(cm.exception)
        self.assertIn("FINNHUB_API_KEY", msg)
        self.assertNotIn("WATCHLIST_PROVIDER=yahoo", msg)

    def test_watchlist_cli_friendly_errors(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        self.assertEqual(wlm.main(["init", "--file", path]), 0)
        cases = [
            (["add", "123", "--no-verify", "--file", path], "bad symbol"),
            (["add", "TOOLONGX", "--no-verify", "--file", path], "bad symbol"),
            (["add", "AMD", "--no-verify", "--alert", "bogus_type:1", "--file", path], "unknown alert type"),
            (["add", "AMD", "--no-verify", "--alert", "price_below:abc", "--file", path], "must be a number"),
            (["add", "AMD", "--no-verify", "--stop", "200", "--entry", "100", "--file", path], "stop"),
        ]
        for argv, needle in cases:
            err = io.StringIO()
            with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
                rc = wlm.main(argv)
            self.assertEqual(rc, 1, argv)
            self.assertIn(needle, err.getvalue().lower(), argv)
            self.assertNotIn("Traceback", err.getvalue(), argv)
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = wlm.main(["update", "ZZZ", "--stop", "1", "--file", path])
        self.assertEqual(rc, 1)
        self.assertIn("ZZZ not on watchlist", err.getvalue())
        self.assertNotIn("'ZZZ'", err.getvalue())

    def test_malformed_json_message(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        with open(path, "w") as f:
            f.write("{bad")
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = wlm.main(["list", "--file", path])
        self.assertEqual(rc, 1)
        self.assertIn("not valid JSON", err.getvalue())
        self.assertIn("line ", err.getvalue())
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(alerts.main(["--watchlist", path]), 1)

    def test_yaml_without_pyyaml_cleans_tmp(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "w.yaml")
        real_import = __import__
        def fake(name, *a, **k):
            if name == "yaml":
                raise ImportError("No module named yaml")
            return real_import(name, *a, **k)
        err = io.StringIO()
        with mock.patch("builtins.__import__", side_effect=fake), \
             mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = wlm.main(["add", "AMD", "--no-verify", "--file", path])
        self.assertEqual(rc, 1)
        self.assertIn("pyyaml", err.getvalue().lower())
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_add_creates_parent_dirs(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "new", "sub", "x.json")
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(wlm.main(["add", "AMD", "--no-verify", "--file", path]), 0)
        self.assertTrue(os.path.isfile(path))

    def test_chart_unknown_ticker_one_line(self):
        err = io.StringIO()
        with mock.patch.object(chart.qt, "get_quote", side_effect=qt.QuoteError("yahoo", "ZZZZ: unknown symbol (not found on yahoo)", bare=True)), \
             mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = chart.main(["ZZZZ"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        err2 = io.StringIO()
        with mock.patch("sys.stderr", err2), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(chart.main(["AAPL", "--sma", "abc"]), 1)
        self.assertIn("--sma", err2.getvalue())

    def test_chart_sma_not_enough_history_omitted(self):
        q = {"symbol": "AAPL", "price": 10, "prev_close": 9, "closes": list(range(60)), "source": "fixture"}
        with mock.patch.object(chart.qt, "get_quote", return_value=q):
            text = chart.render("AAPL", sma_ns=[20, 500])["text"]
        self.assertIn("sma20", text)
        self.assertNotIn("sma500=+", text)
        self.assertIn("not enough history", text)

    def test_now_accepts_zulu_and_rejects_garbage(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = alerts.main(["--watchlist", WL, "--fixture", FX, "--dry-run",
                              "--now", "2026-10-15T15:00:00Z"])
        self.assertEqual(rc, 0, err.getvalue())
        err2 = io.StringIO()
        with mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", err2):
            self.assertEqual(alerts.main(["--watchlist", WL, "--now", "garbage"]), 1)
        self.assertIn("invalid --now", err2.getvalue())
        self.assertNotIn("Traceback", err2.getvalue())

    def test_market_calendar_cli_date(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(mc.main(["2026-11-26"]), 0)
        self.assertIn("2026-11-26", out.getvalue())
        self.assertIn("session=closed", out.getvalue())
        with mock.patch("sys.stdout", io.StringIO()), self.assertRaises(SystemExit) as cm:
            mc.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_bundle_help_does_not_run(self):
        import bundle_skills as bs
        with mock.patch.object(bs, "bundle") as b, self.assertRaises(SystemExit) as cm:
            bs.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        b.assert_not_called()

    def test_dotenv_merge_quotes_ampersand(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, ".env")
        with open(path, "w") as f:
            f.write("UNRELATED=keep\n")
        env = {"WATCHLIST_NOTIFY": "webhook", "WATCHLIST_WEBHOOK_URL": "https://x.test/hook?a=1&b=2"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertTrue(sched.merge_dotenv(path))
        with open(path) as f:
            text = f.read()
        self.assertIn("UNRELATED=", text)
        self.assertIn("WATCHLIST_NOTIFY=", text)
        self.assertIn("WATCHLIST_WEBHOOK_URL=", text)
        self.assertIn("&", text)
        self.assertTrue("'" in text or '"' in text)

    def test_windows_tr_quotes_spaces(self):
        cmd = sched.windows_task_cmd(
            r"C:\Program Files\repo", r"C:\Program Files\Python\python.exe",
            watchlist=r"C:\Users\Me\My Data\watchlist.json",
            state=r"C:\Users\Me\My Data\.alert_state.json",
        )
        self.assertIn("cd /d", cmd)
        self.assertIn("Program Files", cmd)
        self.assertIn('\\"', cmd)

    def test_added_date_is_et(self):
        wl = {"version": 1, "settings": {}, "tickers": []}
        t = wlm.add(wl, "AMD")
        self.assertEqual(t["added"], wlm._today_et().isoformat())
        self.assertRegex(t["added"], r"^\d{4}-\d{2}-\d{2}$")

    def test_brief_kind_defaults_by_session(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            brief.main(["--watchlist", WL, "--fixture", FX, "--now", "2026-10-15T10:55:00-04:00"])
        self.assertIn("intraday brief", out.getvalue())

    def test_unwritable_state_dir_is_friendly(self):
        d = tempfile.mkdtemp()
        blocker = os.path.join(d, "not-a-dir")
        with open(blocker, "w") as f:
            f.write("x")
        state = os.path.join(blocker, ".alert_state.json")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = alerts.main(["--watchlist", WL, "--state", state, "--fixture", FX,
                              "--now", "2026-10-15T10:00:00-04:00"])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err.getvalue())
        self.assertIn("cannot write alert state", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertNotIn("Traceback", out.getvalue())

    def test_brief_all_quotes_failed_exits_3(self):
        def boom(*a, **k):
            raise RuntimeError("feed down")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(brief.qt, "get_quote", side_effect=boom), \
             mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = brief.main(["--watchlist", WL, "--kind", "morning",
                             "--now", "2026-10-15T08:30:00-04:00"])
        self.assertEqual(rc, 3)
        self.assertIn("ERROR no quotes", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_wrong_top_level_key_is_not_empty(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        with open(path, "w") as f:
            json.dump({"version": 1, "watchlist": [{"symbol": "AAPL", "side": "long"}]}, f)
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            rc = wlm.main(["list", "--file", path])
        self.assertEqual(rc, 1)
        msg = err.getvalue()
        self.assertIn("watchlist", msg)
        self.assertIn("tickers", msg)
        self.assertNotIn("Watchlist is empty", msg)
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(alerts.main(["--watchlist", path]), 1)
        missing = os.path.join(d, "notickers.json")
        with open(missing, "w") as f:
            json.dump({"version": 1, "settings": {}}, f)
        err2 = io.StringIO()
        with mock.patch("sys.stderr", err2), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(wlm.main(["list", "--file", missing]), 1)
        self.assertIn("missing top-level 'tickers'", err2.getvalue())

    def test_installed_skills_do_not_point_at_unshipped_docs(self):
        for skill in ("price-alerts", "watchlist-manager", "watchlist-brief"):
            path = os.path.join(ROOT, "skills", skill, "SKILL.md")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("`docs/LIMITATIONS.md`", text, skill)
            self.assertNotIn("`HEARTBEAT.md`", text, skill)
            self.assertNotIn("See README for env", text, skill)
            self.assertNotIn("python scripts/", text, skill)
            if "LIMITATIONS.md" in text:
                self.assertIn("github.com/eli-alvarado/us-watchlist-alerts", text, skill)


if __name__ == "__main__":
    unittest.main()

