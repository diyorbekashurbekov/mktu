"""«What if» — change the contingent of one ОП and recompute the whole university."""
from __future__ import annotations

from .engine import compute

METRICS = ("revenue", "fot", "direct", "overhead", "total_cost", "result", "margin", "cost_per_student", "students")


def assumptions(pct: float, fot_var: float, direct_var: float) -> list[str]:
    sign = "+" if pct >= 0 else "−"
    a = [
        f"Таңдалған ОП-ның барлық курстарындағы контингент {sign}{abs(pct):g}% өзгереді; толық ақылы, жеңілдікті және "
        "грант студенттерінің арақатынасы сақталады (әр санат бірдей пайызға өзгереді).",
        "Тарифтер, жеңілдік үлесі және грант қаржыландыруы өзгермейді → кіріс студенттер санына пропорционал.",
        ("ФОТ өзгермейді (базалық модель: оқытушылар штаты мен жүктемесі тұрақты)." if not fot_var else
         f"ФОТ-тың {fot_var * 100:g}%-ы айнымалы деп есептеледі: ФОТ × (1 + Δ × {fot_var:g})."),
        ("Тікелей шығындар өзгермейді (базалық модель)." if not direct_var else
         f"Тікелей шығындардың {direct_var * 100:g}%-ы айнымалы: тікелей × (1 + Δ × {direct_var:g})."),
        "Жанама шығын орталықтарының жалпы сомасы өзгермейді (500 млн ₸ сақталады), бірақ students драйвері бар "
        "орталықтар жаңартылған студенттер саны бойынша барлық 12 ОП арасында қайта бөлінеді.",
        "area_m2 және lab_hours драйверлері өзгермейді.",
        "Студенттер саны бөлшек болуы мүмкін (дөңгелектеусіз) — бұл модельдік есеп, нақты қабылдау жоспары емес.",
    ]
    return a


def run(ds, base: dict, op_id: str, pct: float, fot_var: float = 0.0, direct_var: float = 0.0) -> dict:
    if op_id not in ds.ops:
        raise KeyError(op_id)
    pct = max(-90.0, min(300.0, float(pct)))
    fot_var = max(0.0, min(1.0, float(fot_var)))
    direct_var = max(0.0, min(1.0, float(direct_var)))
    factor = 1 + pct / 100
    new = compute(ds, {op_id: factor}, fot_var=fot_var, direct_var=direct_var)
    before = {o["op_id"]: o for o in base["ops"]}
    after = {o["op_id"]: o for o in new["ops"]}

    def pick(o):
        return {k: o[k] for k in METRICS}

    rows = []
    for oid, b in before.items():
        a = after[oid]
        rows.append({"op_id": oid, "name": b["name"], "faculty": b["faculty"], "selected": oid == op_id,
                     "before": pick(b), "after": pick(a),
                     "delta": {k: (None if a[k] is None or b[k] is None else a[k] - b[k]) for k in METRICS}})
    sel = next(r for r in rows if r["selected"])
    others_delta = sum(r["delta"]["result"] for r in rows if not r["selected"])
    tb, ta = base["totals"], new["totals"]
    return {
        "op_id": op_id, "name": ds.ops[op_id]["name"], "pct": pct, "factor": factor,
        "fot_var": fot_var, "direct_var": direct_var,
        "assumptions": assumptions(pct, fot_var, direct_var),
        "selected": sel, "rows": rows,
        "others_result_delta": others_delta,
        "totals": {"before": {k: tb[k] for k in ("revenue", "total_cost", "result", "margin", "overhead", "students")},
                   "after": {k: ta[k] for k in ("revenue", "total_cost", "result", "margin", "overhead", "students")}},
        "overhead_preserved": abs(ta["overhead"] - tb["overhead"]) < 1,
        "break_even": break_even(ds, op_id, fot_var, direct_var),
    }


def break_even(ds, op_id: str, fot_var: float = 0.0, direct_var: float = 0.0) -> dict:
    """Contingent change at which the ОП result reaches 0 (same model as the scenario)."""
    def res(f):
        out = compute(ds, {op_id: f}, fot_var=fot_var, direct_var=direct_var)
        return next(o for o in out["ops"] if o["op_id"] == op_id)["result"]

    r1 = res(1.0)
    if abs(r1) < 1:
        return {"reachable": True, "pct": 0.0, "students": None}
    lo, hi = (1.0, 10.0) if r1 < 0 else (0.0001, 1.0)
    if r1 < 0 and res(hi) < 0:
        return {"reachable": False, "pct": None,
                "note": "Контингентті 10 есеге дейін өсіргенде де нәтиже теріс — тек санмен шешілмейді."}
    for _ in range(60):
        mid = (lo + hi) / 2
        if (res(mid) < 0) == (r1 < 0):
            lo = mid
        else:
            hi = mid
    f = (lo + hi) / 2
    students = (ds.drivers.get(op_id) or {}).get("students", 0)
    return {"reachable": True, "pct": (f - 1) * 100, "students": students * f, "base_students": students}
