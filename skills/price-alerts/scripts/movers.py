"""Today's biggest movers on the watchlist (last price vs prior close).

python3 scripts/movers.py
python3 scripts/movers.py --limit 5 --format json
python3 scripts/movers.py --watchlist tests/fixtures/watchlist.json \\
    --fixture tests/fixtures/quotes.json --now 2026-10-15T10:00:00-04:00

Exit 0 on success (including an empty watchlist hint). Exit 2 if the watchlist
file is missing. Exit 3 if every ticker failed to quote.
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screener


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    screener._shared_args(ap)
    ap.add_argument("--limit", type=int, default=None,
                    help="max names to print (default: the whole list)")
    a = ap.parse_args(argv)
    rc, payload = screener.prepare_run(a)
    if rc or payload is None:
        return rc
    wl, quotes, now, _n_failed = payload
    rows = screener.rank_movers(wl, quotes, limit=a.limit)
    print(screener.format_movers(rows, now, fmt=a.format))
    return 0


if __name__ == "__main__":
    sys.exit(main())
