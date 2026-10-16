# Live snapshot log

A scheduled GitHub Action runs `examples/live-watchlist.json` on **weekdays** that are NYSE trading days (stdlib Yahoo, **no secrets**) and writes **at most one** `YYYY-MM-DD.md` here.

- Weekends and full-day holidays are skipped.
- If today’s file already exists, later weekday cron ticks only refresh the [job summary](https://github.com/eli-alvarado/us-watchlist-alerts/actions/workflows/live.yml) — no extra commits.
- Alerts in these files use a **fresh state**: they show conditions that were true on that check, not a latched HEARTBEAT.
- Quote failures stay in the job summary and are **not** committed.

Replayed / fixture runs for tests use `--fixture` and `--now` on `scripts/live_snapshot.py`.

First successful live run: [2026-10-15.md](2026-10-15.md) (manual weekday dispatch; Yahoo chart). `prev_close` in that file is labeled and corrected (0.4.1): Thursday last vs Wednesday 2026-10-14, matching the README ~18:45 ET snapshot.

Informational only. Not financial advice. Never places trades.
