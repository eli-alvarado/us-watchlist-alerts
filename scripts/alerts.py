"""Evaluate watchlist alert rules against quotes, with dedupe + cooldown state.

python scripts/alerts.py --watchlist watchlist.json --state .alert_state.json [--fixture f.json]
       [--now 2026-10-15T10:00:00-04:00] [--force-session] [--dry-run] [--format json|text]

Exit code 0 always on success; output lists only NEW alerts (already-fired ones in cooldown are suppressed).
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import indicators as ind, market_calendar as mc, quotes as qt, watchlist as wlm

DEFAULTS = {"cooldown_minutes": 240, "rearm_pct": 0.5, "sessions": ["regular"],
            "volume_spike_multiple": 2.0, "near_52w_pct": 2.0, "rsi_period": 14,
            "earnings_days": 3, "max_alerts_per_run": 20, "stale_after_seconds": 900}


def _pct(a, b): return (a - b) / b * 100 if b else 0.0


def evaluate_rule(rule, t, q, cfg):
    """Return (fired: bool, message: str, condition_key: str). condition_key distinguishes re-fires."""
    typ = rule["type"]; v = rule.get("value"); p = q.get("price"); pc = q.get("prev_close")
    closes = q.get("closes") or []; sym = t["symbol"]
    if p is None:
        return False, "", typ
    chg = _pct(p, pc) if pc else None
    if typ == "price_above" and p >= v: return True, f"{sym} ${p:.2f} is above ${v:.2f}", f"{typ}:{v}"
    if typ == "price_below" and p <= v: return True, f"{sym} ${p:.2f} is below ${v:.2f}", f"{typ}:{v}"
    if typ == "stop_hit":
        s = v if v is not None else t.get("stop")
        if s is not None and ((t.get("side", "long") != "short" and p <= s) or (t.get("side") == "short" and p >= s)):
            return True, f"{sym} ${p:.2f} hit STOP ${s:.2f}", f"{typ}:{s}"
    if typ == "target_hit":
        short = t.get("side") == "short"
        tgs = [v] if v is not None else list(t.get("targets") or [])
        # nearest remaining target first (long: lowest; short: highest)
        for tg in sorted(tgs, reverse=short):
            if (not short and p >= tg) or (short and p <= tg):
                return True, f"{sym} ${p:.2f} reached target ${tg:.2f}", f"{typ}:{tg}"
    if chg is not None:
        if typ == "pct_change_up" and chg >= v: return True, f"{sym} up {chg:+.2f}% today", typ
        if typ == "pct_change_down" and chg <= -abs(v): return True, f"{sym} down {chg:+.2f}% today", typ
        if typ == "pct_move" and abs(chg) >= v: return True, f"{sym} moved {chg:+.2f}% today", typ
    o = q.get("open")
    if o is not None and pc:
        gap = _pct(o, pc)
        if typ == "gap_up" and gap >= (v or 2): return True, f"{sym} gapped up {gap:+.2f}% (open ${o:.2f})", typ
        if typ == "gap_down" and gap <= -(v or 2): return True, f"{sym} gapped down {gap:+.2f}% (open ${o:.2f})", typ
    hi, lo = q.get("high_52w"), q.get("low_52w")
    prior = closes[-253:-1] if len(closes) > 1 else []
    if typ == "new_52w_high" and prior and p > max(prior): return True, f"{sym} new 52-week high ${p:.2f}", typ
    if typ == "new_52w_low" and prior and p < min(prior): return True, f"{sym} new 52-week low ${p:.2f}", typ
    near = v if v is not None else cfg["near_52w_pct"]
    if typ == "near_52w_high" and hi is not None and _pct(hi, p) <= near:
        return True, f"{sym} within {_pct(hi,p):.1f}% of 52w high ${hi:.2f}", typ
    if typ == "near_52w_low" and lo is not None and _pct(p, lo) <= near:
        return True, f"{sym} within {_pct(p,lo):.1f}% of 52w low ${lo:.2f}", typ
    series = closes[:-1] + [p] if closes else []
    if typ in ("golden_cross", "death_cross"):
        fast, slow = rule.get("fast", 50), rule.get("slow", 200)
        x = ind.ma_cross(series, fast, slow)
        if x and typ.startswith(x): return True, f"{sym} {x} cross: SMA{fast} vs SMA{slow}", typ
    if typ in ("cross_above_ma", "cross_below_ma"):
        n = int(v or 50); x = ind.price_cross_ma(series, n)
        if x and typ == f"cross_{x}_ma": return True, f"{sym} crossed {x} its {n}-day SMA (${ind.sma(series, n):.2f})", f"{typ}:{n}"
    if typ in ("rsi_above", "rsi_below"):
        r = ind.rsi(series, rule.get("period", cfg["rsi_period"]))
        if r is not None and ((typ == "rsi_above" and r >= v) or (typ == "rsi_below" and r <= v)):
            return True, f"{sym} RSI {r:.1f} {'>=' if typ=='rsi_above' else '<='} {v:g}", typ
    if typ == "volume_spike":
        avg = q.get("avg_volume_20d"); vol = q.get("volume"); m = v or cfg["volume_spike_multiple"]
        if avg and vol is not None and vol >= m * avg:
            return True, f"{sym} volume {vol/avg:.1f}x 20-day avg", typ
    if typ == "earnings_within" and q.get("earnings_date"):
        try:
            days = (dt.date.fromisoformat(str(q["earnings_date"])[:10]) - cfg["_today"]).days
        except ValueError:
            return False, "", typ
        if 0 <= days <= (v if v is not None else cfg["earnings_days"]):
            return True, f"{sym} reports earnings in {days} day(s) ({str(q['earnings_date'])[:10]})", f"{typ}:{q['earnings_date']}"
    return False, "", typ


def _expand_rules(t):
    """Implicit stop/target rules, with one target_hit rule per target so T1 latching does not hide T2."""
    rules = list(t.get("alerts") or [])
    if t.get("stop") is not None and not any(r.get("type") == "stop_hit" for r in rules):
        rules.append({"type": "stop_hit"})
    if t.get("targets") and not any(r.get("type") == "target_hit" for r in rules):
        rules.append({"type": "target_hit"})
    out = []
    for r in rules:
        if r.get("type") == "target_hit" and r.get("value") is None:
            for tg in (t.get("targets") or []):
                out.append({**r, "value": tg})
        else:
            out.append(r)
    return out


def load_state(path):
    """Load cooldown state. Corrupt or empty files start fresh (with a warning flag)."""
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("fired"), dict):
                return {"fired": {}, "warning": f"ignored malformed state file {path}"}
            return data
        except (json.JSONDecodeError, OSError) as e:
            return {"fired": {}, "warning": f"reset unreadable state file {path}: {e}"}
    return {"fired": {}}


def save_state(state, path):
    payload = {k: v for k, v in state.items() if k != "warning"}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def should_emit(state, key, now, cooldown_min, trading_date):
    """Anti-spam rules for an alert key that is currently firing:
    - level alerts (price/stop/target/RSI...) stay latched until price re-arms (moves back past the
      level by rearm_pct), so a stock hovering at a level never re-alerts;
    - daily-event alerts (gaps, % moves, volume, crosses, 52w, earnings) fire at most once per trading day;
    - any alert respects cooldown_minutes since its last fire.
    """
    rec = state["fired"].get(key)
    if not rec:
        return True
    if rec.get("once_per_day"):
        if rec.get("trading_date") == trading_date:
            return False
    elif rec.get("active"):
        return False
    last = dt.datetime.fromisoformat(rec["at"])
    return (now - last).total_seconds() >= cooldown_min * 60


DAILY = {"pct_change_up", "pct_change_down", "pct_move", "gap_up", "gap_down", "volume_spike",
         "new_52w_high", "new_52w_low", "golden_cross", "death_cross", "cross_above_ma", "cross_below_ma", "earnings_within"}


def run(wl, state, quotes_by_sym, now, force_session=False, stale_after=None):
    cfg = {**DEFAULTS, **(wl.get("settings") or {})}
    extra = mc.parse_dates(cfg.get("extra_closures"))
    cfg["_today"] = now.astimezone(mc.ET).date()
    sess = mc.session(now, extra=extra)
    out, errors = [], []
    if not force_session and sess not in cfg["sessions"]:
        return {"session": sess, "skipped": True, "alerts": [], "errors": [], "stale": []}
    if stale_after is None:
        stale_after = cfg.get("stale_after_seconds", DEFAULTS["stale_after_seconds"])
    trading_date = cfg["_today"].isoformat()
    cap = cfg["max_alerts_per_run"]
    truncated = False
    for t in wl["tickers"]:
        q = quotes_by_sym.get(t["symbol"])
        if not q or "error" in q:
            errors.append({"symbol": t["symbol"], "error": (q or {}).get("error", "no quote")}); continue
        for r in _expand_rules(t):
            fired, msg, cond = evaluate_rule(r, t, q, cfg)
            key = f"{t['symbol']}|{cond}"
            if fired:
                cd = r.get("cooldown_minutes", cfg["cooldown_minutes"])
                if should_emit(state, key, now, cd, trading_date):
                    if len(out) >= cap:
                        # Do not latch alerts we are not going to report — they must be free to fire next run.
                        truncated = True
                        continue
                    out.append({"symbol": t["symbol"], "type": r["type"], "message": msg, "price": q["price"],
                                "key": key, "session": sess, "source": q.get("source")})
                    state["fired"][key] = {"at": now.isoformat(), "active": True, "trading_date": trading_date,
                                           "once_per_day": r["type"] in DAILY, "price": q["price"]}
            elif r["type"] not in DAILY:
                # re-arm latched level alerts only once price moves back past the level by rearm_pct (hysteresis)
                prefix = f"{t['symbol']}|{r['type']}"
                for k, rec in state["fired"].items():
                    if (k == prefix or k.startswith(prefix + ":")) and rec.get("active"):
                        lvl = k.split(":", 1)[1] if ":" in k else None
                        lvl = float(lvl) if lvl not in (None, "None") else None
                        if r["type"].startswith("rsi") or lvl is None or abs(_pct(q["price"], lvl)) >= cfg["rearm_pct"]:
                            rec["active"] = False
    stale = []
    if stale_after:
        for t in wl["tickers"]:
            q = quotes_by_sym.get(t["symbol"])
            if not q or "error" in q:
                continue
            age = qt.quote_age_seconds(q, now)
            if age is not None and age > stale_after and sess == "regular":
                stale.append({"symbol": t["symbol"], "age_seconds": int(age), "as_of": q.get("as_of"),
                              "source": q.get("source")})
    res = {"session": sess, "skipped": False, "alerts": out, "errors": errors, "stale": stale}
    if truncated:
        res["truncated"] = True
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default=wlm.DEFAULT_PATH)
    ap.add_argument("--state", default=os.environ.get("ALERT_STATE_FILE", ".alert_state.json"))
    ap.add_argument("--fixture"); ap.add_argument("--provider", default="auto")
    ap.add_argument("--now", help="ISO datetime override (testing)")
    ap.add_argument("--force-session", action="store_true", help="evaluate even outside configured sessions")
    ap.add_argument("--dry-run", action="store_true", help="do not write state")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--stale-after", type=int, default=None,
                    help="warn if quote as_of is older than N seconds during regular hours (0=off)")
    a = ap.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(mc.ET)
    if now.tzinfo is None: now = now.replace(tzinfo=mc.ET)
    try:
        mc.refresh_official_calendar(now.year)
    except Exception as e:
        print(f"WARN official NYSE overlay skipped: {e}", file=sys.stderr)
    wl = wlm.load(a.watchlist); state = load_state(a.state)
    warn = state.pop("warning", None)
    quotes = {}
    for t in wl["tickers"]:
        try: quotes[t["symbol"]] = qt.get_quote(t["symbol"], a.provider, a.fixture)
        except Exception as e: quotes[t["symbol"]] = {"error": str(e)}
    stale_after = a.stale_after
    if stale_after is None:
        env = os.environ.get("WATCHLIST_STALE_AFTER")
        stale_after = int(env) if env not in (None, "") else None
    res = run(wl, state, quotes, now, a.force_session, stale_after=stale_after)
    if warn:
        res["state_warning"] = warn
    if not a.dry_run and not res["skipped"]: save_state(state, a.state)
    if a.format == "json":
        print(json.dumps(res, indent=2))
    else:
        et = now.astimezone(mc.ET)
        if warn:
            print(f"WARN {warn}", file=sys.stderr)
        if res["skipped"]: print(f"[{et:%Y-%m-%d %H:%M} ET] session={res['session']} - outside alert sessions, nothing checked")
        elif not res["alerts"]: print(f"[{et:%Y-%m-%d %H:%M} ET] no new alerts")
        for x in res["alerts"]: print(f"ALERT {x['message']}")
        if res.get("truncated"):
            print(f"WARN alert cap ({(wl.get('settings') or {}).get('max_alerts_per_run', DEFAULTS['max_alerts_per_run'])}) reached; remaining alerts left unlatched", file=sys.stderr)
        for e in res["errors"]: print(f"WARN {e['symbol']}: {e['error']}", file=sys.stderr)
        for s in res.get("stale") or []:
            print(f"WARN {s['symbol']}: quote is {s['age_seconds']}s old (as_of {s.get('as_of')}, source={s.get('source')})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
