#!/usr/bin/env python3
"""Replay 15-minute heartbeats on recorded 2026-10-15 Yahoo bars.

Data is **replayed**, not live. See replay_2026-10-15.json _comment.

  python3 docs/demo/heartbeat/replay.py

Compares:
- WITH skill: alerts.run + persistent state + NYSE session gate
- WITHOUT: same evaluate_rule, but no latch/cooldown and no session skip
  (a fresh agent turn every 15 minutes that only looks at the current quote)

Also prints an audit: distinct events vs repeats vs closed-session pings.
"""
from __future__ import annotations
import datetime as dt, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import alerts, market_calendar as mc, watchlist as wlm

REPLAY = os.path.join(HERE, "replay_2026-10-15.json")
WATCH = os.path.join(HERE, "watchlist.json")


def naive_tick(wl, quotes, now):
    """Re-evaluate every true condition. No state, no session gate."""
    cfg = {**alerts.DEFAULTS, **(wl.get("settings") or {})}
    cfg["_today"] = now.astimezone(mc.ET).date()
    out = []
    for t in wl["tickers"]:
        q = quotes.get(t["symbol"])
        if not q or "error" in q:
            continue
        for r in alerts._expand_rules(t):
            fired, msg, cond = alerts.evaluate_rule(r, t, q, cfg)
            if fired:
                out.append({"symbol": t["symbol"], "type": r["type"], "message": msg,
                            "key": f"{t['symbol']}|{cond}"})
    return out


def _bucket(now, skipped, last_close):
    if skipped:
        return "closed"
    if last_close:
        return "after"
    return "regular"


def _stem(key):
    """AAPL|price_above:340 and AAPL|price_above share a condition stem."""
    return key.split(":")[0]


def audit(with_rows, without_rows):
    """Map every without ping to first-seen key vs repeat, and session bucket."""
    events = []
    closed = after = regular_repeat = 0
    by_key = {}
    for wrow, row in zip(with_rows, without_rows):
        bucket = _bucket(row["now"], wrow.get("skipped"), wrow.get("last_close"))
        for a in row["alerts"]:
            key = a["key"]
            rec = by_key.setdefault(key, {"first": None, "count": 0, "repeats": 0})
            rec["count"] += 1
            if rec["first"] is None:
                rec["first"] = {"now": row["now"], "message": a["message"]}
                events.append({"key": key, "now": row["now"], "message": a["message"]})
            else:
                rec["repeats"] += 1
                if bucket == "closed":
                    closed += 1
                elif bucket == "after":
                    after += 1
                else:
                    regular_repeat += 1
    skill_stems = {_stem(k) for row in with_rows for k in row.get("keys") or []}
    missed_keys = [e["key"] for e in events if _stem(e["key"]) not in skill_stems]
    total = sum(len(r["alerts"]) for r in without_rows)
    distinct = len(events)
    skill_n = sum(len(r["alerts"]) for r in with_rows)
    return {
        "without_total": total,
        "distinct_events": distinct,
        "repeats": total - distinct,
        "repeats_regular_hours": regular_repeat,
        "repeats_after_hours": after,
        "repeats_closed_weekend": closed,
        "closed_or_after_total": after + closed,
        "events": events,
        "by_key": {k: {"first": v["first"], "count": v["count"], "repeats": v["repeats"]} for k, v in by_key.items()},
        "skill_alerts": skill_n,
        "skill_covered_every_distinct_event": missed_keys == [],
        "missed_keys": missed_keys,
    }


def run(path=REPLAY, watch=WATCH):
    with open(path) as f:
        doc = json.load(f)
    wl = wlm.load(watch)
    state = {"fired": {}}
    with_rows, without_rows = [], []
    for tick in doc["ticks"]:
        now = dt.datetime.fromisoformat(tick["now"])
        quotes = tick["quotes"]
        res = alerts.run(wl, state, quotes, now)
        naive = naive_tick(wl, quotes, now)
        with_rows.append({
            "now": tick["now"],
            "session": res["session"],
            "skipped": res.get("skipped"),
            "last_close": res.get("last_close"),
            "reason": res.get("reason"),
            "alerts": [a["message"] for a in res["alerts"]],
            "keys": [a["key"] for a in res["alerts"]],
        })
        without_rows.append({
            "now": tick["now"],
            "alerts": naive,
        })
    aud = audit(with_rows, without_rows)
    return {
        "source": doc.get("source"),
        "comment": doc.get("_comment"),
        "with_skill": with_rows,
        "without_skill": [{**r, "alerts": [a["message"] for a in r["alerts"]]} for r in without_rows],
        "audit": aud,
    }


def _print(report):
    print("REPLAYED DATA —", report["source"])
    print(report["comment"][:180] + "…")
    print()
    print("=== WITH skill (one ping per new event) ===")
    w_n = 0
    for row in report["with_skill"]:
        t = row["now"][11:16] + (" Sat" if row["now"].startswith("2026-10-17") else "")
        if row["skipped"]:
            print(f"  {t}  skip session={row['session']} ({row.get('reason')})")
            continue
        extra = " last_close" if row.get("last_close") else ""
        if not row["alerts"]:
            print(f"  {t}  session={row['session']}{extra}  (silent)")
        else:
            for m in row["alerts"]:
                print(f"  {t}  ALERT {m}")
                w_n += 1
    print(f"  pings: {w_n}  (all first-time news)")
    print()
    print("=== WITHOUT skill (re-ping whenever the condition is still true) ===")
    wo_n = 0
    for row in report["without_skill"]:
        t = row["now"][11:16] + (" Sat" if row["now"].startswith("2026-10-17") else "")
        if not row["alerts"]:
            print(f"  {t}  (no condition true)")
        else:
            for m in row["alerts"]:
                print(f"  {t}  ALERT {m}")
                wo_n += 1
    print(f"  pings: {wo_n}")
    a = report["audit"]
    print()
    print("=== AUDIT ===")
    print(f"  Same {a['distinct_events']} important moves caught. {a['repeats']} duplicate pings avoided.")
    print(f"  without-skill pings: {a['without_total']}  =  {a['distinct_events']} first  +  {a['repeats']} repeats")
    print(f"    repeats during regular hours: {a['repeats_regular_hours']}")
    print(f"    repeats after the bell:       {a['repeats_after_hours']}")
    print(f"    repeats Saturday/closed:      {a['repeats_closed_weekend']}")
    print(f"  skill missed a real distinct event: {not a['skill_covered_every_distinct_event']}")
    for e in a["events"]:
        k = a["by_key"][e["key"]]
        print(f"  - {e['now'][11:16]}  {e['message']}   ({k['count']} pings without / 1 with)")
    return w_n, wo_n


if __name__ == "__main__":
    rep = run()
    _print(rep)
    out = os.path.join(HERE, "replay_report.json")
    with open(out, "w") as f:
        json.dump(rep, f, indent=2)
        f.write("\n")
    print("\nwrote", out)
