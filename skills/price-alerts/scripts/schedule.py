#!/usr/bin/env python3
"""Always-on weekday alert check — no agent session required.

Installs a cron entry (macOS/Linux) or prints a Task Scheduler command (Windows)
that runs ``alerts.py --notify`` every 5 minutes on weekdays. ``alerts.py`` already
stays silent on weekends, NYSE holidays, and empty checks.

  python3 scripts/schedule.py              # install
  python3 scripts/schedule.py --dry-run    # print the job, do not install or ping
  python3 scripts/schedule.py uninstall    # remove the cron block
  python3 scripts/quickstart.py schedule   # same commands via quickstart

Requires a notify sink (``WATCHLIST_NOTIFY`` + the sink's env). A successful
install sends one test ping. Never places trades.
"""
from __future__ import annotations
import argparse, os, shlex, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notify, watchlist as wlm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BEGIN = "# us-watchlist-alerts schedule begin"
END = "# us-watchlist-alerts schedule end"
TASK_NAME = "us-watchlist-alerts"
ENV_KEYS = (
    "WATCHLIST_NOTIFY", "NTFY_TOPIC", "NTFY_URL", "NTFY_TOKEN",
    "SLACK_WEBHOOK_URL", "WATCHLIST_WEBHOOK_URL", "WATCHLIST_NOTIFY_FILE",
    "WATCHLIST_FILE", "ALERT_STATE_FILE", "WATCHLIST_PROVIDER",
)
DOTENV = os.path.join(ROOT, ".env")


def _paths(root=ROOT, watchlist=None, state=None):
    """Absolute script + watchlist/state/data-dir. Data dir is never a skill folder."""
    root = os.path.abspath(root)
    script = os.path.join(root, "scripts", "alerts.py")
    wl = os.path.abspath(watchlist or wlm.default_watchlist_path())
    st = os.path.abspath(state or wlm.default_state_path(wl))
    data = os.path.dirname(wl) or os.getcwd()
    return root, script, wl, st, data


def dotenv_path(watchlist=None):
    wl = os.path.abspath(watchlist or wlm.default_watchlist_path())
    return os.path.join(os.path.dirname(wl) or os.getcwd(), ".env")


def load_dotenv(path=DOTENV):
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'").strip('"')
            if k and k not in os.environ:
                os.environ[k] = v


def cron_job_line(root=ROOT, python=None, watchlist=None, state=None):
    python = python or sys.executable
    _, script, wl, st, data = _paths(root, watchlist, state)
    inner = (
        f"cd {shlex.quote(data)} && (set -a; [ -f .env ] && . ./.env; set +a; "
        f"{shlex.quote(python)} {shlex.quote(script)} --watchlist {shlex.quote(wl)} "
        f"--state {shlex.quote(st)} --notify) >> alerts.log 2>&1"
    )
    return f"*/5 * * * 1-5 {inner}"


def strip_block(text):
    out, skip = [], False
    for line in (text or "").splitlines():
        if line.strip() == BEGIN:
            skip = True
            continue
        if line.strip() == END:
            skip = False
            continue
        if not skip:
            out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def render_block(root=ROOT, python=None, watchlist=None, state=None):
    return [BEGIN, cron_job_line(root, python, watchlist, state), END]


def merge_crontab(existing, uninstall=False, root=ROOT, python=None, watchlist=None, state=None):
    kept = strip_block(existing)
    if uninstall:
        return "\n".join(kept) + ("\n" if kept else "")
    if kept and kept[-1] != "":
        kept.append("")
    kept.extend(render_block(root, python, watchlist, state))
    return "\n".join(kept) + "\n"


def windows_task_cmd(root=ROOT, python=None, uninstall=False, watchlist=None, state=None):
    if uninstall:
        return f'schtasks /Delete /TN "{TASK_NAME}" /F'
    python = python or sys.executable
    _, script, wl, st, data = _paths(root, watchlist, state)
    # schtasks /TR has no working-directory flag; cd first and pass absolute paths.
    tr = (
        f'cmd /c cd /d \\"{data}\\" && \\"{python}\\" \\"{script}\\" '
        f'--watchlist \\"{wl}\\" --state \\"{st}\\" --notify'
    )
    return (
        f'schtasks /Create /TN "{TASK_NAME}" /SC MINUTE /MO 5 '
        f'/D MON,TUE,WED,THU,FRI /F /TR "{tr}"'
    )


def redact_env(key, value):
    if any(s in key.upper() for s in ("TOKEN", "SECRET", "KEY", "WEBHOOK", "URL")) and value:
        return "<set>"
    return value


def dotenv_payload():
    lines = ["# us-watchlist-alerts — gitignored. Sourced by the weekday cron job.",
             "# Never places trades."]
    for k in ENV_KEYS:
        v = (os.environ.get(k) or "").strip()
        if v:
            lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def read_crontab():
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"crontab not available: {e}") from e
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip().lower()
        if "no crontab" in err:
            return ""
        raise RuntimeError((r.stderr or r.stdout or f"crontab -l exit {r.returncode}").strip())
    return r.stdout or ""


def write_crontab(text):
    r = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or f"crontab - exit {r.returncode}").strip())


def send_test_ping():
    res = {
        "session": "debug",
        "skipped": False,
        "alerts": [{"symbol": "DEBUG", "type": "schedule",
                    "message": "us-watchlist-alerts: weekday schedule is on. "
                               "You will get a ping when a watchlist rule fires. Never places trades."}],
    }
    return notify.deliver(res, sinks="env")


def _is_windows():
    return sys.platform == "win32"


def run(action="install", dry_run=False, root=ROOT, python=None, platform=None,
        watchlist=None, state=None):
    """Install, uninstall, or dry-run. Returns ``(exit_code, lines)``."""
    python = python or sys.executable
    _, _, wl, st, data = _paths(root, watchlist, state)
    env_file = dotenv_path(wl)
    load_dotenv(env_file)
    if os.path.abspath(env_file) != os.path.abspath(DOTENV):
        load_dotenv(DOTENV)
    win = (_is_windows() if platform is None else platform == "win32")
    lines = []

    if action == "uninstall":
        if win:
            cmd = windows_task_cmd(root, python, uninstall=True, watchlist=wl, state=st)
            lines.append("Windows — run this in an elevated Command Prompt (not installed for you):")
            lines.append(cmd)
            return 0, lines
        new = merge_crontab(read_crontab() if not dry_run else "", uninstall=True,
                            root=root, python=python, watchlist=wl, state=st)
        if dry_run:
            lines.append("Would remove the us-watchlist-alerts cron block.")
            return 0, lines
        write_crontab(new)
        lines.append("Removed weekday cron block.")
        return 0, lines

    errs = notify.sink_config_errors()
    if errs:
        lines.append("Notify is not ready — the always-on job would run silent:")
        lines.extend(f"  - {e}" for e in errs)
        lines.append("Example:")
        lines.append("  export WATCHLIST_NOTIFY=ntfy")
        lines.append("  export NTFY_TOPIC=my-watchlist")
        lines.append("Then re-run. Or use WATCHLIST_NOTIFY=file and WATCHLIST_NOTIFY_FILE for a local log.")
        return 2, lines

    job = cron_job_line(root, python, wl, st)
    if win:
        lines.append("Windows — Task Scheduler is not auto-installed. Run this in an elevated Command Prompt:")
        lines.append(windows_task_cmd(root, python, watchlist=wl, state=st))
        lines.append(f'The command cds to the data directory: {data}')
        lines.append("Set WATCHLIST_NOTIFY and the sink env (NTFY_TOPIC / Slack / webhook) on the task.")
        lines.append("alerts.py stays silent on NYSE holidays and empty checks.")
    else:
        lines.append("Weekday cron (every 5 minutes, Mon–Fri). Holidays/off-hours stay silent via market_calendar:")
        lines.append(job)
        lines.append(f"Working directory (watchlist + state + .env): {data}")
        lines.append("The job sources .env in that directory if present (gitignored).")

    if dry_run:
        lines.append("Dry-run: nothing installed, no test ping sent.")
        return 0, lines

    if not win:
        if not shutil.which("crontab"):
            lines.append("crontab not found. Install cron, or copy the line above into your scheduler.")
            return 1, lines
        existing = read_crontab()
        write_crontab(merge_crontab(existing, root=root, python=python, watchlist=wl, state=st))
        if not os.path.isfile(env_file):
            payload = dotenv_payload()
            if "WATCHLIST_NOTIFY=" in payload:
                os.makedirs(os.path.dirname(env_file) or ".", exist_ok=True)
                with open(env_file, "w") as f:
                    f.write(payload)
                lines.append(f"Wrote {env_file} (gitignored) from the current environment.")
        lines.append("Installed weekday cron. Log: alerts.log in the working directory.")

    results = send_test_ping()
    failed = [r for r in results if not r.get("ok")]
    for r in results:
        if r.get("ok"):
            lines.append(f"Test ping ok ({r.get('sink')}" + (f" {r.get('detail')}" if r.get("detail") else "") + ").")
        else:
            lines.append(f"Test ping failed ({r.get('sink')}): {r.get('error')}")
    if failed:
        lines.append("Schedule is in place, but the test ping did not land. Check the sink env.")
        return 1, lines
    return 0, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="install",
                    choices=("install", "uninstall"),
                    help="install (default) or uninstall the weekday job")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the job; do not write crontab or send a test ping")
    a = ap.parse_args(argv)
    rc, lines = run(action=a.action, dry_run=a.dry_run)
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    sys.exit(main() or 0)
