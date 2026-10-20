#!/usr/bin/env python3
"""Price chart for one ticker. Stdlib ASCII; PNG when matplotlib is installed.

  python3 scripts/chart.py AAPL
  python3 scripts/chart.py AAPL --style candle --sma 20,50 --watchlist watchlist.json
  python3 scripts/chart.py AAPL --fixture tests/fixtures/quotes.json --out /tmp/aapl.png

Never places trades. Informational only.
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quotes as qt, watchlist as wlm

SPARK = "▁▂▃▄▅▆▇█"


def sparkline(closes, width=48):
    """One-line Unicode sparkline. ``closes`` oldest → newest."""
    if not closes:
        return ""
    xs = [float(c) for c in closes if c is not None]
    if not xs:
        return ""
    if len(xs) > width:
        step = len(xs) / width
        xs = [xs[int(i * step)] for i in range(width)]
    lo, hi = min(xs), max(xs)
    span = hi - lo or 1.0
    return "".join(SPARK[min(len(SPARK) - 1, int((v - lo) / span * (len(SPARK) - 1)))] for v in xs)


def sma_series(closes, n):
    """Full-length SMA list (None until the window is full)."""
    if n <= 0:
        return [None] * len(closes)
    out = []
    for i in range(len(closes)):
        window = closes[max(0, i - n + 1):i + 1]
        out.append(sum(window) / n if len(window) == n else None)
    return out


def levels_from_watchlist(wl, symbol):
    """Horizontal levels: stop, targets, entry, price_above / price_below."""
    if not wl:
        return []
    key = symbol.upper()
    ticker = next((t for t in (wl.get("tickers") or []) if t.get("symbol") == key), None)
    if not ticker:
        return []
    out = []
    if ticker.get("stop") is not None:
        out.append(("stop", float(ticker["stop"])))
    if ticker.get("entry") is not None:
        out.append(("entry", float(ticker["entry"])))
    for i, tg in enumerate(ticker.get("targets") or []):
        if tg is not None:
            out.append((f"target{i + 1}", float(tg)))
    for rule in ticker.get("alerts") or []:
        typ = rule.get("type")
        if typ in ("price_above", "price_below") and rule.get("value") is not None:
            out.append((typ, float(rule["value"])))
    # stable unique by (label, rounded price)
    seen, uniq = set(), []
    for label, price in out:
        k = (label, round(price, 4))
        if k in seen:
            continue
        seen.add(k)
        uniq.append((label, price))
    return uniq


def ohlc_bars(quote):
    """(open, high, low, close) tuples, or None if we only have closes."""
    closes = [float(c) for c in (quote.get("closes") or []) if c is not None]
    if not closes:
        return None
    highs = quote.get("highs") or quote.get("_highs") or []
    lows = quote.get("lows") or quote.get("_lows") or []
    opens = quote.get("opens") or quote.get("_opens") or []
    if len(highs) == len(closes) and len(lows) == len(closes):
        bars = []
        for i, c in enumerate(closes):
            o = float(opens[i]) if i < len(opens) and opens[i] is not None else (closes[i - 1] if i else c)
            h = float(highs[i]) if highs[i] is not None else max(o, c)
            l = float(lows[i]) if lows[i] is not None else min(o, c)
            bars.append((o, h, l, c))
        return bars
    # Synthetic bodies from close-to-close so --style candle still draws.
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        bars.append((o, max(o, c), min(o, c), c))
    return bars


def ascii_chart(closes, height=12, width=56, levels=None, smas=None, title=""):
    """Small terminal plot. ``smas`` is {label: series} aligned with closes."""
    xs = [float(c) for c in closes if c is not None]
    if len(xs) < 2:
        return (title + "\n" if title else "") + (sparkline(xs) or "(no closes)")
    if len(xs) > width:
        step = len(xs) / width
        idx = [int(i * step) for i in range(width)]
        xs = [xs[i] for i in idx]
        if smas:
            smas = {k: [s[i] if s and i < len(s) else None for i in idx] for k, s in smas.items()}
    lo, hi = min(xs), max(xs)
    for _, p in levels or []:
        lo, hi = min(lo, p), max(hi, p)
    for series in (smas or {}).values():
        for v in series or []:
            if v is not None:
                lo, hi = min(lo, v), max(hi, v)
    span = hi - lo or 1.0
    pad = span * 0.04
    lo, hi, span = lo - pad, hi + pad, (hi - lo) + 2 * pad

    def row_of(v):
        return int(round((hi - v) / span * (height - 1)))

    grid = [[" "] * len(xs) for _ in range(height)]
    for x, v in enumerate(xs):
        grid[row_of(v)][x] = "*"
    marks = {"sma20": ".", "sma50": "+", "sma200": ":"}
    for name, series in (smas or {}).items():
        ch = marks.get(name, "+")
        for x, v in enumerate(series or []):
            if v is None:
                continue
            r = row_of(v)
            if grid[r][x] == " ":
                grid[r][x] = ch
    level_notes = []
    for label, price in levels or []:
        r = row_of(price)
        for x in range(len(xs)):
            if grid[r][x] == " ":
                grid[r][x] = "-"
        grid[r][0] = ">"
        level_notes.append(f"  {label} ${price:.2f}")
    lines = [title] if title else []
    lines.append(sparkline(closes, width=min(width, 48)))
    for i, row in enumerate(grid):
        label = f"{hi - span * i / (height - 1):8.2f} |"
        lines.append(label + "".join(row))
    lines.append(" " * 10 + "oldest".ljust(max(0, len(xs) - 6)) + "newest")
    if level_notes:
        lines.append("levels: " + ", ".join(s.strip() for s in level_notes))
    if smas:
        lines.append("sma: " + ", ".join(f"{k}={marks.get(k, '+')}" for k in smas))
    return "\n".join(lines)


def has_matplotlib():
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


def render_png(path, quote, style="line", sma_ns=None, levels=None, title=""):
    """Write a PNG. Raises ImportError if matplotlib is missing."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    closes = [float(c) for c in (quote.get("closes") or []) if c is not None]
    if len(closes) < 2:
        raise ValueError("need at least 2 closes")
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
    xs = list(range(len(closes)))
    if style == "candle":
        bars = ohlc_bars(quote) or []
        for i, (o, h, l, c) in enumerate(bars):
            color = "#2e7d32" if c >= o else "#c62828"
            ax.vlines(i, l, h, color=color, linewidth=0.8)
            lo_b, hi_b = min(o, c), max(o, c)
            ax.vlines(i, lo_b, hi_b, color=color, linewidth=3)
    else:
        ax.plot(xs, closes, color="#1565c0", linewidth=1.4, label="close")
    for n in sma_ns or []:
        series = sma_series(closes, n)
        ys = [v if v is not None else float("nan") for v in series]
        ax.plot(xs, ys, linewidth=1.0, label=f"SMA{n}")
    palette = {"stop": "#c62828", "entry": "#6a1b9a", "target1": "#2e7d32",
               "target2": "#00838f", "price_above": "#ef6c00", "price_below": "#ef6c00"}
    for label, price in levels or []:
        ax.axhline(price, color=palette.get(label, "#546e7a"), linestyle="--",
                   linewidth=0.9, label=f"{label} {price:.2f}")
    ax.set_title(title or quote.get("symbol") or "chart")
    ax.set_ylabel("USD")
    ax.grid(True, alpha=0.25)
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        # de-dupe legend
        seen, h2, l2 = set(), [], []
        for h, lab in zip(handles, labels):
            if lab in seen:
                continue
            seen.add(lab); h2.append(h); l2.append(lab)
        ax.legend(h2, l2, loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def render(symbol, fixture=None, watchlist=None, style="line", sma_ns=None,
           out=None, provider="auto"):
    """Return ``{text, path, backend}``. Writes PNG to ``out`` when matplotlib is present."""
    sma_ns = [n for n in (sma_ns or [20, 50]) if n > 0]
    q = qt.get_quote(symbol, provider, fixture)
    closes = [float(c) for c in (q.get("closes") or []) if c is not None]
    if q.get("price") is not None and (not closes or closes[-1] != float(q["price"])):
        closes = closes + [float(q["price"])]
    wl = wlm.load(watchlist) if watchlist and os.path.exists(watchlist) else None
    levels = levels_from_watchlist(wl, symbol)
    smas, sma_notes = {}, []
    for n in sma_ns:
        series = sma_series(closes, n)
        if not series or all(v is None for v in series):
            sma_notes.append(f"sma{n} skipped (not enough history)")
        else:
            smas[f"sma{n}"] = series
    last = closes[-1] if closes else q.get("price")
    pc = q.get("prev_close")
    chg = f" {(last - pc) / pc * 100:+.2f}%" if last and pc else ""
    title = f"{q.get('symbol', symbol.upper())}  ${last:.2f}{chg}  ({q.get('source') or 'quote'})"
    text = ascii_chart(closes, levels=levels, smas=smas, title=title)
    if sma_notes:
        text = text + "\n" + "; ".join(sma_notes)
    backend = "ascii"
    path = None
    if out:
        if has_matplotlib():
            path = render_png(out, {**q, "closes": closes}, style=style,
                              sma_ns=sma_ns, levels=levels, title=title)
            backend = "matplotlib"
            text = f"wrote {path} ({style})\n" + sparkline(closes)
        else:
            dest = out if out.endswith((".txt", ".asc")) else out + ".txt"
            with open(dest, "w") as f:
                f.write(text + "\n")
            path = dest
            text = f"matplotlib not installed; wrote ASCII to {dest}\n" + text
    return {"text": text, "path": path, "backend": backend, "levels": levels,
            "closes": closes, "symbol": q.get("symbol", symbol.upper())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol")
    ap.add_argument("--style", choices=("line", "candle"), default="line")
    ap.add_argument("--sma", default="20,50", help="comma-separated SMA windows, or '' for none")
    ap.add_argument("--watchlist", default=None,
                    help="watchlist path (default: $WATCHLIST_FILE or shared user/project location)")
    ap.add_argument("--fixture")
    ap.add_argument("--out", help="PNG path when matplotlib is installed; ASCII otherwise")
    ap.add_argument("--provider", default=os.environ.get("WATCHLIST_PROVIDER", "auto"))
    a = ap.parse_args(argv)
    sma_ns = []
    if a.sma.strip():
        try:
            sma_ns = [int(x) for x in a.sma.split(",") if x.strip()]
        except ValueError:
            print("error: --sma must be comma-separated integers (e.g. 20,50)", file=sys.stderr)
            return 1
    wl_path = a.watchlist or wlm.default_watchlist_path()
    wl = wl_path if os.path.exists(wl_path) else None
    try:
        result = render(a.symbol, fixture=a.fixture, watchlist=wl, style=a.style,
                        sma_ns=sma_ns, out=a.out, provider=a.provider)
    except (qt.QuoteError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(result["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
