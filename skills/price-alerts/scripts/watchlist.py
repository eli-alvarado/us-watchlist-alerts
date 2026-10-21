"""Watchlist CRUD. Stores JSON (default) or YAML (if PyYAML installed and path ends .yaml/.yml).

python scripts/watchlist.py init
python scripts/watchlist.py init --example
python scripts/watchlist.py init --list-presets
python scripts/watchlist.py init --preset mega-cap-tech
python scripts/watchlist.py add NVDA --thesis "AI capex" --entry 120 \
    --target 150 --target 180 --stop 105 --tag ai --tag semis --alert "price_below:110"
python scripts/watchlist.py add NVDA --no-verify
python scripts/watchlist.py --file swing.json add NVDA --alert price_below:110
python scripts/watchlist.py add NVDA --file swing.json --alert price_below:110
python scripts/watchlist.py list [--tag ai]
python scripts/watchlist.py show NVDA
python scripts/watchlist.py update NVDA --stop 110
python scripts/watchlist.py remove NVDA
python scripts/watchlist.py validate

``add`` checks the symbol on the Yahoo chart (same default quote path) unless
``--no-verify`` or ``WATCHLIST_NO_VERIFY`` is set. Unknown tickers are rejected.
A network/provider outage prints a WARN and still adds the symbol. ``--fixture``
/ ``WATCHLIST_FIXTURE`` verifies against sample quotes instead of the network.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, shutil, sys

SCHEMA_VERSION = 1
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
ALERT_TYPES = {"price_above", "price_below", "pct_change_up", "pct_change_down", "pct_move", "gap_up",
               "gap_down", "new_52w_high", "new_52w_low", "near_52w_high", "near_52w_low", "golden_cross",
               "death_cross", "cross_above_ma", "cross_below_ma", "rsi_above", "rsi_below", "volume_spike",
               "earnings_within", "stop_hit", "target_hit",
               "iv_above", "iv_below", "intraday_range_pct",
               "intraday_low_pct", "intraday_high_pct", "intraday_extreme_pct"}
SESSIONS = {"regular", "pre", "after"}
SIDES = {"long", "short", "watch"}
WATCHLIST_BASENAME = "watchlist.json"
STATE_BASENAME = ".alert_state.json"
APP_DIRNAME = "us-watchlist-alerts"

# Built-in books for ``init --preset``. Symbol lists only (no fixture-era prices).
PRESETS = {
    "mega-cap-tech": {
        "description": "Mega-cap US tech (Magnificent 7)",
        "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
        "tags": ["mega-cap-tech"],
    },
    "index-etfs": {
        "description": "Major US index ETFs",
        "symbols": ["SPY", "QQQ", "DIA", "IWM"],
        "tags": ["index-etfs"],
    },
    "sector-etfs": {
        "description": "SPDR sector ETFs",
        "symbols": ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"],
        "tags": ["sector-etfs"],
    },
    "dividend-staples": {
        "description": "Dividend staples",
        "symbols": ["JNJ", "PG", "KO", "PEP", "WMT", "MCD", "XOM"],
        "tags": ["dividend-staples"],
    },
}


def _is_yaml(p): return p.endswith((".yaml", ".yml"))


def is_skill_install_dir(path):
    """True if ``path`` looks like an ``npx skills add`` skill folder (wiped on reinstall)."""
    path = os.path.abspath(path)
    return (
        os.path.isfile(os.path.join(path, "SKILL.md"))
        and os.path.isfile(os.path.join(path, "scripts", "watchlist.py"))
        and os.path.isfile(os.path.join(path, "scripts", "alerts.py"))
    )


def enclosing_skill_dir(start=None):
    """Walk up from ``start`` (default: cwd) and return the skill folder, if any."""
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if is_skill_install_dir(cur):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def installed_skill_project_root(skill_dir):
    """Project root for ``<root>/.claude/skills/<name>`` or ``<root>/.agents/skills/<name>``.

    ``None`` for the repo's ``skills/`` tree, or a global ``~/.claude/skills`` install
    whose parent would be the home directory (those keep using the user-config path).
    """
    skill_dir = os.path.abspath(skill_dir)
    skills_dir = os.path.dirname(skill_dir)
    if os.path.basename(skills_dir) != "skills":
        return None
    agent_dir = os.path.dirname(skills_dir)
    if os.path.basename(agent_dir) not in (".claude", ".agents"):
        return None
    root = os.path.dirname(agent_dir)
    home = os.path.abspath(os.path.expanduser("~"))
    if os.path.abspath(root) == home:
        return None
    return root


def project_anchor_dir(start=None):
    """Directory whose ``watchlist.json`` should be used, or ``None`` for user-config.

    Running from inside ``.claude/skills/<name>`` or ``.agents/skills/<name>``
    (including ``scripts/``) walks up to the project root so the skill folder and
    ``cd <project>`` share one file. A bare skill copy that is not in that layout
    has no project anchor.
    """
    cwd = os.path.abspath(start or os.getcwd())
    skill = enclosing_skill_dir(cwd)
    if skill:
        return installed_skill_project_root(skill)
    return cwd


def user_data_dir():
    """Stable dir shared by all three skills; survives skill reinstall.

    ``$XDG_CONFIG_HOME/us-watchlist-alerts`` if set, else
    ``~/.config/us-watchlist-alerts`` (Windows: ``%APPDATA%\\us-watchlist-alerts``).
    Override the files directly with ``WATCHLIST_FILE`` / ``ALERT_STATE_FILE``.
    """
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return os.path.join(os.path.abspath(os.path.expanduser(xdg)), APP_DIRNAME)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIRNAME)
    return os.path.join(os.path.expanduser("~"), ".config", APP_DIRNAME)


def _legacy_skill_files(basename):
    """In-skill leftover files from the pre-user-config layout."""
    found, seen = [], set()
    here = os.path.dirname(os.path.abspath(__file__))
    skill_or_repo = os.path.dirname(here)
    candidates = []
    if is_skill_install_dir(skill_or_repo):
        parent = os.path.dirname(skill_or_repo)
        candidates.append(os.path.join(skill_or_repo, basename))
        for name in ("price-alerts", "watchlist-manager", "watchlist-brief"):
            candidates.append(os.path.join(parent, name, basename))
    cwd = os.getcwd()
    if is_skill_install_dir(cwd):
        parent = os.path.dirname(cwd)
        candidates.append(os.path.join(cwd, basename))
        for name in ("price-alerts", "watchlist-manager", "watchlist-brief"):
            candidates.append(os.path.join(parent, name, basename))
    for p in candidates:
        ap = os.path.abspath(p)
        if ap in seen or not os.path.isfile(ap):
            continue
        seen.add(ap)
        found.append(ap)
    return found


def _migrate_file(src, dest):
    parent = os.path.dirname(os.path.abspath(dest))
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not os.path.exists(dest):
        shutil.copy2(src, dest)
    return dest


def default_watchlist_path():
    """Resolve the watchlist path shared by manager / alerts / brief.

    Order:
    1. ``$WATCHLIST_FILE`` if set
    2. ``<project>/watchlist.json`` when that file exists. ``project`` is cwd, or
       the directory that contains ``.claude/skills/<name>`` / ``.agents/skills/<name>``
       if cwd is inside an installed skill (so ``cd`` into the skill cannot split
       the list from the project root)
    3. ``$XDG_CONFIG_HOME/us-watchlist-alerts/watchlist.json`` (or ``~/.config/...``),
       after copying a leftover in-skill ``watchlist.json`` if the dest is new
    4. For a *new* list: ``<project>/watchlist.json`` when a project is identified,
       else the user-config path (never write into a skill folder that
       ``npx skills add`` will replace)
    """
    env = (os.environ.get("WATCHLIST_FILE") or "").strip()
    if env:
        return env
    anchor = project_anchor_dir()
    user_file = os.path.join(user_data_dir(), WATCHLIST_BASENAME)
    anchor_file = os.path.join(anchor, WATCHLIST_BASENAME) if anchor else None
    if anchor_file and os.path.isfile(anchor_file):
        return anchor_file
    if os.path.isfile(user_file):
        return user_file
    legacy = _legacy_skill_files(WATCHLIST_BASENAME)
    if legacy:
        dest = anchor_file or user_file
        _migrate_file(legacy[0], dest)
        src_state = os.path.join(os.path.dirname(legacy[0]), STATE_BASENAME)
        dest_state = os.path.join(os.path.dirname(os.path.abspath(dest)), STATE_BASENAME)
        if os.path.isfile(src_state) and not os.path.isfile(dest_state):
            _migrate_file(src_state, dest_state)
        return dest
    if anchor_file:
        return anchor_file
    return user_file


def note_using(path):
    """Tell the user which watchlist file a mutating / listing command used."""
    print(f"using {os.path.abspath(path)}", file=sys.stderr)


def default_state_path(watchlist_path=None):
    env = (os.environ.get("ALERT_STATE_FILE") or "").strip()
    if env:
        return env
    wl = os.path.abspath(watchlist_path or default_watchlist_path())
    parent = os.path.dirname(wl)
    return os.path.join(parent or os.getcwd(), STATE_BASENAME)


def __getattr__(name):
    if name == "DEFAULT_PATH":
        return default_watchlist_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def bundled_example():
    """``examples/watchlist.json`` next to a git clone or a skill copy."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(os.path.dirname(here), "examples", "watchlist.json"),
        os.path.join(here, "examples", "watchlist.json"),
    ):
        if os.path.exists(cand):
            return cand
    return None


def bundled_fixture():
    """Offline quote fixture shipped with the skill / clone."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(os.path.dirname(here), "examples", "quotes-fixture.json"),
        os.path.join(here, "examples", "quotes-fixture.json"),
        os.path.join(os.path.dirname(here), "tests", "fixtures", "quotes.json"),
    ):
        if os.path.exists(cand):
            return cand
    return None


def missing_watchlist_hint(path):
    ex = bundled_example()
    lines = [
        f"No watchlist at {path}.",
        "Create one:  python3 scripts/watchlist.py init",
        "Sample data: python3 scripts/watchlist.py init --example",
        "Presets:     python3 scripts/watchlist.py init --list-presets",
        "Defaults: $WATCHLIST_FILE, else ./watchlist.json in the project (also used when cwd is",
        "inside .claude/skills/<name> or .agents/skills/<name>),",
        f"else {os.path.join(user_data_dir(), WATCHLIST_BASENAME)} (shared, survives skill reinstall).",
    ]
    if ex:
        lines.append(f"Or pass:     --watchlist {ex}")
    return "\n".join(lines)


def preset_symbols():
    """Uppercase symbols from every built-in preset (used by fixture sample mode)."""
    out = set()
    for spec in PRESETS.values():
        out.update(s.upper() for s in spec["symbols"])
    return out


def list_presets_text():
    lines = []
    for name, spec in PRESETS.items():
        lines.append(f"{name:20} {spec['description']}")
        lines.append(f"{'':20} {', '.join(spec['symbols'])}")
    return "\n".join(lines)


def _env_truthy(name):
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def classify_verify_error(exc):
    """``unknown`` (reject) vs ``network`` (warn, add anyway)."""
    status = getattr(exc, "status", None)
    text = str(exc).lower()
    if "not in fixture" in text:
        return "unknown"
    if status == 404:
        return "unknown"
    try:
        import quotes as qt
        if qt._looks_unknown_symbol([exc]):
            return "unknown"
    except Exception:
        pass
    return "network"


def verify_symbol(symbol, fixture=None):
    """Check ``symbol`` on the Yahoo chart, or against a quote fixture.

    Returns ``("ok", None)``, ``("unknown", message)``, or ``("network", message)``.

    Network / provider outages are *not* fatal: the CLI warns and adds anyway so a
    blip does not block ``watchlist add``. Unknown symbols are rejected. Pass
    ``--no-verify`` (or ``WATCHLIST_NO_VERIFY=1``) to skip this check when offline.
    ``--fixture`` / ``WATCHLIST_FIXTURE`` uses sample quotes instead of the network.
    """
    symbol = (symbol or "").upper()
    fixture = (fixture or os.environ.get("WATCHLIST_FIXTURE") or "").strip() or None
    import quotes as qt
    try:
        qt.get_quote(symbol, provider="yahoo", fixture=fixture, fetch_earnings=False)
        return "ok", None
    except Exception as e:
        if classify_verify_error(e) == "unknown":
            if fixture:
                return "unknown", (
                    f"{symbol} is not in the quote fixture ({fixture}). "
                    "Use a listed sample ticker, or pass --no-verify."
                )
            return "unknown", (
                f"{symbol} is not a known US ticker on Yahoo Finance. "
                "Check the symbol, or pass --no-verify to add it anyway."
            )
        err = str(e).strip() or e.__class__.__name__
        return "network", (
            f"could not verify {symbol} ({err}). Adding anyway. "
            "Pass --no-verify to skip this check when offline."
        )


def init_file(path=None, *, example=False, empty=False, preset=None):
    """Write an empty valid watchlist, copy the sample, or seed a built-in preset.

    ``empty`` is accepted for compatibility; empty is already the default.
    Presets are symbol lists with a tag (no fixture-era price levels).
    """
    chosen = [n for n, v in (("example", example), ("empty", empty), ("preset", preset)) if v]
    if len(chosen) > 1:
        raise ValueError("pass only one of --example, --empty, or --preset")
    if path is None:
        path = default_watchlist_path()
    if os.path.exists(path):
        raise FileExistsError(f"{path} already exists")
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    if example:
        src = bundled_example()
        if not src:
            raise FileNotFoundError("bundled example watchlist not found")
        shutil.copy2(src, path)
        return path, "copied-example"
    if preset:
        spec = PRESETS.get(preset)
        if not spec:
            names = ", ".join(PRESETS)
            raise ValueError(f"unknown preset {preset!r}. Use --list-presets ({names})")
        wl = {"version": SCHEMA_VERSION, "settings": {}, "tickers": []}
        for sym in spec["symbols"]:
            add(wl, sym, tags=list(spec["tags"]), side="watch")
        save(wl, path)
        return path, f"preset:{preset}"
    save({"version": SCHEMA_VERSION, "settings": {}, "tickers": []}, path)
    return path, "empty"


def load(path=None):
    if path is None:
        path = default_watchlist_path()
    if not os.path.exists(path):
        return {"version": SCHEMA_VERSION, "settings": {}, "tickers": []}
    try:
        with open(path) as f:
            if _is_yaml(path):
                try:
                    import yaml
                except ImportError as e:
                    raise ImportError("pip install pyyaml or use .json") from e
                data = yaml.safe_load(f) or {}
            else:
                data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON (line {e.lineno} col {e.colno})") from e
    if not isinstance(data, dict):
        raise ValueError("watchlist root must be an object")
    if "tickers" not in data:
        alt = next((k for k in ("watchlist", "symbols", "stocks", "items") if k in data), None)
        if alt:
            raise ValueError(
                f"{path} has top-level {alt!r} but needs 'tickers' "
                f"(rename that key to 'tickers')"
            )
        keys = ", ".join(sorted(data)) or "(none)"
        raise ValueError(f"{path} is missing top-level 'tickers' (keys: {keys})")
    if not isinstance(data["tickers"], list):
        raise ValueError(f"{path}: 'tickers' must be a list")
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("settings", {})
    return data


def save(wl, path=None):
    if path is None:
        path = default_watchlist_path()
    errs = validate(wl)
    if errs:
        raise ValueError("; ".join(errs))
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            if _is_yaml(path):
                try:
                    import yaml
                except ImportError as e:
                    raise ImportError("pip install pyyaml or use .json") from e
                yaml.safe_dump(wl, f, sort_keys=False)
            else:
                json.dump(wl, f, indent=2); f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def parse_alert(s):
    """'price_below:110' -> {'type':'price_below','value':110.0}; 'golden_cross' -> {'type':...}"""
    t, _, v = s.partition(":")
    t = t.strip()
    if t not in ALERT_TYPES:
        raise ValueError(f"unknown alert type {t!r}")
    a = {"type": t}
    if v:
        try:
            a["value"] = float(v)
        except ValueError:
            raise ValueError(f"alert {t} value must be a number, not {v!r}") from None
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


def _today_et():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return dt.date.today()


def add(wl, sym, **kw):
    sym = sym.upper()
    if not SYMBOL_RE.match(sym):
        raise ValueError(f"bad symbol {sym!r}")
    if find(wl, sym):
        raise ValueError(f"{sym} already on watchlist; use update")
    t = {"symbol": sym, "added": _today_et().isoformat(), "side": kw.get("side") or "long",
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
    t["updated"] = _today_et().isoformat()
    return t


def remove(wl, sym):
    t = find(wl, sym)
    if not t: raise KeyError(sym.upper())
    wl["tickers"].remove(t)
    return t


def _extract_file(argv):
    """Allow ``--file`` before or after the subcommand (``add AAPL --file x.json``)."""
    argv = list(argv if argv is not None else sys.argv[1:])
    path = None
    out = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--file", "-f") and i + 1 < len(argv):
            path = argv[i + 1]
            i += 2
            continue
        if a.startswith("--file="):
            path = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    return out, path


def main(argv=None):
    rest, file_override = _extract_file(argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=None,
                    help="watchlist path (default: $WATCHLIST_FILE, else ./watchlist.json "
                         "in the project even when cwd is .claude/skills/* or .agents/skills/*, "
                         "else ~/.config/us-watchlist-alerts/watchlist.json)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "update"):
        p = sp.add_parser(name); p.add_argument("symbol")
        p.add_argument("--thesis"); p.add_argument("--entry", type=float); p.add_argument("--stop", type=float)
        p.add_argument("--target", type=float, action="append", dest="targets")
        p.add_argument("--tag", action="append", dest="tags")
        p.add_argument("--alert", action="append", dest="alerts")
        p.add_argument("--side", choices=["long", "short", "watch"])
        p.add_argument("--notes")
        if name == "update": p.add_argument("--append", action="store_true", help="append tags/alerts/targets")
        if name == "add":
            p.add_argument("--no-verify", action="store_true",
                           help="skip Yahoo chart lookup (offline / air-gapped). "
                                "Also set by WATCHLIST_NO_VERIFY=1")
            p.add_argument("--fixture", default=None,
                           help="verify the symbol against a quote fixture instead of the network "
                                "(default: $WATCHLIST_FIXTURE)")
    p = sp.add_parser("remove"); p.add_argument("symbol")
    p = sp.add_parser("show"); p.add_argument("symbol")
    p = sp.add_parser("list"); p.add_argument("--tag")
    sp.add_parser("validate")
    p_init = sp.add_parser("init")
    g_init = p_init.add_mutually_exclusive_group()
    g_init.add_argument("--example", action="store_true",
                        help="copy the bundled sample watchlist (AAPL/TSLA/NVDA fixture-era levels; not a live book)")
    g_init.add_argument("--empty", action="store_true",
                        help="write an empty valid watchlist (default; kept for compatibility)")
    g_init.add_argument("--preset", choices=sorted(PRESETS),
                        help="seed a built-in symbol list (no live price levels; works with --fixture / sample mode)")
    g_init.add_argument("--list-presets", action="store_true",
                        help="print built-in presets and exit without writing a file")
    a = ap.parse_args(rest)
    if file_override:
        a.file = file_override
    if a.cmd == "init" and getattr(a, "list_presets", False):
        print(list_presets_text())
        return 0
    if not a.file:
        a.file = default_watchlist_path()
    if a.cmd == "init":
        try:
            path, how = init_file(a.file, example=a.example, empty=a.empty, preset=a.preset)
        except (FileExistsError, FileNotFoundError, ValueError) as e:
            print(e, file=sys.stderr); return 1
        if how == "copied-example":
            print(f"wrote {path} (sample data)")
            print("SAMPLE DATA: AAPL, TSLA, NVDA with fixture-era price levels "
                  "(e.g. AAPL target $250). Not a live book — demos only.")
        elif how.startswith("preset:"):
            name = how.split(":", 1)[1]
            print(f"wrote {path} (preset {name}: {', '.join(PRESETS[name]['symbols'])})")
        else:
            print(f"wrote {path} (empty)")
        note_using(path)
        return 0
    try:
        wl = load(a.file)
        if a.cmd in ("add", "update"):
            kw = {k: getattr(a, k) for k in ("thesis", "entry", "stop", "targets", "tags", "side", "notes")}
            kw["alerts"] = [parse_alert(x) for x in (a.alerts or [])]
            if a.cmd == "update":
                kw["append"] = a.append
            elif a.cmd == "add":
                skip = a.no_verify or _env_truthy("WATCHLIST_NO_VERIFY")
                if not skip:
                    status, msg = verify_symbol(a.symbol, fixture=a.fixture)
                    if status == "unknown":
                        print(f"error: {msg}", file=sys.stderr)
                        return 1
                    if status == "network":
                        print(f"WARN {msg}", file=sys.stderr)
            t = (add if a.cmd == "add" else update)(wl, a.symbol, **kw)
            save(wl, a.file)
            note_using(a.file)
            print(json.dumps(t, indent=2)); return 0
        elif a.cmd == "remove":
            t = remove(wl, a.symbol)
            save(wl, a.file); print(f"removed {t['symbol']}"); return 0
        elif a.cmd == "show":
            t = find(wl, a.symbol)
            if not t:
                print(f"{a.symbol.upper()} not on watchlist", file=sys.stderr); return 1
            print(json.dumps(t, indent=2)); return 0
        elif a.cmd == "list":
            note_using(a.file)
            for t in wl["tickers"]:
                if a.tag and a.tag not in t.get("tags", []): continue
                print(f"{t['symbol']:<7} entry={t.get('entry')} stop={t.get('stop')} targets={t.get('targets')} tags={','.join(t.get('tags', []))}  {t.get('thesis','')}")
            return 0
        elif a.cmd == "validate":
            errs = validate(wl)
            print("OK" if not errs else "\n".join(errs)); return 1 if errs else 0
        return 0
    except KeyError as e:
        print(f"{e.args[0]} not on watchlist", file=sys.stderr); return 1
    except (ValueError, OSError, json.JSONDecodeError, ImportError) as e:
        print(f"error: {e}", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
