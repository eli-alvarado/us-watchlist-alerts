# Limitations

This project is an **informational** US-listed watchlist and alerter. It is not a broker, not a scanner, and not financial advice. Agents that load these skills are instructed **never** to place, modify, or cancel an order without explicit confirmation of that specific order.

## Market calendar

The NYSE calendar in `scripts/market_calendar.py` is **rule-based**:

- Full-day holidays (New Year’s, MLK, Presidents’ Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas), including the usual Sat→Fri / Sun→Mon observations.
- New Year’s Day falling on Saturday is **not** observed on the prior Friday (NYSE practice).
- Early closes (13:00 ET) for the Friday after Thanksgiving, Christmas Eve when it is a weekday, and July 3 when it is Mon–Thu.

It does **not** know about unscheduled closures (national days of mourning, weather, technical outages). If quotes look stale on a weekday the calendar thinks is open, treat the session as closed.

**Override:** set `NYSE_EXTRA_CLOSURES=YYYY-MM-DD,YYYY-MM-DD` or `settings.extra_closures` on the watchlist. `alerts.py` will skip those dates unless you pass `--force-session`.

## Earnings dates

`earnings_date` is filled only when the **yfinance** provider succeeds. The Yahoo chart API, Alpaca snapshot, Finnhub quote, and Alpha Vantage daily series do not populate it here. If yfinance is missing or its calendar shape changes, `earnings_within` silently does not fire. Dates can be wrong or delayed; confirm against the issuer’s IR calendar before acting.

## Quote providers

Auto fallback (`WATCHLIST_PROVIDER=auto` / `--provider auto`), first success wins:

| Order | Provider | Needs | History (MA / RSI / 52w) | Earnings |
|------:|----------|-------|---------------------------|----------|
| 1 | `--fixture` | path | yes (whatever the file has) | if present |
| 2 | `yfinance` | `pip install yfinance` | yes | **yes** |
| 3 | Yahoo public chart | nothing (stdlib) | yes | no |
| 4 | Alpaca snapshot | `ALPACA_API_KEY_ID` + `ALPACA_API_SECRET_KEY` | **no** | no |
| 5 | Finnhub | `FINNHUB_API_KEY` | **no** | no |
| 6 | Alpha Vantage daily | `ALPHAVANTAGE_API_KEY` | yes | no |

The Yahoo v8 chart hosts (`query1`, then `query2`) are **unofficial**. They can change, rate-limit, or start requiring cookies. Free Yahoo / yfinance quotes may be delayed ~15 minutes. Alpaca and Finnhub quotes without daily history will not trigger golden/death cross, RSI, volume-average, or 52-week rules.

`--provider` / `WATCHLIST_PROVIDER` pins a single provider and does not fall through.

## What this does not do

- Non-US listings, FX, crypto, futures, or options chains.
- Intraday bars, Level 2, or guaranteed real-time data.
- Portfolio accounting, tax lots, or broker positions (the watchlist is a thesis/stop/target file, not a broker sync).
- News, filings, or fundamentals (use a research skillset for that).
- Automatic order routing.

## Anti-spam caveats

- Level alerts latch until price re-arms by `rearm_pct` (default 0.5%).
- Daily events fire at most once per trading date per ticker/type.
- `max_alerts_per_run` truncates **output** without latching the omitted alerts, so the next run can emit them.
- Deleting `.alert_state.json` mid-session will re-send alerts.
