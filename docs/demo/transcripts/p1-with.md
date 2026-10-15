Watching AAPL, NVDA, and SPY. I will alert if any of them drops **3% or more vs prior close** today (`pct_change_down: 3`). Informational only — not financial advice. I will not place, modify, or cancel any trade.

**Rules (plain English):** ping when last (or last regular close after the bell) is down ≥ 3% from the previous session close. Daily-event, at most once per ticker per trading day.

**Entries**
- AAPL | long | entry 225 | stop 210 | T1 250 / T2 270 | added `pct_change_down:3` (kept existing alerts)
- NVDA | long | entry 160 | stop 140 | T1 190 | added `pct_change_down:3` (kept existing alerts)
- SPY | watch | no entry/stop/targets | thesis left blank | `pct_change_down:3` only (newly added)

**Check (18:51 ET, after-hours, last regular close — no `--force-session` needed)**  
None of AAPL / NVDA / SPY is down 3% today, so those new rules did not fire.

Last regular prints (yahoo-chart; unofficial, can lag ~15m):
- AAPL $342.00 vs prev close $342.96 → **-0.28%**
- NVDA $217.23 vs prev close $221.30 → **-1.84%**
- SPY $771.79 vs prev close $769.60 → **+0.28%**

🔔 5 new alerts from **other existing** rules (18:51 ET, after session / last close, data: yahoo-chart):
- AAPL $342.00 is above $240.00 (thesis: services margin + iPhone cycle; stop $210, T1 $250)
- AAPL within 1.8% of 52w high $348.15
- AAPL $342.00 reached target $250.00
- AAPL $342.00 reached target $270.00
- NVDA $217.23 reached target $190.00 (thesis: AI datacenter capex; stop $140, T1 $190)

TSLA stayed on the list unchanged; nothing new fired for it.
