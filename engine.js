/*
 * Profitability AI — есептеу ядросы.
 * Барлық сумманы осы код есептейді. AI тек осы нәтижелерді оқиды және түсіндіреді.
 * Браузерде: window.PAI. Node-та: require("./engine.js").
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PAI = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---------- Excel құрылымы ----------
  const SCHEMA = {
    "ОП": ["op_id", "название_ОП", "факультет", "уровень", "срок_обучения_лет", "учебный_год"],
    "Контингент": ["op_id", "курс", "контракт_полный", "контракт_со_скидкой", "грант", "тариф_контракт_тг", "финансирование_грант_тг", "скидка_доля"],
    "Штат_ППС": ["teacher_id", "зарплата_в_месяц_тг", "месяцев_оплаты", "начисления_работодателя_доля"],
    "Нагрузка_ППС": ["teacher_id", "op_id", "часы_в_год"],
    "Прямые_затраты": ["cost_id", "op_id", "категория", "сумма_в_год_тг"],
    "Общие_затраты": ["cost_center_id", "статья", "сумма_в_год_тг", "драйвер_распределения"],
    "Драйверы": ["op_id", "студентов_активных", "площадь_м2", "лабораторные_часы"],
    "История_набора": ["op_id", "учебный_год", "заявок", "зачислено", "план_набора"],
    "Сырые_сигналы": ["source_row_id", "op_id", "показатель", "учебный_год", "значение"]
  };
  const NUMERIC = {
    "ОП": ["срок_обучения_лет"],
    "Контингент": ["курс", "контракт_полный", "контракт_со_скидкой", "грант", "тариф_контракт_тг", "финансирование_грант_тг", "скидка_доля"],
    "Штат_ППС": ["зарплата_в_месяц_тг", "месяцев_оплаты", "начисления_работодателя_доля"],
    "Нагрузка_ППС": ["часы_в_год"],
    "Прямые_затраты": ["сумма_в_год_тг"],
    "Общие_затраты": ["сумма_в_год_тг"],
    "Драйверы": ["студентов_активных", "площадь_м2", "лабораторные_часы"],
    "История_набора": ["заявок", "зачислено", "план_набора"]
  };
  const SHARES = { "Контингент": ["скидка_доля"], "Штат_ППС": ["начисления_работодателя_доля"] };
  const UNIQUE = { "ОП": "op_id", "Штат_ППС": "teacher_id", "Прямые_затраты": "cost_id", "Общие_затраты": "cost_center_id", "Драйверы": "op_id" };
  const REF_OP = ["Контингент", "Нагрузка_ППС", "Прямые_затраты", "Драйверы", "История_набора"];
  const DRIVER_MAP = { students: "студентов_активных", area_m2: "площадь_м2", lab_hours: "лабораторные_часы" };
  const DRIVER_LABEL = { students: "белсенді студенттер", area_m2: "аудан, м²", lab_hours: "зертхана сағаты" };
  const SIGNAL_METRICS = { applications: "өтінім саны", conversion_pct: "конверсия, %" };

  const FORMULAS = {
    revenue: "Табыс = Σ(контракт_полный × тариф_контракт + контракт_со_скидкой × тариф_контракт × (1 − скидка_доля) + грант × финансирование_грант)",
    fotTeacher: "Жылдық ФОТ = зарплата_в_месяц × месяцев_оплаты × (1 + начисления_работодателя_доля)",
    fotOp: "ФОТ үлесі = жылдық ФОТ × оқытушының осы БББ-дағы сағаты ÷ оның барлық сағаты",
    direct: "Тікелей шығын = Прямые_затраты парағындағы осы op_id жолдарының қосындысы",
    overhead: "Жанама шығын = Σ орталық сомасы × БББ драйвері ÷ 12 БББ драйверінің қосындысы",
    total: "Жалпы шығын = ФОТ + тікелей + жанама",
    result: "Қаржылық нәтиже = табыс − жалпы шығын",
    margin: "Рентабельділік = нәтиже ÷ табыс × 100%",
    cps: "1 студенттің өзіндік құны = жалпы шығын ÷ белсенді студенттер"
  };

  // ---------- көмекшілер ----------
  const clean = (s) => String(s == null ? "" : s).trim();
  function toNum(v) {
    if (typeof v === "number") return Number.isFinite(v) ? v : NaN;
    if (typeof v === "string") {
      const s = v.replace(/[\s ]/g, "").replace(",", ".");
      if (s !== "" && !isNaN(+s)) return +s;
    }
    return NaN;
  }
  const isEmpty = (v) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");
  const sum = (a) => a.reduce((s, v) => s + v, 0);
  function median(a) {
    const s = [...a].filter(Number.isFinite).sort((x, y) => x - y);
    if (!s.length) return NaN;
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /**
   * Excel парақтарын тексереді және есептеуге дайын деректерге айналдырады.
   * raw: { парақАты: [{баған: мән, _row: Excel жол нөмірі}] }
   * Ақаулы жол есептен шығарылады және issues тізіміне жазылады (база бұзылмайды).
   */
  function normalize(raw) {
    const issues = [];
    const add = (level, sheet, row, msg) => issues.push({ level, sheet, row, msg });
    const byKey = {};
    Object.keys(raw || {}).forEach((k) => { byKey[clean(k).toLowerCase()] = k; });
    const sheets = {};
    const summary = [];

    for (const name of Object.keys(SCHEMA)) {
      const real = byKey[name.toLowerCase()];
      if (!real) { add("fatal", name, null, `«${name}» парағы табылмады.`); summary.push({ sheet: name, found: false, rows: 0, used: 0 }); continue; }
      const rows = (raw[real] || []).map((r) => {
        const o = { _row: r._row };
        for (const k of Object.keys(r)) if (k !== "_row") o[clean(k)] = typeof r[k] === "string" ? r[k].trim() : r[k];
        return o;
      }).filter((r) => Object.keys(r).some((k) => k !== "_row" && !isEmpty(r[k])));
      const cols = new Set(rows.flatMap((r) => Object.keys(r)));
      const missing = SCHEMA[name].filter((c) => !cols.has(c));
      if (missing.length && rows.length) { add("fatal", name, null, `«${name}» парағында бағандар жоқ: ${missing.join(", ")}.`); }
      sheets[name] = { rows, missingCols: missing };
      summary.push({ sheet: name, found: true, rows: rows.length, used: 0 });
    }
    if (issues.some((i) => i.level === "fatal")) return { ok: false, issues, summary, data: null };

    const opIds = new Set();
    const data = {};
    for (const name of Object.keys(SCHEMA)) {
      if (name === "Сырые_сигналы") continue;
      const kept = [];
      const seen = new Map();
      for (const r of sheets[name].rows) {
        const errs = [];
        for (const c of SCHEMA[name]) if (isEmpty(r[c])) errs.push(`«${c}» бос`);
        for (const c of NUMERIC[name] || []) {
          if (isEmpty(r[c])) continue;
          const v = toNum(r[c]);
          if (!Number.isFinite(v)) errs.push(`«${c}» сан емес (${r[c]})`);
          else if (v < 0) errs.push(`«${c}» теріс (${v})`);
          else r[c] = v;
        }
        for (const c of SHARES[name] || []) if (Number.isFinite(r[c]) && r[c] > 1) errs.push(`«${c}» үлесі 1-ден үлкен (${r[c]})`);
        const u = UNIQUE[name];
        if (u && !isEmpty(r[u])) {
          if (seen.has(r[u])) errs.push(`${u}=${r[u]} қайталанады (алғашқысы ${seen.get(r[u])}-жолда)`);
          else seen.set(r[u], r._row);
        }
        if (name === "Общие_затраты" && !isEmpty(r["драйвер_распределения"]) && !DRIVER_MAP[r["драйвер_распределения"]])
          errs.push(`белгісіз драйвер «${r["драйвер_распределения"]}»`);
        if (REF_OP.includes(name) && !isEmpty(r.op_id) && opIds.size && !opIds.has(r.op_id)) errs.push(`op_id=${r.op_id} «ОП» парағында жоқ`);
        if (errs.length) add("error", name, r._row, errs.join("; ") + ". Жол есептен шығарылды.");
        else kept.push(r);
      }
      if (name === "ОП") kept.forEach((r) => opIds.add(r.op_id));
      data[name] = kept;
      const s = summary.find((x) => x.sheet === name); if (s) s.used = kept.length;
    }
    data["Сырые_сигналы"] = sheets["Сырые_сигналы"].rows;
    const ss = summary.find((x) => x.sheet === "Сырые_сигналы"); if (ss) ss.used = 0;

    // Сілтеме тексерістері
    const staff = new Set(data["Штат_ППС"].map((t) => t.teacher_id));
    data["Нагрузка_ППС"] = data["Нагрузка_ППС"].filter((l) => {
      if (staff.has(l.teacher_id)) return true;
      add("error", "Нагрузка_ППС", l._row, `teacher_id=${l.teacher_id} «Штат_ППС» парағында жоқ. Жол есептен шығарылды.`);
      return false;
    });
    const loaded = new Set(data["Нагрузка_ППС"].map((l) => l.teacher_id));
    data["Штат_ППС"].forEach((t) => { if (!loaded.has(t.teacher_id)) add("warning", "Штат_ППС", t._row, `${t.teacher_id} оқытушысының жүктемесі жоқ, оның ФОТ-ы бағдарламаларға бөлінбейді.`); });
    const drv = new Set(data["Драйверы"].map((d) => d.op_id));
    for (const id of opIds) if (!drv.has(id)) add("error", "Драйверы", null, `${id} үшін драйвер жолы жоқ, жанама шығын 0 деп алынады.`);
    // Контингент пен драйвердегі студент санының сәйкестігі
    const cnt = {};
    data["Контингент"].forEach((c) => { cnt[c.op_id] = (cnt[c.op_id] || 0) + c["контракт_полный"] + c["контракт_со_скидкой"] + c["грант"]; });
    data["Драйверы"].forEach((d) => {
      if (cnt[d.op_id] !== undefined && cnt[d.op_id] !== d["студентов_активных"])
        add("warning", "Драйверы", d._row, `${d.op_id}: белсенді студенттер ${d["студентов_активных"]}, ал «Контингент» бойынша ${cnt[d.op_id]}.`);
    });
    if (opIds.size === 0) add("fatal", "ОП", null, "Бірде-бір жарамды бағдарлама жоқ.");
    return { ok: !issues.some((i) => i.level === "fatal"), issues, summary, data };
  }

  /**
   * Кейс әдістемесі бойынша P&L. scenario = {op_id, pct} болса:
   * табыс студент санына пропорционал, ФОТ пен тікелей шығын өзгермейді,
   * students драйвері бар жанама орталықтар жаңа драйвер бойынша қайта бөлінеді.
   */
  function compute(d, scenario) {
    const f = (id) => (scenario && scenario.op_id === id ? 1 + scenario.pct / 100 : 1);
    const ops = d["ОП"].map((o) => ({
      op_id: o.op_id, name: o["название_ОП"], faculty: o["факультет"], level: o["уровень"], years: o["срок_обучения_лет"], _row: o._row,
      revenue: 0, revenueBase: 0, rev: { full: 0, disc: 0, grant: 0 }, revRows: [],
      contingent: { full: 0, disc: 0, grant: 0 },
      fot: 0, fotRows: [], direct: 0, directRows: [], overhead: 0, ohRows: [],
      students: 0, studentsBase: 0, driverRow: null
    }));
    const by = Object.fromEntries(ops.map((o) => [o.op_id, o]));

    for (const c of d["Контингент"]) {
      const o = by[c.op_id]; if (!o) continue;
      const t = c["тариф_контракт_тг"], disc = c["скидка_доля"];
      const full = c["контракт_полный"] * t, dsc = c["контракт_со_скидкой"] * t * (1 - disc), gr = c["грант"] * c["финансирование_грант_тг"];
      o.rev.full += full; o.rev.disc += dsc; o.rev.grant += gr; o.revenueBase += full + dsc + gr;
      o.contingent.full += c["контракт_полный"]; o.contingent.disc += c["контракт_со_скидкой"]; o.contingent.grant += c["грант"];
      o.revRows.push({ row: c._row, course: c["курс"], full: c["контракт_полный"], disc: c["контракт_со_скидкой"], grant: c["грант"], tariff: t, grantFund: c["финансирование_грант_тг"], discount: disc, amount: full + dsc + gr });
    }
    ops.forEach((o) => { o.revenue = o.revenueBase * f(o.op_id); });

    const staff = Object.fromEntries(d["Штат_ППС"].map((t) => [t.teacher_id, t]));
    const annual = (t) => t["зарплата_в_месяц_тг"] * t["месяцев_оплаты"] * (1 + t["начисления_работодателя_доля"]);
    const hours = {};
    d["Нагрузка_ППС"].forEach((l) => { hours[l.teacher_id] = (hours[l.teacher_id] || 0) + l["часы_в_год"]; });
    for (const l of d["Нагрузка_ППС"]) {
      const o = by[l.op_id], t = staff[l.teacher_id]; if (!o || !t) continue;
      const a = annual(t), th = hours[l.teacher_id];
      const alloc = th > 0 ? a * l["часы_в_год"] / th : 0;
      o.fot += alloc;
      o.fotRows.push({ row: l._row, teacher_id: l.teacher_id, staffRow: t._row, salary: t["зарплата_в_месяц_тг"], months: t["месяцев_оплаты"], charge: t["начисления_работодателя_доля"],
        hours: l["часы_в_год"], totalHours: th, annual: a, share: th > 0 ? l["часы_в_год"] / th : 0, alloc });
    }
    const fotAnnualTotal = sum(d["Штат_ППС"].map(annual));
    const fotUnallocated = sum(d["Штат_ППС"].filter((t) => !(hours[t.teacher_id] > 0)).map(annual));

    for (const c of d["Прямые_затраты"]) {
      const o = by[c.op_id]; if (!o) continue;
      o.direct += c["сумма_в_год_тг"];
      o.directRows.push({ row: c._row, cost_id: c.cost_id, category: c["категория"], amount: c["сумма_в_год_тг"] });
    }

    const drivers = Object.fromEntries(d["Драйверы"].map((r) => [r.op_id, r]));
    ops.forEach((o) => {
      const r = drivers[o.op_id];
      o.driverRow = r ? r._row : null;
      o.studentsBase = r ? r["студентов_активных"] : 0;
      o.students = o.studentsBase * f(o.op_id);
    });
    const drvVal = (o, key) => {
      const r = drivers[o.op_id]; if (!r) return 0;
      return key === "студентов_активных" ? o.students : r[key];
    };
    let ohTotal = 0;
    for (const c of d["Общие_затраты"]) {
      const key = DRIVER_MAP[c["драйвер_распределения"]];
      const total = sum(ops.map((o) => drvVal(o, key)));
      ohTotal += c["сумма_в_год_тг"];
      for (const o of ops) {
        const v = drvVal(o, key);
        const alloc = total > 0 ? c["сумма_в_год_тг"] * v / total : 0;
        o.overhead += alloc;
        o.ohRows.push({ row: c._row, center: c.cost_center_id, name: c["статья"], amount: c["сумма_в_год_тг"], driver: c["драйвер_распределения"], opValue: v, totalValue: total, alloc });
      }
    }

    ops.forEach((o) => {
      o.total = o.fot + o.direct + o.overhead;
      o.result = o.revenue - o.total;
      o.margin = o.revenue !== 0 ? (o.result / o.revenue) * 100 : null;
      o.cps = o.students > 0 ? o.total / o.students : null;
      o.fotPerStudent = o.students > 0 ? o.fot / o.students : null;
      o.revPerStudent = o.students > 0 ? o.revenue / o.students : null;
      o.directPerStudent = o.students > 0 ? o.direct / o.students : null;
      o.teachers = new Set(o.fotRows.map((r) => r.teacher_id)).size;
      o.hours = sum(o.fotRows.map((r) => r.hours));
    });
    const T = {
      revenue: sum(ops.map((o) => o.revenue)), fot: sum(ops.map((o) => o.fot)), direct: sum(ops.map((o) => o.direct)),
      overhead: sum(ops.map((o) => o.overhead)), students: sum(ops.map((o) => o.students))
    };
    T.total = T.fot + T.direct + T.overhead; T.result = T.revenue - T.total;
    T.margin = T.revenue ? (T.result / T.revenue) * 100 : null;
    T.cps = T.students ? T.total / T.students : null;
    const checks = [
      { id: "fot", label: "Бөлінген ФОТ = барлық оқытушылардың жылдық ФОТ-ы", expected: fotAnnualTotal - fotUnallocated, actual: T.fot, note: fotUnallocated ? `Жүктемесі жоқ оқытушылардың ${fotUnallocated} ₸ ФОТ-ы бөлінбеді` : "" },
      { id: "oh", label: "Бөлінген жанама шығын = «Общие_затраты» қосындысы", expected: ohTotal, actual: T.overhead, note: "" }
    ].map((c) => ({ ...c, diff: c.actual - c.expected, pass: Math.abs(c.actual - c.expected) <= 1 }));
    return { ops, totals: T, checks, fotAnnualTotal, fotUnallocated, ohTotal, scenario: scenario || null };
  }

  /** «Сырые_сигналы» сапасын тексереді. P&L-ге ешқашан қосылмайды. */
  function detectAnomalies(d) {
    const rows = d["Сырые_сигналы"] || [];
    const opIds = new Set(d["ОП"].map((o) => o.op_id));
    const years = new Set([...d["ОП"].map((o) => clean(o["учебный_год"])), ...d["История_набора"].map((h) => clean(h["учебный_год"]))]);
    const seen = new Map();
    const anomalies = [], clean_ = [];
    for (const r of rows) {
      const found = [];
      const id = clean(r.source_row_id);
      if (!id) found.push({ type: "ID жоқ", why: "Жолдың source_row_id идентификаторы бос, сондықтан оны қадағалау мүмкін емес.", action: "Дереккөз жүйесінен ID-ді қалпына келтіру." });
      else if (seen.has(id)) found.push({ type: "Қайталанған ID", why: `${id} идентификаторы ${seen.get(id)}-жолда бар. Бір көрсеткіш екі рет есептелуі мүмкін.`, action: "Көшірмені жою немесе жаңа бірегей ID беру." });
      if (id && !seen.has(id)) seen.set(id, r._row);
      if (!opIds.has(clean(r.op_id))) found.push({ type: "Белгісіз БББ", why: `op_id=${clean(r.op_id) || "бос"} «ОП» анықтамалығында жоқ.`, action: "БББ кодын анықтамалықпен салыстырып түзету немесе жолды алып тастау." });
      const metric = clean(r["показатель"]);
      if (!SIGNAL_METRICS[metric]) found.push({ type: "Белгісіз көрсеткіш", why: `«${metric}» көрсеткіші сипатталмаған.`, action: "Көрсеткіштер анықтамалығын тексеру." });
      const y = clean(r["учебный_год"]);
      const m = y.match(/^(\d{4})\s*[–-]\s*(\d{4})$/);
      if (!years.has(y)) found.push({ type: "Жарамсыз кезең", why: `«${y || "бос"}» оқу жылы деректер кезеңіне (${[...years].sort().join(", ")}) кірмейді${m && +m[1] > new Date().getFullYear() + 5 ? ", әрі тым алыс болашақ" : ""}.`, action: "Оқу жылын түзету немесе жолды мұрағатқа жіберу." });
      const vRaw = r["значение"];
      const v = toNum(vRaw);
      if (isEmpty(vRaw)) found.push({ type: "Мән жоқ", why: "«значение» бос. Оны 0 деп алу қате қорытындыға әкеледі.", action: "Мәнді дереккөзден сұрату, оған дейін талдаудан шығару." });
      else if (!Number.isFinite(v)) found.push({ type: "Сан емес", why: `«${vRaw}» сан емес.`, action: "Мән пішімін түзету." });
      else {
        if (v < 0) found.push({ type: "Теріс мән", why: `${SIGNAL_METRICS[metric] || metric} теріс бола алмайды (${v}).`, action: "Белгі қатесін немесе енгізу қатесін тексеру." });
        if (metric === "conversion_pct" && v > 100) found.push({ type: "100%-дан асқан пайыз", why: `Конверсия ${v}%. Пайыз 0–100 аралығында болуы керек.`, action: "Есептеу формуласын (зачислено ÷ заявок) және бірлікті тексеру." });
        if (metric === "applications" && !Number.isInteger(v)) found.push({ type: "Бөлшек сан", why: `Өтінім саны бүтін болуы керек (${v}).`, action: "Мәнді тексеру." });
      }
      if (found.length) anomalies.push({ source_row_id: id || "—", row: r._row, op_id: clean(r.op_id), metric, year: y, value: vRaw, comment: clean(r["источник_комментарий"]), issues: found, type: found.map((x) => x.type).join(" + ") });
      else clean_.push(r);
    }
    // Ішкі деректермен салыстыру (ақпарат ретінде)
    const hist = {};
    d["История_набора"].forEach((h) => { hist[h.op_id + "|" + clean(h["учебный_год"])] = h; });
    let compared = 0, mismatched = 0;
    clean_.forEach((r) => {
      if (clean(r["показатель"]) !== "applications") return;
      const h = hist[clean(r.op_id) + "|" + clean(r["учебный_год"])];
      if (!h) return; compared++;
      if (toNum(r["значение"]) !== h["заявок"]) mismatched++;
    });
    const info = compared ? [`Сыртқы жүйедегі өтінім саны ${compared} БББ-ның ${mismatched}-інде «История_набора» парағымен сәйкес келмейді. Сондықтан «Сырые_сигналы» тек сапа тексерісіне қолданылады және P&L-ге кірмейді.`] : [];
    return { anomalies, clean: clean_, total: rows.length, info };
  }

  /** «История_набора» бойынша келесі жылдың болжамы (сызықтық тренд + 80% болжам аралығы). */
  function forecast(d) {
    const T80_DF1 = 3.078; // Стьюдент t, 80%, еркіндік дәрежесі = 3 − 2 = 1
    const out = [];
    for (const o of d["ОП"]) {
      const h = d["История_набора"].filter((x) => x.op_id === o.op_id).sort((a, b) => clean(a["учебный_год"]).localeCompare(clean(b["учебный_год"])));
      if (h.length < 2) { out.push({ op_id: o.op_id, name: o["название_ОП"], n: h.length, insufficient: true }); continue; }
      const fit = (key) => {
        const ys = h.map((x) => x[key]), n = ys.length, xs = ys.map((_, i) => i);
        const mx = sum(xs) / n, my = sum(ys) / n;
        const sxx = sum(xs.map((x) => (x - mx) ** 2));
        const b = sum(xs.map((x, i) => (x - mx) * (ys[i] - my))) / sxx, a = my - b * mx;
        const x0 = n, point = a + b * x0;
        const sse = sum(xs.map((x, i) => (ys[i] - (a + b * x)) ** 2));
        const s = n > 2 ? Math.sqrt(sse / (n - 2)) : NaN;
        const half = n > 2 ? T80_DF1 * s * Math.sqrt(1 + 1 / n + (x0 - mx) ** 2 / sxx) : NaN;
        // s = 0: үш нүкте бір түзудің бойында, қателікті бағалау мүмкін емес (бұл «белгісіздік жоқ» дегенді білдірмейді)
        const exactFit = n > 2 && sse < 1e-9;
        return { values: ys, slope: b, point, lo: exactFit ? null : Math.max(0, point - half), hi: exactFit ? null : point + half, half, exactFit };
      };
      const apps = fit("заявок"), enr = fit("зачислено");
      const conv = sum(h.map((x) => x["зачислено"])) / sum(h.map((x) => x["заявок"]));
      const last = h[h.length - 1];
      out.push({ op_id: o.op_id, name: o["название_ОП"], n: h.length, years: h.map((x) => clean(x["учебный_год"])), rows: h.map((x) => x._row),
        apps, enr, conv, lastPlan: last["план_набора"], lastEnr: last["зачислено"], planFill: last["план_набора"] ? last["зачислено"] / last["план_набора"] : null });
    }
    return out;
  }

  /** «БББ-ны түсіндір»: медианамен салыстырып 3–5 фактор және кемінде 2 басқару нұсқасы. */
  function explainOp(res, op_id) {
    const o = res.ops.find((x) => x.op_id === op_id); if (!o) return null;
    const med = (k) => median(res.ops.map((x) => x[k]));
    const dev = (v, m) => (m ? (v - m) / m * 100 : 0);
    const grantShare = o.revenue ? o.rev.grant / o.revenue * 100 : 0;
    const contract = o.contingent.full + o.contingent.disc;
    const discShare = contract ? o.contingent.disc / contract * 100 : 0;
    const ohShare = o.total ? o.overhead / o.total * 100 : 0;
    const cand = [
      { key: "students", w: Math.abs(dev(o.students, med("students"))), bad: o.students < med("students"),
        text: `Контингент: ${fmt0(o.students)} белсенді студент, медиана ${fmt0(med("students"))} (${pctS(dev(o.students, med("students")))}). ${o.students < med("students") ? "Топ шағын, сондықтан тұрақты ФОТ аз студентке бөлінеді." : "Ірі топ шығынды көп студентке таратады."}`,
        src: `Драйверы, ${o.driverRow}-жол` },
      { key: "fotPerStudent", w: Math.abs(dev(o.fotPerStudent, med("fotPerStudent"))), bad: o.fotPerStudent > med("fotPerStudent"),
        text: `1 студентке ФОТ: ${fmt0(o.fotPerStudent)} ₸, медиана ${fmt0(med("fotPerStudent"))} ₸ (${pctS(dev(o.fotPerStudent, med("fotPerStudent")))}). ${o.teachers} оқытушы, ${fmt0(o.hours)} сағат.`,
        src: `Нагрузка_ППС, ${o.fotRows.length} жол; Штат_ППС` },
      { key: "revPerStudent", w: Math.abs(dev(o.revPerStudent, med("revPerStudent"))), bad: o.revPerStudent < med("revPerStudent"),
        text: `1 студенттен табыс: ${fmt0(o.revPerStudent)} ₸, медиана ${fmt0(med("revPerStudent"))} ₸ (${pctS(dev(o.revPerStudent, med("revPerStudent")))}). Тариф ${fmt0(o.revRows[0] ? o.revRows[0].tariff : 0)} ₸.`,
        src: `Контингент, ${o.revRows.map((r) => r.row).join(", ")}-жолдар` },
      { key: "directPerStudent", w: Math.abs(dev(o.directPerStudent, med("directPerStudent"))), bad: o.directPerStudent > med("directPerStudent"),
        text: `1 студентке тікелей шығын: ${fmt0(o.directPerStudent)} ₸, медиана ${fmt0(med("directPerStudent"))} ₸ (${pctS(dev(o.directPerStudent, med("directPerStudent")))}). Барлығы ${fmt0(o.direct)} ₸.`,
        src: `Прямые_затраты, ${o.directRows.map((r) => r.cost_id).join(", ")}` },
      { key: "grant", w: Math.abs(grantShare - 30), bad: false,
        text: `Табыстың ${fx1(grantShare)}%-ы грант, ${fx1(100 - grantShare)}%-ы келісімшарт. Жеңілдікпен оқитындар келісімшарт студенттерінің ${fx1(discShare)}%-ы.`,
        src: "Контингент" },
      { key: "oh", w: Math.abs(ohShare - 30) / 2, bad: ohShare > 35,
        text: `Жанама шығын жалпы шығынның ${fx1(ohShare)}%-ы (${fmt0(o.overhead)} ₸). Ол студент саны, аудан және зертхана сағаты бойынша бөлінеді.`,
        src: "Общие_затраты × Драйверы" }
    ].filter((c) => Number.isFinite(c.w));
    const loss = o.result < 0;
    cand.sort((a, b) => (loss ? (b.bad - a.bad) : 0) || b.w - a.w);
    const factors = cand.slice(0, loss ? 5 : 4);
    const options = [];
    if (o.students < med("students")) options.push({ title: "Қабылдауды көбейту немесе ағындарды біріктіру", effect: "Студент саны артқанда тұрақты ФОТ көп студентке бөлінеді, бір студенттің өзіндік құны төмендейді.", risk: "Сұраныс жеткіліксіз болуы мүмкін. Топ ірілеуі сапаға әсер етуі мүмкін." });
    if (o.fotPerStudent > med("fotPerStudent")) options.push({ title: "Ортақ пәндерді басқа БББ-мен бірге оқыту", effect: "Оқытушы сағаттарының бір бөлігі бірнеше БББ-ға бөлінеді, бұл БББ-ның ФОТ үлесі азаяды.", risk: "Оқытушы жүктемесі мен кесте күрделенеді, аккредиттеу талаптарын тексеру керек." });
    if (o.directPerStudent > med("directPerStudent")) options.push({ title: "Зертхана мен жабдықты ортақ пайдалану", effect: "Тікелей шығынның бір бөлігін басқа БББ-мен бөлісу.", risk: "Клиникалық/зертханалық базаға қойылатын талаптар бұзылмауы керек." });
    if (o.revPerStudent < med("revPerStudent")) options.push({ title: "Тариф пен жеңілдік саясатын қайта қарау", effect: "1 студенттен түсетін табысты арттыру.", risk: "Баға өссе, өтінім саны азаюы мүмкін. Бәсекелес бағаларын талдау керек." });
    if (!loss) options.push({ title: "Сапаны сақтап, өсуге инвестиция", effect: "Пайда бағдарламаны дамытуға (жаңа трек, халықаралық топ) жұмсалады.", risk: "Инвестиция қайтарымы бірден көрінбейді." });
    options.push({ title: "Демеушілік және серіктестік", effect: "Жұмыс берушілермен бірлескен бағдарлама, мақсатты грант немесе жабдық демеушілігі.", risk: "Серіктеске тәуелділік, келісімшарт міндеттемелері." });
    return {
      op: o, loss, factors, options: options.slice(0, 3),
      ethics: "Бағдарламаны тек қаржылық нәтиже бойынша жабу ұсынылмайды. Шешім академиялық, кадрлық, стратегиялық және әлеуметтік негіздемені қажет етеді."
    };
  }

  function fmt0(v) { return Number.isFinite(v) ? Math.round(v).toLocaleString("ru-RU") : "н/д"; }
  function fx1(v) { return v.toFixed(1).replace(".", ","); }
  function pctS(v) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(0) + "%"; }

  return { SCHEMA, FORMULAS, DRIVER_MAP, DRIVER_LABEL, SIGNAL_METRICS, normalize, compute, detectAnomalies, forecast, explainOp, median, toNum };
});
