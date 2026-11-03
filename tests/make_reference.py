"""
Тәуелсіз эталон: Excel-ді openpyxl арқылы оқып, кейс әдістемесін Python-да қайта есептейді.
Нәтиже: tests/fixture.json (парақтар, Excel жол нөмірімен) және tests/reference.json (дұрыс жауаптар).
Іске қосу:  python tests/make_reference.py data/Profitability_AI_Test_Data.xlsx
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

src = Path(sys.argv[1])
out = Path(__file__).resolve().parent
wb = openpyxl.load_workbook(src, data_only=True)

fixture = {}
for ws in wb.worksheets:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        continue
    head = [str(h).strip() if h is not None else "" for h in rows[0]]
    items = []
    for i, r in enumerate(rows[1:], start=2):
        if all(v is None for v in r):
            continue
        o = {h: v for h, v in zip(head, r) if h}
        o["_row"] = i
        items.append(o)
    fixture[ws.title] = items


def sheet(name):
    return fixture[name]


ops = [o["op_id"] for o in sheet("ОП")]
rev = defaultdict(float)
for c in sheet("Контингент"):
    t = c["тариф_контракт_тг"]
    rev[c["op_id"]] += (c["контракт_полный"] * t
                        + c["контракт_со_скидкой"] * t * (1 - c["скидка_доля"])
                        + c["грант"] * c["финансирование_грант_тг"])

staff = {t["teacher_id"]: t for t in sheet("Штат_ППС")}
annual = {k: t["зарплата_в_месяц_тг"] * t["месяцев_оплаты"] * (1 + t["начисления_работодателя_доля"]) for k, t in staff.items()}
hours = defaultdict(float)
for l in sheet("Нагрузка_ППС"):
    hours[l["teacher_id"]] += l["часы_в_год"]
fot = defaultdict(float)
for l in sheet("Нагрузка_ППС"):
    fot[l["op_id"]] += annual[l["teacher_id"]] * l["часы_в_год"] / hours[l["teacher_id"]]

direct = defaultdict(float)
for d in sheet("Прямые_затраты"):
    direct[d["op_id"]] += d["сумма_в_год_тг"]

drv = {d["op_id"]: d for d in sheet("Драйверы")}
key = {"students": "студентов_активных", "area_m2": "площадь_м2", "lab_hours": "лабораторные_часы"}


def overhead(students_factor=None):
    students_factor = students_factor or {}
    oh = defaultdict(float)
    for c in sheet("Общие_затраты"):
        k = key[c["драйвер_распределения"]]
        val = {o: drv[o][k] * (students_factor.get(o, 1) if k == "студентов_активных" else 1) for o in ops}
        tot = sum(val.values())
        for o in ops:
            oh[o] += c["сумма_в_год_тг"] * val[o] / tot
    return oh


def pnl(op_id=None, pct=0):
    f = {op_id: 1 + pct / 100} if op_id else {}
    oh = overhead(f)
    res = {}
    for o in ops:
        r = rev[o] * f.get(o, 1)
        total = fot[o] + direct[o] + oh[o]
        st = drv[o]["студентов_активных"] * f.get(o, 1)
        res[o] = {
            "revenue": r, "fot": fot[o], "direct": direct[o], "overhead": oh[o], "total": total,
            "result": r - total, "margin": (r - total) / r * 100 if r else None,
            "cps": total / st if st else None,
        }
    return res


reference = {
    "base": pnl(),
    "fot_annual_total": sum(annual.values()),
    "overhead_total": sum(c["сумма_в_год_тг"] for c in sheet("Общие_затраты")),
    "scenario_OP004_plus10": pnl("OP-004", 10),
    "scenario_OP012_minus10": pnl("OP-012", -10),
    "expected_anomaly_rows": ["SRC-004", "SRC-901", "SRC-902", "SRC-903", "SRC-904", "SRC-905"],
}

(out / "fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
(out / "reference.json").write_text(json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8")
print("fixture и reference жазылды:", len(fixture), "парақ")
