"""Minimal stdio MCP server (JSON-RPC 2.0, stdlib only).

Exposes watchlist, quotes, alerts, brief, NYSE status, movers, and gappers.
No API key. Never places trades. Skill remains the primary interface.

Framing: MCP stdio is newline-delimited JSON (one JSON-RPC message per line,
no headers). Replies are compact JSON plus a trailing newline. Reads still
accept Content-Length framing from older clients. Protocol goes to stdout;
logs and stray prints go to stderr.
"""
from __future__ import annotations
import datetime as dt, io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts, brief, market_calendar as mc, quotes as qt, screener, watchlist as wlm

PROTOCOL = "2024-11-05"
SUPPORTED = {"2024-11-05", "2025-03-26", "2025-06-18"}
SERVER_NAME = "us-watchlist-alerts"
SERVER_VERSION = "0.6.0"

TOOLS = [
    {
        "name": "get_quotes",
        "description": "Fetch US equity/ETF quotes (Yahoo chart by default; no API key). "
                       "Pass fixture for offline/sample data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbols": {"type": "array", "items": {"type": "string"},
                            "description": "Tickers. Default: every symbol on the watchlist."},
                "watchlist": {"type": "string"},
                "fixture": {"type": "string"},
                "provider": {"type": "string", "description": "auto|yahoo|alpaca|…"},
            },
        },
    },
    {
        "name": "watchlist_list",
        "description": "List tickers on the watchlist (shared JSON/YAML file).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "tag": {"type": "string"},
            },
        },
    },
    {
        "name": "watchlist_add",
        "description": "Add a ticker. Does not place a trade. Unknown symbols are rejected "
                       "unless no_verify is true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "thesis": {"type": "string"},
                "entry": {"type": "number"},
                "stop": {"type": "number"},
                "targets": {"type": "array", "items": {"type": "number"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "alerts": {"type": "array", "items": {"type": "string"},
                           "description": "e.g. price_below:110 or pct_change_down:5"},
                "side": {"type": "string", "enum": ["long", "short", "watch"]},
                "file": {"type": "string"},
                "no_verify": {"type": "boolean"},
                "fixture": {"type": "string"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "watchlist_remove",
        "description": "Remove a ticker from the watchlist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "file": {"type": "string"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_alerts",
        "description": "Evaluate watchlist alert rules. Reports only NEW alerts "
                       "(latch / once-per-day / cooldown). Never places trades.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "watchlist": {"type": "string"},
                "state": {"type": "string"},
                "fixture": {"type": "string"},
                "now": {"type": "string", "description": "ISO datetime override"},
                "dry_run": {"type": "boolean"},
                "force_session": {"type": "boolean"},
            },
        },
    },
    {
        "name": "morning_brief",
        "description": "Morning / close / intraday watchlist brief (table, movers, earnings).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["morning", "close", "intraday"]},
                "watchlist": {"type": "string"},
                "fixture": {"type": "string"},
                "now": {"type": "string"},
                "format": {"type": "string", "enum": ["markdown", "json"]},
            },
        },
    },
    {
        "name": "market_status",
        "description": "NYSE session (pre/regular/after/closed), holiday name, next session, "
                       "early-close flag. Local calendar; no API key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "when": {"type": "string", "description": "ISO date or datetime (default: now ET)"},
            },
        },
    },
    {
        "name": "movers",
        "description": "Biggest movers on the watchlist today (last vs prior close).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "watchlist": {"type": "string"},
                "fixture": {"type": "string"},
                "now": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "gappers",
        "description": "Watchlist names that gapped vs prior close. threshold is percent "
                       "(default 2, same as gap_up/gap_down alerts).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "watchlist": {"type": "string"},
                "fixture": {"type": "string"},
                "now": {"type": "string"},
                "threshold": {"type": "number"},
            },
        },
    },
]


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": err}


def _tool_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


def _dump(obj):
    return json.dumps(obj, indent=2, default=str)


def _watchlist_path(args):
    return args.get("file") or args.get("watchlist") or wlm.default_watchlist_path()


def _parse_now(raw):
    if not raw:
        return dt.datetime.now(mc.ET)
    return mc.parse_iso(raw)


def _collect_quotes(wl, provider, fixture):
    return screener.load_quotes(wl, provider or "auto", qt.resolve_fixture(fixture))


def tool_get_quotes(args):
    fixture = qt.resolve_fixture(args.get("fixture"))
    provider = args.get("provider") or os.environ.get("WATCHLIST_PROVIDER", "auto")
    symbols = [str(s).upper() for s in (args.get("symbols") or [])]
    if not symbols:
        path = _watchlist_path(args)
        if not os.path.exists(path):
            return _tool_result(wlm.missing_watchlist_hint(path), True)
        wl = wlm.load(path)
        symbols = [t["symbol"] for t in wl.get("tickers") or []]
        if not symbols:
            return _tool_result("Watchlist is empty. Add one: watchlist_add symbol=NVDA")
    out = {}
    for s in symbols:
        try:
            out[s] = qt.get_quote(s, provider, fixture)
            out[s].pop("closes", None)
        except Exception as e:
            out[s] = {"error": str(e)}
    return _tool_result(_dump(out), any("error" in v for v in out.values()))


def tool_watchlist_list(args):
    path = _watchlist_path(args)
    if not os.path.exists(path):
        return _tool_result(wlm.missing_watchlist_hint(path), True)
    wl = wlm.load(path)
    tag = args.get("tag")
    tickers = [t for t in wl.get("tickers") or [] if not tag or tag in (t.get("tags") or [])]
    return _tool_result(_dump({"file": os.path.abspath(path), "tickers": tickers}))


def tool_watchlist_add(args):
    symbol = (args.get("symbol") or "").upper()
    if not symbol:
        return _tool_result("symbol is required", True)
    path = _watchlist_path(args)
    if not os.path.exists(path):
        wlm.init_file(path)
    wl = wlm.load(path)
    skip = bool(args.get("no_verify"))
    if not skip:
        status, msg = wlm.verify_symbol(symbol, fixture=qt.resolve_fixture(args.get("fixture")))
        if status == "unknown":
            return _tool_result(msg, True)
    alerts_in = args.get("alerts") or []
    parsed = [wlm.parse_alert(x) for x in alerts_in]
    t = wlm.add(
        wl, symbol,
        thesis=args.get("thesis"), entry=args.get("entry"), stop=args.get("stop"),
        targets=args.get("targets") or [], tags=args.get("tags") or [],
        alerts=parsed, side=args.get("side"),
    )
    wlm.save(wl, path)
    return _tool_result(_dump(t))


def tool_watchlist_remove(args):
    symbol = (args.get("symbol") or "").upper()
    path = _watchlist_path(args)
    if not os.path.exists(path):
        return _tool_result(wlm.missing_watchlist_hint(path), True)
    wl = wlm.load(path)
    try:
        t = wlm.remove(wl, symbol)
    except KeyError:
        return _tool_result(f"{symbol} not on watchlist", True)
    wlm.save(wl, path)
    return _tool_result(f"removed {t['symbol']}")


def tool_run_alerts(args):
    path = _watchlist_path(args)
    if not os.path.exists(path):
        return _tool_result(wlm.missing_watchlist_hint(path), True)
    argv = ["--watchlist", path, "--format", "json"]
    if args.get("fixture"):
        argv += ["--fixture", args["fixture"]]
    if args.get("now"):
        argv += ["--now", args["now"]]
    if args.get("state"):
        argv += ["--state", args["state"]]
    if args.get("dry_run"):
        argv.append("--dry-run")
    if args.get("force_session"):
        argv.append("--force-session")
    buf = io.StringIO()
    err = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = buf, err
        rc = alerts.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    text = buf.getvalue().strip() or err.getvalue().strip() or "no new alerts"
    return _tool_result(text, rc not in (0,))


def tool_morning_brief(args):
    path = _watchlist_path(args)
    if not os.path.exists(path):
        return _tool_result(wlm.missing_watchlist_hint(path), True)
    argv = ["--watchlist", path, "--format", args.get("format") or "markdown"]
    if args.get("kind"):
        argv += ["--kind", args["kind"]]
    if args.get("fixture"):
        argv += ["--fixture", args["fixture"]]
    if args.get("now"):
        argv += ["--now", args["now"]]
    buf = io.StringIO()
    err = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = buf, err
        rc = brief.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    text = buf.getvalue().strip() or err.getvalue().strip()
    return _tool_result(text, rc not in (0,))


def tool_market_status(args):
    try:
        return _tool_result(_dump(screener.market_status(args.get("when"))))
    except ValueError as e:
        return _tool_result(str(e), True)


def _screen(args, kind):
    path = _watchlist_path(args)
    if not os.path.exists(path):
        return _tool_result(wlm.missing_watchlist_hint(path), True)
    try:
        now = _parse_now(args.get("now"))
    except ValueError as e:
        return _tool_result(str(e), True)
    try:
        wl = wlm.load(path)
    except (ValueError, OSError, json.JSONDecodeError, ImportError) as e:
        return _tool_result(str(e), True)
    if not wl.get("tickers"):
        return _tool_result("Watchlist is empty. Add one: watchlist_add symbol=NVDA")
    quotes, n_failed = _collect_quotes(wl, args.get("provider"), args.get("fixture"))
    if wl["tickers"] and n_failed == len(wl["tickers"]):
        return _tool_result(f"ERROR no quotes ({n_failed}/{len(wl['tickers'])} failed)", True)
    if kind == "movers":
        rows = screener.rank_movers(wl, quotes, limit=args.get("limit"))
        return _tool_result(screener.format_movers(rows, now, fmt="json"))
    if kind == "gappers":
        threshold = args.get("threshold")
        if threshold is None:
            threshold = 2.0
        rows = screener.rank_gappers(wl, quotes, threshold=threshold)
        return _tool_result(screener.format_gappers(rows, now, threshold, fmt="json"))
    raise ValueError(kind)


def call_tool(name, arguments):
    args = arguments or {}
    if name == "get_quotes":
        return tool_get_quotes(args)
    if name == "watchlist_list":
        return tool_watchlist_list(args)
    if name == "watchlist_add":
        return tool_watchlist_add(args)
    if name == "watchlist_remove":
        return tool_watchlist_remove(args)
    if name == "run_alerts":
        return tool_run_alerts(args)
    if name == "morning_brief":
        return tool_morning_brief(args)
    if name == "market_status":
        return tool_market_status(args)
    if name == "movers":
        return _screen(args, "movers")
    if name == "gappers":
        return _screen(args, "gappers")
    return _tool_result(f"unknown tool: {name}", True)


def handle(msg):
    """Dispatch one JSON-RPC object. Notifications return None."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") not in (None, "2.0"):
        return _err(None, -32600, "invalid request")
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if method is None:
        return _err(mid, -32600, "invalid request")
    if method == "initialize":
        client_ver = params.get("protocolVersion") or PROTOCOL
        ver = client_ver if client_ver in SUPPORTED else PROTOCOL
        return _ok(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "US watchlist, NYSE-aware alerts, briefs, movers, and gappers. "
                "No API key. Never places trades. Informational only."
            ),
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if mid is None and str(method).startswith("notifications/"):
        return None
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if not name:
            return _err(mid, -32602, "tools/call requires name")
        try:
            return _ok(mid, call_tool(name, params.get("arguments") or {}))
        except Exception as e:
            return _ok(mid, _tool_result(f"{type(e).__name__}: {e}", True))
    if method == "shutdown":
        return _ok(mid, {})
    return _err(mid, -32601, f"method not found: {method}")


def write_message(msg, out):
    """Write one JSON-RPC message as a single compact JSON line."""
    line = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode()
    out.write(line + b"\n")
    out.flush()


def read_message(inp):
    """Read one MCP message (Content-Length framing or a JSON line)."""
    first = inp.readline()
    if not first:
        return None
    if first.lower().startswith(b"content-length:"):
        try:
            length = int(first.split(b":", 1)[1])
        except ValueError:
            return {"jsonrpc": "2.0", "error": {"code": -32700, "message": "bad Content-Length"}}
        while True:
            line = inp.readline()
            if line in (b"", b"\n", b"\r\n"):
                break
        body = inp.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
    raw = first.strip()
    if not raw:
        return read_message(inp)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}


def serve(inp=None, out=None):
    inp = inp or sys.stdin.buffer
    out = out or sys.stdout.buffer
    # Keep stdout for protocol only. Tool code that print()s would otherwise
    # interleave with JSON-RPC replies and break MCP clients.
    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        while True:
            msg = read_message(inp)
            if msg is None:
                break
            if msg.get("error") and "method" not in msg and "result" not in msg:
                write_message(msg if "jsonrpc" in msg else _err(None, -32700, "parse error"), out)
                continue
            resp = handle(msg)
            if resp is not None:
                write_message(resp, out)
            if msg.get("method") == "shutdown":
                break
    finally:
        sys.stdout = saved_stdout


def main(argv=None):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
