"""In-memory application state built from one uploaded workbook."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

from .engine import acceptance_checks, compute
from .forecast import forecast_all
from .loader import load_dataset
from .quality import detect


def _fingerprint(pnl: dict) -> str:
    core = [(o["op_id"], round(o["revenue"], 6), round(o["fot"], 6), round(o["direct"], 6), round(o["overhead"], 6))
            for o in pnl["ops"]]
    return hashlib.sha256(json.dumps(core).encode()).hexdigest()[:16]


class AppState:
    def __init__(self, data: bytes, filename: str):
        self.ds = load_dataset(data, filename)
        self.pnl = compute(self.ds)
        self.checks = acceptance_checks(self.ds, self.pnl)
        self.quality = detect(self.ds)
        # Isolation proof: P&L recomputed with the raw-signal sheet removed must be identical.
        stripped = copy.copy(self.ds)
        stripped.signals = []
        same = _fingerprint(compute(stripped)) == _fingerprint(self.pnl)
        self.quality["pnl_isolated"] = same
        self.checks.append({"id": "signals", "title": "Сырые_сигналы базалық P&L-ге әсер етпейді",
                            "expected": _fingerprint(self.pnl), "actual": _fingerprint(compute(stripped)),
                            "diff": 0 if same else None, "tolerance": 0, "unit": "hash", "pass": same,
                            "detail": f"{self.quality['count']} аномалия табылды; P&L сигналдармен және сигналдарсыз бірдей"})
        self.forecast = forecast_all(self.ds)
        self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.size = len(data)
        self.sha = hashlib.sha256(data).hexdigest()[:12]

    def summary(self) -> dict:
        ds = self.ds
        warnings = [i for i in ds.issues if i["level"] == "warning"]
        return {
            "dataset": {"filename": ds.filename, "loaded_at": self.loaded_at, "size": self.size, "sha": self.sha,
                        "study_year": ds.study_year, "sheets": ds.sheets, "ops": len(ds.ops),
                        "teachers": len(ds.staff), "issues": ds.issues, "warnings": len(warnings)},
            "pnl": self.pnl, "checks": self.checks, "quality": self.quality, "forecast": self.forecast,
            "faculties": sorted({o["faculty"] for o in ds.ops.values()}),
        }
