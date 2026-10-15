# Changelog

## 0.2.0 — 2026-10-15

Make the heartbeat loop trustworthy: closures, earnings without yfinance, official data when keyed.

- **Unscheduled closures:** `data/holidays_overrides.json` ships known NYSE mourning/weather days (incomplete on purpose). Still overridable via `NYSE_EXTRA_CLOSURES` / `settings.extra_closures`. With Alpaca keys, `alerts.py` / `brief.py` overlay the official Trading API calendar so missing weekdays are treated as closed.
- **Earnings without yfinance:** after a quote is fetched, dates are filled from Yahoo `calendarEvents` (stdlib), then Finnhub earnings calendar, then Alpha Vantage `EARNINGS_CALENDAR`. yfinance remains first if it already set the field.
- **Official quote path:** when Alpaca keys are set, `auto` tries Alpaca first (snapshot **and** daily bars, so MA/RSI/52-week rules work). Finnhub now pulls candles for history too.
- **Robust HTTP:** retries on 429/5xx with backoff; `QuoteError` includes provider, HTTP status, and a hint. `WATCHLIST_HTTP_TIMEOUT` is configurable.
- **Stale quotes:** `--stale-after` / `WATCHLIST_STALE_AFTER` / `settings.stale_after_seconds` (default 900s) warn during the regular session when `as_of` is too old.

## 0.1.0 — 2026-10-15

Initial skills, stdlib scripts, fixture tests, CI on Python 3.10–3.13, README comparison and limitations.
