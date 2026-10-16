# Live snapshot log

A scheduled GitHub Action runs `examples/live-watchlist.json` on **weekdays** that are NYSE trading days (stdlib Yahoo, **no secrets**).

- Every run writes the [job summary](https://github.com/eli-alvarado/us-watchlist-alerts/actions/workflows/live.yml).
- Dated `YYYY-MM-DD.md` files are published to the **[`live-snapshots`](https://github.com/eli-alvarado/us-watchlist-alerts/tree/live-snapshots/docs/live)** branch — **never to `main`**.
- If today’s file already exists on that branch, later weekday cron ticks only refresh the job summary.
- Alerts in these files use a **fresh state**: they show conditions that were true on that check, not a latched HEARTBEAT.
- Quote failures stay in the job summary and are **not** committed.

Replayed / fixture runs for tests use `--fixture` and `--now` on `scripts/live_snapshot.py`.

First successful live run (landed on `main` before this rule): [2026-10-15.md](2026-10-15.md) (manual weekday dispatch; Yahoo chart; `prev_close` corrected in 0.4.1). New days: [`live-snapshots` / docs/live](https://github.com/eli-alvarado/us-watchlist-alerts/tree/live-snapshots/docs/live).

Informational only. Not financial advice. Never places trades.
