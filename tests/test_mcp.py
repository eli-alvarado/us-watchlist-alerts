"""Stdlib MCP server: handshake, tools, fixture calls. No network."""
from __future__ import annotations
import io, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mcp_server as mcp
import watchlist as wlm

FX = os.path.join(ROOT, "tests", "fixtures", "quotes.json")
WL = os.path.join(ROOT, "tests", "fixtures", "watchlist.json")
NOW = "2026-10-15T10:00:00-04:00"


def _call(name, **arguments):
    resp = mcp.handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    self_ok = resp.get("result") or {}
    text = (self_ok.get("content") or [{}])[0].get("text") or ""
    return resp, text, bool(self_ok.get("isError"))


class McpProtocol(unittest.TestCase):
    def test_initialize_and_tools_list(self):
        init = mcp.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}},
        })
        self.assertEqual(init["result"]["serverInfo"]["name"], "us-watchlist-alerts")
        self.assertEqual(init["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(mcp.handle({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }))
        listed = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertTrue({
            "get_quotes", "watchlist_list", "watchlist_add", "watchlist_remove",
            "run_alerts", "morning_brief", "market_status", "movers",
        } <= names)
        unknown = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(unknown["error"]["code"], -32601)

    def test_get_quotes_and_movers_fixture(self):
        resp, text, err = _call("get_quotes", symbols=["AAPL"], fixture=FX)
        self.assertFalse(err, text)
        q = json.loads(text)
        self.assertAlmostEqual(q["AAPL"]["price"], 241.5)
        resp, text, err = _call("movers", watchlist=WL, fixture=FX, now=NOW)
        self.assertFalse(err, text)
        payload = json.loads(text)
        self.assertEqual(payload["movers"][0]["symbol"], "TSLA")

    def test_gappers_and_market_status(self):
        resp, text, err = _call("gappers", watchlist=WL, fixture=FX, now=NOW, threshold=2)
        self.assertFalse(err, text)
        payload = json.loads(text)
        self.assertEqual([g["symbol"] for g in payload["gappers"]], ["TSLA"])
        resp, text, err = _call("market_status", when="2026-11-26")
        self.assertFalse(err, text)
        st = json.loads(text)
        self.assertEqual(st["session"], "closed")
        self.assertIn("Thanksgiving", st["holiday"] or "")

    def test_alerts_brief_and_watchlist_crud(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "wl.json")
        wlm.save({"version": 1, "settings": {}, "tickers": []}, path)
        resp, text, err = _call("watchlist_add", symbol="AMD", file=path, no_verify=True)
        self.assertFalse(err, text)
        self.assertEqual(json.loads(text)["symbol"], "AMD")
        resp, text, err = _call("watchlist_list", file=path)
        self.assertFalse(err, text)
        self.assertEqual([t["symbol"] for t in json.loads(text)["tickers"]], ["AMD"])
        resp, text, err = _call("watchlist_remove", symbol="AMD", file=path)
        self.assertFalse(err, text)
        self.assertIn("removed AMD", text)
        resp, text, err = _call(
            "run_alerts", watchlist=WL, fixture=FX, now=NOW, dry_run=True,
            state=os.path.join(d, "s.json"),
        )
        self.assertFalse(err, text)
        res = json.loads(text)
        self.assertFalse(res["skipped"])
        self.assertTrue(res["alerts"])
        resp, text, err = _call(
            "morning_brief", watchlist=WL, fixture=FX, kind="morning",
            now="2026-10-15T08:30:00-04:00", format="json",
        )
        self.assertFalse(err, text)
        brief = json.loads(text)
        self.assertEqual(brief["movers"][0]["symbol"], "TSLA")

    def test_unknown_tool(self):
        resp, text, err = _call("not_a_tool")
        self.assertTrue(err)
        self.assertIn("unknown tool", text)

    def test_stdio_roundtrip(self):
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "market_status", "arguments": {"when": "2026-10-15T10:00:00-04:00"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown"},
        ]
        raw = "".join(json.dumps(r) + "\n" for r in reqs)
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "mcp_server.py")],
            input=raw.encode(), cwd=ROOT, capture_output=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        bodies = []
        data = proc.stdout
        i = 0
        while i < len(data):
            if data[i:i + 15].lower().startswith(b"content-length:"):
                nl = data.find(b"\r\n\r\n", i)
                header = data[i:nl]
                length = int(header.split(b":", 1)[1])
                start = nl + 4
                bodies.append(json.loads(data[start:start + length]))
                i = start + length
                continue
            i += 1
        ids = [b.get("id") for b in bodies]
        self.assertIn(1, ids)
        self.assertIn(2, ids)
        self.assertIn(3, ids)
        listed = next(b for b in bodies if b.get("id") == 2)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertIn("get_quotes", names)
        status = next(b for b in bodies if b.get("id") == 3)
        payload = json.loads(status["result"]["content"][0]["text"])
        self.assertEqual(payload["session"], "regular")


if __name__ == "__main__":
    unittest.main()
