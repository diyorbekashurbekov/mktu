"""Bonus: next-year enrollment forecast from «История_набора» with honest uncertainty."""
from __future__ import annotations

import math
import re

T_80_DF1 = 3.078  # Student t, two-sided 80 %, df = n − 2 = 1


def _next_year(label: str) -> str:
    m = re.match(r"(\d{4})\D+(\d{4})", label or "")
    if not m:
        return "келесі жыл"
    return f"{int(m.group(1)) + 1}–{int(m.group(2)) + 1}"


def _linfit(ys):
    n = len(ys)
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    resid = [y - (icpt + slope * x) for x, y in zip(xs, ys)]
    return slope, icpt, resid, mx, sxx


def forecast_op(rows: list[dict]) -> dict | None:
    rows = sorted(rows, key=lambda r: r["year"])
    if len(rows) < 2:
        return None
    enrolled = [r["enrolled"] for r in rows]
    apps = [r["applications"] for r in rows]
    plan = [r["plan"] for r in rows]
    n = len(rows)
    slope, icpt, resid, mx, sxx = _linfit(enrolled)
    trend = icpt + slope * n
    conv = [e / a for e, a in zip(enrolled, apps) if a]
    avg_conv = sum(conv) / len(conv) if conv else None
    a_slope, a_icpt, *_ = _linfit(apps)
    apps_next = a_icpt + a_slope * n
    via_conv = apps_next * avg_conv if avg_conv else None
    naive = enrolled[-1]
    methods = {"trend": trend, "last": naive}
    if via_conv is not None:
        methods["applications_x_conversion"] = via_conv
    point = sum(methods.values()) / len(methods)

    interval = None
    if n >= 3:
        s = math.sqrt(sum(e * e for e in resid) / (n - 2)) if n > 2 else 0.0
        se = s * math.sqrt(1 + 1 / n + (n - mx) ** 2 / sxx)
        t = T_80_DF1 if n == 3 else 1.645
        interval = (trend - t * se, trend + t * se)
    lo = min(list(methods.values()) + ([interval[0]] if interval else []))
    hi = max(list(methods.values()) + ([interval[1]] if interval else []))
    lo = max(0.0, lo)
    return {
        "history": [{"year": r["year"], "applications": r["applications"], "enrolled": r["enrolled"],
                     "plan": r["plan"], "row": r["row"],
                     "plan_fill": (r["enrolled"] / r["plan"] * 100) if r["plan"] else None,
                     "conversion": (r["enrolled"] / r["applications"] * 100) if r["applications"] else None}
                    for r in rows],
        "next_year": _next_year(rows[-1]["year"]),
        "point": point, "low": lo, "high": hi,
        "methods": methods, "trend_interval_80": interval,
        "avg_conversion": avg_conv * 100 if avg_conv else None,
        "growth_per_year": slope,
        "spread_pct": (hi - lo) / point * 100 if point else None,
        "last_plan": plan[-1],
    }


def forecast_all(ds) -> dict:
    by_op = {}
    for r in ds.history:
        by_op.setdefault(r["op_id"], []).append(r)
    items = []
    for op_id, op in ds.ops.items():
        f = forecast_op(by_op.get(op_id, []))
        if f:
            items.append({"op_id": op_id, "name": op["name"], "faculty": op["faculty"], **f})
    return {
        "items": items,
        "method": ("Үш әдістің орташасы: (1) зачислено бойынша сызықтық тренд, (2) соңғы жыл мәні (наивті), "
                   "(3) өтінімдер тренді × орташа конверсия. Диапазон = әдістердің min–max мәні және трендтің 80% "
                   "болжам интервалы (t = 3,078, df = 1)."),
        "caveats": [
            "Тек 3 бақылау бар: сызықтық трендтің 2 параметрін бағалағаннан кейін еркіндік дәрежесі 1 ғана қалады — "
            "қалдық дисперсия іс жүзінде бағаланбайды, интервал өте кең.",
            "3 нүктеде маусымдылықты, құрылымдық үзілістерді (жаңа грант квотасы, демография, бәсекелестер) және "
            "кездейсоқ шуды ажырату мүмкін емес — бір «жақсы жыл» трендті толық өзгертеді.",
            "Өтінімдер мен конверсияның өзі тұрақсыз (Сырые_сигналы көрсеткендей, сыртқы көздерде қателер бар).",
            "Сенімді болжам үшін кемінде 5–7 жылдық қатар, айлық өтінім динамикасы, грант квоталары және "
            "демографиялық деректер қажет.",
        ],
    }
