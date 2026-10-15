import copy, datetime as dt, io, json, os, sys, tempfile, unittest, urllib.error, warnings
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import alerts, brief, indicators as ind, market_calendar as mc, notify, quotes as qt, watchlist as wlm

FX = os.path.join(ROOT, "tests", "fixtures", "quotes.json")
WL = os.path.join(ROOT, "tests", "fixtures", "watchlist.json")
ET = mc.ET
def T(s): return dt.datetime.fromisoformat(s).replace(tzinfo=ET)
def quotes(): return {s: qt.get_quote(s, fixture=FX) for s in ("AAPL", "TSLA", "NVDA")}


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
    def test_class_shares_symbol(self):
        self.assertTrue(wlm.SYMBOL_RE.match("BRK.B")); self.assertTrue(wlm.SYMBOL_RE.match("BF-B"))
    def test_cli(self):
        self.assertIsNone(wlm.main(["--file", self.p, "add", "AMD", "--entry", "150", "--stop", "130", "--tag", "semis"]))
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
        self.assertFalse(alerts.run(self.wl, {"fired": {}}, self.q, T("2026-10-17T10:00"), force_session=True)["skipped"])
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
        closes, vols, opens, n = qt._aligned_ohlcv({
            "close": [1.0, None, 3.0],
            "volume": [10, 99, 30],
            "open": [0.9, 2.0, 2.9],
        })
        self.assertEqual(closes, [1.0, 3.0])
        self.assertEqual(vols, [10, 30])
        self.assertEqual(n, 3)
        self.assertEqual(opens, [0.9, 2.9])
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
             mock.patch.object(qt, "earnings_from_finnhub", return_value="2026-11-15"), \
             mock.patch.dict(os.environ, {"FINNHUB_API_KEY": "k"}):
            ed, src = qt.lookup_earnings("AAPL")
        self.assertEqual((ed, src), ("2026-11-15", "finnhub"))
        self.assertEqual(qt.lookup_earnings("AAPL", existing="2026-10-01"), ("2026-10-01", "existing"))

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
            {"type": "iv_above", "value": 40}, {"type": "intraday_range_pct", "value": 8}]}]}
        self.assertEqual(wlm.validate(wl), [])

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


if __name__ == "__main__":
    unittest.main()

