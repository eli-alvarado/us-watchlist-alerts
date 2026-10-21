"""Watchlist movers (last vs prior close) and gappers (open vs prior close).

Used by ``movers.py``, ``gappers.py``, and the stdio MCP server. Stdlib only.
"""
from __future__ import annotations
import datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_calendar as mc, quotes as qt, watchlist as wlm


def pct(a, b):
    """Percent change of ``a`` vs ``b``, or None if ``b`` is missing/zero."""
    if a is None or b in (None, 0):
        return None
    return (a - b) / b * 100


def load_quotes(wl, provider="auto", fixture=None):
    """Return ``(quotes_by_symbol, n_failed)`` for every ticker on the list."""
    quotes, n_failed = {}, 0
    for t in wl.get("tickers") or []:
        sym = t["symbol"]
        try:
            quotes[sym] = qt.get_quote(sym, provider, fixture)
        except Exception as e:
            quotes[sym] = {"error": str(e)}
            n_failed += 1
    return quotes, n_failed


def rank_movers(wl, quotes, limit=None):
    """Biggest absolute % moves vs prior close, largest first."""
    rows = []
    for t in wl.get("tickers") or []:
        q = quotes.get(t["symbol"])
        if not q or q.get("error") or q.get("price") is None:
            continue
        chg = pct(q["price"], q.get("prev_close"))
        if chg is None:
            continue
        rows.append({
            "symbol": t["symbol"], "price": q["price"],
            "prev_close": q.get("prev_close"), "change_pct": chg,
            "source": q.get("source"),
        })
    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return rows


def rank_gappers(wl, quotes, threshold=2.0):
    """Open vs prior close; keep names whose absolute gap is at least ``threshold`` %."""
    rows = []
    for t in wl.get("tickers") or []:
        q = quotes.get(t["symbol"])
        if not q or q.get("error") or q.get("open") is None:
            continue
        gap = pct(q["open"], q.get("prev_close"))
        if gap is None or abs(gap) < float(threshold):
            continue
        rows.append({
            "symbol": t["symbol"], "open": q["open"],
            "prev_close": q.get("prev_close"), "gap_pct": gap,
            "direction": "up" if gap > 0 else "down",
            "source": q.get("source"),
        })
    rows.sort(key=lambda r: abs(r["gap_pct"]), reverse=True)
    return rows


def market_status(when=None):
    """NYSE session, holiday name, next session. Local calendar only (no network)."""
    now = when if isinstance(when, dt.datetime) else (
        mc.parse_iso(when) if when else dt.datetime.now(mc.ET)
    )
    now = now.astimezone(mc.ET)
    day = now.date()
    extra = mc.extra_closures()
    return {
        "as_of": now.isoformat(timespec="minutes"),
        "session": mc.session(now, extra=extra),
        "trading_day": mc.is_trading_day(day, extra=extra),
        "holiday": mc.holiday_name(day, extra=extra),
        "next_session": mc.next_trading_day(day, extra=extra).isoformat(),
        "early_close": day in mc.early_closes(day.year),
    }


def _sources(rows):
    return ", ".join(sorted({r.get("source") for r in rows if r.get("source")})) or "unknown"


def format_movers(rows, now, fmt="text"):
    et = now.astimezone(mc.ET)
    if fmt == "json":
        return json.dumps({
            "as_of": et.isoformat(timespec="minutes"),
            "session": mc.session(et),
            "movers": rows,
            "source": _sources(rows),
        }, indent=2)
    lines = [f"Biggest movers vs prior close — {et:%a %b %d, %Y %H:%M} ET ({mc.session(et)})"]
    if not rows:
        lines.append("(none)")
    for r in rows:
        lines.append(f"{r['symbol']:<6} ${r['price']:,.2f}  {r['change_pct']:+.2f}%")
    lines.append(f"_Data: {_sources(rows)}. Informational only - not financial advice._")
    return "\n".join(lines)


def format_gappers(rows, now, threshold, fmt="text"):
    et = now.astimezone(mc.ET)
    if fmt == "json":
        return json.dumps({
            "as_of": et.isoformat(timespec="minutes"),
            "threshold": float(threshold),
            "gappers": rows,
            "source": _sources(rows),
        }, indent=2)
    lines = [f"Gappers vs prior close (threshold {float(threshold):.1f}%) — {et:%a %b %d, %Y %H:%M} ET"]
    if not rows:
        lines.append(f"No gappers at or above {float(threshold):.1f}%")
    for r in rows:
        lines.append(
            f"{r['symbol']:<6} open ${r['open']:,.2f}  prev ${r['prev_close']:,.2f}  "
            f"gap {r['gap_pct']:+.2f}%  {r['direction']}"
        )
    lines.append(f"_Data: {_sources(rows)}. Informational only - not financial advice._")
    return "\n".join(lines)


def _shared_args(ap):
    ap.add_argument("--watchlist", default=None,
                    help="watchlist path (default: $WATCHLIST_FILE or shared user/project location)")
    ap.add_argument("--fixture", help="quote fixture (default: $WATCHLIST_FIXTURE)")
    ap.add_argument("--provider", default=os.environ.get("WATCHLIST_PROVIDER", "auto"))
    ap.add_argument("--now", help="ISO datetime override (testing)")
    ap.add_argument("--format", choices=["text", "json"], default="text")


def prepare_run(args):
    """Resolve watchlist / clock / quotes. Returns ``(rc, payload_or_none)``.

    ``payload`` is ``(wl, quotes, now, n_failed)`` on success.
    """
    args.fixture = qt.resolve_fixture(args.fixture)
    if not args.watchlist:
        args.watchlist = wlm.default_watchlist_path()
    try:
        now = mc.parse_iso(args.now) if args.now else dt.datetime.now(mc.ET)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1, None
    if not os.path.exists(args.watchlist):
        print(wlm.missing_watchlist_hint(args.watchlist), file=sys.stderr)
        return 2, None
    try:
        wl = wlm.load(args.watchlist)
    except (ValueError, OSError, json.JSONDecodeError, ImportError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1, None
    if not wl.get("tickers"):
        print("Watchlist is empty. Add one: python3 scripts/watchlist.py add NVDA")
        return 0, None
    quotes, n_failed = load_quotes(wl, args.provider, args.fixture)
    n_tickers = len(wl["tickers"])
    if n_tickers and n_failed == n_tickers:
        print(f"ERROR no quotes ({n_failed}/{n_tickers} failed)", file=sys.stderr)
        return 3, None
    return 0, (wl, quotes, now, n_failed)
