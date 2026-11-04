"""«Объяснить ОП»: factor decomposition + management options with risks.

The decomposition is exact: result = (university average result per student × N)
+ Σ per-student gaps × N, so every factor's tenge impact adds up to the result.
"""
from __future__ import annotations

from . import fmt
from .scenario import break_even, run as run_scenario


def L(lang, kz, ru):
    return ru if lang == "ru" else kz


def _rel(a, b):
    return None if a is None or not b else (a / b - 1) * 100


def explain(ds, pnl: dict, op_id: str, lang: str = "kz") -> dict:
    o = next(x for x in pnl["ops"] if x["op_id"] == op_id)
    t = pnl["totals"]
    s = o["students"] or 0
    srcs = []
    if not s:
        return {"op_id": op_id, "name": o["name"], "factors": [], "options": [],
                "summary": L(lang, "Белсенді студенттер саны 0 — бір студентке шаққандағы талдау мүмкін емес (н/д).",
                             "Активных студентов 0 — анализ на одного студента невозможен (н/д)."),
                "sources": srcs, "ethics": ethics(lang)}

    base = (t["result"] / t["students"]) * s
    gaps = {
        "revenue": (o["revenue_per_student"] - t["revenue_per_student"]) * s,
        "fot": -(o["fot_per_student"] - t["fot_per_student"]) * s,
        "direct": -(o["direct_per_student"] - t["direct_per_student"]) * s,
        "overhead": -(o["overhead_per_student"] - t["overhead_per_student"]) * s,
    }
    ops = pnl["ops"]
    median_students = sorted(x["students"] for x in ops)[len(ops) // 2]
    paid_uni = [x for x in ops if x["tariff"]]
    avg_tariff = (sum(x["tariff"] * (x["paid_full"] + x["discounted"]) for x in paid_uni)
                  / max(1, sum(x["paid_full"] + x["discounted"] for x in paid_uni)))
    area_ps, area_ps_u = o["area_m2"] / s, sum(x["area_m2"] for x in ops) / t["students"]
    lab_ps, lab_ps_u = o["lab_hours"] / s, sum(x["lab_hours"] for x in ops) / t["students"]
    top_direct = max(o["direct_rows"], key=lambda r: r["amount"], default=None)

    factors = []
    factors.append({
        "key": "revenue", "impact": gaps["revenue"],
        "title": L(lang, "Бір студентке кіріс", "Доход на одного студента"),
        "text": L(lang,
                  f"{fmt.money0(o['revenue_per_student'])} / студент, университет бойынша орташа "
                  f"{fmt.money0(t['revenue_per_student'])} ({fmt.pct(_rel(o['revenue_per_student'], t['revenue_per_student']), 1)}). "
                  f"Тариф {fmt.money0(o['tariff'])} (ақылы студенттер бойынша орташа {fmt.money0(avg_tariff)}), "
                  f"грант үлесі {fmt.pct((o['grant_share'] or 0) * 100, 1)} (университет: {fmt.pct((t['grant_share'] or 0) * 100, 1)}), "
                  f"жеңілдік {fmt.pct((o['discount_rate'] or 0) * 100, 0)} × {fmt.num(o['discounted'], 0)} студент.",
                  f"{fmt.money0(o['revenue_per_student'])} на студента при среднем по вузу "
                  f"{fmt.money0(t['revenue_per_student'])} ({fmt.pct(_rel(o['revenue_per_student'], t['revenue_per_student']), 1)}). "
                  f"Тариф {fmt.money0(o['tariff'])} (средний по платным {fmt.money0(avg_tariff)}), "
                  f"доля грантов {fmt.pct((o['grant_share'] or 0) * 100, 1)} (вуз: {fmt.pct((t['grant_share'] or 0) * 100, 1)}), "
                  f"скидка {fmt.pct((o['discount_rate'] or 0) * 100, 0)} × {fmt.num(o['discounted'], 0)} студ."),
        "source": fmt.rows_ref("Контингент", [r["row"] for r in o["revenue_rows"]]),
    })
    factors.append({
        "key": "fot", "impact": gaps["fot"],
        "title": L(lang, "Бір студентке ФОТ", "ФОТ на одного студента"),
        "text": L(lang,
                  f"{fmt.money0(o['fot_per_student'])} / студент (университет: {fmt.money0(t['fot_per_student'])}). "
                  f"Оқытушы сағаты бір студентке {fmt.num(o['hours_per_student'], 1)} (университет: {fmt.num(t['hours_per_student'], 1)}) — "
                  f"{len(o['teachers'])} оқытушы, оның {o['shared_teachers']}-і басқа ОП-мен ортақ; "
                  f"1 сағат құны {fmt.money0(o['fot_per_hour'])} (университет: {fmt.money0(t['fot_per_hour'])}).",
                  f"{fmt.money0(o['fot_per_student'])} на студента (вуз: {fmt.money0(t['fot_per_student'])}). "
                  f"Часов ППС на студента {fmt.num(o['hours_per_student'], 1)} (вуз: {fmt.num(t['hours_per_student'], 1)}) — "
                  f"{len(o['teachers'])} преподавателей, из них {o['shared_teachers']} совместных; "
                  f"стоимость часа {fmt.money0(o['fot_per_hour'])} (вуз: {fmt.money0(t['fot_per_hour'])})."),
        "source": fmt.rows_ref("Нагрузка_ППС", [r for tch in o["teachers"] for r in tch["load_rows"]])
                  + "; " + fmt.rows_ref("Штат_ППС", [tch["staff_row"] for tch in o["teachers"]]),
    })
    factors.append({
        "key": "direct", "impact": gaps["direct"],
        "title": L(lang, "Тікелей шығындар", "Прямые затраты"),
        "text": L(lang,
                  f"{fmt.money0(o['direct'])} ({fmt.money0(o['direct_per_student'])} / студент, университет: "
                  f"{fmt.money0(t['direct_per_student'])}). Ең ірі бап: {top_direct['category'] if top_direct else '—'} "
                  f"{fmt.money0(top_direct['amount'] if top_direct else None)}.",
                  f"{fmt.money0(o['direct'])} ({fmt.money0(o['direct_per_student'])} на студента, вуз: "
                  f"{fmt.money0(t['direct_per_student'])}). Крупнейшая статья: {top_direct['category'] if top_direct else '—'} "
                  f"{fmt.money0(top_direct['amount'] if top_direct else None)}."),
        "source": fmt.rows_ref("Прямые_затраты", [r["row"] for r in o["direct_rows"]]),
    })
    factors.append({
        "key": "overhead", "impact": gaps["overhead"],
        "title": L(lang, "Жанама шығындар үлесі", "Доля накладных расходов"),
        "text": L(lang,
                  f"{fmt.money0(o['overhead'])} ({fmt.money0(o['overhead_per_student'])} / студент, университет: "
                  f"{fmt.money0(t['overhead_per_student'])}). Бір студентке аудан {fmt.num(area_ps, 2)} м² "
                  f"(университет: {fmt.num(area_ps_u, 2)}), зертхана сағаты {fmt.num(lab_ps, 2)} (университет: {fmt.num(lab_ps_u, 2)}).",
                  f"{fmt.money0(o['overhead'])} ({fmt.money0(o['overhead_per_student'])} на студента, вуз: "
                  f"{fmt.money0(t['overhead_per_student'])}). Площадь на студента {fmt.num(area_ps, 2)} м² "
                  f"(вуз: {fmt.num(area_ps_u, 2)}), лаб. часов {fmt.num(lab_ps, 2)} (вуз: {fmt.num(lab_ps_u, 2)})."),
        "source": f"Общие_затраты, Драйверы!{o['driver_row']}",
    })
    if s < 0.6 * median_students:
        fixed = o["fot"] + o["direct"]
        factors.append({
            "key": "scale", "impact": None,
            "title": L(lang, "Шағын контингент (масштаб әсері)", "Малый контингент (эффект масштаба)"),
            "text": L(lang,
                      f"{fmt.num(s, 0)} студент — медианадан ({fmt.num(median_students, 0)}) едәуір аз. "
                      f"ФОТ пен тікелей шығындар ({fmt.money0(fixed)}) студент санына тәуелсіз, сондықтан аз студентке бөлінеді.",
                      f"{fmt.num(s, 0)} студентов — существенно ниже медианы ({fmt.num(median_students, 0)}). "
                      f"ФОТ и прямые ({fmt.money0(fixed)}) почти не зависят от числа студентов и ложатся на меньшую базу."),
            "source": f"Драйверы!{o['driver_row']}",
        })
    ranked = sorted([f for f in factors if f["impact"] is not None], key=lambda f: abs(f["impact"]), reverse=True)
    extra = [f for f in factors if f["impact"] is None]
    factors = (ranked[:4] + extra)[:5]
    for f in factors:
        if f["impact"] is not None:
            f["direction"] = "plus" if f["impact"] >= 0 else "minus"
            f["impact_display"] = fmt.signed_money(f["impact"])

    options = _options(ds, pnl, o, t, gaps, lang)
    summary = L(lang,
                f"{o['name']}: кіріс {fmt.money(o['revenue'])}, шығын {fmt.money(o['total_cost'])}, нәтиже "
                f"{fmt.money(o['result'])}, рентабельділік {fmt.pct(o['margin'])}. Егер ОП университеттің бір студентке "
                f"шаққандағы орташа көрсеткіштерімен жұмыс істесе, нәтиже {fmt.money0(base)} болар еді; айырма "
                f"{fmt.signed_money(o['result'] - base)} төмендегі факторлармен толық түсіндіріледі.",
                f"{o['name']}: доход {fmt.money(o['revenue'])}, расходы {fmt.money(o['total_cost'])}, результат "
                f"{fmt.money(o['result'])}, рентабельность {fmt.pct(o['margin'])}. При средних по вузу показателях на "
                f"студента результат составил бы {fmt.money0(base)}; отклонение {fmt.signed_money(o['result'] - base)} "
                f"полностью раскладывается на факторы ниже.")
    return {"op_id": op_id, "name": o["name"], "summary": summary, "baseline": base,
            "gaps": gaps, "factors": factors, "options": options, "ethics": ethics(lang),
            "formula": "Нәтиже = N × (орт. нәтиже/студент) + N × Δкіріс/студ − N × ΔФОТ/студ − N × Δтікелей/студ − N × Δжанама/студ"}


def ethics(lang):
    return L(lang,
             "ОП-ны тек қаржылық нәтиже бойынша жабу туралы шешім қабылдауға болмайды: академиялық сапа, кадрлық әлеует, "
             "стратегиялық маңыз (мысалы, педагогтар мен медбикелер тапшылығы) және әлеуметтік негіздер бірге қаралуы тиіс.",
             "Нельзя решать о закрытии ОП только по финансовому результату: нужны академические, кадровые, "
             "стратегические и социальные основания.")


def _options(ds, pnl, o, t, gaps, lang):
    opts = []
    be = break_even(ds, o["op_id"])
    if o["result"] < 0:
        if be["reachable"]:
            opts.append({
                "title": L(lang, f"Контингентті +{fmt.num(be['pct'], 1)}% арттыру (≈{fmt.num(be['students'], 0)} студент)",
                           f"Увеличить контингент на +{fmt.num(be['pct'], 1)}% (≈{fmt.num(be['students'], 0)} студентов)"),
                "effect": L(lang, "Нәтиже 0-ге жетеді (сценарийдің базалық моделі: кіріс ∝ студенттер, ФОТ пен тікелей тұрақты).",
                            "Результат выходит в ноль (базовая модель сценария: доход ∝ студентам, ФОТ и прямые неизменны)."),
                "risks": L(lang, "Өтінімдер жеткіліксіз болуы мүмкін; конверсияны көтеру талапкерлер сапасын төмендетеді; "
                           "аудитория/оқытушы сыйымдылығы шектеулі — ФОТ бір сәтте өсуі мүмкін.",
                           "Может не хватить заявок; рост конверсии снижает качество абитуриентов; ограничена ёмкость "
                           "аудиторий и ППС — ФОТ может вырасти скачком."),
            })
        else:
            opts.append({"title": L(lang, "Контингентпен ғана шешілмейді", "Только набором не решается"),
                         "effect": be.get("note", ""), "risks": "—"})
        paid_units = o["paid_full"] + o["discounted"] * (1 - (o["discount_rate"] or 0))
        if paid_units and o["tariff"]:
            t_be = (o["total_cost"] - o["revenue_grant"]) / paid_units
            opts.append({
                "title": L(lang, f"Тарифті {fmt.money0(t_be)} деңгейіне қайта қарау ({fmt.pct(_rel(t_be, o['tariff']), 1)})",
                           f"Пересмотр тарифа до {fmt.money0(t_be)} ({fmt.pct(_rel(t_be, o['tariff']), 1)})"),
                "effect": L(lang, "Ақылы студенттер саны өзгермесе, нәтиже 0-ге жетеді: тариф = (шығын − грант кірісі) / "
                            "(толық + жеңілдікті × (1 − жеңілдік)).",
                            "При неизменном числе платных результат = 0: тариф = (расходы − грантовый доход) / "
                            "(полные + скидочные × (1 − скидка))."),
                "risks": L(lang, "Сұраныс икемділігі: бағаның өсуі өтінімдерді азайтады; бәсекелестік және қолжетімділік "
                           "(әлеуметтік әсер); тарифті өзгерту қаржы-экономикалық қызметтің бекітуін талап етеді.",
                           "Эластичность спроса: рост цены снижает заявки; конкурентность и доступность; изменение тарифа "
                           "требует утверждения финансово-экономической службой."),
            })
    if gaps["fot"] < 0 and o["hours_per_student"] and t["hours_per_student"]:
        saving = o["fot"] * max(0.0, 1 - t["hours_per_student"] / o["hours_per_student"]) * 0.5
        opts.append({
            "title": L(lang, "Ортақ пәндер бойынша ағындарды біріктіру / жүктемені оңтайландыру",
                       "Объединение потоков по общим дисциплинам / оптимизация нагрузки"),
            "effect": L(lang, f"Бағалау: сағат/студент айырмасының жартысын жапса — ФОТ шамамен {fmt.money0(saving)}-ге азаяды "
                        f"(болжам: ФОТ сағатқа пропорционал).",
                        f"Оценка: если закрыть половину разрыва часов на студента — ФОТ снизится примерно на {fmt.money0(saving)} "
                        f"(допущение: ФОТ пропорционален часам)."),
            "risks": L(lang, "Топтардың үлкеюі оқыту сапасына әсер етеді; аккредитация нормалары; оқытушылардың шамадан тыс "
                       "жүктемесі және кадрлардың кетуі.",
                       "Рост групп влияет на качество; нормы аккредитации; перегрузка и отток преподавателей."),
        })
    if gaps["direct"] < 0 and o["direct_per_student"] and t["direct_per_student"]:
        saving = (o["direct_per_student"] - t["direct_per_student"]) * o["students"] * 0.3
        opts.append({
            "title": L(lang, "Зертханалар мен лицензияларды басқа ОП-мен ортақ пайдалану",
                       "Совместное использование лабораторий и лицензий с другими ОП"),
            "effect": L(lang, f"Бағалау: орташадан артық бөлігінің 30%-ы — шамамен {fmt.money0(saving)} үнемдеу.",
                        f"Оценка: 30% от превышения над средним — около {fmt.money0(saving)} экономии."),
            "risks": L(lang, "Практикалық дайындық сапасы, кесте қақтығыстары, жабдықтың тозуы.",
                       "Качество практической подготовки, конфликты расписания, износ оборудования."),
        })
    if o["result"] >= 0:
        sc = run_scenario(ds, pnl, o["op_id"], 10)
        opts.append({
            "title": L(lang, "Сапаны сақтай отырып қабылдауды +10% кеңейту", "Расширить набор на +10% при сохранении качества"),
            "effect": L(lang, f"Сценарий: ОП нәтижесі {fmt.signed_money(sc['selected']['delta']['result'])}, "
                        f"университет нәтижесі {fmt.signed_money(sc['totals']['after']['result'] - sc['totals']['before']['result'])}.",
                        f"Сценарий: результат ОП {fmt.signed_money(sc['selected']['delta']['result'])}, "
                        f"результат вуза {fmt.signed_money(sc['totals']['after']['result'] - sc['totals']['before']['result'])}."),
            "risks": L(lang, "Аудитория мен оқытушы сыйымдылығы; ФОТ өзгермейді деген болжам +10%-дан жоғары жарамсыз.",
                       "Ёмкость аудиторий и ППС; допущение о неизменном ФОТ не работает при большом росте."),
        })
        opts.append({
            "title": L(lang, "Профицитті сапаға реинвестициялау", "Реинвестировать профицит в качество"),
            "effect": L(lang, "Зертханаларды жаңарту, оқытушыларды дамыту, шығынды стратегиялық ОП-ларды қолдау.",
                        "Обновление лабораторий, развитие ППС, поддержка стратегически важных убыточных ОП."),
            "risks": L(lang, "Бүгінгі маржа тұрақты деп есептеу қаупі: нарық пен грант квоталары өзгереді.",
                       "Риск считать текущую маржу устойчивой: рынок и квоты грантов меняются."),
        })
    return opts[:4] if len(opts) >= 2 else opts
