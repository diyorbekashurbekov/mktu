"""HTTP server (stdlib only). Single-user demo: the uploaded workbook lives in memory."""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import analyst, insights, llm, scenario
from .loader import ValidationFailed
from .state import AppState
from .xlsx import XlsxError

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DEMO_FILE = ROOT / "data" / "Profitability_AI_Test_Data.xlsx"
MAX_UPLOAD = 10 * 1024 * 1024

_lock = threading.Lock()
_state: AppState | None = None


def load_demo() -> AppState:
    return AppState(DEMO_FILE.read_bytes(), DEMO_FILE.name)


def get_state() -> AppState:
    global _state
    with _lock:
        if _state is None:
            _state = load_demo()
        return _state


def set_state(state: AppState):
    global _state
    with _lock:
        _state = state


def _json_default(o):
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o).__name__)


class Handler(BaseHTTPRequestHandler):
    server_version = "ProfitabilityAI/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("PROFITAI_QUIET") != "1":
            super().log_message(fmt, *args)

    # -- helpers --------------------------------------------------------------
    def _send(self, code, body: bytes, ctype: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self, limit=64 * 1024) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ValueError("too_large")
        return self.rfile.read(length) if length else b""

    def _payload(self) -> dict:
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    # -- routes ---------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/api/state":
                st = get_state()
                return self._json(200, {**st.summary(), "llm": llm.status(), "examples": {
                    "kz": analyst.examples("kz"), "ru": analyst.examples("ru")}})
            if path == "/api/explain":
                st = get_state()
                op = q.get("op")
                if op not in st.ds.ops:
                    return self._json(404, {"error": "Белгісіз ОП"})
                return self._json(200, insights.explain(st.ds, st.pnl, op, q.get("lang", "kz")))
            if path == "/api/export.csv":
                return self._export()
            return self._static(path)
        except Exception as exc:  # pragma: no cover - defensive
            return self._json(500, {"error": f"Сервер қатесі: {exc}"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                return self._upload()
            if path == "/api/reset":
                set_state(load_demo())
                return self._json(200, {"ok": True})
            if path == "/api/ask":
                data = self._payload()
                return self._json(200, analyst.ask(get_state(), str(data.get("question", "")), data.get("op_id")))
            if path == "/api/scenario":
                data = self._payload()
                st = get_state()
                op = data.get("op_id")
                if op not in st.ds.ops:
                    return self._json(404, {"error": "Белгісіз ОП"})
                return self._json(200, scenario.run(st.ds, st.pnl, op, float(data.get("pct", 10)),
                                                    float(data.get("fot_var", 0)), float(data.get("direct_var", 0))))
            return self._json(404, {"error": "Табылмады"})
        except ValueError as exc:
            if str(exc) == "too_large":
                return self._json(413, {"error": "Сұраныс тым үлкен"})
            return self._json(400, {"error": f"Қате сұраныс: {exc}"})
        except Exception as exc:  # pragma: no cover
            return self._json(500, {"error": f"Сервер қатесі: {exc}"})

    def _upload(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return self._json(400, {"error": "Файл бос"})
        if length > MAX_UPLOAD:
            return self._json(413, {"error": "Файл 10 МБ-тан үлкен"})
        raw = self.rfile.read(length)
        name = unquote(self.headers.get("X-Filename") or "upload.xlsx")[:200]
        if not name.lower().endswith((".xlsx", ".xlsm")):
            return self._json(415, {"error": "Тек .xlsx файлы қабылданады"})
        try:
            st = AppState(raw, os.path.basename(name))
        except ValidationFailed as exc:
            return self._json(422, {"error": "Файл құрылымы талаптарға сай емес — алдыңғы деректер сақталды",
                                    "issues": exc.issues})
        except XlsxError as exc:
            return self._json(422, {"error": str(exc), "issues": []})
        set_state(st)
        return self._json(200, {"ok": True, "filename": st.ds.filename, "ops": len(st.ds.ops),
                                "warnings": sum(1 for i in st.ds.issues if i["level"] == "warning")})

    def _export(self):
        st = get_state()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["op_id", "название_ОП", "факультет", "студентов_активных", "доход", "ФОТ", "прямые", "накладные",
                    "итого_затраты", "фин_результат", "рентабельность_%", "себестоимость_студента"])
        for o in st.pnl["ops"]:
            w.writerow([o["op_id"], o["name"], o["faculty"], o["students"], f"{o['revenue']:.2f}", f"{o['fot']:.2f}",
                        f"{o['direct']:.2f}", f"{o['overhead']:.2f}", f"{o['total_cost']:.2f}", f"{o['result']:.2f}",
                        "н/д" if o["margin"] is None else f"{o['margin']:.2f}",
                        "н/д" if o["cost_per_student"] is None else f"{o['cost_per_student']:.2f}"])
        body = ("﻿" + buf.getvalue()).encode("utf-8")
        self._send(200, body, "text/csv; charset=utf-8",
                   {"Content-Disposition": 'attachment; filename="profitability_pnl.csv"'})

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else unquote(path).lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve() or not target.is_file():
            return self._json(404, {"error": "Табылмады"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def main():
    port = int(os.environ.get("PORT", "8010"))
    host = os.environ.get("HOST", "127.0.0.1")
    get_state()
    srv = ThreadingHTTPServer((host, port), Handler)
    mode = f"Claude ({llm.MODEL})" if llm.available() else "ережелік (офлайн)"
    print(f"Profitability AI: http://{host}:{port}  ·  ИИ режимі: {mode}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
