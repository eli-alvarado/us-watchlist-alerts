"""End-to-end CLI + stdio MCP smoke test.

Spawns the real ``scripts/*.py`` CLIs and ``mcp_server.py`` as subprocesses
in an isolated temp HOME/project. Quote data comes from bundled fixtures or a
deterministic urllib shim — never a live network call.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SAMPLE_FX = os.path.join(ROOT, "examples", "quotes-fixture.json")
TEST_FX = os.path.join(ROOT, "tests", "fixtures", "quotes.json")
TEST_WL = os.path.join(ROOT, "tests", "fixtures", "watchlist.json")
README = os.path.join(ROOT, "README.md")
SKILL_MANAGER = os.path.join(ROOT, "skills", "watchlist-manager", "SKILL.md")
SKILL_ALERTS = os.path.join(ROOT, "skills", "price-alerts", "SKILL.md")
NOW_OPEN = "2026-10-15T10:00:00-04:00"
NOW_CLOSE = "2026-10-15T16:15:00-04:00"
NOW_MORNING = "2026-10-15T08:30:00-04:00"
NOW_WEEKEND = "2026-10-17T10:00:00-04:00"
NOW_HOLIDAY = "2026-11-26T10:00:00-05:00"
MEGA_CAP = ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA")

# Loaded at interpreter startup (PYTHONPATH). Makes urllib fail fast with no sleep.
_NETWORK_SHIM = """\
import time
import urllib.error
import urllib.request

time.sleep = lambda *a, **k: None

def _boom(*a, **k):
    raise urllib.error.URLError("timed out")

urllib.request.urlopen = _boom
_orig_build = urllib.request.build_opener

def _build(*a, **k):
    opener = _orig_build(*a, **k)
    opener.open = _boom
    return opener

urllib.request.build_opener = _build
"""

FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.S)
PY_LINE_RE = re.compile(
    r"python3?\s+(\S*scripts/\S+\.py)(.*)$"
)
SHELL_FENCE_LANGS = {"", "bash", "sh", "shell"}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fenced_blocks(path):
    """Return bodies of copy-paste shell fences (not mermaid/json/example output)."""
    out = []
    for lang, body in FENCE_RE.findall(_read(path)):
        if lang.strip().lower() in SHELL_FENCE_LANGS:
            out.append(body)
    return out


def _watchlist_py_steps(block):
    """Return (script_basename, argv) for python3 scripts/*.py lines in a fence."""
    steps = []
    for raw in block.splitlines():
        line = raw.split("#", 1)[0].strip().rstrip("\\").strip()
        if not line or "python3" not in line:
            continue
        m = PY_LINE_RE.search(line)
        if not m:
            continue
        script = os.path.basename(m.group(1).rstrip("`.,);"))
        args = m.group(2).strip()
        argv = args.split() if args else []
        argv = [a for a in argv if a not in ("|", "||")]
        steps.append((script, argv))
    return steps


class SmokeDir:
    """Brand-new user: empty HOME, project cwd, skill copies, fixture quotes."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="wl-smoke-")
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.home)
        os.makedirs(self.project)
        skills_root = os.path.join(self.project, ".claude", "skills")
        os.makedirs(skills_root)
        for name in ("watchlist-manager", "price-alerts", "watchlist-brief"):
            shutil.copytree(
                os.path.join(ROOT, "skills", name),
                os.path.join(skills_root, name),
            )
        self.shim_dir = os.path.join(self.tmp, "shim")
        os.makedirs(self.shim_dir)
        with open(os.path.join(self.shim_dir, "sitecustomize.py"), "w", encoding="utf-8") as f:
            f.write(_NETWORK_SHIM)
        self.env = os.environ.copy()
        self.env["HOME"] = self.home
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        self.env["WATCHLIST_FIXTURE"] = SAMPLE_FX
        self.env["WATCHLIST_NOTIFY"] = "file"
        self.env["WATCHLIST_NOTIFY_FILE"] = os.path.join(self.tmp, "notify.jsonl")
        self.env["WATCHLIST_HTTP_TIMEOUT"] = "1"
        for k in (
            "WATCHLIST_FILE", "ALERT_STATE_FILE", "WATCHLIST_NO_VERIFY",
            "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY",
            "FINNHUB_API_KEY", "ALPHAVANTAGE_API_KEY",
        ):
            self.env.pop(k, None)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run(self, script, args, extra_env=None, cwd=None, timeout=25):
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
            for k, v in list(extra_env.items()):
                if v is None:
                    env.pop(k, None)
        argv = [sys.executable, "-u", os.path.join(SCRIPTS, script), *args]
        return subprocess.run(
            argv,
            cwd=cwd or self.project,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def skill(self, name, script, args, extra_env=None):
        """Run the documented ``.claude/skills/<name>/scripts/<script>`` path."""
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        rel = os.path.join(".claude", "skills", name, "scripts", script)
        argv = [sys.executable, "-u", rel, *args]
        return subprocess.run(
            argv,
            cwd=self.project,
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
        )

    def network_env(self):
        env = dict(self.env)
        env["WATCHLIST_FIXTURE"] = None
        env["WATCHLIST_PROVIDER"] = "yahoo"
        env["PYTHONPATH"] = self.shim_dir + os.pathsep + env.get("PYTHONPATH", "")
        return env


def _ndjson(raw):
    if raw.startswith(b"Content-Length"):
        raise AssertionError("stdio MCP must not reply with Content-Length framing")
    lines = [ln for ln in raw.split(b"\n") if ln.strip()]
    out = []
    for line in lines:
        msg = json.loads(line)
        out.append(msg)
    return out


class DocumentedRecipes(unittest.TestCase):
    """Copy-paste fences must not be a sequence that the CLI rejects."""

    def test_fences_do_not_init_then_reinit_preset(self):
        failures = []
        for path in (README, SKILL_MANAGER, SKILL_ALERTS):
            for i, block in enumerate(_fenced_blocks(path), 1):
                steps = _watchlist_py_steps(block)
                saw_write_init = False
                for script, argv in steps:
                    if script != "watchlist.py" or (argv[:1] != ["init"]):
                        continue
                    flags = set(argv[1:])
                    if "--list-presets" in flags:
                        continue
                    if saw_write_init:
                        failures.append(
                            f"{os.path.relpath(path, ROOT)} fence #{i}: "
                            "a second `init` that writes a file (already exists)"
                        )
                    saw_write_init = True
        self.assertFalse(failures, "\n".join(failures))

    def test_fences_do_not_add_a_symbol_already_in_that_preset(self):
        failures = []
        for path in (README, SKILL_MANAGER, SKILL_ALERTS):
            for i, block in enumerate(_fenced_blocks(path), 1):
                steps = _watchlist_py_steps(block)
                preset = None
                for script, argv in steps:
                    if script != "watchlist.py":
                        continue
                    if argv[:1] == ["init"] and "--preset" in argv:
                        idx = argv.index("--preset")
                        if idx + 1 < len(argv):
                            preset = argv[idx + 1]
                    if preset and argv[:1] == ["add"] and len(argv) > 1:
                        sym = argv[1].upper()
                        names = {
                            "mega-cap-tech": MEGA_CAP,
                            "index-etfs": ("SPY", "QQQ", "DIA", "IWM"),
                            "sector-etfs": (
                                "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
                                "XLP", "XLU", "XLB", "XLRE", "XLC",
                            ),
                            "dividend-staples": (
                                "JNJ", "PG", "KO", "PEP", "WMT", "MCD", "XOM",
                            ),
                        }
                        if sym in names.get(preset, ()):
                            failures.append(
                                f"{os.path.relpath(path, ROOT)} fence #{i}: "
                                f"init --preset {preset} then add {sym} "
                                "(already on that list; use update --append)"
                            )
        self.assertFalse(failures, "\n".join(failures))


class CliSmoke(unittest.TestCase):
    def test_fresh_empty_watchlist_and_core_skill_commands(self):
        with SmokeDir() as sm:
            r = sm.skill("watchlist-manager", "watchlist.py", ["init"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("(empty)", r.stdout)
            self.assertIn("using ", r.stderr)

            r = sm.run("alerts.py", ["--now", NOW_OPEN])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Watchlist is empty", r.stdout)

            r = sm.run("brief.py", ["--kind", "morning", "--now", NOW_MORNING])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Watchlist is empty", r.stdout)

            r = sm.run("movers.py", ["--now", NOW_OPEN])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Watchlist is empty", r.stdout)

            r = sm.skill(
                "watchlist-manager", "watchlist.py",
                ["add", "NVDA", "--thesis", "AI capex", "--entry", "160",
                 "--target", "190", "--target", "220", "--stop", "140",
                 "--tag", "ai", "--tag", "semis", "--alert", "price_below:150",
                 "--no-verify"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            entry = json.loads(r.stdout)
            self.assertEqual(entry["symbol"], "NVDA")
            self.assertEqual(entry["stop"], 140)

            r = sm.run("watchlist.py", ["list"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("NVDA", r.stdout)
            self.assertIn("using ", r.stderr)

            r = sm.run("watchlist.py", ["show", "NVDA"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["symbol"], "NVDA")

            r = sm.run("watchlist.py", ["update", "NVDA", "--stop", "145"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["stop"], 145)

            r = sm.run(
                "watchlist.py",
                ["update", "NVDA", "--tag", "megacap", "--alert", "rsi_above:75",
                 "--append"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            r = sm.run("watchlist.py", ["validate"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("OK", r.stdout)

            r = sm.run(
                "alerts.py",
                ["--now", NOW_OPEN, "--state", os.path.join(sm.tmp, "state.json")],
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

            r = sm.run(
                "alerts.py",
                ["--format", "json", "--dry-run", "--now", NOW_OPEN,
                 "--state", os.path.join(sm.tmp, "state-dry.json")],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertIn("alerts", payload)
            self.assertFalse(payload.get("skipped"))

            r = sm.run(
                "brief.py",
                ["--kind", "morning", "--format", "json", "--now", NOW_MORNING],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            brief = json.loads(r.stdout)
            self.assertEqual(brief["tickers"][0]["symbol"], "NVDA")

            r = sm.run("brief.py", ["--kind", "close", "--now", NOW_CLOSE])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("NVDA", r.stdout)

            r = sm.run("quotes.py", ["NVDA"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("NVDA", r.stdout)

            r = sm.run("chart.py", ["NVDA"])
            self.assertEqual(r.returncode, 0, r.stderr)

            r = sm.run("movers.py", ["--now", NOW_OPEN, "--format", "json"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["movers"][0]["symbol"], "NVDA")

            r = sm.run("gappers.py", ["--threshold", "2", "--now", NOW_OPEN])
            self.assertEqual(r.returncode, 0, r.stderr)

            r = sm.run("market_calendar.py", [NOW_OPEN[:10]])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("session=regular", r.stdout)
            self.assertIn("trading_day=True", r.stdout)

            r = sm.run("watchlist.py", ["remove", "NVDA"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("removed NVDA", r.stdout)

            r = sm.run("watchlist.py", ["list"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("NVDA", r.stdout)

    def test_preset_then_update_alert_then_add_new_symbol(self):
        with SmokeDir() as sm:
            r = sm.skill("watchlist-manager", "watchlist.py", ["init", "--list-presets"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("mega-cap-tech", r.stdout)

            r = sm.skill(
                "watchlist-manager", "watchlist.py",
                ["init", "--preset", "mega-cap-tech"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("AAPL", r.stdout)

            r = sm.run(
                "watchlist.py",
                ["add", "AAPL", "--alert", "pct_change_down:3", "--no-verify"],
            )
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("already on watchlist", r.stderr)
            self.assertIn("update", r.stderr)

            r = sm.run(
                "watchlist.py",
                ["update", "AAPL", "--alert", "pct_change_down:3", "--append"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            updated = json.loads(r.stdout)
            types = [a["type"] for a in updated.get("alerts") or []]
            self.assertIn("pct_change_down", types)

            r = sm.run("watchlist.py", ["add", "AMD", "--no-verify"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["symbol"], "AMD")

            r = sm.skill("price-alerts", "alerts.py", ["--now", NOW_OPEN, "--dry-run"])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_documented_empty_then_add_skill_paths(self):
        with SmokeDir() as sm:
            r = sm.skill("watchlist-manager", "watchlist.py", ["init"])
            self.assertEqual(r.returncode, 0, r.stderr)
            r = sm.skill(
                "watchlist-manager", "watchlist.py",
                ["add", "AAPL", "--alert", "pct_change_down:3", "--no-verify"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["symbol"], "AAPL")
            r = sm.skill("price-alerts", "alerts.py", ["--now", NOW_OPEN, "--dry-run"])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_missing_watchlist_invalid_ticker_holiday_weekend_network(self):
        with SmokeDir() as sm:
            r = sm.run("alerts.py", ["--now", NOW_OPEN])
            self.assertEqual(r.returncode, 2, r.stdout)
            self.assertIn("init", r.stderr)

            r = sm.run("watchlist.py", ["init"])
            self.assertEqual(r.returncode, 0, r.stderr)

            r = sm.run("watchlist.py", ["add", "ABCDEF"])
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("bad symbol", r.stderr)

            r = sm.run("watchlist.py", ["add", "ZZZZ"])
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("ZZZZ", r.stderr)
            self.assertIn("--no-verify", r.stderr)

            r = sm.run("watchlist.py", ["add", "AAPL", "--no-verify"])
            self.assertEqual(r.returncode, 0, r.stderr)

            r = sm.run(
                "alerts.py",
                ["--now", NOW_WEEKEND, "--state", os.path.join(sm.tmp, "wk.json")],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("market closed", r.stdout)
            self.assertIn("weekend", r.stdout)

            r = sm.run(
                "alerts.py",
                ["--now", NOW_HOLIDAY, "--state", os.path.join(sm.tmp, "hol.json")],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("market closed", r.stdout)
            self.assertRegex(r.stdout.lower(), r"holiday|thanksgiving")

            r = sm.run("market_calendar.py", ["2026-11-26"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Thanksgiving", r.stdout)

            net = sm.network_env()
            r = sm.run(
                "watchlist.py", ["add", "MSFT"],
                extra_env=net,
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertIn("WARN", r.stderr)
            self.assertIn("Adding anyway", r.stderr)
            self.assertEqual(json.loads(r.stdout)["symbol"], "MSFT")

            r = sm.run(
                "alerts.py",
                ["--now", NOW_OPEN, "--state", os.path.join(sm.tmp, "net-al.json")],
                extra_env=net,
            )
            self.assertEqual(r.returncode, 3, r.stdout)
            self.assertIn("ERROR no quotes", r.stderr)

    def test_fixture_alerts_json_and_quickstart(self):
        with SmokeDir() as sm:
            r = sm.run(
                "alerts.py",
                ["--watchlist", TEST_WL, "--fixture", TEST_FX,
                 "--now", "2026-10-15T18:30:00-04:00",
                 "--state", os.path.join(sm.tmp, "fx-state.json"),
                 "--notify", "file"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("ALERT AAPL", r.stdout)
            self.assertIn("market closed, showing last regular close", r.stdout)

            r = sm.run(
                "brief.py",
                ["--watchlist", TEST_WL, "--fixture", TEST_FX,
                 "--kind", "morning", "--now", NOW_MORNING, "--format", "json"],
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            brief = json.loads(r.stdout)
            self.assertEqual(brief["movers"][0]["symbol"], "TSLA")

            r = sm.run("quickstart.py", [])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertFalse(os.path.exists(os.path.join(sm.project, "watchlist.json")))


class McpStdioSmoke(unittest.TestCase):
    def _rpc(self, requests, env, cwd, timeout=20):
        raw_in = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in requests)
        proc = subprocess.run(
            [sys.executable, "-u", os.path.join(SCRIPTS, "mcp_server.py")],
            input=raw_in.encode(),
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=timeout,
        )
        return proc

    def test_stdio_initialize_list_and_core_tools(self):
        with SmokeDir() as sm:
            wl = os.path.join(sm.project, "watchlist.json")
            state = os.path.join(sm.tmp, "mcp-state.json")
            reqs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "e2e-smoke", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "watchlist_list", "arguments": {"file": wl}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "watchlist_add",
                            "arguments": {"symbol": "AAPL", "file": wl,
                                          "no_verify": True,
                                          "alerts": ["pct_change_down:3"]}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                 "params": {"name": "watchlist_list", "arguments": {"file": wl}}},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                 "params": {"name": "get_quotes",
                            "arguments": {"symbols": ["AAPL"], "fixture": TEST_FX}}},
                {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                 "params": {"name": "run_alerts",
                            "arguments": {"watchlist": wl, "fixture": TEST_FX,
                                          "now": NOW_OPEN, "dry_run": True,
                                          "state": state}}},
                {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                 "params": {"name": "morning_brief",
                            "arguments": {"watchlist": wl, "fixture": TEST_FX,
                                          "kind": "morning", "now": NOW_MORNING,
                                          "format": "json"}}},
                {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                 "params": {"name": "market_status",
                            "arguments": {"when": NOW_HOLIDAY}}},
                {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                 "params": {"name": "movers",
                            "arguments": {"watchlist": wl, "fixture": TEST_FX,
                                          "now": NOW_OPEN}}},
                {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                 "params": {"name": "gappers",
                            "arguments": {"watchlist": wl, "fixture": TEST_FX,
                                          "now": NOW_OPEN, "threshold": 2}}},
                {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
                 "params": {"name": "watchlist_remove",
                            "arguments": {"symbol": "AAPL", "file": wl}}},
                {"jsonrpc": "2.0", "id": 13, "method": "shutdown"},
            ]
            proc = self._rpc(reqs, sm.env, sm.project)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            bodies = _ndjson(proc.stdout)
            by_id = {b.get("id"): b for b in bodies}
            self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "us-watchlist-alerts")
            names = {t["name"] for t in by_id[2]["result"]["tools"]}
            need = {
                "get_quotes", "watchlist_list", "watchlist_add", "watchlist_remove",
                "run_alerts", "morning_brief", "market_status", "movers", "gappers",
            }
            self.assertTrue(need <= names, names)

            missing = by_id[3]["result"]
            self.assertTrue(missing.get("isError"), missing)
            self.assertIn("init", missing["content"][0]["text"])

            added = json.loads(by_id[4]["result"]["content"][0]["text"])
            self.assertEqual(added["symbol"], "AAPL")
            listed = json.loads(by_id[5]["result"]["content"][0]["text"])
            self.assertEqual([t["symbol"] for t in listed["tickers"]], ["AAPL"])

            quote = json.loads(by_id[6]["result"]["content"][0]["text"])
            self.assertAlmostEqual(quote["AAPL"]["price"], 241.5)

            alerts = json.loads(by_id[7]["result"]["content"][0]["text"])
            self.assertFalse(alerts["skipped"])

            brief = json.loads(by_id[8]["result"]["content"][0]["text"])
            self.assertTrue(brief.get("tickers") or brief.get("movers"))

            status = json.loads(by_id[9]["result"]["content"][0]["text"])
            self.assertEqual(status["session"], "closed")
            self.assertIn("Thanksgiving", status["holiday"] or "")

            movers = json.loads(by_id[10]["result"]["content"][0]["text"])
            self.assertEqual(movers["movers"][0]["symbol"], "AAPL")

            self.assertIn("removed AAPL", by_id[12]["result"]["content"][0]["text"])
            self.assertEqual(by_id[13]["result"], {})

    def test_stdio_weekend_and_unknown_ticker(self):
        with SmokeDir() as sm:
            wl = os.path.join(sm.project, "watchlist.json")
            reqs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "e2e-smoke", "version": "0"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "watchlist_add",
                            "arguments": {"symbol": "AAPL", "file": wl,
                                          "no_verify": True}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "watchlist_add",
                            "arguments": {"symbol": "ZZZZ", "file": wl,
                                          "fixture": TEST_FX}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "run_alerts",
                            "arguments": {"watchlist": wl, "fixture": TEST_FX,
                                          "now": NOW_WEEKEND, "dry_run": True,
                                          "state": os.path.join(sm.tmp, "wk.json")}}},
                {"jsonrpc": "2.0", "id": 5, "method": "shutdown"},
            ]
            proc = self._rpc(reqs, sm.env, sm.project)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            bodies = _ndjson(proc.stdout)
            by_id = {b.get("id"): b for b in bodies}
            self.assertFalse(by_id[2]["result"].get("isError"))
            zzzz = by_id[3]["result"]
            self.assertTrue(zzzz.get("isError"), zzzz)
            self.assertIn("ZZZZ", zzzz["content"][0]["text"])
            alerts = json.loads(by_id[4]["result"]["content"][0]["text"])
            self.assertTrue(alerts["skipped"])
            self.assertEqual(alerts.get("reason"), "weekend")


if __name__ == "__main__":
    unittest.main()
