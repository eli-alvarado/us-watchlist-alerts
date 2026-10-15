# Changelog

## Unreleased

- **With vs. without demo** (`docs/demo/`): live 2026-10-15 after-hours transcripts (Cursor Grok 4.6). Unedited. The without-skill agent did fine on quotes and the NYSE calendar; the skill’s edge is persist + session labeling + evaluating the rest of the book.

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
