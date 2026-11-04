"""HTTP API end-to-end: upload → state → ask → scenario → export."""
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from helpers import demo_bytes, demo_sheets, make_xlsx

os.environ["PROFITAI_QUIET"] = "1"
os.environ["PROFITAI_LLM"] = "off"
from profitai import server  # noqa: E402


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, path, data=None, headers=None, method=None):
        r = urllib.request.Request(self.base + path, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def jpost(self, path, payload):
        code, body, _ = self.req(path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        return code, json.loads(body)

    def test_flow(self):
        code, body, _ = self.req("/api/upload", demo_bytes(), {"X-Filename": "Profitability_AI_Test_Data.xlsx"})
        self.assertEqual(code, 200, body)
        code, body, _ = self.req("/api/state")
        st = json.loads(body)
        self.assertEqual(len(st["pnl"]["ops"]), 12)
        self.assertEqual(st["quality"]["count"], 6)
        self.assertTrue(all(c["pass"] for c in st["checks"]))
        code, a = self.jpost("/api/ask", {"question": "Какие ОП убыточны?"})
        self.assertEqual(code, 200)
        self.assertEqual(a["op_ids"], ["OP-004", "OP-007", "OP-011"])
        code, sc = self.jpost("/api/scenario", {"op_id": "OP-001", "pct": 10})
        self.assertEqual(code, 200)
        self.assertTrue(sc["overhead_preserved"])
        code, ex, _ = self.req("/api/explain?op=OP-004&lang=ru")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(len(json.loads(ex)["options"]), 2)
        code, csv_body, headers = self.req("/api/export.csv")
        self.assertEqual(code, 200)
        self.assertIn("OP-012", csv_body.decode("utf-8-sig"))

    def test_invalid_upload_keeps_previous_state(self):
        sheets = demo_sheets()
        del sheets["Драйверы"]
        code, body, _ = self.req("/api/upload", make_xlsx(sheets), {"X-Filename": "broken.xlsx"})
        self.assertEqual(code, 422)
        self.assertTrue(json.loads(body)["issues"])
        code, body, _ = self.req("/api/state")
        self.assertEqual(len(json.loads(body)["pnl"]["ops"]), 12)

    def test_rejects_non_xlsx(self):
        code, _, _ = self.req("/api/upload", b"abc", {"X-Filename": "x.csv"})
        self.assertEqual(code, 415)
        code, _, _ = self.req("/api/upload", b"abc", {"X-Filename": "x.xlsx"})
        self.assertEqual(code, 422)

    def test_static_and_traversal(self):
        code, body, _ = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Profitability AI", body)
        code, _, _ = self.req("/../profitai/server.py")
        self.assertEqual(code, 404)

    def test_unknown_op(self):
        code, _ = self.jpost("/api/scenario", {"op_id": "OP-999", "pct": 10})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
