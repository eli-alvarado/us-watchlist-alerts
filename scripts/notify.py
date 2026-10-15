"""Deliver fired alerts to optional sinks. Never places trades.

Sinks (enable with ``WATCHLIST_NOTIFY=ntfy,slack`` and/or ``alerts.py --notify``):

- ``webhook`` — JSON POST to ``WATCHLIST_WEBHOOK_URL``
- ``slack`` — ``{"text": ...}`` POST to ``SLACK_WEBHOOK_URL`` (incoming webhook)
- ``ntfy`` — POST body to ``{NTFY_URL}/{NTFY_TOPIC}`` (default host ``https://ntfy.sh``;
  optional ``NTFY_TOKEN``)
- ``desktop`` — Linux ``notify-send`` (no-op with an error on other platforms)
- ``file`` — append one JSON line to ``WATCHLIST_NOTIFY_FILE``

Empty / skipped / dry-run runs do not notify. Delivery failures are returned, never raised.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, shutil, subprocess, sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))
import quotes as qt

VALID_SINKS = ("webhook", "slack", "ntfy", "desktop", "file")


def parse_sinks(spec=None):
    """Return ``(known, unknown)`` sink names from a comma/semicolon list or env."""
    raw = spec if spec not in (None, "", "env") else os.environ.get("WATCHLIST_NOTIFY") or ""
    parts = [p.strip().lower() for p in str(raw).replace(";", ",").split(",") if p.strip()]
    known, unknown = [], []
    seen = set()
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        (known if p in VALID_SINKS else unknown).append(p)
    return known, unknown


def format_text(res):
    alerts = res.get("alerts") or []
    n = len(alerts)
    sess = res.get("session") or "?"
    lines = [f"{n} new alert{'s' if n != 1 else ''} ({sess})"]
    for a in alerts:
        lines.append(f"- {a.get('message') or a}")
    return "\n".join(lines)


def _ok(sink, detail=None):
    out = {"sink": sink, "ok": True}
    if detail:
        out["detail"] = detail
    return out


def _err(sink, error):
    return {"sink": sink, "ok": False, "error": str(error)}


def _ntfy_endpoint():
    url = (os.environ.get("NTFY_URL") or "https://ntfy.sh").rstrip("/")
    topic = (os.environ.get("NTFY_TOPIC") or "").strip()
    if topic:
        if url.endswith("/" + topic):
            return url
        return url + "/" + topic
    path = urlparse(url).path or ""
    if path not in ("", "/"):
        return url
    return None


def _post_json(url, payload, provider):
    qt._post(url, payload, provider=provider, retries=1)


def _post_text(url, text, headers, provider):
    qt._post(url, text, headers=headers, provider=provider, retries=1)


def _webhook(res, text):
    url = (os.environ.get("WATCHLIST_WEBHOOK_URL") or "").strip()
    if not url:
        return _err("webhook", "WATCHLIST_WEBHOOK_URL is not set")
    payload = {
        "source": "us-watchlist-alerts",
        "session": res.get("session"),
        "count": len(res.get("alerts") or []),
        "alerts": res.get("alerts") or [],
        "text": text,
    }
    _post_json(url, payload, "webhook")
    return _ok("webhook", url.split("?", 1)[0])


def _slack(text):
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    if not url:
        return _err("slack", "SLACK_WEBHOOK_URL is not set")
    _post_json(url, {"text": text}, "slack")
    return _ok("slack")


def _ntfy(text, title):
    endpoint = _ntfy_endpoint()
    if not endpoint:
        return _err("ntfy", "set NTFY_TOPIC (and optional NTFY_URL)")
    headers = {"Title": title, "Priority": "default", "Content-Type": "text/plain; charset=utf-8"}
    token = (os.environ.get("NTFY_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    _post_text(endpoint, text, headers, "ntfy")
    return _ok("ntfy", endpoint)


def _desktop(text, title):
    binary = shutil.which("notify-send")
    if not binary:
        return _err("desktop", "notify-send not found (Linux desktop only)")
    body = text if len(text) < 900 else text[:890] + "\n…"
    try:
        r = subprocess.run([binary, "-a", "us-watchlist-alerts", title, body],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return _err("desktop", e)
    if r.returncode != 0:
        return _err("desktop", (r.stderr or r.stdout or f"exit {r.returncode}").strip())
    return _ok("desktop")


def _file(res):
    path = (os.environ.get("WATCHLIST_NOTIFY_FILE") or "").strip()
    if not path:
        return _err("file", "WATCHLIST_NOTIFY_FILE is not set")
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "session": res.get("session"),
        "count": len(res.get("alerts") or []),
        "alerts": res.get("alerts") or [],
    }
    with open(path, "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return _ok("file", path)


def deliver(res, sinks=None):
    """Send ``res['alerts']`` to each sink. Never raises."""
    known, unknown = parse_sinks(sinks)
    out = [_err(name, "unknown sink") for name in unknown]
    if not known and not unknown:
        return [_err("notify", "no sinks configured (set WATCHLIST_NOTIFY or pass --notify ntfy,slack)")]
    text = format_text(res)
    n = len(res.get("alerts") or [])
    title = f"{n} watchlist alert{'s' if n != 1 else ''}"
    dispatch = {
        "webhook": lambda: _webhook(res, text),
        "slack": lambda: _slack(text),
        "ntfy": lambda: _ntfy(text, title),
        "desktop": lambda: _desktop(text, title),
        "file": lambda: _file(res),
    }
    for name in known:
        try:
            out.append(dispatch[name]())
        except Exception as e:
            out.append(_err(name, e))
    return out


def should_deliver(res, dry_run=False):
    return (not dry_run) and (not (res or {}).get("skipped")) and bool((res or {}).get("alerts"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sinks", default="env", help="comma-separated sinks, or 'env' for WATCHLIST_NOTIFY")
    ap.add_argument("--text", help="send this text as a single synthetic alert (debug)")
    a = ap.parse_args(argv)
    if a.text:
        res = {"session": "debug", "skipped": False, "alerts": [{"message": a.text, "symbol": "DEBUG"}]}
    else:
        print("pass --text to send a test notification", file=sys.stderr)
        return 2
    results = deliver(res, sinks=a.sinks)
    print(json.dumps(results, indent=2, default=str))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
