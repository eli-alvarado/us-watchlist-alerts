# Contributing

Thanks for helping make this usable enough to recommend. The bar is: **offline tests stay green**, **no API keys required for the default path**, and **the agent must never place a trade**.

## Setup

```bash
git clone https://github.com/eli-alvarado/us-watchlist-alerts
cd us-watchlist-alerts
python3 -m unittest discover -s tests
```

Scripts use the Python 3.10+ standard library. Optional extras in `requirements.txt` (`yfinance`, `PyYAML`) are not needed for CI.

## How to change things

| Change | Where | Tests |
|---|---|---|
| New alert type | `scripts/alerts.py` `evaluate_rule`, `watchlist.ALERT_TYPES`, `skills/price-alerts/SKILL.md` | Add a fixture-driven case in `tests/test_all.py` |
| Notify sink | `scripts/notify.py` `VALID_SINKS` + README env table | Mock `quotes._post`; never hit a real webhook in CI |
| Calendar / extra closures | `scripts/market_calendar.py` | Holiday, early-close, or `NYSE_EXTRA_CLOSURES` assertion |
| Quote field / fallback | `scripts/quotes.py` | Mock `_get` or use `tests/fixtures/quotes.json` |
| Schema | `scripts/watchlist.py` `validate`, `examples/` | Validation tests |
| Agent instructions | `skills/*/SKILL.md`, `HEARTBEAT.md` | Read them as the agent would; keep "no trades" language |

`npx skills add` copies each `skills/<name>/` folder. After editing a root script or `data/holidays_overrides.json`, run `python3 scripts/bundle_skills.py` so the copies stay identical (CI asserts this). That bundle also ships `examples/quotes-fixture.json` and `scripts/quickstart.py`.

Do not commit API keys, webhook URLs, or `.alert_state.json`. See [SECURITY.md](SECURITY.md).

Run from the repo root so `scripts/` imports resolve the same way the skills document.

## Pull requests

1. Branch off `main`.
2. Keep PRs focused. A calendar fix and a README rewrite can be separate.
3. `python3 -m unittest discover -s tests` must pass. CI runs that command on Python 3.10–3.13.
4. Do not add network calls to the default unittest suite.
5. Do not add a broker "just send the order" path.

## Good first issues

These are sized for a first PR. File one with the [good first issue template](.github/ISSUE_TEMPLATE/good_first_issue.yml) if it is not already open:

- Add a newly announced NYSE unscheduled closure to `data/holidays_overrides.json` with a name and a calendar test (do not pretend the rule-based table invents mourning days).
- Add a `--format json` snapshot assertion for `brief.py` morning output against the existing fixtures.
- Teach `from_yfinance` another calendar shape you have actually seen in the wild, with a mock in `tests/test_all.py`.
- Expand `examples/watchlist.yaml` with a short + `extra_closures` example that still validates.
- Windows notes: `zoneinfo` needs the `tzdata` package on some installs — document the exact pip extra without making it required on Linux CI.

## Releases

Maintainers tag `v0.x.y` on `main` after CI is green and update [CHANGELOG.md](CHANGELOG.md). See [GROWTH_PLAN.md](GROWTH_PLAN.md).
