"""Rule-based anomaly detection on «Сырые_сигналы».

The sheet is an external feed for data-quality checks only — nothing here is
read by the P&L engine. Detection never relies on the free-text comment column;
each rule is a verifiable condition on the values themselves.
"""
from __future__ import annotations

import re
from collections import Counter

KNOWN_METRICS = {"applications": "заявки (саны)", "conversion_pct": "конверсия (%)"}
COUNT_METRICS = {"applications"}
PCT_METRICS = {"conversion_pct"}

TYPES = {
    "duplicate_id": "Қайталанған идентификатор",
    "unknown_op": "Белгісіз ОП",
    "negative_value": "Теріс мән",
    "pct_out_of_range": "Пайыз 0–100 шегінен тыс",
    "missing_value": "Мән жоқ",
    "invalid_period": "Жарамсыз кезең",
    "non_numeric": "Сан емес мән",
    "unknown_metric": "Белгісіз көрсеткіш",
    "missing_id": "Идентификатор жоқ",
}

YEAR_RE = re.compile(r"^(\d{4})\s*[–\-—/]\s*(\d{4})$")


def _num(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    if isinstance(value, bool):
        return None, "nan"
    if isinstance(value, (int, float)):
        return value, None
    try:
        return float(str(value).replace(" ", "").replace(",", ".")), None
    except ValueError:
        return None, "nan"


def _valid_years(ds) -> set[str]:
    years = {r["year"] for r in ds.history if r.get("year")}
    if ds.study_year:
        years.add(ds.study_year)
    return {y.replace("-", "–") for y in years}


def detect(ds) -> dict:
    signals = ds.signals
    valid_years = _valid_years(ds)
    current = ds.study_year.replace("-", "–") if ds.study_year else None
    anomalies = []
    flagged_rows = set()

    def flag(kind, rec, why, action, severity="high", field=None):
        flagged_rows.add(rec["row"])
        anomalies.append({
            "type": kind, "type_label": TYPES[kind], "severity": severity,
            "source_row_id": rec.get("source_row_id"), "excel_row": rec["row"], "op_id": rec.get("op_id"),
            "metric": rec.get("metric"), "year": rec.get("year"), "value": rec.get("value"),
            "field": field, "why": why, "action": action, "source_comment": rec.get("comment"),
            "ref": f"Сырые_сигналы!{rec['row']}",
        })

    id_counts = Counter(r.get("source_row_id") for r in signals if r.get("source_row_id"))
    first_seen = {}
    for rec in signals:
        sid = rec.get("source_row_id")
        if not sid:
            flag("missing_id", rec, "source_row_id бос — жолды көзге дейін қадағалау мүмкін емес.",
                 "Бастапқы жүйеден идентификаторды қалпына келтіру.", "medium", "source_row_id")
        elif id_counts[sid] > 1:
            if sid not in first_seen:
                first_seen[sid] = rec
            else:
                orig = first_seen[sid]
                same = all(orig.get(k) == rec.get(k) for k in ("op_id", "metric", "year", "value"))
                flag("duplicate_id", rec,
                     f"{sid} идентификаторы {orig['row']}-жолда бұрын кездескен"
                     + (" (мәндері де бірдей — толық дубль)." if same else ", бірақ мәндері өзгеше."),
                     "Дубльді жою немесе көзден жаңа ID сұрау; есепке тек бірінші жазбаны қалдыру.",
                     "medium", "source_row_id")

        op_id = rec.get("op_id")
        if op_id not in ds.ops:
            flag("unknown_op", rec, f"«{op_id}» ОП анықтамалығында жоқ (белгілі: {len(ds.ops)} ОП).",
                 "Код картасын тексеру; ОП анықталғанша жолды карантинге қою.", "high", "op_id")

        metric = rec.get("metric")
        if metric not in KNOWN_METRICS:
            flag("unknown_metric", rec, f"«{metric}» көрсеткіші сөздікте жоқ.",
                 "Көрсеткіштер сөздігін жаңарту немесе жолды алып тастау.", "medium", "показатель")

        year = (rec.get("year") or "").replace("-", "–")
        m = YEAR_RE.match(year)
        if not m or int(m.group(2)) - int(m.group(1)) != 1:
            flag("invalid_period", rec, f"«{rec.get('year')}» оқу жылының форматына сәйкес емес (YYYY–YYYY+1).",
                 "Кезеңді көз жүйесінде түзету.", "high", "учебный_год")
        elif valid_years and year not in valid_years:
            fut = current and int(m.group(1)) > int(current[:4])
            flag("invalid_period", rec,
                 f"Кезең {year} датасеттің кезеңдерінен тыс ({', '.join(sorted(valid_years))})"
                 + ("; болашақ жыл — нақты дерек бола алмайды." if fut else "."),
                 "Кезеңді тексеріп түзету; түзетілгенге дейін талдаудан шығару.", "high", "учебный_год")

        value, err = _num(rec.get("value"))
        if err == "missing":
            flag("missing_value", rec, "«значение» бағаны бос.",
                 "Көзден мәнді қайта жүктеу; нөлмен толтырмау (бұл бұрмалайды).", "medium", "значение")
        elif err == "nan":
            flag("non_numeric", rec, f"«{rec.get('value')}» сан емес.", "Форматты түзету.", "medium", "значение")
        elif metric in COUNT_METRICS and value < 0:
            flag("negative_value", rec, f"Өтінімдер саны теріс бола алмайды: {value:g}.",
                 "Көздегі белгіні/жүктеуді тексеру; түзетілгенге дейін жолды пайдаланбау.", "high", "значение")
        elif metric in PCT_METRICS and not 0 <= value <= 100:
            flag("pct_out_of_range", rec, f"Конверсия {value:g}% — 100%-дан жоғары (немесе 0-ден төмен) болуы мүмкін емес.",
                 "Есептеу базасын тексеру (зачислено/заявок × 100); мәнді түзету.", "high", "значение")

    reconciliation = []
    hist = {(r["op_id"], r["year"].replace("-", "–")): r for r in ds.history}
    for rec in signals:
        if rec["row"] in flagged_rows or rec.get("metric") != "applications":
            continue
        h = hist.get((rec.get("op_id"), (rec.get("year") or "").replace("-", "–")))
        value, err = _num(rec.get("value"))
        if h and err is None and value != h["applications"]:
            reconciliation.append({"source_row_id": rec.get("source_row_id"), "excel_row": rec["row"],
                                   "op_id": rec["op_id"], "signal": value, "history": h["applications"],
                                   "history_row": h["row"], "diff": value - h["applications"]})

    return {"anomalies": anomalies, "count": len(anomalies), "rows_checked": len(signals),
            "clean_rows": len(signals) - len(flagged_rows),
            "by_type": dict(Counter(a["type"] for a in anomalies)),
            "reconciliation": reconciliation,
            "pnl_isolated": True}
