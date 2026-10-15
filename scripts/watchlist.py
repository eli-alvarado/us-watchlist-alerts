"""Watchlist CRUD. Stores JSON (default) or YAML (if PyYAML installed and path ends .yaml/.yml).

python scripts/watchlist.py [--file watchlist.json] add NVDA --thesis "AI capex" --entry 120 \
    --target 150 --target 180 --stop 105 --tag ai --tag semis --alert "price_below:110"
python scripts/watchlist.py list [--tag ai]
python scripts/watchlist.py show NVDA
python scripts/watchlist.py update NVDA --stop 110
python scripts/watchlist.py remove NVDA
python scripts/watchlist.py validate
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, sys

SCHEMA_VERSION = 1
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
ALERT_TYPES = {"price_above", "price_below", "pct_change_up", "pct_change_down", "pct_move", "gap_up",
               "gap_down", "new_52w_high", "new_52w_low", "near_52w_high", "near_52w_low", "golden_cross",
               "death_cross", "cross_above_ma", "cross_below_ma", "rsi_above", "rsi_below", "volume_spike",
               "earnings_within", "stop_hit", "target_hit",
               "iv_above", "iv_below", "intraday_range_pct"}
SESSIONS = {"regular", "pre", "after"}
SIDES = {"long", "short", "watch"}
DEFAULT_PATH = os.environ.get("WATCHLIST_FILE", "watchlist.json")


def _is_yaml(p): return p.endswith((".yaml", ".yml"))


def load(path=DEFAULT_PATH):
    if not os.path.exists(path):
        return {"version": SCHEMA_VERSION, "settings": {}, "tickers": []}
    with open(path) as f:
        if _is_yaml(path):
            import yaml
            data = yaml.safe_load(f) or {}
        else:
            data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("watchlist root must be an object")
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("settings", {})
    data.setdefault("tickers", [])
    return data


def save(wl, path=DEFAULT_PATH):
    errs = validate(wl)
    if errs:
        raise ValueError("; ".join(errs))
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        if _is_yaml(path):
            import yaml
            yaml.safe_dump(wl, f, sort_keys=False)
        else:
            json.dump(wl, f, indent=2); f.write("\n")
    os.replace(tmp, path)


def parse_alert(s):
    """'price_below:110' -> {'type':'price_below','value':110.0}; 'golden_cross' -> {'type':...}"""
    t, _, v = s.partition(":")
    a = {"type": t.strip()}
    if v:
        a["value"] = float(v)
    return a


def validate(wl):
    errs = []
    if not isinstance(wl.get("tickers"), list):
        return ["'tickers' must be a list"]
    settings = wl.get("settings") or {}
    if settings.get("sessions") is not None:
        sess = settings["sessions"]
        if not isinstance(sess, list) or not sess or any(x not in SESSIONS for x in sess):
            errs.append("settings.sessions must be a non-empty list of regular/pre/after")
    if settings.get("extra_closures") is not None:
        try:
            for d in settings["extra_closures"]:
                dt.date.fromisoformat(str(d)[:10])
        except (TypeError, ValueError):
            errs.append("settings.extra_closures must be ISO dates (YYYY-MM-DD)")
    seen = set()
    for i, t in enumerate(wl["tickers"]):
        s = t.get("symbol", "")
        if not SYMBOL_RE.match(s): errs.append(f"tickers[{i}]: bad symbol {s!r}")
        if s in seen: errs.append(f"duplicate symbol {s}")
        seen.add(s)
        side = t.get("side", "long")
        if side not in SIDES:
            errs.append(f"{s}: side must be long, short, or watch")
        for k in ("entry", "stop"):
            if t.get(k) is not None and not isinstance(t[k], (int, float)): errs.append(f"{s}: {k} must be a number")
        for x in t.get("targets", []) or []:
            if not isinstance(x, (int, float)): errs.append(f"{s}: targets must be numbers")
        if t.get("stop") is not None and t.get("entry") is not None:
            if side == "long" and t["stop"] >= t["entry"]:
                errs.append(f"{s}: stop {t['stop']} should be below entry {t['entry']} for a long")
            if side == "short" and t["stop"] <= t["entry"]:
                errs.append(f"{s}: stop {t['stop']} should be above entry {t['entry']} for a short")
        for a in t.get("alerts", []) or []:
            if a.get("type") not in ALERT_TYPES: errs.append(f"{s}: unknown alert type {a.get('type')!r}")
    return errs


def find(wl, sym):
    sym = sym.upper()
    return next((t for t in wl["tickers"] if t["symbol"] == sym), None)


def add(wl, sym, **kw):
    sym = sym.upper()
    if find(wl, sym):
        raise ValueError(f"{sym} already on watchlist; use update")
    t = {"symbol": sym, "added": dt.date.today().isoformat(), "side": kw.get("side") or "long",
         "thesis": kw.get("thesis") or "", "entry": kw.get("entry"), "targets": kw.get("targets") or [],
         "stop": kw.get("stop"), "tags": kw.get("tags") or [], "alerts": kw.get("alerts") or [],
         "notes": kw.get("notes") or ""}
    wl["tickers"].append(t)
    return t


def update(wl, sym, **kw):
    t = find(wl, sym)
    if not t: raise KeyError(sym.upper())
    for k, v in kw.items():
        if v is None or v == []: continue
        if k in ("tags", "alerts", "targets") and kw.get("append"):
            t[k] = (t.get(k) or []) + v
        elif k != "append":
            t[k] = v
    t["updated"] = dt.date.today().isoformat()
    return t


def remove(wl, sym):
    t = find(wl, sym)
    if not t: raise KeyError(sym.upper())
    wl["tickers"].remove(t)
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=DEFAULT_PATH)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "update"):
        p = sp.add_parser(name); p.add_argument("symbol")
        p.add_argument("--thesis"); p.add_argument("--entry", type=float); p.add_argument("--stop", type=float)
        p.add_argument("--target", type=float, action="append", dest="targets")
        p.add_argument("--tag", action="append", dest="tags"); p.add_argument("--alert", action="append", dest="alerts")
        p.add_argument("--side", choices=["long", "short", "watch"]); p.add_argument("--notes")
        if name == "update": p.add_argument("--append", action="store_true", help="append tags/alerts/targets")
    p = sp.add_parser("remove"); p.add_argument("symbol")
    p = sp.add_parser("show"); p.add_argument("symbol")
    p = sp.add_parser("list"); p.add_argument("--tag")
    sp.add_parser("validate")
    a = ap.parse_args(argv)
    wl = load(a.file)
    if a.cmd in ("add", "update"):
        kw = {k: getattr(a, k) for k in ("thesis", "entry", "stop", "targets", "tags", "side", "notes")}
        kw["alerts"] = [parse_alert(x) for x in (a.alerts or [])]
        if a.cmd == "update": kw["append"] = a.append
        try:
            t = (add if a.cmd == "add" else update)(wl, a.symbol, **kw)
        except (ValueError, KeyError) as e:
            print(e, file=sys.stderr); return 1
        save(wl, a.file); print(json.dumps(t, indent=2))
    elif a.cmd == "remove":
        try:
            t = remove(wl, a.symbol)
        except KeyError as e:
            print(f"{e.args[0]} not on watchlist", file=sys.stderr); return 1
        save(wl, a.file); print(f"removed {t['symbol']}")
    elif a.cmd == "show":
        t = find(wl, a.symbol)
        if not t:
            print(f"{a.symbol.upper()} not on watchlist", file=sys.stderr); return 1
        print(json.dumps(t, indent=2))
    elif a.cmd == "list":
        for t in wl["tickers"]:
            if a.tag and a.tag not in t.get("tags", []): continue
            print(f"{t['symbol']:<7} entry={t.get('entry')} stop={t.get('stop')} targets={t.get('targets')} tags={','.join(t.get('tags', []))}  {t.get('thesis','')}")
    elif a.cmd == "validate":
        errs = validate(wl)
        print("OK" if not errs else "\n".join(errs)); return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
