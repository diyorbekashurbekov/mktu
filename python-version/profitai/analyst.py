"""AI analyst — tools that compute answers from the P&L, plus an offline intent router.

Every figure in an answer comes from the engine (verifiable code); the text only
interprets it. Each answer carries facts, the formula, source rows and assumptions.
The same tools are exposed to Claude in llm.py.
"""
from __future__ import annotations

import re

from . import fmt
from .insights import explain as explain_op, ethics
from .scenario import run as run_scenario

KZ_CHARS = set("әғқңөұүһі")


def detect_lang(text: str) -> str:
    low = text.lower()
    if any(c in KZ_CHARS for c in low):
        return "kz"
    if re.search(r"[а-я]", low):  # Cyrillic without Kazakh-specific letters
        return "ru"
    return "kz"


def L(lang, kz, ru):
    return ru if lang == "ru" else kz


rows_ref = fmt.rows_ref


# metric -> (kz label, ru label, formatter, formula, sheets)
METRICS = {
    "result": ("Қаржылық нәтиже", "Финансовый результат", fmt.money, "Доход − (ФОТ + прямые + накладные)",
               "Контингент, Штат_ППС, Нагрузка_ППС, Прямые_затраты, Общие_затраты, Драйверы"),
    "margin": ("Рентабельділік", "Рентабельность", fmt.pct, "Финансовый результат / Доход × 100%",
               "Контингент, Штат_ППС, Нагрузка_ППС, Прямые_затраты, Общие_затраты, Драйверы"),
    "revenue": ("Кіріс", "Доход", fmt.money,
                "Σ(контракт_полный × тариф + контракт_со_скидкой × тариф × (1 − скидка) + грант × финансирование_грант)",
                "Контингент"),
    "fot": ("ФОТ", "ФОТ", fmt.money, "Σ зарплата × месяцев × (1 + начисления) × часы_на_ОП / все_часы_преподавателя",
            "Штат_ППС, Нагрузка_ППС"),
    "direct": ("Тікелей шығындар", "Прямые затраты", fmt.money, "Σ сумма_в_год по op_id", "Прямые_затраты"),
    "overhead": ("Жанама шығындар", "Накладные затраты", fmt.money,
                 "Σ_центров сумма × драйвер_ОП / Σ драйвер_12_ОП", "Общие_затраты, Драйверы"),
    "total_cost": ("Жалпы шығын", "Итого затраты", fmt.money, "ФОТ + прямые + накладные",
                   "Штат_ППС, Нагрузка_ППС, Прямые_затраты, Общие_затраты, Драйверы"),
    "cost_per_student": ("Бір студенттің өзіндік құны", "Себестоимость одного студента", fmt.money,
                         "Итого затраты / студентов_активных", "Драйверы + все листы затрат"),
    "fot_per_student": ("Бір студентке ФОТ", "ФОТ на одного студента", fmt.money, "ФОТ ОП / студентов_активных",
                        "Штат_ППС, Нагрузка_ППС, Драйверы"),
    "revenue_per_student": ("Бір студентке кіріс", "Доход на одного студента", fmt.money,
                            "Доход / студентов_активных", "Контингент, Драйверы"),
    "students": ("Белсенді студенттер", "Активные студенты", lambda x: fmt.num(x, 0), "студентов_активных", "Драйверы"),
}

# Russian/Kazakh name forms, keyed by the programme name (so a different upload is matched by its own names)
ALIASES = {
    "информатика": [r"информатик"],
    "информационные системы": [r"информационн\w*\s+систем", r"ақпараттық\s+жүйе"],
    "кибербезопасность": [r"кибер"],
    "прикладная математика": [r"математ"],
    "педагогика и психология": [r"педагогик", r"психолог"],
    "иностранные языки": [r"иностранн\w*\s+язык", r"шет\s+тіл"],
    "переводческое дело": [r"перевод", r"аударма"],
    "экономика": [r"экономик"],
    "менеджмент": [r"менеджмент"],
    "финансы": [r"\bфинанс(ы|ам|ах|ами)?\b", r"\bқаржы\b(?!\s*(лық|нәтиже))"],
    "сестринское дело": [r"сестрин", r"мейірге", r"медсестр"],
    "общая медицина": [r"общ\w*\s+медицин", r"жалпы\s+медицин", r"лечебн"],
}
FACULTY_ALIASES = [
    (r"инженер", "Инженерный"), (r"естествен|жаратылыс", "Естественно"), (r"педагог", "Педагогич"),
    (r"гуманит", "Гуманитар"), (r"бизнес", "Бизнес"), (r"медицин", "Медицин"),
]


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е").replace("−", "-").replace("–", "-")


def find_ops(state, text: str) -> list[str]:
    low = _norm(text)
    found = []
    for m in re.finditer(r"(?:op|оп|бб)\s*-?\s*0*(\d{1,3})\b", low):
        oid = f"OP-{int(m.group(1)):03d}"
        if oid in state.ds.ops and oid not in found:
            found.append(oid)
    for oid, op in state.ds.ops.items():
        name = _norm(op["name"])
        pats = ALIASES.get(name, [])
        hit = name in low or any(re.search(p, low) for p in pats)
        if not hit and not pats:
            words = [w for w in re.findall(r"\w+", name) if len(w) >= 4]
            hit = bool(words) and all(re.search(r"\b" + re.escape(w[:max(4, len(w) - 3)]), low) for w in words)
        if hit and oid not in found:
            found.append(oid)
    return found


def find_faculty(state, text: str):
    low = _norm(text)
    if "факультет" not in low:
        return None
    faculties = sorted({o["faculty"] for o in state.ds.ops.values()})
    for pat, stem in FACULTY_ALIASES:
        if re.search(pat, low):
            for f in faculties:
                if f.startswith(stem):
                    return f
    for f in faculties:
        if _norm(f.split()[0])[:5] in low:
            return f
    return None


def _answer(lang, intent, title, text, facts=None, table=None, formula=None, sources=None,
            assumptions=None, followups=None, **extra):
    base_assumptions = [L(lang, "Барлық сомалар — теңге, бір оқу жылы (2025–2026); экранда 2 таңбаға дейін дөңгелектенген.",
                          "Все суммы — тенге за один учебный год; округление до 2 знаков только на экране."),
                        L(lang, "Қаржылық нәтиже — кассалық қалдық емес; салық, амортизация, стипендия модельденбейді.",
                          "Финансовый результат не является кассовым остатком; налоги, амортизация, стипендии не моделируются.")]
    return {"lang": lang, "intent": intent, "title": title, "text": text, "facts": facts or [],
            "table": table, "formula": formula, "sources": sources or [],
            "assumptions": (assumptions or []) + base_assumptions, "followups": followups or [], **extra}


def _op(state, oid):
    return next(o for o in state.pnl["ops"] if o["op_id"] == oid)


def _pnl_sources(o):
    return [rows_ref("Контингент", [r["row"] for r in o["revenue_rows"]]),
            rows_ref("Нагрузка_ППС", [r for t in o["teachers"] for r in t["load_rows"]]),
            rows_ref("Штат_ППС", [t["staff_row"] for t in o["teachers"]]),
            rows_ref("Прямые_затраты", [r["row"] for r in o["direct_rows"]]),
            rows_ref("Общие_затраты", [r["row"] for r in o["overhead_rows"]]),
            rows_ref("Драйверы", [o["driver_row"]])]


def _pnl_table(lang, ops):
    cols = [L(lang, "ОП", "ОП"), L(lang, "Кіріс", "Доход"), L(lang, "Жалпы шығын", "Итого затраты"),
            L(lang, "Нәтиже", "Результат"), L(lang, "Рентаб.", "Рентаб."), L(lang, "Құн/студент", "Себест./студ.")]
    return {"columns": cols, "rows": [[f"{o['op_id']} {o['name']}", fmt.money0(o["revenue"]), fmt.money0(o["total_cost"]),
                                       fmt.money0(o["result"]), fmt.pct(o["margin"]), fmt.money0(o["cost_per_student"])]
                                      for o in ops]}


# ----------------------------------------------------------------------------- tools

def tool_status_list(state, status="loss", lang="kz"):
    ops = [o for o in state.pnl["ops"] if (o["result"] < 0) == (status == "loss")]
    ops.sort(key=lambda o: o["result"])
    if status != "loss":
        ops.reverse()
    total = sum(o["result"] for o in ops)
    if status == "loss":
        title = L(lang, "Шығынды ОП-лар", "Убыточные ОП")
        if ops:
            text = L(lang, f"{len(ops)} ОП шығындарын жаппайды (нәтиже < 0). Жиынтық шығын: **{fmt.money(total)}**. ",
                     f"{len(ops)} ОП не покрывают свои затраты (результат < 0). Совокупный убыток: **{fmt.money(total)}**. ")
            text += "; ".join(f"**{o['name']}** ({o['op_id']}): {fmt.money(o['result'])}, {fmt.pct(o['margin'])}" for o in ops) + "."
            worst = ops[0]
            text += L(lang, f" Ең терең шығын — {worst['name']}: бір студентке шығын {fmt.money0(worst['cost_per_student'])}, "
                      f"кіріс {fmt.money0(worst['revenue_per_student'])}.",
                      f" Глубже всего — {worst['name']}: себестоимость студента {fmt.money0(worst['cost_per_student'])} "
                      f"при доходе {fmt.money0(worst['revenue_per_student'])}.")
        else:
            text = L(lang, "Барлық ОП шығындарын жабады.", "Все ОП покрывают свои затраты.")
    else:
        title = L(lang, "Шығынын жабатын ОП-лар", "ОП, покрывающие затраты")
        text = L(lang, f"{len(ops)} ОП оң нәтижеге ие, жиыны **{fmt.money(total)}**. Көшбасшы — **{ops[0]['name']}** "
                 f"({fmt.money(ops[0]['result'])}).", f"{len(ops)} ОП с положительным результатом, всего **{fmt.money(total)}**. "
                 f"Лидер — **{ops[0]['name']}** ({fmt.money(ops[0]['result'])}).") if ops else "—"
    return _answer(lang, "status_list", title, text,
                   facts=[{"label": L(lang, "ОП саны", "Число ОП"), "value": str(len(ops))},
                          {"label": L(lang, "Жиынтық нәтиже", "Суммарный результат"), "value": fmt.money(total)}],
                   table=_pnl_table(lang, ops), formula=METRICS["result"][3],
                   sources=[rows_ref("Контингент", [r["row"] for o in ops for r in o["revenue_rows"]]),
                            rows_ref("Прямые_затраты", [r["row"] for o in ops for r in o["direct_rows"]]),
                            rows_ref("Драйверы", [o["driver_row"] for o in ops]),
                            "Штат_ППС, Нагрузка_ППС, Общие_затраты"],
                   followups=[L(lang, f"{ops[0]['name']} неге шығынды?", f"Почему {ops[0]['name']} убыточна?")] if ops and status == "loss" else [],
                   op_ids=[o["op_id"] for o in ops])


def tool_rank(state, metric="result", order="desc", limit=5, lang="kz", faculty=None):
    if metric not in METRICS:
        metric = "result"
    kz, ru, f, formula, sheets = METRICS[metric]
    ops = [o for o in state.pnl["ops"] if o[metric] is not None and (not faculty or o["faculty"] == faculty)]
    ops.sort(key=lambda o: o[metric], reverse=(order == "desc"))
    top = ops[:max(1, min(int(limit or 5), 12))]
    label = L(lang, kz, ru)
    head = top[0]
    avg = state.pnl["totals"].get(metric)
    word = L(lang, "ең жоғары" if order == "desc" else "ең төмен", "самый высокий" if order == "desc" else "самый низкий")
    text = L(lang, f"{label} бойынша {word} көрсеткіш — **{head['name']}** ({head['op_id']}): **{f(head[metric])}**.",
             f"{label}: {word} показатель у **{head['name']}** ({head['op_id']}): **{f(head[metric])}**.")
    if avg is not None and metric not in ("result", "revenue", "fot", "direct", "overhead", "total_cost", "students"):
        text += L(lang, f" Университет бойынша: {f(avg)}.", f" По вузу в целом: {f(avg)}.")
    if metric == "fot_per_student":
        text += L(lang, f" Себебі: {fmt.num(head['hours_per_student'], 1)} оқытушы сағаты / студент "
                  f"(университет: {fmt.num(state.pnl['totals']['hours_per_student'], 1)}), {len(head['teachers'])} оқытушы, "
                  f"{fmt.num(head['students'], 0)} студент.",
                  f" Причина: {fmt.num(head['hours_per_student'], 1)} часов ППС на студента "
                  f"(вуз: {fmt.num(state.pnl['totals']['hours_per_student'], 1)}), {len(head['teachers'])} преподавателей на "
                  f"{fmt.num(head['students'], 0)} студентов.")
    table = {"columns": ["#", "ОП", label], "rows": [[str(i + 1), f"{o['op_id']} {o['name']}", f(o[metric])]
                                                    for i, o in enumerate(top)]}
    return _answer(lang, "rank", label, text,
                   facts=[{"label": label, "value": f(head[metric])}, {"label": "ОП", "value": head["name"]}],
                   table=table, formula=formula, sources=[sheets] + _pnl_sources(head)[:1],
                   op_ids=[o["op_id"] for o in top])


def tool_op_summary(state, op_id, lang="kz"):
    o = _op(state, op_id)
    t = state.pnl["totals"]
    text = L(lang,
             f"**{o['name']}** ({o['faculty']}): кіріс **{fmt.money(o['revenue'])}**, ФОТ {fmt.money(o['fot'])}, "
             f"тікелей {fmt.money(o['direct'])}, жанама {fmt.money(o['overhead'])} → жалпы шығын {fmt.money(o['total_cost'])}. "
             f"Нәтиже **{fmt.money(o['result'])}**, рентабельділік **{fmt.pct(o['margin'])}** "
             f"(университет: {fmt.pct(t['margin'])}). Бір студенттің өзіндік құны {fmt.money(o['cost_per_student'])} "
             f"({fmt.num(o['students'], 0)} белсенді студент).",
             f"**{o['name']}** ({o['faculty']}): доход **{fmt.money(o['revenue'])}**, ФОТ {fmt.money(o['fot'])}, "
             f"прямые {fmt.money(o['direct'])}, накладные {fmt.money(o['overhead'])} → итого {fmt.money(o['total_cost'])}. "
             f"Результат **{fmt.money(o['result'])}**, рентабельность **{fmt.pct(o['margin'])}** "
             f"(вуз: {fmt.pct(t['margin'])}). Себестоимость студента {fmt.money(o['cost_per_student'])} "
             f"({fmt.num(o['students'], 0)} активных студентов).")
    facts = [{"label": L(lang, "Кіріс", "Доход"), "value": fmt.money(o["revenue"])},
             {"label": "ФОТ", "value": fmt.money(o["fot"])},
             {"label": L(lang, "Тікелей", "Прямые"), "value": fmt.money(o["direct"])},
             {"label": L(lang, "Жанама", "Накладные"), "value": fmt.money(o["overhead"])},
             {"label": L(lang, "Нәтиже", "Результат"), "value": fmt.money(o["result"])},
             {"label": L(lang, "Рентабельділік", "Рентабельность"), "value": fmt.pct(o["margin"])}]
    return _answer(lang, "op_summary", f"{o['op_id']} · {o['name']}", text, facts=facts,
                   formula="Результат = Доход − (ФОТ + прямые + накладные); Рентабельность = Результат / Доход × 100%",
                   sources=_pnl_sources(o),
                   followups=[L(lang, f"{o['name']} нәтижесін түсіндір", f"Почему у {o['name']} такой результат?"),
                              L(lang, f"{o['name']} контингенті +10% болса не болады?", f"Что если контингент {o['name']} вырастет на 10%?")],
                   op_ids=[op_id])


def tool_explain(state, op_id, lang="kz"):
    o = _op(state, op_id)
    ex = explain_op(state.ds, state.pnl, op_id, lang)
    text = ex["summary"] + "\n\n" + L(lang, "**Негізгі факторлар:**", "**Ключевые факторы:**") + "\n" + "\n".join(
        f"{i + 1}. **{f['title']}**" + (f" ({f['impact_display']})" if f.get("impact_display") else "") + f" — {f['text']}"
        for i, f in enumerate(ex["factors"]))
    text += "\n\n" + L(lang, "**Басқарушылық нұсқалар:**", "**Управленческие варианты:**") + "\n" + "\n".join(
        f"• **{p['title']}**. {p['effect']} " + L(lang, "Тәуекел: ", "Риски: ") + p["risks"] for p in ex["options"])
    text += "\n\n" + ex["ethics"]
    return _answer(lang, "explain", L(lang, f"{o['name']}: нәтиже неге осындай", f"{o['name']}: почему такой результат"),
                   text, facts=[{"label": L(lang, "Нәтиже", "Результат"), "value": fmt.money(o["result"])},
                                {"label": L(lang, "Рентабельділік", "Рентабельность"), "value": fmt.pct(o["margin"])},
                                {"label": L(lang, "Орташа деңгейдегі база", "База при средних"), "value": fmt.money0(ex["baseline"])}],
                   formula=ex["formula"], sources=_pnl_sources(o) + [f["source"] for f in ex["factors"]][:2],
                   assumptions=[L(lang, "Факторлардың теңгедегі әсері = (ОП көрсеткіші/студент − университет орташасы/студент) × ОП студенттері; "
                                  "қосындысы нәтиже мен база арасындағы айырмаға тең.",
                                  "Влияние фактора = (показатель ОП на студента − средний по вузу) × студенты ОП; "
                                  "сумма равна разнице между результатом и базой.")],
                   explain=ex, op_ids=[op_id])


def tool_compare(state, op_ids, lang="kz"):
    ops = [_op(state, i) for i in op_ids[:4]]
    keys = ["revenue", "fot", "direct", "overhead", "total_cost", "result", "margin", "cost_per_student", "students"]
    table = {"columns": [L(lang, "Көрсеткіш", "Показатель")] + [o["name"] for o in ops],
             "rows": [[L(lang, METRICS[k][0], METRICS[k][1])] + [METRICS[k][2](o[k]) for o in ops] for k in keys]}
    best = max(ops, key=lambda o: o["result"])
    text = L(lang, f"Салыстыру: ең жоғары нәтиже — **{best['name']}** ({fmt.money(best['result'])}). ",
             f"Сравнение: лучший результат у **{best['name']}** ({fmt.money(best['result'])}). ")
    text += "; ".join(f"{o['name']}: {fmt.money(o['result'])} ({fmt.pct(o['margin'])})" for o in ops) + "."
    srcs = []
    for o in ops:
        srcs += _pnl_sources(o)[:1]
    return _answer(lang, "compare", L(lang, "ОП салыстыру", "Сравнение ОП"), text, table=table,
                   formula=METRICS["result"][3], sources=srcs + ["Штат_ППС, Нагрузка_ППС, Прямые_затраты, Общие_затраты, Драйверы"],
                   op_ids=op_ids)


def tool_faculty(state, faculty=None, lang="kz"):
    groups = {}
    for o in state.pnl["ops"]:
        g = groups.setdefault(o["faculty"], {"revenue": 0, "total_cost": 0, "result": 0, "students": 0, "ops": []})
        for k in ("revenue", "total_cost", "result", "students"):
            g[k] += o[k]
        g["ops"].append(o)
    items = sorted(groups.items(), key=lambda kv: kv[1]["result"], reverse=True)
    if faculty:
        items = [(k, v) for k, v in items if k == faculty]
    rows = [[k, fmt.money0(v["revenue"]), fmt.money0(v["total_cost"]), fmt.money0(v["result"]),
             fmt.pct(v["result"] / v["revenue"] * 100 if v["revenue"] else None), str(len(v["ops"]))] for k, v in items]
    if faculty and items:
        k, v = items[0]
        text = L(lang, f"**{k}**: {len(v['ops'])} ОП, кіріс {fmt.money(v['revenue'])}, нәтиже **{fmt.money(v['result'])}**. ",
                 f"**{k}**: {len(v['ops'])} ОП, доход {fmt.money(v['revenue'])}, результат **{fmt.money(v['result'])}**. ")
        text += "; ".join(f"{o['name']}: {fmt.money(o['result'])} ({fmt.pct(o['margin'])})" for o in v["ops"]) + "."
    else:
        k, v = items[0]
        k2, v2 = items[-1]
        text = L(lang, f"Ең жоғары нәтиже — **{k}** ({fmt.money(v['result'])}), ең төмен — **{k2}** ({fmt.money(v2['result'])}).",
                 f"Лучший результат — **{k}** ({fmt.money(v['result'])}), худший — **{k2}** ({fmt.money(v2['result'])}).")
    return _answer(lang, "faculty", L(lang, "Факультеттер бойынша", "По факультетам"), text,
                   table={"columns": [L(lang, "Факультет", "Факультет"), L(lang, "Кіріс", "Доход"), L(lang, "Шығын", "Затраты"),
                                      L(lang, "Нәтиже", "Результат"), L(lang, "Рентаб.", "Рентаб."), "ОП"], "rows": rows},
                   formula=L(lang, "Факультет = оның ОП-ларының қосындысы", "Факультет = сумма его ОП"),
                   sources=["ОП!2–13 (факультет)", "+ барлық P&L парақтары"])


def tool_totals(state, lang="kz"):
    t = state.pnl["totals"]
    text = L(lang,
             f"Университет (12 ОП): кіріс **{fmt.money(t['revenue'])}**, жалпы шығын {fmt.money(t['total_cost'])} "
             f"(ФОТ {fmt.money(t['fot'])}, тікелей {fmt.money(t['direct'])}, жанама {fmt.money(t['overhead'])}). "
             f"Нәтиже **{fmt.money(t['result'])}**, рентабельділік **{fmt.pct(t['margin'])}**. "
             f"Шығынды ОП: {t['loss_count']}. Бір студенттің орташа өзіндік құны {fmt.money(t['cost_per_student'])}.",
             f"Вуз (12 ОП): доход **{fmt.money(t['revenue'])}**, итого затраты {fmt.money(t['total_cost'])} "
             f"(ФОТ {fmt.money(t['fot'])}, прямые {fmt.money(t['direct'])}, накладные {fmt.money(t['overhead'])}). "
             f"Результат **{fmt.money(t['result'])}**, рентабельность **{fmt.pct(t['margin'])}**. "
             f"Убыточных ОП: {t['loss_count']}. Средняя себестоимость студента {fmt.money(t['cost_per_student'])}.")
    return _answer(lang, "totals", L(lang, "Университет бойынша жиынтық", "Итого по вузу"), text,
                   facts=[{"label": L(lang, "Кіріс", "Доход"), "value": fmt.money(t["revenue"])},
                          {"label": L(lang, "Шығын", "Затраты"), "value": fmt.money(t["total_cost"])},
                          {"label": L(lang, "Нәтиже", "Результат"), "value": fmt.money(t["result"])},
                          {"label": L(lang, "Рентабельділік", "Рентабельность"), "value": fmt.pct(t["margin"])}],
                   table=_pnl_table(lang, sorted(state.pnl["ops"], key=lambda o: -o["result"])),
                   formula=METRICS["result"][3],
                   sources=["Контингент", "Штат_ППС", "Нагрузка_ППС", "Прямые_затраты", "Общие_затраты", "Драйверы"])


def tool_anomalies(state, lang="kz"):
    q = state.quality
    rows = [[a["source_row_id"] or "—", str(a["excel_row"]), a["type_label"], a["op_id"] or "—",
             "—" if a["value"] is None else str(a["value"]), a["why"], a["action"]] for a in q["anomalies"]]
    kinds = ", ".join(sorted({a["type_label"] for a in q["anomalies"]}))
    text = L(lang,
             f"«Сырые_сигналы» парағында {q['rows_checked']} жол тексерілді, **{q['count']} аномалия** табылды ({kinds}). "
             f"Бұл парақ P&L есебіне кірмейді — базалық нәтиже өзгермейді (тексеріс: сигналдарсыз қайта есептеу "
             f"нәтижесі бірдей).",
             f"В листе «Сырые_сигналы» проверено {q['rows_checked']} строк, найдено **{q['count']} аномалий** ({kinds}). "
             f"Лист не входит в P&L — базовый расчёт не меняется (проверка: пересчёт без сигналов даёт тот же результат).")
    return _answer(lang, "anomalies", L(lang, "Сырые_сигналы аномалиялары", "Аномалии в «Сырые_сигналы»"), text,
                   facts=[{"label": L(lang, "Тексерілген жол", "Проверено строк"), "value": str(q["rows_checked"])},
                          {"label": L(lang, "Аномалия", "Аномалий"), "value": str(q["count"])}],
                   table={"columns": ["ID", L(lang, "Excel жолы", "Строка"), L(lang, "Түрі", "Тип"), "ОП",
                                      L(lang, "Мән", "Значение"), L(lang, "Неге күдікті", "Почему подозрительно"),
                                      L(lang, "Ұсыныс", "Действие")], "rows": rows},
                   formula=L(lang, "Ережелер: ID бірегейлігі; op_id ∈ ОП; applications ≥ 0; 0 ≤ conversion_pct ≤ 100; мән бос емес; "
                             "кезең ∈ датасет жылдары", "Правила: уникальность ID; op_id ∈ ОП; applications ≥ 0; 0 ≤ conversion_pct ≤ 100; "
                             "значение не пусто; период ∈ годы датасета"),
                   sources=[a["ref"] for a in q["anomalies"]],
                   assumptions=[L(lang, "Анықтау «источник_комментарий» бағанына сүйенбейді — тек мәндерге қойылған ережелер.",
                                  "Обнаружение не опирается на колонку «источник_комментарий» — только правила по значениям.")])


def tool_scenario(state, op_id, pct=10.0, lang="kz"):
    sc = run_scenario(state.ds, state.pnl, op_id, pct)
    s = sc["selected"]
    b, a, d = s["before"], s["after"], s["delta"]
    uni = sc["totals"]["after"]["result"] - sc["totals"]["before"]["result"]
    text = L(lang,
             f"**{sc['name']}** контингенті {fmt.num(pct, 0)}% өзгерсе: кіріс {fmt.money0(b['revenue'])} → **{fmt.money0(a['revenue'])}** "
             f"({fmt.signed_money(d['revenue'])}), жанама {fmt.money0(b['overhead'])} → {fmt.money0(a['overhead'])} "
             f"({fmt.signed_money(d['overhead'])}), нәтиже {fmt.money0(b['result'])} → **{fmt.money0(a['result'])}** "
             f"({fmt.signed_money(d['result'])}), рентабельділік {fmt.pct(b['margin'])} → {fmt.pct(a['margin'])}. "
             f"Басқа ОП-лардың нәтижесі жанама шығын қайта бөлінгендіктен {fmt.signed_money(sc['others_result_delta'])} өзгереді; "
             f"университет бойынша {fmt.signed_money(uni)}. Жанама шығын жиыны сақталды: {fmt.money0(sc['totals']['after']['overhead'])}.",
             f"Если контингент **{sc['name']}** изменится на {fmt.num(pct, 0)}%: доход {fmt.money0(b['revenue'])} → **{fmt.money0(a['revenue'])}** "
             f"({fmt.signed_money(d['revenue'])}), накладные {fmt.money0(b['overhead'])} → {fmt.money0(a['overhead'])} "
             f"({fmt.signed_money(d['overhead'])}), результат {fmt.money0(b['result'])} → **{fmt.money0(a['result'])}** "
             f"({fmt.signed_money(d['result'])}), рентабельность {fmt.pct(b['margin'])} → {fmt.pct(a['margin'])}. "
             f"Результат остальных ОП меняется на {fmt.signed_money(sc['others_result_delta'])} из-за перераспределения накладных; "
             f"по вузу {fmt.signed_money(uni)}. Сумма накладных сохранена: {fmt.money0(sc['totals']['after']['overhead'])}.")
    be = sc["break_even"]
    if b["result"] < 0 and be.get("reachable"):
        text += L(lang, f" Шығынсыздық нүктесі: контингент +{fmt.num(be['pct'], 1)}% (≈{fmt.num(be['students'], 0)} студент).",
                  f" Точка безубыточности: контингент +{fmt.num(be['pct'], 1)}% (≈{fmt.num(be['students'], 0)} студентов).")
    return _answer(lang, "scenario", L(lang, f"Сценарий: {sc['name']} {fmt.num(pct, 0)}%", f"Сценарий: {sc['name']} {fmt.num(pct, 0)}%"),
                   text, facts=[{"label": L(lang, "Δ нәтиже ОП", "Δ результата ОП"), "value": fmt.signed_money(d["result"])},
                                {"label": L(lang, "Δ университет", "Δ по вузу"), "value": fmt.signed_money(uni)},
                                {"label": L(lang, "Жаңа рентаб.", "Новая рентаб."), "value": fmt.pct(a["margin"])}],
                   formula=L(lang, "Кіріс' = Кіріс × (1+Δ); students' = students × (1+Δ); жанама' = Σ орталық × драйвер'/Σ драйвер'",
                             "Доход' = Доход × (1+Δ); students' = students × (1+Δ); накладные' = Σ центр × драйвер'/Σ драйвер'"),
                   sources=["Контингент", "Драйверы (students)", "Общие_затраты (students-драйвер орталықтары)"],
                   assumptions=sc["assumptions"], scenario=sc, op_ids=[op_id])


def tool_forecast(state, op_id=None, lang="kz"):
    fc = state.forecast
    items = [i for i in fc["items"] if not op_id or i["op_id"] == op_id]
    if not items:
        return _answer(lang, "forecast", L(lang, "Болжам", "Прогноз"), L(lang, "История_набора деректері жоқ.", "Нет данных История_набора."))
    rows = [[f"{i['op_id']} {i['name']}", " / ".join(str(h["enrolled"]) for h in i["history"]),
             fmt.num(i["point"], 0), f"{fmt.num(i['low'], 0)}–{fmt.num(i['high'], 0)}", str(i["last_plan"])] for i in items]
    if op_id:
        i = items[0]
        text = L(lang, f"**{i['name']}**: {i['next_year']} жылға қабылдау болжамы ≈ **{fmt.num(i['point'], 0)}** студент, "
                 f"ықтимал диапазон {fmt.num(i['low'], 0)}–{fmt.num(i['high'], 0)} (±{fmt.num(i['spread_pct'] / 2, 0)}%). "
                 f"Соңғы жоспар: {i['last_plan']}.",
                 f"**{i['name']}**: прогноз набора на {i['next_year']} ≈ **{fmt.num(i['point'], 0)}** студентов, "
                 f"вероятный диапазон {fmt.num(i['low'], 0)}–{fmt.num(i['high'], 0)} (±{fmt.num(i['spread_pct'] / 2, 0)}%). "
                 f"Последний план: {i['last_plan']}.")
    else:
        total = sum(i["point"] for i in items)
        text = L(lang, f"Келесі жылға 12 ОП бойынша жиынтық қабылдау болжамы ≈ **{fmt.num(total, 0)}** студент.",
                 f"Суммарный прогноз набора по 12 ОП на следующий год ≈ **{fmt.num(total, 0)}** студентов.")
    text += " " + L(lang, "Маңызды: тек 3 бақылау — болжам сенімсіз.", "Важно: всего 3 наблюдения — прогноз ненадёжен.")
    return _answer(lang, "forecast", L(lang, "Қабылдау болжамы", "Прогноз набора"), text,
                   table={"columns": ["ОП", L(lang, "Зачислено (3 жыл)", "Зачислено (3 года)"), L(lang, "Болжам", "Прогноз"),
                                      L(lang, "Диапазон", "Диапазон"), L(lang, "Соңғы жоспар", "Последний план")], "rows": rows},
                   formula=fc["method"], sources=[rows_ref("История_набора", [h["row"] for i in items for h in i["history"]])],
                   assumptions=fc["caveats"])


def tool_methodology(state, lang="kz"):
    text = L(lang, "Есеп кейстің міндетті әдістемесімен жүргізіледі; сомаларды LLM емес, тексерілетін Python коды есептейді.",
             "Расчёт ведётся по обязательной методике кейса; суммы считает проверяемый Python-код, а не LLM.")
    rows = [[L(lang, METRICS[k][0], METRICS[k][1]), METRICS[k][3], METRICS[k][4]] for k in
            ("revenue", "fot", "direct", "overhead", "total_cost", "result", "margin", "cost_per_student")]
    checks = state.checks
    text += " " + L(lang, "Қабылдау тексерістері: ", "Приёмочные проверки: ") + "; ".join(
        f"{c['title']} — {'✓' if c['pass'] else '✗'}" for c in checks)
    return _answer(lang, "methodology", L(lang, "Әдістеме және формулалар", "Методика и формулы"), text,
                   table={"columns": [L(lang, "Көрсеткіш", "Показатель"), L(lang, "Формула", "Формула"), L(lang, "Дереккөз", "Источник")],
                          "rows": rows}, formula="Σ / × — engine.py", sources=["profitai/engine.py"])


def tool_help(state, lang="kz"):
    ex = examples(lang)
    text = L(lang, "Бұл сұрақты деректер негізінде түсіне алмадым. Ойдан сан шығармаймын — төмендегі сұрақ түрлерін қолданып көріңіз:",
             "Не удалось сопоставить вопрос с данными. Выдумывать числа не буду — попробуйте вопросы такого типа:")
    text += "\n" + "\n".join(f"• {e}" for e in ex)
    return _answer(lang, "help", L(lang, "Не сұрауға болады", "Что можно спросить"), text, followups=ex[:4])


def examples(lang):
    return [L(lang, "Қандай ОП шығынды?", "Какие ОП убыточны?"),
            L(lang, "Қолданбалы математиканың нәтижесі неге осындай?", "Почему у прикладной математики такой результат?"),
            L(lang, "Бір студентке ФОТ қай жерде ең жоғары?", "Где самый высокий ФОТ на студента?"),
            L(lang, "Сырые_сигналы ішінде қандай қателер бар?", "Какие ошибки в Сырые_сигналы?"),
            L(lang, "Информатика контингенті +10% болса не болады?", "Что если контингент Информатики вырастет на 10%?"),
            L(lang, "Келесі жылға қабылдау болжамы қандай?", "Какой прогноз набора на следующий год?"),
            L(lang, "Факультеттерді салыстыр", "Сравни факультеты"),
            L(lang, "Кіріс қалай есептеледі?", "Как считается доход?")]


TOOLS = {
    "status_list": tool_status_list, "rank": tool_rank, "op_summary": tool_op_summary, "explain_op": tool_explain,
    "compare": tool_compare, "faculty": tool_faculty, "totals": tool_totals, "anomalies": tool_anomalies,
    "scenario": tool_scenario, "forecast": tool_forecast, "methodology": tool_methodology,
}


# ----------------------------------------------------------------------------- router

def _has(low, pattern):
    return re.search(pattern, low) is not None


def _metric(low):
    per_student = _has(low, r"студент|на одного|на 1|бір студент|шаққанда|/\s*студ")
    if _has(low, r"фот|зарплат|оплат\w* труд|еңбекақы|жалақы"):
        return "fot_per_student" if per_student else "fot"
    if _has(low, r"себестоим|өзіндік құн|стоимость (обучения|одного)"):
        return "cost_per_student"
    if _has(low, r"рентаб|маржа|тиімділ"):
        return "margin"
    if _has(low, r"накладн|косвен|жанама|общ\w* затрат|орталық шығ"):
        return "overhead"
    if _has(low, r"прям\w* затрат|тікелей"):
        return "direct"
    if _has(low, r"доход|выручк|кіріс|табыс"):
        return "revenue_per_student" if per_student else "revenue"
    if _has(low, r"(итого|общ\w*|все\w*) (затрат|расход)|жалпы шығ|расход|шығын(дар|ы)?\b"):
        return "cost_per_student" if per_student else "total_cost"
    if _has(low, r"прибыл|пайда|результат|нәтиже"):
        return "result"
    if _has(low, r"студент|контингент"):
        return "students"
    return None


def route(state, question: str, op_hint: str | None = None) -> dict:
    lang = detect_lang(question)
    low = _norm(question)
    ops = find_ops(state, question)
    if op_hint and not ops and op_hint in state.ds.ops:
        ops = [op_hint]
    faculty = find_faculty(state, question)

    if _has(low, r"аномал|сыры\w* сигнал|сигнал|ошибк|қате|некоррект|проблемн\w* запис|сапасы|дубл"):
        return tool_anomalies(state, lang)
    if _has(low, r"прогноз|болжа|следующ\w* год|келесі жыл|набор\w* на"):
        return tool_forecast(state, ops[0] if ops else None, lang)
    pct_m = re.search(r"([+\-]?\s*\d+(?:[.,]\d+)?)\s*%", low)
    scenario_words = _has(low, r"что (будет|если)|если|егер|сценар|не болса|болса|өссе|азайса|увелич|сниз|сократ|рост|вырас")
    if (scenario_words and (ops or pct_m)) or (ops and pct_m):
        pct = float(pct_m.group(1).replace(" ", "").replace(",", ".")) if pct_m else 10.0
        if _has(low, r"сниж|сниз|сократ|уменьш|упад|паден|азай|кеміс|кемі|төменде|-\s*\d") and pct > 0:
            pct = -pct
        if ops:
            return tool_scenario(state, ops[0], pct, lang)
    if _has(low, r"формул|методик|как (счита|рассчит|вычисл)|қалай есепте|әдістеме"):
        return tool_methodology(state, lang)
    if len(ops) >= 2 and _has(low, r"сравн|салыстыр|\bvs\b|против|или|және|мен|чем"):
        return tool_compare(state, ops, lang)
    if ops and _has(low, r"почему|объясн|неге|түсіндір|себеб|фактор|причин|анализ|талда|что влия|не әсер"):
        return tool_explain(state, ops[0], lang)
    if _has(low, r"не покрыва|убыт|отрицат|минус|шығынды|залал|теріс"):
        return tool_status_list(state, "loss", lang)
    if _has(low, r"покрыва|прибыльн|окупа|пайдалы|оң нәтиже|жабат"):
        return tool_status_list(state, "profit", lang)
    if _has(low, r"факультет") and not ops:
        if faculty and not _has(low, r"сравн|салыстыр|все|барлық"):
            return tool_faculty(state, faculty, lang)
        return tool_faculty(state, None, lang)
    metric = _metric(low)
    rank_words = _has(low, r"самы|наибол|наимен|максим|миним|высок|низк|больш|меньш|ең|рейтинг|топ|лучш|худш|где|қай|какая|какой|какие")
    if metric and (rank_words or not ops):
        order = "asc" if _has(low, r"наимен|миним|низк|меньш|ең төмен|ең аз|худш|lowest") else "desc"
        if metric == "result" and _has(low, r"худш"):
            order = "asc"
        return tool_rank(state, metric, order, 5, lang, faculty)
    if ops:
        if len(ops) >= 2:
            return tool_compare(state, ops, lang)
        return tool_op_summary(state, ops[0], lang)
    if _has(low, r"итог|всего|университет|в целом|жалпы|барлығы|вуз|сводк|қорытынды"):
        return tool_totals(state, lang)
    return tool_help(state, lang)


def ask(state, question: str, op_hint: str | None = None) -> dict:
    question = (question or "").strip()[:500]
    if not question:
        return tool_help(state, "kz")
    from . import llm  # local import: optional dependency
    if llm.available():
        try:
            ans = llm.ask(state, question, op_hint)
            if ans:
                return ans
        except Exception as exc:  # network / quota / refusal -> deterministic answer
            fallback = route(state, question, op_hint)
            fallback["mode"] = "rules"
            fallback["llm_error"] = str(exc)[:200]
            return fallback
    ans = route(state, question, op_hint)
    ans["mode"] = "rules"
    return ans
