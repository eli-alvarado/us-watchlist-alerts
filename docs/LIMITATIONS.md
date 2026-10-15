# Limitations

This project is an **informational** US-listed watchlist and alerter. It is not a broker, not a scanner, and not financial advice. Agents that load these skills are instructed **never** to place, modify, or cancel an order without explicit confirmation of that specific order.

## Market calendar

Regular NYSE holidays and 1:00 PM ET early closes are **rule-based** in `scripts/market_calendar.py` (New Year’s, MLK, Presidents’ Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas; New Year’s on Saturday is not observed Friday).

Unscheduled closures (days of mourning, weather, outages) are handled in layers, none of which is a complete live exchange feed:

1. **Bundled file** `data/holidays_overrides.json` — known historical special days (e.g. 2025-01-09 Carter mourning, Sandy 2012). Incomplete; PRs welcome when NYSE announces a new one.
2. **Local overrides** — `NYSE_EXTRA_CLOSURES=YYYY-MM-DD,...` or watchlist `settings.extra_closures`.
3. **Official overlay (optional)** — with Alpaca keys, `alerts.py` / `brief.py` pull `GET /v2/calendar` and treat weekdays missing from that list as closed. The response is cached on disk for the ET calendar day (`.nyse_calendar_cache.json` / `NYSE_CALENDAR_CACHE`) so a 15-minute HEARTBEAT does not hit the API every tick. If today's fetch fails, a same-year stale cache is reused. Network failure without a cache is ignored and the rule-based + bundled calendar still applies.

If quotes look stale on a weekday the calendar thinks is open, treat the session as closed and add the date to `extra_closures`.

## Earnings dates

Filled independently of the price provider, first success:

| Order | Source | Needs |
|------:|--------|-------|
| 1 | Already on the quote (yfinance / fixture) | — |
| 2 | Yahoo `quoteSummary` `calendarEvents` | unofficial; cookie + crumb |
| 3 | Yahoo quote HTML | unofficial; same page often embeds the date |
| 4 | Nasdaq analyst `earnings-date` | nothing (free JSON) |
| 5 | Finnhub `/calendar/earnings` | `FINNHUB_API_KEY` |
| 6 | Alpha Vantage `EARNINGS_CALENDAR` | `ALPHAVANTAGE_API_KEY` |

Dates can be wrong, delayed, or missing. Confirm against the issuer’s IR calendar before acting. `earnings_source` on the quote dict says which layer won.

## Quote providers

Auto fallback (`WATCHLIST_PROVIDER=auto` / `--provider auto`), first success wins:

| Order | Provider | Needs | History (MA / RSI / 52w) | Notes |
|------:|----------|-------|---------------------------|-------|
| 1 | `--fixture` | path | if present in file | tests/demos |
| 2 | Alpaca snapshot + daily bars | `ALPACA_API_KEY_ID` + `ALPACA_API_SECRET_KEY` | **yes** when bars succeed | official US feed; tried first when keyed |
| 3 | `yfinance` | `pip install yfinance` | yes | unofficial Yahoo wrapper |
| 4 | Yahoo public chart | nothing (stdlib) | yes | unofficial; `query1` then `query2` |
| 5 | Finnhub quote + candles | `FINNHUB_API_KEY` | **yes** when candles succeed | |
| 6 | Alpha Vantage daily | `ALPHAVANTAGE_API_KEY` | yes | hard daily cap |

Yahoo hosts are unofficial and can change, rate-limit, or require cookies. Free Yahoo / yfinance quotes may be delayed ~15 minutes. HTTP calls retry 429/5xx; failures raise `QuoteError` with provider, status, and a hint.

**Yahoo `chartPreviousClose` is not yesterday's close.** On a 1-year daily chart it is the print before the range (often ~12 months old). This repo uses `previousClose` / `regularMarketPreviousClose` when present, otherwise the prior daily bar. `as_of` prefers `regularMarketTime`.

**Yahoo crumb:** quoteSummary and options need cookies (`fc.yahoo.com` 404 is OK) plus a crumb (from the quote HTML, or `/v1/test/getcrumb`). `getcrumb` 429s easily; the HTML crumb is preferred. When that still fails, earnings fall through to Nasdaq; IV tries yfinance if installed. Remaining failures set `earnings_error` / `iv_error` and print a WARN — they do not invent values. The daily chart path does not need a crumb.

`--provider` / `WATCHLIST_PROVIDER` pins a single provider and does not fall through.

## Quote dict fields

| Field | Meaning |
|---|---|
| `symbol` | Uppercase ticker |
| `price` | Last / regular-session price used by alerts |
| `prev_close` | Prior session close |
| `open` | Session open (gap alerts) |
| `day_high` / `day_low` | Session range |
| `volume` | Session volume |
| `avg_volume_20d` | Mean of prior ~20 daily volumes |
| `high_52w` / `low_52w` | 52-week extremes |
| `closes` | Daily closes, oldest → newest (omitted from CLI unless `--full`) |
| `earnings_date` | ISO date or `null` |
| `earnings_source` | `yfinance`, `yahoo-calendar`, `yahoo-html`, `nasdaq`, `finnhub`, `alphavantage`, or `null` |
| `source` | Winning quote provider (`alpaca`, `yahoo-chart`, …) |
| `as_of` | UTC timestamp when the quote was assembled |
| `atm_iv` | Nearest-expiry ATM implied vol in **percent**, or `null` |
| `iv_expiry` | ISO date of that options expiration, or `null` |
| `iv_source` | `yahoo-options` or `yfinance-options` when filled |

`--stale-after` (default 900s, env `WATCHLIST_STALE_AFTER`, setting `stale_after_seconds`) warns during the **regular** session when `as_of` is older than that. `0` disables.

## ATM implied volatility

`iv_above` / `iv_below` use Yahoo's unofficial `v7/finance/options/{symbol}` chain (nearest expiration only). The ATM strike is the closest listed strike to last price; call and put `impliedVolatility` are averaged when both are present and positive. Yahoo usually returns a decimal (`0.25` → 25%); values already in percent pass through. The chain is fetched **only** for tickers that have an IV rule, and never on `--fixture` unless `atm_iv` is already in the file.

Skipped (the rule does not fire) when IV is missing or `0`. This is **not** IV rank, IV percentile, unusual options activity, or a Black-Scholes model. Those need history or flow data this project does not have on the free path.

Nearest-expiry can be **0DTE**. After the bell on expiration day that print can look implausibly tight (SPY printed ~1.8% on 2026-10-15). We do not invent the next expiry when Yahoo only returns today's chain.

## Intraday range and session extremes

`intraday_range_pct` is `(day_high - day_low) / prev_close * 100` (falls back to `day_low` if `prev_close` is missing). If the provider omitted `day_high`/`day_low`, the rule is silent. Daily `closes` are never used as a substitute.

**Default % moves (`pct_change_up` / `pct_change_down` / `pct_move`) use last vs prior close.** After the bell that last is the regular close. A session low that recovered (NVDA 2026-10-15: low −3.82%, close −1.84%) does **not** fire `pct_change_down: 3`.

**Opt-in session extremes:** `intraday_low_pct` / `intraday_high_pct` / alias `intraday_extreme_pct` compare `day_low` / `day_high` to prior close. Same skip if high/low are missing. Once per trading day. Not added unless the user asks.

## Alert delivery

`scripts/notify.py` POSTs fired alerts to webhook / Slack / ntfy, runs Linux `notify-send`, or appends JSONL. Failures are warnings. Sinks are not brokers: there is still no order ticket, no signed trading request, and no "just send it" path.

## What this does not do

- Non-US listings, FX, crypto, futures, or a full options chain / greeks / payoff calculator.
- Intraday bars (beyond the session high/low the quote already carries), Level 2, or guaranteed real-time data on the free path.
- IV rank, unusual options flow, or email/Telegram (use ntfy for phones).
- Portfolio accounting, tax lots, or broker positions (the watchlist is a thesis/stop/target file, not a broker sync).
- News, filings, or fundamentals (use a research skillset for that).
- Automatic order routing.

## Anti-spam caveats

- Level alerts latch until price (or IV, for `iv_*`) re-arms by `rearm_pct` (default 0.5%).
- Daily events fire at most once per trading date per ticker/type.
- `max_alerts_per_run` truncates **output** without latching the omitted alerts, so the next run can emit them.
- Deleting `.alert_state.json` mid-session will re-send alerts.
