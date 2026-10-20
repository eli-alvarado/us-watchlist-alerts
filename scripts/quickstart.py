#!/usr/bin/env python3
"""One-command smoke test after ``npx skills add`` or a git clone.

  python3 scripts/quickstart.py           # offline fixture (labeled, not live)
  python3 scripts/quickstart.py --live    # live Yahoo quote + last-close alerts
  python3 scripts/quickstart.py schedule  # weekday cron / Task Scheduler (see schedule.py)

The fixture demo reads the bundled example **in place** and never writes
``watchlist.json``. ``--live`` uses the user's real list (shared project / user-config
path) and prints the ``init`` hint if it is missing.
"""
from __future__ import annotations
import argparse, os, sys, tempfile
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
    ap.add_argument("--file", default=None,
                    help="watchlist path. Fixture demo ignores this and reads the bundled "
                         "example. --live uses the user's default list if omitted.")
    a = ap.parse_args(argv)
    if a.live:
        wl = a.file or wlm.default_watchlist_path()
        if not os.path.exists(wl):
            print(wlm.missing_watchlist_hint(wl), file=sys.stderr)
            return 2
        print("LIVE Yahoo — delayed ~15 min. Not financial advice. Never places trades.")
        rc = alerts.main(["--watchlist", wl, "--state", wlm.default_state_path(wl)])
        if rc:
            return rc
        return brief.main(["--watchlist", wl, "--kind", "close"]) or 0
    example = wlm.bundled_example()
    fx = wlm.bundled_fixture()
    if not example:
        print("No bundled example watchlist.", file=sys.stderr)
        return 2
    if not fx:
        print("No bundled quotes fixture; pass --live or --fixture yourself.", file=sys.stderr)
        return 2
    print("FIXTURE DEMO — replayed sample quotes, not a live feed.")
    print("Reads the bundled example in place; does not write watchlist.json.")
    print("Not financial advice. Never places trades.")
    fd, state = tempfile.mkstemp(prefix="quickstart-state-", suffix=".json")
    os.close(fd)
    with open(state, "w") as f:
        f.write('{"fired": {}}\n')
    try:
        rc = alerts.main([
            "--watchlist", example,
            "--state", state,
            "--fixture", fx,
            "--now", "2026-10-15T18:30:00-04:00",
        ])
        if rc:
            return rc
        return brief.main(["--watchlist", example, "--fixture", fx,
                           "--kind", "close", "--now", "2026-10-15T16:15:00-04:00"]) or 0
    finally:
        for p in (state, state + ".tmp"):
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main() or 0)
