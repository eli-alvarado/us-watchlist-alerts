#!/usr/bin/env python3
"""One-command smoke test after ``npx skills add`` or a git clone.

  python3 scripts/quickstart.py           # offline fixture (labeled, not live)
  python3 scripts/quickstart.py --live    # live Yahoo quote + last-close alerts
  python3 scripts/quickstart.py schedule  # weekday cron / Task Scheduler (see schedule.py)

Creates ``watchlist.json`` from the bundled example if it is missing.
Run it from the skill folder (next to SKILL.md) or from a clone of this repo.
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts, brief, watchlist as wlm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # skill folder or repo root


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "schedule":
        import schedule as sched
        return sched.main(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="hit Yahoo instead of the bundled fixture")
    ap.add_argument("--file", default=os.path.join(ROOT, "watchlist.json"))
    a = ap.parse_args(argv)
    if not os.path.exists(a.file):
        path, how = wlm.init_file(a.file)
        print(f"wrote {path} ({how})")
    fx = None if a.live else wlm.bundled_fixture()
    if not a.live and not fx:
        print("No bundled quotes fixture; pass --live or --fixture yourself.", file=sys.stderr)
        return 2
    if a.live:
        print("LIVE Yahoo — delayed ~15 min. Not financial advice. Never places trades.")
        rc = alerts.main(["--watchlist", a.file, "--state", os.path.join(ROOT, ".alert_state.json")])
        if rc:
            return rc
        return brief.main(["--watchlist", a.file, "--kind", "close"]) or 0
    print("FIXTURE DEMO — replayed sample quotes, not a live feed.")
    print("Not financial advice. Never places trades.")
    rc = alerts.main([
        "--watchlist", a.file,
        "--state", os.path.join(ROOT, ".quickstart_state.json"),
        "--fixture", fx,
        "--now", "2026-10-15T18:30:00-04:00",
    ])
    if rc:
        return rc
    return brief.main(["--watchlist", a.file, "--fixture", fx,
                       "--kind", "close", "--now", "2026-10-15T16:15:00-04:00"]) or 0


if __name__ == "__main__":
    sys.exit(main() or 0)
