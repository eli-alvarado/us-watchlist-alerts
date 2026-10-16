#!/usr/bin/env python3
"""Session-aware weekday snapshot for the scheduled GitHub Action.

Writes at most one ``docs/live/YYYY-MM-DD.md`` per ET weekday / trading day.
Always appends the same markdown to ``$GITHUB_STEP_SUMMARY`` when set.
Never commits secrets. Quote failures stay in the job summary (exit 0).

  python3 scripts/live_snapshot.py --watchlist examples/live-watchlist.json --out docs/live
  python3 scripts/live_snapshot.py --now 2026-10-17T10:00:00-04:00   # Saturday skip
  python3 scripts/live_snapshot.py --fixture tests/fixtures/quotes.json --now 2026-10-15T16:20:00-04:00
"""
from __future__ import annotations
import argparse, datetime as dt, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alerts, brief, market_calendar as mc, quotes as qt, watchlist as wlm


def _write(path, text):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a" if path == os.environ.get("GITHUB_STEP_SUMMARY") else "w") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def _gh_output(key, value):
    dest = os.environ.get("GITHUB_OUTPUT")
    if not dest:
        return
    with open(dest, "a") as f:
        f.write(f"{key}={value}\n")


def render_snapshot(wl, quotes, res, now, source_note):
    et = now.astimezone(mc.ET)
    day = et.date().isoformat()
    sess = res.get("session")
    lines = [
        f"# Live snapshot — {day}",
        "",
        f"**REPLAYED fixture — not live.**" if source_note.startswith("fixture")
        else f"**Live public quotes** (Yahoo unofficial; may be delayed ~15 minutes).",
        "",
        f"- Time: {et:%Y-%m-%d %H:%M} ET",
        f"- Session: `{sess}`" + (" — last regular close" if res.get("last_close") else ""),
        f"- Source: {source_note}",
        f"- Alerts below use a **fresh state** (what is true on this check, not a latched HEARTBEAT).",
        "",
        "## Quotes",
        "",
        "| Ticker | Last | Prev close | Day % | Source |",
        "|---|---:|---:|---:|---|",
    ]
    for t in wl["tickers"]:
        q = quotes.get(t["symbol"]) or {}
        if "error" in q:
            lines.append(f"| {t['symbol']} | — | — | — | error: {q['error']} |")
            continue
        pc = q.get("prev_close")
        chg = (q["price"] - pc) / pc * 100 if pc else 0
        lines.append(
            f"| {t['symbol']} | ${q['price']:.2f} | ${pc:.2f} | {chg:+.2f}% | {q.get('source') or source_note} |"
        )
    lines += ["", "## Conditions true on this check", ""]
    if res.get("skipped"):
        lines.append(f"Skipped: {res.get('reason')} (next session {res.get('next_session')}).")
    elif not res.get("alerts"):
        lines.append("None.")
    else:
        for a in res["alerts"]:
            lines.append(f"- ALERT {a['message']}")
    lines += ["", "## Close brief", "", "_Informational only — not financial advice. Never places trades._", ""]
    try:
        lines.append(brief.render(wl, quotes, "close", now))
    except Exception as e:
        lines.append(f"(brief failed: {e})")
    return "\n".join(lines).rstrip() + "\n"


def run(watch, out_dir, now=None, fixture=None, force=False):
    now = now or dt.datetime.now(mc.ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=mc.ET)
    day = now.astimezone(mc.ET).date()
    dest = os.path.join(out_dir, f"{day.isoformat()}.md")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")

    if not mc.is_trading_day(day):
        why = mc.holiday_name(day) or ("weekend" if day.weekday() >= 5 else "closed")
        md = f"# Live snapshot — {day.isoformat()}\n\nSkipped: not a trading day ({why}).\n"
        if summary:
            _write(summary, md)
        print(f"skip {day.isoformat()} ({why})")
        _gh_output("commit_path", "")
        _gh_output("skipped", "1")
        return {"skipped": True, "reason": why, "path": dest}

    if os.path.exists(dest) and not force:
        with open(dest) as f:
            existing = f.read()
        if summary:
            _write(summary, existing)
        print(f"already have {dest} — one tidy update per weekday")
        _gh_output("commit_path", "")
        _gh_output("skipped", "already")
        return {"skipped": True, "reason": "already", "path": dest}

    if not os.path.exists(watch):
        print(wlm.missing_watchlist_hint(watch), file=sys.stderr)
        _gh_output("commit_path", "")
        return {"skipped": True, "reason": "no-watchlist", "path": dest}

    wl = wlm.load(watch)
    quotes, errors = {}, []
    for t in wl["tickers"]:
        try:
            quotes[t["symbol"]] = qt.get_quote(t["symbol"], "auto", fixture)
        except Exception as e:
            quotes[t["symbol"]] = {"error": str(e)}
            errors.append(f"{t['symbol']}: {e}")
    if errors and all("error" in (quotes.get(t["symbol"]) or {}) for t in wl["tickers"]):
        md = f"# Live snapshot — {day.isoformat()}\n\nQuote fetch failed (not committed):\n\n" + "\n".join(f"- {e}" for e in errors) + "\n"
        if summary:
            _write(summary, md)
        print(md)
        _gh_output("commit_path", "")
        _gh_output("skipped", "fetch-failed")
        return {"skipped": True, "reason": "fetch-failed", "errors": errors, "path": dest}

    state = {"fired": {}}
    res = alerts.run(wl, state, quotes, now)
    sources = { (quotes.get(t["symbol"]) or {}).get("source") for t in wl["tickers"] }
    sources.discard(None)
    source_note = "fixture" if fixture else ("+".join(sorted(sources)) or "unknown")
    md = render_snapshot(wl, quotes, res, now, source_note)
    os.makedirs(out_dir, exist_ok=True)
    _write(dest, md)
    if summary:
        _write(summary, md)
    print(f"wrote {dest}")
    _gh_output("commit_path", dest)
    _gh_output("skipped", "")
    return {"skipped": False, "path": dest, "alerts": len(res.get("alerts") or []), "session": res.get("session")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "live-watchlist.json"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "live"))
    ap.add_argument("--now")
    ap.add_argument("--fixture")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now) if a.now else None
    if now and now.tzinfo is None:
        now = now.replace(tzinfo=mc.ET)
    run(a.watchlist, a.out, now=now, fixture=a.fixture, force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
