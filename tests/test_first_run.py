"""First-run e2e: empty HOME, documented CLI, fixture data only (no network)."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import quotes as qt
import watchlist as wlm

SAMPLE_FX = os.path.join(ROOT, "examples", "quotes-fixture.json")
TEST_FX = os.path.join(ROOT, "tests", "fixtures", "quotes.json")
TEST_WL = os.path.join(ROOT, "tests", "fixtures", "watchlist.json")
NOW = "2026-10-15T11:00:00-04:00"
DOC_FILES = (
    os.path.join(ROOT, "README.md"),
    os.path.join(ROOT, "skills", "watchlist-manager", "SKILL.md"),
    os.path.join(ROOT, "skills", "price-alerts", "SKILL.md"),
    os.path.join(ROOT, "skills", "watchlist-brief", "SKILL.md"),
)
SCRIPT_NAMES = (
    "watchlist.py", "alerts.py", "brief.py", "chart.py", "quotes.py",
    "schedule.py", "quickstart.py", "market_calendar.py",
    "movers.py", "gappers.py",
)
IGNORE_DOC_FLAGS = {
    "all", "depth",  # npx / git
}
CMD_RE = re.compile(
    r"(?:(?P<env>(?:[A-Z][A-Z0-9_]*=\S+\s+)+))?python3?\s+"
    r"(?P<script>\S*scripts/\S+\.py)"
    r"(?P<args>(?:\s+(?:\[[^\]]+\]|\"[^\"]*\"|'[^']*'|--?\S+|\S+))*)"
)
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
INLINE_RE = re.compile(r"`(python3? [^`]+)`")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _help(script, argv):
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), *argv, "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    return (r.stdout or "") + (r.stderr or "")


def collect_cli():
    """Flags and subcommands actually implemented by each script."""
    flags, commands = {}, {}
    for name in SCRIPT_NAMES:
        help_text = _help(name, [])
        flags[name] = set(re.findall(r"--[a-z][a-z0-9-]*", help_text))
        cmds = set()
        usage_lines = []
        for line in help_text.splitlines():
            if line.startswith("usage:") or (usage_lines and (line.startswith(" ") or line.startswith("\t"))):
                usage_lines.append(line)
                continue
            if usage_lines:
                break
        usage = " ".join(usage_lines)
        positional = re.sub(r"--[\w-]+(?:\s+\{[^}]+\})?", "", usage)
        for m in re.finditer(r"\{([\w,-]+)\}", positional):
            cmds.update(x.strip() for x in m.group(1).split(",") if x.strip())
        if name == "quickstart.py":
            cmds.add("schedule")
        for cmd in list(cmds):
            try:
                ht = _help(name, [cmd])
            except Exception:
                continue
            flags[name].update(re.findall(r"--[a-z][a-z0-9-]*", ht))
        commands[name] = cmds
    return flags, commands


def _strip_comment(line):
    out, quote = [], None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _command_candidates(text):
    """Fenced code blocks plus inline `` `python3 …` `` spans only (not following prose)."""
    chunks = []
    for block in FENCE_RE.findall(text):
        chunks.append(re.sub(r"\\\s*\n\s*", " ", block))
    for span in INLINE_RE.findall(text):
        chunks.append(span)
    return chunks


def _normalize_cmd_line(raw):
    line = _strip_comment(raw)
    if " && " in line:
        line = line.split(" && ")[-1]
    line = re.sub(r"\s*(?:>>|>|<)\s+\S+.*$", "", line)
    line = re.sub(r"\[[^\]]+\]", lambda m: m.group(0)[1:-1], line)
    return line.strip().strip("`").rstrip(".,);")


def extract_doc_commands(text, source=""):
    """Return documented ``python3 scripts/….py`` invocations."""
    found = []
    seen = set()
    for chunk in _command_candidates(text):
        for raw in chunk.splitlines():
            line = _normalize_cmd_line(raw)
            if "scripts/" not in line or ".py" not in line:
                continue
            if "python3" not in line and not re.search(r"\bpython\s+", line):
                continue
            for m in CMD_RE.finditer(line):
                script = os.path.basename(m.group("script").rstrip("`.,);"))
                if script not in SCRIPT_NAMES:
                    continue
                try:
                    args = shlex.split(m.group("args") or "")
                except ValueError:
                    args = (m.group("args") or "").split()
                args = [a.rstrip("`.,);") for a in args if a not in ("|", "||")]
                env = {}
                env_blob = m.group("env") or ""
                for part in env_blob.split():
                    if "=" in part:
                        k, _, v = part.partition("=")
                        env[k] = v
                key = (script, tuple(args), tuple(sorted(env.items())))
                if key in seen:
                    continue
                seen.add(key)
                found.append({
                    "script": script,
                    "args": args,
                    "env": env,
                    "source": source,
                    "raw": m.group(0).strip(),
                })
    return found


def all_doc_commands():
    out = []
    for path in DOC_FILES:
        out.extend(extract_doc_commands(_read(path), os.path.relpath(path, ROOT)))
    return out


def all_doc_flags():
    flags = set()
    for path in DOC_FILES:
        flags.update(re.findall(r"--[a-z][a-z0-9-]*", _read(path)))
    return flags


class FreshUser:
    """Brand-new user: empty HOME, no config, fixture quotes only."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        self.empty = os.path.join(self.tmp, "empty")
        os.makedirs(self.home)
        os.makedirs(self.project)
        os.makedirs(self.empty)
        self.skill = os.path.join(self.project, ".claude", "skills", "watchlist-manager")
        os.makedirs(os.path.dirname(self.skill), exist_ok=True)
        import shutil
        shutil.copytree(os.path.join(ROOT, "skills", "watchlist-manager"), self.skill)
        self.env = os.environ.copy()
        self.env["HOME"] = self.home
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        self.env["WATCHLIST_FIXTURE"] = SAMPLE_FX
        self.env["WATCHLIST_NOTIFY"] = "file"
        self.env["WATCHLIST_NOTIFY_FILE"] = os.path.join(self.tmp, "notify.jsonl")
        self.env["WATCHLIST_HTTP_TIMEOUT"] = "2"
        for k in (
            "WATCHLIST_FILE", "ALERT_STATE_FILE", "WATCHLIST_NO_VERIFY",
            "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY",
            "FINNHUB_API_KEY", "ALPHAVANTAGE_API_KEY",
        ):
            self.env.pop(k, None)
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cwd_for(self, kind):
        if kind == "project":
            return self.project
        if kind == "empty":
            return self.empty
        if kind == "skill":
            return self.skill
        raise ValueError(kind)

    def rewrite_args(self, args, cwd):
        out = []
        for a in args:
            if a in ("tests/fixtures/watchlist.json", "./tests/fixtures/watchlist.json"):
                out.append(TEST_WL)
            elif a in ("tests/fixtures/quotes.json", "./tests/fixtures/quotes.json"):
                out.append(TEST_FX)
            elif a in ("examples/quotes-fixture.json",):
                out.append(SAMPLE_FX)
            elif a == "ticker.png":
                out.append(os.path.join(self.tmp, "ticker.png"))
            else:
                out.append(a)
        return out

    def seed_for(self, cmd, cwd):
        script, args = cmd["script"], cmd["args"]
        if script == "watchlist.py" and args and args[0] in ("update", "remove", "show"):
            sym = args[1] if len(args) > 1 else "AAPL"
            extra = []
            if "--file" in args:
                i = args.index("--file")
                extra = ["--file", args[i + 1]]
            self.run_script("watchlist.py", ["add", sym, "--no-verify", *extra], cwd)
        elif script in ("alerts.py", "brief.py", "movers.py", "gappers.py"):
            if any(a in ("--watchlist", "--file") or a.startswith("--watchlist=") for a in args):
                return
            if cmd["env"].get("WATCHLIST_FILE"):
                return
            self.run_script("watchlist.py", ["init"], cwd)
            self.run_script("watchlist.py", ["add", "AAPL", "--no-verify"], cwd)

    def run_script(self, script, args, cwd, extra_env=None):
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        argv = [sys.executable, os.path.join(SCRIPTS, script), *self.rewrite_args(args, cwd)]
        return subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=25,
        )

    def run_doc(self, cmd, cwd_kind):
        cwd = self.cwd_for(cwd_kind)
        script, args = cmd["script"], list(cmd["args"])
        if script == "schedule.py" and "--dry-run" not in args:
            args = args + ["--dry-run"]
        if script == "quickstart.py" and "--live" in args:
            return None
        if script == "watchlist.py" and args[:1] == ["init"] and "--example" in args:
            # --example needs the bundled sample next to a clone / skill copy.
            cwd = self.skill
        extra = dict(cmd["env"])
        if extra.get("WATCHLIST_FILE") and not os.path.isabs(extra["WATCHLIST_FILE"]):
            extra["WATCHLIST_FILE"] = os.path.join(cwd, extra["WATCHLIST_FILE"])
            parent = os.path.dirname(extra["WATCHLIST_FILE"])
            if parent:
                os.makedirs(parent, exist_ok=True)
            if not os.path.exists(extra["WATCHLIST_FILE"]):
                wlm.save({"version": 1, "settings": {}, "tickers": []}, extra["WATCHLIST_FILE"])
        if extra.get("ALERT_STATE_FILE") and not os.path.isabs(extra["ALERT_STATE_FILE"]):
            extra["ALERT_STATE_FILE"] = os.path.join(cwd, extra["ALERT_STATE_FILE"])
        if extra.get("WATCHLIST_NOTIFY_FILE") == "/tmp/alerts.jsonl":
            extra["WATCHLIST_NOTIFY_FILE"] = os.path.join(self.tmp, "alerts.jsonl")
        seeded = dict(cmd)
        seeded["args"] = args
        seeded["env"] = extra
        self.seed_for(seeded, cwd)
        return self.run_script(script, args, cwd, extra_env=extra)


class DocsMatchCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flags, cls.commands = collect_cli()
        cls.docs = all_doc_commands()

    def test_every_documented_flag_exists(self):
        implemented = set()
        for fs in self.flags.values():
            implemented.update(fs)
        documented = all_doc_flags()
        unknown = {f for f in documented if f.lstrip("-") not in {x.lstrip("-") for x in implemented}}
        unknown = {f for f in unknown if f.lstrip("-") not in IGNORE_DOC_FLAGS}
        # argparse stores --list-presets as that exact string
        implemented_plain = {f.lstrip("-") for f in implemented}
        leftover = {f for f in documented if f.lstrip("-") not in implemented_plain
                    and f.lstrip("-") not in IGNORE_DOC_FLAGS}
        self.assertFalse(leftover, f"docs mention flags that are not on any CLI: {sorted(leftover)}")

    def test_every_documented_subcommand_exists(self):
        for cmd in self.docs:
            args = cmd["args"]
            if not args:
                continue
            if args[0].startswith("-"):
                continue
            allowed = self.commands.get(cmd["script"]) or set()
            if not allowed:
                continue
            self.assertIn(
                args[0], allowed,
                f"{cmd['source']}: {cmd['raw']} uses unknown {cmd['script']} command {args[0]!r}",
            )

    def test_extracted_documented_commands(self):
        scripts = {c["script"] for c in self.docs}
        self.assertIn("watchlist.py", scripts)
        self.assertIn("alerts.py", scripts)
        self.assertIn("brief.py", scripts)
        self.assertTrue(self.docs)


class FirstRunEmptyHome(unittest.TestCase):
    """Brand-new user in a temp HOME; fixture quotes; several working directories."""

    def test_documented_commands_run_from_empty_state(self):
        commands = all_doc_commands()
        self.assertGreaterEqual(len(commands), 10)
        failures = []
        for kind in ("project", "empty", "skill"):
            for cmd in commands:
                if cmd["script"] == "quickstart.py" and "--live" in cmd["args"]:
                    continue
                with FreshUser() as user:
                    proc = user.run_doc(cmd, kind)
                if proc is None:
                    continue
                if proc.returncode != 0:
                    failures.append(
                        f"{kind} {cmd['source']}: {cmd['raw']} -> {proc.returncode}\n"
                        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
                    )
        self.assertFalse(failures, "documented commands failed:\n" + "\n---\n".join(failures))

    def test_first_run_sequence_covers_new_flags(self):
        for kind in ("project", "empty", "skill"):
            with FreshUser() as user:
                cwd = user.cwd_for(kind)
                r = user.run_script("watchlist.py", ["init", "--list-presets"], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("mega-cap-tech", r.stdout)
                r = user.run_script("watchlist.py", ["init", "--preset", "mega-cap-tech"], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("AAPL", r.stdout)
                r = user.run_script(
                    "alerts.py",
                    ["--fixture", SAMPLE_FX, "--now", NOW, "--state",
                     os.path.join(user.tmp, "s.json")],
                    cwd,
                )
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                r = user.run_script(
                    "brief.py",
                    ["--fixture", SAMPLE_FX, "--kind", "close", "--now",
                     "2026-10-15T16:15:00-04:00"],
                    cwd,
                )
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                r = user.run_script("watchlist.py", ["add", "AMD", "--no-verify"], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                r = user.run_script("watchlist.py", ["add", "MSFT"], cwd)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn("already on watchlist", r.stderr)
                r = user.run_script("watchlist.py", ["add", "ZZZZ"], cwd)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("--no-verify", r.stderr)
                r = user.run_script("watchlist.py", ["add", "ZZZZ", "--no-verify"], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                r = user.run_script("quotes.py", ["AAPL", "NVDA"], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                r = user.run_script("chart.py", ["AAPL", "--fixture", SAMPLE_FX], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                r = user.run_script("market_calendar.py", [], cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                r = user.run_script("movers.py", ["--now", NOW], cwd)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                r = user.run_script("gappers.py", ["--threshold", "2", "--now", NOW], cwd)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                r = user.run_script("quickstart.py", [], cwd)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                r = user.run_script("schedule.py", ["--dry-run"], cwd)
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_every_preset_works_with_sample_fixture(self):
        for name, spec in wlm.PRESETS.items():
            with FreshUser() as user:
                cwd = user.cwd_for("project")
                r = user.run_script("watchlist.py", ["init", "--preset", name], cwd)
                self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")
                wl = wlm.load(os.path.join(cwd, "watchlist.json"))
                self.assertEqual(
                    [t["symbol"] for t in wl["tickers"]],
                    spec["symbols"],
                    name,
                )
                state = os.path.join(user.tmp, "state.json")
                r = user.run_script(
                    "alerts.py",
                    ["--fixture", SAMPLE_FX, "--now", NOW, "--state", state, "--dry-run"],
                    cwd,
                )
                self.assertEqual(r.returncode, 0, f"{name} alerts: {r.stderr}\n{r.stdout}")
                self.assertNotIn("ERROR no quotes", r.stderr)
                r = user.run_script(
                    "brief.py",
                    ["--fixture", SAMPLE_FX, "--kind", "morning", "--now",
                     "2026-10-15T08:30:00-04:00", "--format", "json"],
                    cwd,
                )
                self.assertEqual(r.returncode, 0, f"{name} brief: {r.stderr}\n{r.stdout}")
                self.assertNotIn("ERROR no quotes", r.stderr)
                for sym in spec["symbols"]:
                    q = qt.get_quote(sym, fixture=SAMPLE_FX)
                    self.assertEqual(q["symbol"], sym)


if __name__ == "__main__":
    unittest.main()
