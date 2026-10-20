# HEARTBEAT - scheduled watchlist check

Run this checklist on every scheduled tick (suggested: every 15-30 min, 09:30-16:00 ET, plus 08:45 ET morning brief and 16:10 ET close brief).
Stay **silent** unless there is something new. Never place or modify orders.

No agent session? `python3 scripts/schedule.py` installs weekday cron every 5 minutes (`--notify`); `alerts.py` still skips holidays and empty checks. Uninstall with `python3 scripts/schedule.py uninstall`. GitHub Actions option: `examples/alerts-cron.yml` on a private fork.

1. **Session gate** - `python3 scripts/market_calendar.py`.
   - Weekend / full-day holiday: do nothing, reply nothing. Exception: if a brief is scheduled for this tick on a holiday, send one line: "Market closed today (<holiday>), next session <date>."
   - `pre` / `after` / overnight on a **trading day**: `alerts.py` evaluates last regular close and sets `last_close`. Mention that in the message. Do not require `--force-session`.
   - Unscheduled closures: bundled `data/holidays_overrides.json`, plus `settings.extra_closures` / `NYSE_EXTRA_CLOSURES`. With Alpaca keys, `alerts.py` overlays the official calendar (cached on disk for the ET day). If the user tells you the market is shut and it is not in those lists, add the date and stay silent.
2. **Watchlist sanity** - `python3 scripts/watchlist.py validate`. If invalid, notify the user once with the errors (don't repeat every tick).
3. **Alerts** - `python3 scripts/alerts.py --format json` (add `--notify` if `WATCHLIST_NOTIFY` is set so ntfy/Slack/webhook fire without you pasting the JSON). Default `%` rules are last vs prior close; session-low/high extremes only fire if the watchlist has opt-in `intraday_low_pct` / `intraday_high_pct` / `intraday_extreme_pct`.
   - `alerts` empty -> stay silent. Do not retry notify.
   - Otherwise send ONE message grouped by ticker (format in `skills/price-alerts/SKILL.md`). Include ET time and data source. If notify already delivered, do not duplicate the same text in chat unless the user is sitting in this conversation.
   - `errors` for the same ticker 3 ticks in a row -> tell the user once (possible delisting/typo/provider outage).
   - `notify` entries with `ok: false` -> tell the user once that that sink failed; do not page every tick.
4. **Brief ticks** - at the morning/close times run the `watchlist-brief` skill instead of (not in addition to) a separate alert message; fold new alerts into the brief.
5. **Stale data check** - `alerts.py` already emits `stale` when `as_of` is older than `stale_after_seconds` in a regular session; tell the user once. Also, if every quote's price is unchanged for 3 ticks during the regular session, warn once that the data feed may be stale/delayed.
6. **Housekeeping** - state is updated automatically by `alerts.py`; never delete `.alert_state.json` mid-day (that would re-send alerts). Daily events are keyed to the **session date of the last close**, so overnight ticks must not be treated as a new day. If `alerts.py` prints a state-file warning, tell the user once that duplicates are possible on this run. The watchlist lives at `$WATCHLIST_FILE` / the project `./watchlist.json` / `~/.config/us-watchlist-alerts/` — not inside the skill folder.

Hard rules: no trades without explicit per-order user confirmation; no buy/sell advice; at most one notification per tick.
