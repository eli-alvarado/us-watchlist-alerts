# Security

This project is a **local watchlist and alerter**. It never places, modifies, or cancels a trade. Treat it like any other script that can reach the network and write files in the project directory or `~/.config/us-watchlist-alerts/`.

## What we store

| File / env | What it is | Commit it? |
|---|---|---|
| `watchlist.json` | Your tickers, thesis, stops, alert rules. Default: project `./watchlist.json` or `~/.config/us-watchlist-alerts/watchlist.json` (`$WATCHLIST_FILE` overrides). Shared by all three skills; not inside the skill folder. | Optional (it is your research, not a secret) |
| `.alert_state.json` | Latch / cooldown state (next to the watchlist; `$ALERT_STATE_FILE` overrides) | **No** (already gitignored; can leak what fired) |
| `.nyse_calendar_cache.json` | Cached Alpaca calendar | **No** (gitignored) |
| `.env` | Keys and webhook URLs (cron sources this from the data dir) | **No** (gitignored) |

## API keys and tokens

None are required for the default Yahoo chart path.

If you set them, they belong in the **environment** (or a local `.env` you do not commit), never in `watchlist.json`, never in a skill `SKILL.md`, and never in a GitHub issue:

| Variable | Used for |
|---|---|
| `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` | Official quotes + `/v2/calendar` overlay |
| `FINNHUB_API_KEY` | Optional quotes / earnings |
| `ALPHAVANTAGE_API_KEY` | Optional daily history / earnings |
| `WATCHLIST_WEBHOOK_URL` / `SLACK_WEBHOOK_URL` | Alert delivery |
| `NTFY_TOPIC` / `NTFY_TOKEN` | Alert delivery |

The scheduled [live snapshot](docs/live/) workflow uses **no secrets** and does **not** push to `main`. Dated files go to the `live-snapshots` branch. Do not add keys to that job.

Paper or live Alpaca keys still do **not** enable order entry in this repo. There is no `submit_order` path. If you connect a broker skill from another project, these skills tell the agent to refuse unconfirmed orders.

## Notify sinks

`WATCHLIST_NOTIFY=webhook,slack,ntfy,desktop,file` only delivers **new** alerts. A webhook URL is a credential. Prefer a dedicated ntfy topic or Slack incoming webhook, not a shared channel with write-up rights. Sink failures print `WARN notify …` and do not abort the check.

`python3 scripts/schedule.py` writes notify env into a local `.env` (gitignored) so weekday cron can source it. Do not commit that file. The public `live.yml` workflow must stay secret-free; personal GitHub Actions alerts belong in a private fork using `examples/alerts-cron.yml`.

## What the scripts send outbound

On `provider=auto` with no keys: HTTPS to unofficial Yahoo chart / quote / options hosts, and sometimes Nasdaq earnings-date. With keys: Alpaca, Finnhub, or Alpha Vantage as documented in [docs/LIMITATIONS.md](docs/LIMITATIONS.md). User-Agent is `us-watchlist-alerts/<version>`.

## Reporting a vulnerability

Open a private security advisory on this GitHub repo, or email the address on the owning profile. Please do not file a public issue that includes keys, webhook URLs, or a working exploit against Yahoo/Nasdaq.

## Agent install note

`npx skills add` copies `scripts/` next to each `SKILL.md`. Those scripts run with the same permissions as your agent. Review them before the first run, as the installer says.
