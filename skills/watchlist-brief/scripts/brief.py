"""Render a markdown or JSON watchlist brief (morning or close).

python scripts/brief.py --watchlist watchlist.json --kind morning|close [--fixture f.json] [--format markdown|json]
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import indicators as ind, market_calendar as mc, quotes as qt, watchlist as wlm


def row_data(t, q):
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
        to_target = to_go
    else:
        to_target = None
    return {
        "symbol": t["symbol"], "price": p, "change_pct": chg,
        "rsi14": r, "trend": trend,
        "to_stop_pct": cushion if stop else None,
        "to_target_1_pct": to_target,
    }


def row(t, q):
    data = row_data(t, q)
    rsi = "-" if data["rsi14"] is None else f'{data["rsi14"]:.0f}'
    stop = "-" if data["to_stop_pct"] is None else f'{data["to_stop_pct"]:+.1f}%'
    target = "-" if data["to_target_1_pct"] is None else f'{data["to_target_1_pct"]:+.1f}%'
    return (f"| {data['symbol']} | ${data['price']:,.2f} | {data['change_pct']:+.2f}% | "
            f"{rsi} | {data['trend']} | {stop} | {target} |"), data["change_pct"]


def render_json(wl, quotes, kind, now):
    """Return the machine-readable counterpart to the markdown brief."""
    today = now.astimezone(mc.ET).date()
    tickers = []
    sources = set()
    movers = []
    for ticker in wl["tickers"]:
        quote = quotes.get(ticker["symbol"])
        if not quote or "error" in quote:
            continue
        if quote.get("source"):
            sources.add(quote["source"])
        data = row_data(ticker, quote)
        tickers.append(data)
        movers.append((abs(data["change_pct"]), data["symbol"], data["change_pct"]))
    movers.sort(reverse=True)

    earnings = []
    for symbol, quote in quotes.items():
        if not quote or quote.get("error") or not quote.get("earnings_date"):
            continue
        try:
            day = dt.date.fromisoformat(str(quote["earnings_date"])[:10])
        except ValueError:
            continue
        if day >= today:
            earnings.append((day, symbol))
    earnings.sort()

    return {
        "tickers": tickers,
        "movers": [{"symbol": symbol, "change_pct": change} for _, symbol, change in movers[:3]],
        "earnings": [{"symbol": symbol, "date": day.isoformat()} for day, symbol in earnings],
        "source": ", ".join(sorted(sources)) if sources else "unknown",
    }


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
    ap = argparse.ArgumentParser(); ap.add_argument("--watchlist", default=None,
                    help="watchlist path (default: $WATCHLIST_FILE or shared user/project location)")
    ap.add_argument("--kind", default=None, choices=["morning", "close", "intraday"],
                    help="brief kind (default: morning before the open, close after the bell, else intraday)")
    ap.add_argument("--fixture")
    ap.add_argument("--provider", default=os.environ.get("WATCHLIST_PROVIDER", "auto")); ap.add_argument("--now")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    a = ap.parse_args(argv)
    if not a.watchlist:
        a.watchlist = wlm.default_watchlist_path()
    try:
        now = mc.parse_iso(a.now) if a.now else dt.datetime.now(mc.ET)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if a.kind is None:
        sess = mc.session(now)
        a.kind = "morning" if sess == "pre" else "close" if sess in ("after", "closed") else "intraday"
    if not os.path.exists(a.watchlist):
        print(wlm.missing_watchlist_hint(a.watchlist), file=sys.stderr)
        return 2
    try:
        mc.refresh_official_calendar(now.year)
    except Exception as e:
        print(f"WARN official NYSE overlay skipped: {e}", file=sys.stderr)
    try:
        wl = wlm.load(a.watchlist)
    except (ValueError, OSError, json.JSONDecodeError, ImportError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not wl.get("tickers"):
        print("Watchlist is empty. Add one: python3 scripts/watchlist.py add NVDA")
        return 0
    quotes = {}
    for t in wl["tickers"]:
        try: quotes[t["symbol"]] = qt.get_quote(t["symbol"], a.provider, a.fixture)
        except Exception as e: quotes[t["symbol"]] = {"error": str(e)}
    if a.format == "json":
        print(json.dumps(render_json(wl, quotes, a.kind, now), indent=2, sort_keys=True))
    else:
        print(render(wl, quotes, a.kind, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
