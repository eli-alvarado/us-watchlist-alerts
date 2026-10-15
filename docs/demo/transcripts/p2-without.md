# Morning brief — Thursday, October 15, 2026

US cash session is already closed (regular close **16:00 EDT**). Figures below are live Yahoo Finance / Nasdaq prints: Thursday’s regular-session close, plus after-hours as of **~18:50 EDT**. I did not invent prices. Daily RSI-14 is computed from Yahoo daily closes (Wilder smoothing), so it can differ slightly from a broker’s RSI.

**Tape:** all three names finished red. Apple is hugging its 52-week high. Tesla reports next week. Nvidia closed under its 50-day average after a ~2.7% gap down.

## Snapshot (regular close, Thursday)

| | Side | Close | Chg vs Wed | After-hours (~18:50 EDT) | Day range | Volume vs 10-day avg |
|---|---|---|---|---|---|---|
| **AAPL** | long | $342.00 | −$0.96 (−0.28%) | $341.48 (−0.15% from close) | $341.60–$347.85 | 39.6M vs 35.7M (1.11×) |
| **TSLA** | watch | $362.44 | −$4.72 (−1.29%) | $362.68 (+0.07%) | $355.23–$363.75 | 26.5M vs 31.9M (0.83×) |
| **NVDA** | long | $217.23 | −$4.07 (−1.84%) | $217.42 (+0.09%) | $212.85–$218.47 | 126.4M vs 102.0M (1.24×) |

Wednesday closes: AAPL $342.96, TSLA $367.16, NVDA $221.30.

---

### AAPL — long (added 2026-10-01)
**Thesis:** Services margin expansion + iPhone upgrade cycle.

High-level grind: opened $346.95 (gap **+1.16%** vs Wednesday), tagged $347.85, faded to a $342.00 close. The 52-week high is **$348.15** (printed Oct 13). Thursday’s close is **1.77% under that high**, inside your 2% `near_52w_high` band. After-hours $341.48.

**Vs your plan:** entry $225 → close is **+52.0%**. Both targets ($250 / $270) are already behind the market. Stop $210 is far away.

- 50-day avg $324.46 — well above
- 200-day avg $291.77 — well above (50-day still above 200-day)
- 52-week $243.42–$348.15
- RSI-14 (daily) **60.6** — not stretched
- Trailing P/E 39.0; Yahoo avg analyst rating 2.2 Buy
- **Earnings: Monday, November 2, 2026, 16:00 EDT** (18 calendar days)

**Alerts**
- `price_above 240` — **live** (price has been through it)
- `near_52w_high 2%` — **live** (1.77% below $348.15)
- `earnings_within 14` — not yet (18 days to Nov 2)
- `rsi_above 75` — no (60.6)

**Friday watch:** whether it can reclaim the $348.15 high versus a failed breakout back through the $341–$342 shelf.

---

### TSLA — watch (no position)
**Thesis:** Waiting for capitulation volume before considering entry.

This was not capitulation. Close $362.44, −1.29%, on **below-average** volume. Opened $360.58 (gap **−1.79%**), session low $355.23. No 5% down day, no 3% gap-down, RSI 46.5 — none of the washout triggers fired. 50-day $357.94 is just underneath; 200-day $388.98 is still overhead (50-day remains below 200-day). 52-week range $297.38–$498.83; still ~27% off the high.

**Alerts**
- `pct_change_down 5` — no (−1.29%)
- `gap_down 3` — no (−1.79% open)
- `volume_spike 2.5` — no (0.83× 10-day average)
- `rsi_below 30` — no (46.5)
- `earnings_within 3` — not yet

**Calendar:** Tesla earnings **Wednesday, October 21, 2026, 16:00 EDT** (6 calendar days). That is the event that could produce the volume/RSI washout you are waiting on. Until then this stays a watch, not a setup.

---

### NVDA — long (added 2026-10-01)
**Thesis:** AI datacenter capex.

Softest of the three. Opened $215.34 (**gap −2.69%** vs $221.30), low $212.85, close $217.23 (−1.84%) on 126.4M shares (~1.24× the 10-day average, not a 2× spike). After-hours $217.42.

**Vs your plan:** entry $160 → close **+35.8%**. Target $190 is already behind the market. Stop $140 is 35.5% below the close.

- 50-day avg $223.21 — **close is 2.7% below**
- 200-day avg $202.69 — still above
- 52-week $164.27–$243.37 (10.7% off the high)
- RSI-14 (daily) **40.2** — cooling, not oversold
- Trailing P/E 28.4; Yahoo avg analyst rating 1.3 Strong Buy
- **Earnings: Tuesday, November 17, 2026, 16:00 EDT** (~33 days)

**Alerts**
- `golden_cross 50/200` — 50-day remains above 200-day; **not a new cross today** (already in that regime)
- `cross_below_ma 50` — **live** ($217.23 vs $223.21 50-day)
- `price_below 150` — no

**Friday watch:** first test is getting back **above the 50-day (~$223)**. Failure to hold Thursday’s $212.85 low would be the next downside tell. The $150 price alert is not in play.

---

## Into Friday’s regular open (09:30 EDT)

1. **AAPL** — 52-week squeeze is the live alert. A hold above ~$341 keeps the breakout intact; a slip toward the 50-day ($324) would be the first real fade.
2. **NVDA** — already under the 50-day after a 2.7% gap down. That is the only new technical break on the book.
3. **TSLA** — no entry trigger. Clock is running toward **Oct 21 earnings**; your 3-day earnings alert will arm around Oct 18.

Source: Yahoo Finance quote + 1-year daily chart (`query1.finance.yahoo.com`), Nasdaq Real Time Price, pulled **22:50 UTC / 18:50 EDT** on 2026-10-15. After-hours prints can still move. There is no Friday pre-market tape yet because that session has not opened.
