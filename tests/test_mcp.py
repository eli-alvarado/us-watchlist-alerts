"""Stdlib MCP server: handshake, tools, fixture calls. No network."""
from __future__ import annotations
import io, json, os, subprocess, sys, tempfile, unittest
from unittest import mock

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

    def test_initialize_and_tools_list_do_not_fetch_quotes(self):
        """Glama introspection must work offline — catalog only, no Yahoo."""
        with mock.patch.object(mcp.qt, "get_quote", side_effect=AssertionError("quotes fetched")):
            with mock.patch.object(mcp.qt, "_get", side_effect=AssertionError("http")):
                init = mcp.handle({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "glama", "version": "0"}},
                })
                listed = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(init["result"]["serverInfo"]["name"], "us-watchlist-alerts")
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertIn("get_quotes", names)
        self.assertIn("gappers", names)

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

    def _assert_ndjson_replies(self, raw):
        """Every stdout byte must be one compact JSON-RPC line; no headers."""
        self.assertFalse(raw.startswith(b"Content-Length"), raw[:80])
        self.assertNotIn(b"Content-Length:", raw)
        self.assertTrue(raw.endswith(b"\n"), raw[-40:])
        lines = raw.split(b"\n")
        self.assertEqual(lines[-1], b"", "stdout must end with a trailing newline")
        bodies = []
        for line in lines[:-1]:
            self.assertTrue(line, "empty line on stdout")
            self.assertFalse(line.lower().startswith(b"content-length:"), line)
            self.assertNotIn(b"\r", line)
            msg = json.loads(line)
            self.assertIsInstance(msg, dict)
            self.assertEqual(msg.get("jsonrpc"), "2.0")
            self.assertEqual(line, json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode())
            bodies.append(msg)
        return bodies

    def test_write_message_is_one_compact_json_line(self):
        buf = io.BytesIO()
        mcp.write_message({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, buf)
        raw = buf.getvalue()
        self.assertEqual(raw, b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n')
        self.assertNotIn(b"Content-Length", raw)

    def test_read_message_still_accepts_content_length(self):
        body = b'{"jsonrpc":"2.0","id":9,"method":"ping"}'
        framed = b"Content-Length: %d\r\n\r\n" % len(body) + body
        msg = mcp.read_message(io.BytesIO(framed))
        self.assertEqual(msg["method"], "ping")
        self.assertEqual(msg["id"], 9)

    def test_serve_reads_headers_writes_ndjson(self):
        body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        framed = b"Content-Length: %d\r\n\r\n" % len(body) + body
        out = io.BytesIO()
        mcp.serve(io.BytesIO(framed), out)
        self.assertEqual(out.getvalue(), b'{"jsonrpc":"2.0","id":1,"result":{}}\n')

    def test_serve_prints_go_to_stderr(self):
        orig = mcp.handle

        def noisy(msg):
            print("debug from tool")
            return orig(msg)

        inp = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        out = io.BytesIO()
        err = io.StringIO()
        saved_err = sys.stderr
        mcp.handle = noisy
        try:
            sys.stderr = err
            mcp.serve(inp, out)
        finally:
            mcp.handle = orig
            sys.stderr = saved_err
        self.assertNotIn(b"debug from tool", out.getvalue())
        self.assertIn("debug from tool", err.getvalue())
        self.assertEqual(json.loads(out.getvalue()), {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_stdio_roundtrip(self):
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "market_status",
                        "arguments": {"when": "2026-10-15T10:00:00-04:00"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "get_quotes",
                        "arguments": {"symbols": ["AAPL"], "fixture": FX}}},
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown"},
        ]
        raw_in = "".join(json.dumps(r) + "\n" for r in reqs)
        proc = subprocess.run(
            [sys.executable, "-u", os.path.join(ROOT, "scripts", "mcp_server.py")],
            input=raw_in.encode(), cwd=ROOT, capture_output=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        bodies = self._assert_ndjson_replies(proc.stdout)
        ids = [b.get("id") for b in bodies]
        self.assertEqual(ids, [1, 2, 3, 4, 5])
        self.assertEqual(bodies[0]["result"]["serverInfo"]["name"], "us-watchlist-alerts")
        names = {t["name"] for t in bodies[1]["result"]["tools"]}
        self.assertIn("get_quotes", names)
        status = json.loads(bodies[2]["result"]["content"][0]["text"])
        self.assertEqual(status["session"], "regular")
        quote = json.loads(bodies[3]["result"]["content"][0]["text"])
        self.assertAlmostEqual(quote["AAPL"]["price"], 241.5)


if __name__ == "__main__":
    unittest.main()
