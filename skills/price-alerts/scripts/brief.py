"""Render a markdown watchlist brief (morning or close).

python scripts/brief.py --watchlist watchlist.json --kind morning|close [--fixture f.json]
"""
from __future__ import annotations
import argparse, datetime as dt, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import indicators as ind, market_calendar as mc, quotes as qt, watchlist as wlm


def row(t, q):
    p, pc = q["price"], q.get("prev_close")
    chg = (p - pc) / pc * 100 if pc else 0
    closes = (q.get("closes") or [])[:-1] + [p]
    r = ind.rsi(closes); s50 = ind.sma(closes, 50); s200 = ind.sma(closes, 200)
    trend = "n/a" if not (s50 and s200) else ("up (50>200)" if s50 > s200 else "down (50<200)")
    stop = t.get("stop"); side = t.get("side", "long")
    # Positive % = cushion remaining before the stop / distance still to target 1.
    if stop:
        cushion = (stop - p) / p * 100 if side == "short" else (p - stop) / p * 100
        dist = f"{cushion:+.1f}%"
    else:
        dist = "-"
    tg = (t.get("targets") or [None])[0]
    if tg:
        to_go = (p - tg) / p * 100 if side == "short" else (tg - p) / p * 100
        to_t = f"{to_go:+.1f}%"
    else:
        to_t = "-"
    return f"| {t['symbol']} | ${p:,.2f} | {chg:+.2f}% | {'-' if r is None else f'{r:.0f}'} | {trend} | {dist} | {to_t} |", chg


def render(wl, quotes, kind, now):
    et = now.astimezone(mc.ET)
    extra = mc.parse_dates((wl.get("settings") or {}).get("extra_closures"))
    lines = [f"# Watchlist {kind} brief - {et:%a %b %d, %Y %I:%M %p} ET", ""]
    if not mc.is_trading_day(et.date(), extra=extra):
        why = mc.holiday_name(et.date(), extra=extra) or ("weekend" if et.weekday() >= 5 else "closed")
        nxt = mc.next_trading_day(et.date(), extra=extra)
        lines += [f"_Market closed today ({why}). Next session: {nxt:%a %b %d}._", ""]
    lines += ["| Ticker | Price | Chg | RSI14 | Trend | To stop | To target 1 |", "|---|---|---|---|---|---|---|"]
    movers, errs = [], []
    sources = set()
    for t in wl["tickers"]:
        q = quotes.get(t["symbol"])
        if not q or "error" in q: errs.append(t["symbol"]); continue
        if q.get("source"): sources.add(q["source"])
        line, chg = row(t, q); lines.append(line); movers.append((abs(chg), t["symbol"], chg))
    movers.sort(reverse=True)
    if movers:
        lines += ["", "**Biggest movers:** " + ", ".join(f"{s} {c:+.1f}%" for _, s, c in movers[:3])]
    today = et.date()
    earn = []
    for s, q in quotes.items():
        if not q or q.get("error") or not q.get("earnings_date"):
            continue
        try:
            d = dt.date.fromisoformat(str(q["earnings_date"])[:10])
        except ValueError:
            continue
        if d >= today:
            earn.append((d, f"{s} ({d.isoformat()})"))
    earn.sort()
    if earn:
        lines.append("**Earnings dates:** " + ", ".join(x for _, x in earn))
    if errs: lines.append("**Data unavailable:** " + ", ".join(errs))
    stale = []
    for t in wl["tickers"]:
        q = quotes.get(t["symbol"])
        if not q or "error" in q:
            continue
        age = qt.quote_age_seconds(q, now)
        limit = (wl.get("settings") or {}).get("stale_after_seconds", 900)
        if limit and age is not None and age > limit and mc.session(now, extra=extra) == "regular":
            stale.append(t["symbol"])
    if stale:
        lines.append("**Stale quotes:** " + ", ".join(stale) + " (as_of older than settings.stale_after_seconds)")
    src = ", ".join(sorted(sources)) if sources else "unknown"
    lines += ["", f"_Data: {src}. Informational only - not financial advice._"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--watchlist", default=wlm.DEFAULT_PATH)
    ap.add_argument("--kind", default="morning", choices=["morning", "close"]); ap.add_argument("--fixture")
    ap.add_argument("--provider", default="auto"); ap.add_argument("--now")
    a = ap.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(mc.ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=mc.ET)
    try:
        mc.refresh_official_calendar(now.year)
    except Exception as e:
        print(f"WARN official NYSE overlay skipped: {e}", file=sys.stderr)
    wl = wlm.load(a.watchlist); quotes = {}
    for t in wl["tickers"]:
        try: quotes[t["symbol"]] = qt.get_quote(t["symbol"], a.provider, a.fixture)
        except Exception as e: quotes[t["symbol"]] = {"error": str(e)}
    print(render(wl, quotes, a.kind, now))


if __name__ == "__main__":
    sys.exit(main())
