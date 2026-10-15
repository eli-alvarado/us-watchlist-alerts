#!/usr/bin/env python3
"""Replay 15-minute heartbeats on recorded 2026-10-15 Yahoo bars.

Data is **replayed**, not live. See replay_2026-10-15.json _comment.

  python3 docs/demo/heartbeat/replay.py

Compares:
- WITH skill: alerts.run + persistent state + NYSE session gate
- WITHOUT: same evaluate_rule, but no latch/cooldown and no session skip
  (a fresh agent turn every 15 minutes that only looks at the current quote)
"""
from __future__ import annotations
import datetime as dt, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import alerts, watchlist as wlm

REPLAY = os.path.join(HERE, "replay_2026-10-15.json")
WATCH = os.path.join(HERE, "watchlist.json")


def naive_tick(wl, quotes, now):
    """Re-evaluate every true condition. No state, no session gate."""
    cfg = {**alerts.DEFAULTS, **(wl.get("settings") or {})}
    cfg["_today"] = now.date() if now.tzinfo is None else now.astimezone().date()
    out = []
    for t in wl["tickers"]:
        q = quotes.get(t["symbol"])
        if not q or "error" in q:
            continue
        for r in alerts._expand_rules(t):
            fired, msg, cond = alerts.evaluate_rule(r, t, q, cfg)
            if fired:
                out.append({"symbol": t["symbol"], "type": r["type"], "message": msg, "key": f"{t['symbol']}|{cond}"})
    return out


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
        })
        without_rows.append({
            "now": tick["now"],
            "alerts": [a["message"] for a in naive],
        })
    return {
        "source": doc.get("source"),
        "comment": doc.get("_comment"),
        "with_skill": with_rows,
        "without_skill": without_rows,
    }


def _print(report):
    print("REPLAYED DATA —", report["source"])
    print(report["comment"][:180] + "…")
    print()
    print("=== WITH skill (latch + daily once + session gate) ===")
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
    print(f"  total new alerts: {w_n}")
    print()
    print("=== WITHOUT skill (fresh evaluate every tick, no state, no session gate) ===")
    wo_n = 0
    for row in report["without_skill"]:
        t = row["now"][11:16] + (" Sat" if row["now"].startswith("2026-10-17") else "")
        if not row["alerts"]:
            print(f"  {t}  (no condition true)")
        else:
            for m in row["alerts"]:
                print(f"  {t}  ALERT {m}")
                wo_n += 1
    print(f"  total alerts: {wo_n}")
    return w_n, wo_n


if __name__ == "__main__":
    rep = run()
    _print(rep)
    out = os.path.join(HERE, "replay_report.json")
    with open(out, "w") as f:
        json.dump(rep, f, indent=2)
        f.write("\n")
    print("\nwrote", out)
