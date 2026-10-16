# Heartbeat replay — same news, fewer pings

**Same 3 important moves caught. 58 duplicate pings avoided.**

Fewer is better. The skill reported every distinct event on this tape, then went quiet. Without memory, the same two headlines were sent again every 15 minutes.

**REPLAYED data**, not a live feed. 15-minute Yahoo chart bars for Thursday 2026-10-15 (`query1`, `range=5d`, `interval=15m`, `includePrePost=true`), pulled 2026-10-15 ~18:57 ET. `prev_close` is Yahoo `previousClose` (not `chartPreviousClose`). Session high/low are running extremes of those bars. Saturday 2026-10-17 10:00 ET reuses Friday’s last snapshot.

```bash
python3 docs/demo/heartbeat/replay.py
```

CI asserts: 3 distinct events, all covered by the skill; 61 without-skill pings = 3 first + 58 repeats (50 during regular hours, 6 after the bell, 2 Saturday).

![Same 3 moves; 58 extra pings avoided](side-by-side.png)

## Audit of the 61 without-skill pings

| Distinct event (first time) | Pings without | Pings with | Repeats |
|---|---:|---:|---:|
| 09:30 AAPL over $340 | 30 | 1 | 29 |
| 09:30 NVDA session low −3.70% | 30 | 1 | 29 |
| 09:45 NVDA last print −3.26% | 1 | 1 | 0 |
| **Total** | **61** | **3** | **58** |

Of those 58 repeats: **50** while the regular session was still open, **6** after 4:00 PM ET, **2** on Saturday.

**Did the skill miss a real event?** No. At 09:45 the NVDA low moved from $213.12 (−3.70%) to $212.85 (−3.82%). That is the same once-per-day “session low is past −3%” condition, not a new headline. SPY never hit 3% on either path.

Closed-session pings (after the bell + Saturday) were **8**, and all 8 were repeats of news already sent at 09:30.

## Setup

User request, restated every 15 minutes: *keep an eye on these — ping me if AAPL is above 340 or if NVDA/SPY drops 3% today (including a session low that recovers).*

| Ticker | Rules |
|---|---|
| AAPL | `price_above 340` (level — latch after the first fire) |
| NVDA | `pct_change_down: 3` (last vs prior close) **and** opt-in `intraday_low_pct: 3` |
| SPY | same two % rules (never trigger on this tape) |

**With:** `alerts.run` + one `.alert_state.json` + default `sessions=["regular"]`.

**Without:** the same `evaluate_rule`, no state, no session gate — a fresh look at the current quote every 15 minutes.

## Tape (replayed)

NVDA prior close **$221.30** (Wednesday 2026-10-14, Yahoo `previousClose` at ~18:57 ET). 09:30 last −2.59%, session low already **−3.70%**. 09:45 last **−3.26%**, low **−3.82%**. Last recovered to about **−1.8%** by the close. AAPL stayed **$341–$347** all day (never dropped back through $340, so the level stays latched).

## Files

| File | What |
|---|---|
| [replay_2026-10-15.json](replay_2026-10-15.json) | Labeled snapshots |
| [watchlist.json](watchlist.json) | Rules used |
| [replay.py](replay.py) | Both paths + audit |
| [replay_out.txt](replay_out.txt) | Captured stdout (includes AUDIT block) |
| [replay_report.json](replay_report.json) | Rows + `audit` object |
| [render.py](render.py) | Regenerates `side-by-side.png` (needs Pillow; docs only) |
