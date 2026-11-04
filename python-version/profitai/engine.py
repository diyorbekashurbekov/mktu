"""Deterministic P&L engine — implements the mandatory methodology of the case.

Доход ОП      = Σ(контракт_полный × тариф + контракт_со_скидкой × тариф × (1 − скидка) + грант × финансирование_грант)
ФОТ препод.   = зарплата_в_месяц × месяцев_оплаты × (1 + начисления)
Доля ФОТ на ОП = годовой ФОТ × часы на ОП / все часы преподавателя
Прямые        = Σ Прямые_затраты по op_id
Накладные     = Σ_центров сумма_центра × драйвер_ОП / Σ драйвер (12 ОП)
Итого         = ФОТ + прямые + накладные;  Результат = доход − итого
Рентабельность = результат / доход × 100 %;  Себестоимость = итого / активные студенты

Every number carries its source rows so the AI analyst can cite them.
"""
from __future__ import annotations

from collections import defaultdict

from .loader import Dataset

DRIVER_LABEL = {"students": "студентов_активных", "area_m2": "площадь_м2", "lab_hours": "лабораторные_часы"}


def safe_div(a, b):
    """None means «н/д» — never divide by zero."""
    return None if not b else a / b


def teacher_annual_fot(rec) -> float:
    return rec["salary"] * rec["months"] * (1 + rec["charges"])


def compute(ds: Dataset, factors: dict | None = None, fot_var: float = 0.0, direct_var: float = 0.0) -> dict:
    """Return the full P&L.

    `factors` ({op_id: multiplier}) switches on scenario mode: revenue and the
    `students` driver scale with the multiplier, ФОТ / прямые scale only by their
    declared variable share (0 in the base model), area / lab drivers stay fixed.
    """
    factors = factors or {}
    ops = {}
    for op_id, op in ds.ops.items():
        ops[op_id] = {
            "op_id": op_id, "name": op["name"], "faculty": op["faculty"], "level": op.get("level"),
            "years": op.get("years"), "source_row": op["row"],
            "paid_full": 0, "discounted": 0, "grant": 0,
            "revenue_full": 0.0, "revenue_discount": 0.0, "revenue_grant": 0.0,
            "revenue_rows": [], "teachers": [], "direct_rows": [], "overhead_rows": [],
            "fot": 0.0, "direct": 0.0, "overhead": 0.0, "teacher_hours": 0.0,
        }

    # 1. Revenue (Контингент)
    for r in ds.contingent:
        o = ops[r["op_id"]]
        full = r["full"] * r["tariff"]
        disc = r["disc"] * r["tariff"] * (1 - r["discount"])
        grant = r["grant"] * r["grant_fin"]
        o["paid_full"] += r["full"]
        o["discounted"] += r["disc"]
        o["grant"] += r["grant"]
        o["revenue_full"] += full
        o["revenue_discount"] += disc
        o["revenue_grant"] += grant
        o["revenue_rows"].append({"row": r["row"], "course": r["course"], "full": r["full"], "disc": r["disc"],
                                  "grant": r["grant"], "tariff": r["tariff"], "grant_fin": r["grant_fin"],
                                  "discount": r["discount"], "revenue": full + disc + grant})

    # 2. ФОТ (Штат_ППС × доля часов из Нагрузка_ППС)
    hours_by_teacher = defaultdict(float)
    for r in ds.load:
        hours_by_teacher[r["teacher_id"]] += r["hours"]
    total_staff_fot = sum(teacher_annual_fot(t) for t in ds.staff.values())
    unallocated_fot = sum(teacher_annual_fot(t) for tid, t in ds.staff.items() if not hours_by_teacher.get(tid))
    per_op_teacher = defaultdict(lambda: defaultdict(lambda: {"hours": 0.0, "rows": []}))
    for r in ds.load:
        slot = per_op_teacher[r["op_id"]][r["teacher_id"]]
        slot["hours"] += r["hours"]
        slot["rows"].append(r["row"])
    for op_id, teachers in per_op_teacher.items():
        o = ops[op_id]
        for tid, slot in sorted(teachers.items()):
            t = ds.staff[tid]
            annual = teacher_annual_fot(t)
            share = slot["hours"] / hours_by_teacher[tid]
            o["fot"] += annual * share
            o["teacher_hours"] += slot["hours"]
            o["teachers"].append({"teacher_id": tid, "staff_row": t["row"], "load_rows": slot["rows"],
                                  "salary": t["salary"], "months": t["months"], "charges": t["charges"],
                                  "annual_fot": annual, "hours_op": slot["hours"],
                                  "hours_total": hours_by_teacher[tid], "share": share,
                                  "allocated": annual * share, "shared": share < 1})

    # 3. Прямые затраты
    for r in ds.direct:
        o = ops[r["op_id"]]
        o["direct"] += r["amount"]
        o["direct_rows"].append({"row": r["row"], "cost_id": r["cost_id"], "category": r["category"],
                                 "amount": r["amount"]})

    # Scenario multipliers on revenue / ФОТ / прямые (base model: ФОТ & прямые fixed)
    for op_id, f in factors.items():
        o = ops[op_id]
        o["scenario_factor"] = f
        for k in ("revenue_full", "revenue_discount", "revenue_grant"):
            o[k] *= f
        for k in ("paid_full", "discounted", "grant"):
            o[k] *= f
        o["fot"] *= 1 + (f - 1) * fot_var
        o["direct"] *= 1 + (f - 1) * direct_var

    # 4. Накладные — драйверы (students scaled in scenario, area / lab fixed)
    drivers = {}
    for op_id in ops:
        d = ds.drivers.get(op_id)
        drivers[op_id] = {
            "students": (d["students"] if d else 0) * factors.get(op_id, 1.0),
            "area_m2": d["area_m2"] if d else 0,
            "lab_hours": d["lab_hours"] if d else 0,
            "row": d["row"] if d else None,
        }
    driver_totals = {k: sum(v[k] for v in drivers.values()) for k in DRIVER_LABEL}
    total_overhead_pool = sum(c["amount"] for c in ds.overhead)
    unallocated_oh = 0.0
    for c in ds.overhead:
        key = c["driver_key"]
        total = driver_totals[key]
        if not total:
            unallocated_oh += c["amount"]
            continue
        for op_id, o in ops.items():
            share = drivers[op_id][key] / total
            alloc = c["amount"] * share
            o["overhead"] += alloc
            o["overhead_rows"].append({"row": c["row"], "center_id": c["center_id"], "name": c["name"],
                                       "amount": c["amount"], "driver": key, "driver_label": DRIVER_LABEL[key],
                                       "op_driver": drivers[op_id][key], "total_driver": total,
                                       "share": share, "allocated": alloc})

    # 5. Totals per ОП
    rows = []
    for op_id, o in ops.items():
        o["students"] = drivers[op_id]["students"]
        o["students_contingent"] = o["paid_full"] + o["discounted"] + o["grant"]
        o["area_m2"] = drivers[op_id]["area_m2"]
        o["lab_hours"] = drivers[op_id]["lab_hours"]
        o["driver_row"] = drivers[op_id]["row"]
        o["revenue"] = o["revenue_full"] + o["revenue_discount"] + o["revenue_grant"]
        o["total_cost"] = o["fot"] + o["direct"] + o["overhead"]
        o["result"] = o["revenue"] - o["total_cost"]
        o["margin"] = None if not o["revenue"] else o["result"] / o["revenue"] * 100
        o["cost_per_student"] = safe_div(o["total_cost"], o["students"])
        o["revenue_per_student"] = safe_div(o["revenue"], o["students"])
        o["fot_per_student"] = safe_div(o["fot"], o["students"])
        o["direct_per_student"] = safe_div(o["direct"], o["students"])
        o["overhead_per_student"] = safe_div(o["overhead"], o["students"])
        o["result_per_student"] = safe_div(o["result"], o["students"])
        o["hours_per_student"] = safe_div(o["teacher_hours"], o["students"])
        o["fot_per_hour"] = safe_div(o["fot"], o["teacher_hours"])
        o["grant_share"] = safe_div(o["grant"], o["students_contingent"])
        o["paid_share"] = safe_div(o["paid_full"] + o["discounted"], o["students_contingent"])
        tariffs = [r["tariff"] for r in o["revenue_rows"]]
        o["tariff"] = max(tariffs) if tariffs else None
        o["grant_fin"] = max((r["grant_fin"] for r in o["revenue_rows"]), default=None)
        o["discount_rate"] = max((r["discount"] for r in o["revenue_rows"]), default=None)
        o["shared_teachers"] = sum(1 for t in o["teachers"] if t["shared"])
        o["status"] = "loss" if o["result"] < 0 else "profit"
        rows.append(o)

    tot = {k: sum(o[k] for o in rows) for k in
           ("revenue", "fot", "direct", "overhead", "total_cost", "result", "students", "teacher_hours",
            "paid_full", "discounted", "grant", "revenue_full", "revenue_discount", "revenue_grant")}
    tot["margin"] = None if not tot["revenue"] else tot["result"] / tot["revenue"] * 100
    tot["cost_per_student"] = safe_div(tot["total_cost"], tot["students"])
    tot["revenue_per_student"] = safe_div(tot["revenue"], tot["students"])
    tot["fot_per_student"] = safe_div(tot["fot"], tot["students"])
    tot["direct_per_student"] = safe_div(tot["direct"], tot["students"])
    tot["overhead_per_student"] = safe_div(tot["overhead"], tot["students"])
    tot["hours_per_student"] = safe_div(tot["teacher_hours"], tot["students"])
    tot["fot_per_hour"] = safe_div(tot["fot"], tot["teacher_hours"])
    tot["grant_share"] = safe_div(tot["grant"], tot["paid_full"] + tot["discounted"] + tot["grant"])
    tot["loss_count"] = sum(1 for o in rows if o["result"] < 0)
    tot["op_count"] = len(rows)
    tot["staff_fot"] = total_staff_fot
    tot["unallocated_fot"] = unallocated_fot
    tot["overhead_pool"] = total_overhead_pool
    tot["unallocated_overhead"] = unallocated_oh
    tot["teachers"] = len(ds.staff)

    return {"ops": rows, "totals": tot, "driver_totals": driver_totals,
            "scenario": {"factors": factors, "fot_var": fot_var, "direct_var": direct_var} if factors else None}


def acceptance_checks(ds: Dataset, pnl: dict) -> list[dict]:
    """The case's acceptance tests, evaluated on the live data."""
    t = pnl["totals"]
    checks = []

    def add(cid, title, expected, actual, tol, unit, detail):
        diff = None if expected is None or actual is None else actual - expected
        ok = diff is not None and abs(diff) <= tol
        checks.append({"id": cid, "title": title, "expected": expected, "actual": actual, "diff": diff,
                       "tolerance": tol, "unit": unit, "pass": ok, "detail": detail})

    add("ops", "Барлық ОП жүктелді", len(ds.ops), len(pnl["ops"]), 0, "ОП",
        "ОП парағындағы бағдарламалар саны = есептелген бағдарламалар саны")
    add("fot", "Бөлінген ФОТ = барлық оқытушылардың жылдық ФОТ-ы", t["staff_fot"], t["fot"], 1, "₸",
        "Σ(жалақы × ай × (1 + аударымдар)) Штат_ППС бойынша, Σ ОП-ға бөлінген ФОТ-пен салыстырылады")
    add("overhead", "Бөлінген жанама шығын = Общие_затраты сомасы", t["overhead_pool"], t["overhead"], 1, "₸",
        "Әр орталық драйвер бойынша 12 ОП арасында толық бөлінеді (күтілетін: 500 000 000 ₸)")
    mism = [i for i in ds.issues if i["code"] == "crosscheck"]
    add("students", "Контингент = Драйверы.студентов_активных", 0, len(mism), 0, "сәйкессіздік",
        "Әр ОП үшін курстар бойынша студенттер саны драйвер парағымен сәйкес")
    margin_ok = all(o["margin"] is None or abs(o["margin"] - o["result"] / o["revenue"] * 100) < 1e-9
                    for o in pnl["ops"])
    add("identity", "Нәтиже = Кіріс − (ФОТ + тікелей + жанама)", 0,
        max(abs(o["result"] - (o["revenue"] - o["fot"] - o["direct"] - o["overhead"])) for o in pnl["ops"]),
        1, "₸", "Әр ОП бойынша теңдік тексерілді; рентабельділік формуласы: " + ("OK" if margin_ok else "қате"))
    return checks
