"""Gap up/down vs prior close on the watchlist (open vs yesterday's close).

python3 scripts/gappers.py
python3 scripts/gappers.py --threshold 2
python3 scripts/gappers.py --watchlist tests/fixtures/watchlist.json \\
    --fixture tests/fixtures/quotes.json --threshold 2 --now 2026-10-15T10:00:00-04:00

Default threshold is 2% (same as the ``gap_up`` / ``gap_down`` alert types).
Exit 0 on success (including an empty watchlist hint or no names over the
threshold). Exit 2 if the watchlist file is missing. Exit 3 if every ticker
failed to quote.
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screener


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    screener._shared_args(ap)
    ap.add_argument("--threshold", type=float, default=2.0,
                    help="minimum absolute gap %% vs prior close (default: 2)")
    a = ap.parse_args(argv)
    rc, payload = screener.prepare_run(a)
    if rc or payload is None:
        return rc
    wl, quotes, now, _n_failed = payload
    rows = screener.rank_gappers(wl, quotes, threshold=a.threshold)
    print(screener.format_gappers(rows, now, a.threshold, fmt=a.format))
    return 0


if __name__ == "__main__":
    sys.exit(main())
