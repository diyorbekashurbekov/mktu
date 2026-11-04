"""Workbook -> validated Dataset.

Structure check (sheets, columns), type check per row, referential integrity.
A bad row in a P&L sheet is excluded with a warning instead of breaking the
calculation; the raw-signal sheet is kept aside and never enters the P&L.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .xlsx import read_workbook

TEXT, INT, NUM, SHARE = "text", "int", "num", "share"

# sheet key -> (expected sheet name, [(field, header, type, required)])
SCHEMA = {
    "ops": ("ОП", [
        ("op_id", "op_id", TEXT, True),
        ("name", "название_ОП", TEXT, True),
        ("faculty", "факультет", TEXT, True),
        ("level", "уровень", TEXT, False),
        ("years", "срок_обучения_лет", INT, False),
        ("study_year", "учебный_год", TEXT, False),
    ]),
    "contingent": ("Контингент", [
        ("op_id", "op_id", TEXT, True),
        ("course", "курс", INT, True),
        ("full", "контракт_полный", INT, True),
        ("disc", "контракт_со_скидкой", INT, True),
        ("grant", "грант", INT, True),
        ("tariff", "тариф_контракт_тг", NUM, True),
        ("grant_fin", "финансирование_грант_тг", NUM, True),
        ("discount", "скидка_доля", SHARE, True),
    ]),
    "staff": ("Штат_ППС", [
        ("teacher_id", "teacher_id", TEXT, True),
        ("name", "имя_условное", TEXT, False),
        ("salary", "зарплата_в_месяц_тг", NUM, True),
        ("months", "месяцев_оплаты", NUM, True),
        ("charges", "начисления_работодателя_доля", SHARE, True),
    ]),
    "load": ("Нагрузка_ППС", [
        ("teacher_id", "teacher_id", TEXT, True),
        ("op_id", "op_id", TEXT, True),
        ("hours", "часы_в_год", NUM, True),
        ("desc", "описание", TEXT, False),
    ]),
    "direct": ("Прямые_затраты", [
        ("cost_id", "cost_id", TEXT, True),
        ("op_id", "op_id", TEXT, True),
        ("category", "категория", TEXT, True),
        ("amount", "сумма_в_год_тг", NUM, True),
        ("note", "примечание", TEXT, False),
    ]),
    "overhead": ("Общие_затраты", [
        ("center_id", "cost_center_id", TEXT, True),
        ("name", "статья", TEXT, True),
        ("amount", "сумма_в_год_тг", NUM, True),
        ("driver", "драйвер_распределения", TEXT, True),
    ]),
    "drivers": ("Драйверы", [
        ("op_id", "op_id", TEXT, True),
        ("students", "студентов_активных", NUM, True),
        ("area_m2", "площадь_м2", NUM, True),
        ("lab_hours", "лабораторные_часы", NUM, True),
    ]),
    "history": ("История_набора", [
        ("op_id", "op_id", TEXT, True),
        ("year", "учебный_год", TEXT, True),
        ("applications", "заявок", NUM, True),
        ("enrolled", "зачислено", NUM, True),
        ("plan", "план_набора", NUM, True),
    ]),
    "signals": ("Сырые_сигналы", [
        ("source_row_id", "source_row_id", TEXT, False),
        ("op_id", "op_id", TEXT, False),
        ("metric", "показатель", TEXT, False),
        ("year", "учебный_год", TEXT, False),
        ("value", "значение", None, False),
        ("comment", "источник_комментарий", TEXT, False),
    ]),
}
OPTIONAL_SHEETS = {"history", "signals"}
# normalized driver name -> Драйверы field (students ↔ студентов_активных, area_m2 ↔ площадь_м2, lab_hours ↔ лабораторные_часы)
DRIVER_KEYS = {"students": "students", "aream2": "area_m2", "labhours": "lab_hours"}


def _norm(text) -> str:
    return re.sub(r"[\s_\-–—]+", "", str(text or "")).casefold().replace("ё", "е")


@dataclass
class Dataset:
    filename: str
    ops: dict = field(default_factory=dict)
    contingent: list = field(default_factory=list)
    staff: dict = field(default_factory=dict)
    load: list = field(default_factory=list)
    direct: list = field(default_factory=list)
    overhead: list = field(default_factory=list)
    drivers: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    sheets: dict = field(default_factory=dict)  # key -> {"name", "rows", "valid"}
    study_year: str = ""

    @property
    def blocking(self) -> list:
        return [i for i in self.issues if i["level"] == "error"]


class ValidationFailed(Exception):
    def __init__(self, issues):
        super().__init__("; ".join(i["message"] for i in issues if i["level"] == "error"))
        self.issues = issues


def _issue(level, sheet, message, row=None, column=None, code="schema"):
    return {"level": level, "sheet": sheet, "row": row, "column": column, "message": message, "code": code}


def _coerce(value, kind):
    """Return (value, error_text)."""
    if kind is None:
        return value, None
    if value is None:
        return None, "бос мән"
    if kind == TEXT:
        return str(value).strip(), None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(str(value).replace(" ", "").replace(",", "."))
        except ValueError:
            return None, f"сан емес: «{value}»"
    if value < 0:
        return None, f"теріс мән: {value}"
    if kind == SHARE and value > 1:
        return None, f"үлес 0..1 аралығында болуы керек: {value}"
    if kind == INT:
        if float(value) != int(value):
            return None, f"бүтін сан болуы керек: {value}"
        return int(value), None
    return float(value) if isinstance(value, float) else value, None


def load_dataset(data: bytes, filename: str = "workbook.xlsx") -> Dataset:
    book = read_workbook(data)
    ds = Dataset(filename=filename)
    by_norm = {_norm(name): name for name in book}

    parsed: dict[str, list[dict]] = {}
    for key, (sheet_name, fields) in SCHEMA.items():
        actual = by_norm.get(_norm(sheet_name))
        if actual is None:
            level = "warning" if key in OPTIONAL_SHEETS else "error"
            ds.issues.append(_issue(level, sheet_name, f"«{sheet_name}» парағы табылмады"))
            parsed[key] = []
            continue
        rows = book[actual]
        if not rows:
            ds.issues.append(_issue("error" if key not in OPTIONAL_SHEETS else "warning", sheet_name, "Парақ бос"))
            parsed[key] = []
            continue
        header = [_norm(c) for c in rows[0]["cells"]]
        colmap = {}
        for fname, title, kind, required in fields:
            if _norm(title) in header:
                colmap[fname] = header.index(_norm(title))
            elif required:
                ds.issues.append(_issue("error", sheet_name, f"Міндетті «{title}» бағаны жоқ", column=title))
        out = []
        for raw in rows[1:]:
            cells = raw["cells"]
            rec = {"row": raw["row"]}
            bad = []
            for fname, title, kind, required in fields:
                if fname not in colmap:
                    rec[fname] = None
                    continue
                idx = colmap[fname]
                value = cells[idx] if idx < len(cells) else None
                if key == "signals":
                    rec[fname] = value
                    continue
                coerced, err = _coerce(value, kind)
                if err and (required or value is not None):
                    bad.append(f"{title}: {err}")
                rec[fname] = coerced
            if bad:
                ds.issues.append(_issue("warning", sheet_name,
                                        "Жол есептен шығарылды — " + "; ".join(bad),
                                        row=raw["row"], code="row_excluded"))
                continue
            out.append(rec)
        ds.sheets[key] = {"name": actual, "rows": len(rows) - 1, "valid": len(out)}
        parsed[key] = out

    if ds.blocking:
        raise ValidationFailed(ds.issues)

    # --- reference data and integrity ---------------------------------------
    for rec in parsed["ops"]:
        if rec["op_id"] in ds.ops:
            ds.issues.append(_issue("warning", "ОП", f"{rec['op_id']} қайталанады — бірінші жол қолданылды",
                                    row=rec["row"], code="duplicate"))
            continue
        ds.ops[rec["op_id"]] = rec
        ds.study_year = ds.study_year or (rec.get("study_year") or "")
    if not ds.ops:
        raise ValidationFailed(ds.issues + [_issue("error", "ОП", "Бірде-бір жарамды ОП жоқ")])

    def known_op(rec, sheet):
        if rec["op_id"] in ds.ops:
            return True
        ds.issues.append(_issue("warning", sheet, f"Белгісіз op_id «{rec['op_id']}» — жол есептен шығарылды",
                                row=rec["row"], code="unknown_op"))
        return False

    ds.contingent = [r for r in parsed["contingent"] if known_op(r, "Контингент")]
    for rec in parsed["staff"]:
        if rec["teacher_id"] in ds.staff:
            ds.issues.append(_issue("warning", "Штат_ППС", f"{rec['teacher_id']} қайталанады — бірінші жол қолданылды",
                                    row=rec["row"], code="duplicate"))
            continue
        ds.staff[rec["teacher_id"]] = rec
    for rec in parsed["load"]:
        if not known_op(rec, "Нагрузка_ППС"):
            continue
        if rec["teacher_id"] not in ds.staff:
            ds.issues.append(_issue("warning", "Нагрузка_ППС",
                                    f"{rec['teacher_id']} Штат_ППС ішінде жоқ — сағаттар бөлінбейді",
                                    row=rec["row"], code="unknown_teacher"))
            continue
        ds.load.append(rec)
    ds.direct = [r for r in parsed["direct"] if known_op(r, "Прямые_затраты")]
    for rec in parsed["overhead"]:
        drv = DRIVER_KEYS.get(_norm(rec["driver"]))
        if drv is None:
            ds.issues.append(_issue("error", "Общие_затраты", f"Белгісіз драйвер «{rec['driver']}»",
                                    row=rec["row"], code="driver"))
            continue
        rec["driver_key"] = drv
        ds.overhead.append(rec)
    for rec in parsed["drivers"]:
        if known_op(rec, "Драйверы"):
            ds.drivers[rec["op_id"]] = rec
    ds.history = [r for r in parsed["history"] if r["op_id"] in ds.ops]
    ds.signals = parsed["signals"]

    if ds.blocking:
        raise ValidationFailed(ds.issues)

    # --- completeness / cross-checks ----------------------------------------
    for op_id in ds.ops:
        if op_id not in ds.drivers:
            ds.issues.append(_issue("warning", "Драйверы", f"{op_id} үшін драйвер жоқ — жанама шығын 0", code="missing"))
        if not any(r["op_id"] == op_id for r in ds.contingent):
            ds.issues.append(_issue("warning", "Контингент", f"{op_id} үшін контингент жоқ — кіріс 0", code="missing"))
    for op_id, drv in ds.drivers.items():
        counted = sum(r["full"] + r["disc"] + r["grant"] for r in ds.contingent if r["op_id"] == op_id)
        if counted != drv["students"]:
            ds.issues.append(_issue("warning", "Драйверы",
                                    f"{op_id}: студентов_активных={drv['students']}, ал Контингент бойынша {counted}",
                                    row=drv["row"], code="crosscheck"))
    loaded = {r["teacher_id"] for r in ds.load}
    for tid, rec in ds.staff.items():
        if tid not in loaded:
            ds.issues.append(_issue("warning", "Штат_ППС", f"{tid} оқытушысының жүктемесі жоқ — ФОТ бөлінбейді",
                                    row=rec["row"], code="unallocated"))
    seen = set()
    for rec in ds.direct:
        if rec["cost_id"] in seen:
            ds.issues.append(_issue("warning", "Прямые_затраты", f"cost_id {rec['cost_id']} қайталанады",
                                    row=rec["row"], code="duplicate"))
        seen.add(rec["cost_id"])
    return ds
