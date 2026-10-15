**No 3% drop alert on the last print.** AAPL, NVDA, and SPY are all inside 3% of Wednesday’s close. I added a `pct_change_down` 3% alert on all three (and added SPY to the watchlist).

Live quotes from Yahoo Finance, Thursday 2026-10-15. Regular session closed at **4:00 PM EDT**. After-hours last prints around **6:50 PM EDT**. Percent change is vs Wednesday 2026-10-14 close.

| Symbol | Wed close | Regular close (4:00 PM EDT) | Today % (regular) | After-hours last | Today % (incl. AH) | Session low | Low vs Wed close | 3% trigger |
|--------|-----------|-----------------------------|-------------------|------------------|--------------------|-------------|------------------|------------|
| **AAPL** | $342.96 | $342.00 | **−0.28%** | $341.48 (6:50:35 PM EDT) | −0.43% | $341.60 | −0.40% | $332.67 |
| **NVDA** | $221.30 | $217.23 | **−1.84%** | $217.42 (6:50:19 PM EDT) | −1.75% | $212.85 | **−3.82%** | $214.66 |
| **SPY** | $769.60 | $771.79 | **+0.28%** | $771.54 (6:50:49 PM EDT) | +0.25% | $764.44 | −0.67% | $746.51 |

**Alert status (last price vs prior close):**
- **AAPL** — no alert (−0.28% regular / −0.43% after hours)
- **NVDA** — no alert on the last print (−1.84% regular / −1.75% after hours)
- **SPY** — no alert (+0.28% regular / +0.25% after hours)

**Intraday note:** NVDA’s regular-session low of **$212.85** was **−3.82%** vs Wednesday’s close, so it *did* trade through a 3% drop during the day and then recovered into the close. AAPL and SPY never got within 3% on the downside.

Watchlist updates: AAPL and NVDA already listed; I attached `{"type": "pct_change_down", "value": 3}` to both and added SPY as a watch with the same alert.
