# Changelog

## Unreleased

- `examples/watchlist.yaml` `extra_closures` is `[]` again. 2026-11-04 is a regular NYSE session; copying that sample would have muted alerts that day.
- **Live snapshot never writes `main`.** `.github/workflows/live.yml` publishes dated `docs/live/YYYY-MM-DD.md` to the [`live-snapshots`](https://github.com/eli-alvarado/us-watchlist-alerts/tree/live-snapshots/docs/live) branch and the job summary. `scripts/publish_live_snapshot.sh` refuses `main` / `master` / the remote default. The 2026-10-15 file that github-actions[bot] pushed to main (`b236a62`) was the violation this closes. CI and label-good-first do not push.

## 0.4.1 — 2026-10-16

After-hours `prev_close` and weekday wording.

- **Yahoo 1d after ~20:00 ET:** the chart keeps today’s timestamp with `close: None`. `_aligned_ohlcv` now drops that timestamp with the null close, so `prev_close` is yesterday (NVDA $221.30 on 2026-10-15) not two sessions ago ($228.52). `previousClose` that has rolled onto last is ignored when bars disagree.
- **Docs:** `docs/live/2026-10-15.md` uses Thursday last vs Wednesday prior close (same as README ~18:45 ET and the heartbeat replay). The original 20:09 ET Action write is footnoted. Live Action copy says **weekday**, not daily.
- README install notes from Unreleased 0.4.0: Claude Code needs `-a claude-code`; Cursor / Codex / Gemini CLI use `-a cursor` / `-a codex` / `-a gemini-cli`. `watchlist.py init --empty` starts a live book.

## 0.4.0 — 2026-10-15

Pre-launch hardening. Still no auto-trade.

- **Fresh-install friction:** `watchlist.py init` copies the bundled example. `--file` works after the subcommand (`add AAPL --file swing.json`). `alerts.py` / `brief.py` print a hint instead of a silent empty run when the watchlist file is missing. `scripts/quickstart.py` is a one-command fixture demo after `npx skills add`. Offline `examples/quotes-fixture.json` ships inside each skill folder.
- **Hero GIF** (`docs/hero.gif`, ~15s, labeled fixture / replayed) plus a How-it-works mermaid and FAQ (cost, never trades, privacy, data sources). [SECURITY.md](SECURITY.md) covers API keys and notify URLs.
- **Scheduled live snapshot** (`.github/workflows/live.yml`): sample watchlist on weekdays, session-aware, no secrets. Job summary every run; **at most one** `docs/live/YYYY-MM-DD.md` commit per ET trading day.
- README SEO: title and lede use “US stock watchlist”, “price alerts”, “Claude Code / Cursor / Codex”, “no API key”, “NYSE”.
- Heartbeat framing from Unreleased: same 3 important moves; 58 duplicate pings avoided.

## 0.3.3 — 2026-10-15

- **Opt-in session extremes:** `intraday_low_pct` / `intraday_high_pct` / alias `intraday_extreme_pct` fire on session low or high vs prior close. Default `pct_change_*` remains last vs prior close (a recovered low does not fire). Docs say this plainly.
- **Heartbeat replay demo** (`docs/demo/heartbeat/`): replayed Yahoo 15-minute bars for 2026-10-15. Same rules every tick: **3 alerts with the skill, 61 without** (no latch, no weekend skip). README with-vs-without now leads with this.

## 0.3.2 — 2026-10-15

First-run friction: install, after-hours, earnings/IV.

- **`npx skills add` ships `scripts/`** (and holiday data + example watchlist) inside each skill folder, so the one-liner is enough to run `quotes.py` / `alerts.py` without a separate clone.
- **After-hours last-close mode:** on a trading day outside `settings.sessions`, evaluate the last regular close and print `market closed, showing last regular close`. Weekends and full-day holidays stay skipped (with the next session date). `--force-session` is no longer required after the bell.
- **Earnings / ATM IV:** Yahoo crumb from `fc.yahoo.com` + quote HTML (browser UA), then Nasdaq analyst `earnings-date` as a key-free fallback. IV tries Yahoo options (crumb) then yfinance if installed. Failures set `earnings_error` / `iv_error` (one line, no raw JSON dump) instead of inventing values. Live 2026-10-15 after hours: AAPL/NVDA earnings + ATM IV via crumb; Nasdaq agreed when Yahoo layers were forced off.

## 0.3.1 — 2026-10-15

Live Yahoo path: do not treat `chartPreviousClose` as yesterday's close (it is the print before the chart range, so a 1y chart produced fake +16–37% daily moves). `prev_close` is now `previousClose` / `regularMarketPreviousClose`, else the prior daily bar. `as_of` uses `regularMarketTime` when present. quoteSummary / options attach a Yahoo crumb + cookies when Yahoo will mint one (those endpoints 401 without it).

## 0.3.0 — 2026-10-15

Alert delivery, ATM IV / intraday-range rules, and a cheaper official calendar.

- **Notify sinks:** `scripts/notify.py` plus `alerts.py --notify`. Env `WATCHLIST_NOTIFY=webhook,slack,ntfy,desktop,file`. JSON webhook (`WATCHLIST_WEBHOOK_URL`), Slack incoming webhook (`SLACK_WEBHOOK_URL`), ntfy (`NTFY_TOPIC` / `NTFY_URL` / `NTFY_TOKEN`), Linux `notify-send`, JSONL file (`WATCHLIST_NOTIFY_FILE`). Empty, skipped, and `--dry-run` runs do not deliver. A sink failure is a `WARN`, not a crash. Still never places trades.
- **ATM IV alerts:** `iv_above` / `iv_below` use unofficial Yahoo `v7/finance/options` nearest-expiry ATM call/put IV (percent). Fetched only for tickers that have those rules, skipped when IV is missing or zero. No IV rank, unusual-options flow, or Black-Scholes.
- **Intraday range:** `intraday_range_pct` fires from provider `day_high` / `day_low` only — never invented from daily closes.
- **Calendar disk cache:** Alpaca `/v2/calendar` is stored in `.nyse_calendar_cache.json` (override `NYSE_CALENDAR_CACHE`) for the ET day so HEARTBEAT ticks do not hit the API every 15 minutes. Same-year stale cache is reused if today's fetch fails.
- Demo GIF refreshed to show `NOTIFY file`. Multi-watchlist profiles documented.

## 0.2.0 — 2026-10-15

Make the heartbeat loop trustworthy: closures, earnings without yfinance, official data when keyed.

- **Unscheduled closures:** `data/holidays_overrides.json` ships known NYSE mourning/weather days (incomplete on purpose). Still overridable via `NYSE_EXTRA_CLOSURES` / `settings.extra_closures`. With Alpaca keys, `alerts.py` / `brief.py` overlay the official Trading API calendar so missing weekdays are treated as closed.
- **Earnings without yfinance:** after a quote is fetched, dates are filled from Yahoo `calendarEvents` (stdlib), then Finnhub earnings calendar, then Alpha Vantage `EARNINGS_CALENDAR`. yfinance remains first if it already set the field.
- **Official quote path:** when Alpaca keys are set, `auto` tries Alpaca first (snapshot **and** daily bars, so MA/RSI/52-week rules work). Finnhub now pulls candles for history too.
- **Robust HTTP:** retries on 429/5xx with backoff; `QuoteError` includes provider, HTTP status, and a hint. `WATCHLIST_HTTP_TIMEOUT` is configurable.
- **Stale quotes:** `--stale-after` / `WATCHLIST_STALE_AFTER` / `settings.stale_after_seconds` (default 900s) warn during the regular session when `as_of` is too old.

## 0.1.0 — 2026-10-15

Initial skills, stdlib scripts, fixture tests, CI on Python 3.10–3.13, README comparison and limitations.
