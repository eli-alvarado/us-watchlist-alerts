# HEARTBEAT - scheduled watchlist check

Run this checklist on every scheduled tick (suggested: every 15-30 min, 09:30-16:00 ET, plus 08:45 ET morning brief and 16:10 ET close brief).
Stay **silent** unless there is something new. Never place or modify orders.

1. **Session gate** - `python scripts/market_calendar.py`.
   - `closed` (weekend/holiday/overnight/unscheduled): do nothing, reply nothing. Exception: if a brief is scheduled for this tick on a holiday, send one line: "Market closed today (<holiday>), next session <date>."
   - Unscheduled closures: bundled `data/holidays_overrides.json`, plus `settings.extra_closures` / `NYSE_EXTRA_CLOSURES`. With Alpaca keys, `alerts.py` overlays the official calendar automatically. If the user tells you the market is shut and it is not in those lists, add the date and stay silent.
   - `pre`/`after`: only continue if `settings.sessions` includes it.
2. **Watchlist sanity** - `python scripts/watchlist.py validate`. If invalid, notify the user once with the errors (don't repeat every tick).
3. **Alerts** - `python scripts/alerts.py --format json`.
   - `alerts` empty -> stay silent.
   - Otherwise send ONE message grouped by ticker (format in `skills/price-alerts/SKILL.md`). Include ET time and data source.
   - `errors` for the same ticker 3 ticks in a row -> tell the user once (possible delisting/typo/provider outage).
4. **Brief ticks** - at the morning/close times run the `watchlist-brief` skill instead of (not in addition to) a separate alert message; fold new alerts into the brief.
5. **Stale data check** - `alerts.py` already emits `stale` when `as_of` is older than `stale_after_seconds` in a regular session; tell the user once. Also, if every quote's price is unchanged for 3 ticks during the regular session, warn once that the data feed may be stale/delayed.
6. **Housekeeping** - state is updated automatically by `alerts.py`; never delete `.alert_state.json` mid-day (that would re-send alerts). If `alerts.py` prints a state-file warning, tell the user once that duplicates are possible on this run.

Hard rules: no trades without explicit per-order user confirmation; no buy/sell advice; at most one notification per tick.
