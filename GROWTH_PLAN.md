# Growth plan

How this repo gets in front of people who would actually use it, without pretending it is a 70-skill trading terminal.

## Positioning

One sentence: **stdlib US watchlist + anti-spam price alerts + NYSE hours, for any agent that reads `SKILL.md`.**

Complementary to, not a clone of:

- [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) — research / screening / journaling
- [himself65/finance-skills](https://github.com/himself65/finance-skills) — valuation and market analysis
- [gauss314/skills](https://github.com/gauss314/skills) — data adapters and **order execution**
- [chjm-ai/stock-monitor-skill](https://github.com/chjm-ai/stock-monitor-skill) — China A-shares (this repo is the US analog)

Lead with "no keys, no MCP, will not auto-trade."

## Skill directories and marketplaces

Submit or list, in this order:

1. **Claude Code plugin marketplace** — already has `.claude-plugin/marketplace.json`. Document `/plugin marketplace add eli-alvarado/us-watchlist-alerts` then `/plugin install us-watchlist-alerts`.
2. **skills.sh / `npx skills add`** — register `eli-alvarado/us-watchlist-alerts` so one command installs into Claude Code, Cursor, Codex, Gemini CLI, Copilot.
3. **Cursor skill listings** — `.cursor/skills/` path is in the README; submit if Cursor publishes a directory.
4. **Claude.ai skill zip** — GitHub release assets of `skills/watchlist-manager`, `skills/price-alerts`, `skills/watchlist-brief` (plus a note that scripts must sit next to the clone).
5. **OpenClaw / agent skill catalogs** — same `SKILL.md` layout; HEARTBEAT.md is the scheduler hook.
6. **Gemini CLI extensions / Codex plugin lists** as they stabilize; until then keep `~/.gemini/skills` and `~/.codex/skills` instructions accurate.

Do not split the three skills across marketplaces. Alerts without the watchlist schema are incomplete.

## Awesome-lists to submit to

Open a small, polite PR (one bullet, honest scope) on:

| List | Why |
|---|---|
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | Cross-agent, curated; finance/productivity section |
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | Large Claude-oriented catalog |
| [travisvn/awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills) | Claude Code workflows |
| [philipbankier/awesome-agent-skills](https://github.com/philipbankier/awesome-agent-skills) | Cross-platform (SKILL.md + Cursor + OpenClaw) |
| [sindresorhus/awesome](https://github.com/sindresorhus/awesome) | Only after a child list exists; do not spam the parent |

Skip bulk-generated "thousands of skills" scrapers unless they accept a single well-described repo. When filing, link CI, the comparison table, and LIMITATIONS.md so reviewers can see it is not vapor.

## Launch posts

Keep each post to: what it does, what it refuses to do, fixture demo GIF, install one-liner.

- **Show HN** — title like *Show HN: Agent skills for a US stock watchlist with de-duplicated price alerts*. Comment: stdlib, Yahoo unofficial, no auto-trade.
- **Reddit** — r/ClaudeAI, r/codex, r/cursor, r/LocalLLaMA (agent-skills angle), r/algotrading (expect "why not a real broker API" — answer: this is the heartbeat layer, pair with Alpaca if you execute). Avoid sounding like a signal service.
- **X** — short demo GIF thread; tag agent-skills / Claude Code / Gemini CLI, not ticker hype.
- **HN "Ask"** only if there is a real question (how should agents handle broker confirmation?). Prefer Show HN.

Time the post after a **GitHub release** (`v0.3.0`) so the README badge and tag exist.

## Credibility work

- [x] CI on Python 3.10–3.13 (`python3 -m unittest discover -s tests`)
- [x] CONTRIBUTING.md, issue templates, limitations doc
- [x] CHANGELOG.md (0.1.0 … 0.3.2)
- [x] GitHub release v0.2.0
- [ ] File 3–5 **good first issues** (see CONTRIBUTING.md) so the repo looks open, not a dump
- [ ] Pin a discussion or README FAQ: delayed data, unofficial Yahoo, no China listings
- [ ] Optional: `pre-commit` only if it stays one ruff/format hook — do not bury contributors in tooling

## Roadmap

### v0.2 — make the current loop trustworthy

- [x] `data/holidays_overrides.json` for known unscheduled closures (incomplete; not a live NYSE feed)
- [x] Official Alpaca calendar overlay when API keys are set
- [x] Earnings without yfinance: Yahoo `calendarEvents`, then Finnhub, then Alpha Vantage
- [x] Official quote path: Alpaca snapshot + daily bars first when keyed; Finnhub candles
- [x] HTTP retries, `QuoteError` with status/hint, `--stale-after`
- [x] Quote dict field table in LIMITATIONS.md
- [x] Tagged GitHub release `v0.2.0`

### v0.3 — still no auto-trade

- [x] Notify sinks (webhook, Slack, ntfy, Linux desktop, JSONL file) so HEARTBEAT can be cron + ntfy **without** the agent placing orders
- [x] ATM IV alerts from unofficial Yahoo options chain (skip if missing/zero; no IV rank / UOA)
- [x] Intraday range alerts only from provider `day_high`/`day_low`; refuse to fake them from daily closes
- [x] Multi-watchlist files documented (`WATCHLIST_FILE` + per-profile `ALERT_STATE_FILE`)
- [x] Cache Alpaca calendar on disk for the ET day so HEARTBEAT ticks do not hit `/v2/calendar` every 15 minutes
- [x] Demo GIF showing notify
- [x] v0.3.2: `npx skills add` ships `scripts/` (no extra clone); after-hours last-close without `--force-session`; Yahoo crumb + Nasdaq earnings / IV degrade
- International listings stay out of scope unless someone owns the calendar and a legal data source.

### v0.4 — still no auto-trade

- Email / Telegram sinks (need credentials + bounce/rate hygiene; ntfy covers many phones today)
- IV rank / percentile only if a free source actually returns a history, not a synthetic from prices
- Live NYSE status feed (calendar cache is not a substitute for "market halted")
- Marketplace / awesome-list submissions from the list above

Out of scope on purpose: CANSLIM, DCF, options payoff, live order entry. Point at the comparison table instead of growing into a junk drawer.
