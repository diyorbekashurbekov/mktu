// Кейстің 7-бөліміндегі қабылдау сынақтары. Іске қосу: node tests/engine.test.js
const fs = require("fs");
const path = require("path");
const PAI = require("../engine.js");

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixture.json"), "utf8"));
const ref = JSON.parse(fs.readFileSync(path.join(__dirname, "reference.json"), "utf8"));

let failed = 0, passed = 0;
function check(name, ok, detail) {
  if (ok) { passed++; console.log("  ✓", name); }
  else { failed++; console.log("  ✗", name, detail || ""); }
}
const close = (a, b, tol) => a === null || b === null ? a === b : Math.abs(a - b) <= tol;

function comparePnl(res, expected, label) {
  for (const [id, e] of Object.entries(expected)) {
    const o = res.ops.find((x) => x.op_id === id);
    const bad = ["revenue", "fot", "direct", "overhead", "total", "result", "cps"].filter((k) => !close(o[k], e[k], 1));
    if (!close(o.margin, e.margin, 0.01)) bad.push("margin");
    check(`${label} ${id} ${o.name}`, bad.length === 0, bad.map((k) => `${k}: ${o[k]} ≠ ${e[k]}`).join("; "));
  }
}

console.log("1. Файл қолмен түзетусіз жүктеледі");
const norm = PAI.normalize(fixture);
check("9 парақ табылды, қате жоқ", norm.ok && norm.issues.filter((i) => i.level !== "warning").length === 0, JSON.stringify(norm.issues));
const base = PAI.compute(norm.data);
check("12 БББ көрсетіледі", base.ops.length === 12);

console.log("2. ФОТ сәйкестігі (±1 ₸)");
check(`бөлінген ФОТ ${base.totals.fot} = ${ref.fot_annual_total}`, close(base.totals.fot, ref.fot_annual_total, 1));

console.log("3. Жанама шығын = 500 000 000 ₸ (±1 ₸)");
check(`бөлінген ${base.totals.overhead}`, close(base.totals.overhead, 500000000, 1) && close(ref.overhead_total, 500000000, 0));

console.log("4. Әр БББ бойынша метрикалар эталонмен сәйкес (сома ±1 ₸, рентабельділік ±0,01 п.п.)");
comparePnl(base, ref.base, "база");

console.log("5. 6 аномалия табылды, P&L-ге әсер етпейді");
const an = PAI.detectAnomalies(norm.data);
const ids = an.anomalies.map((a) => a.source_row_id + "@" + a.row);
check(`аномалия саны = 6 (${ids.join(", ")})`, an.anomalies.length === 6);
check("күтілген ID-лер табылды", ref.expected_anomaly_rows.every((id) => an.anomalies.some((a) => a.source_row_id === id)));
const noSignals = JSON.parse(JSON.stringify(fixture)); noSignals["Сырые_сигналы"] = [];
const base2 = PAI.compute(PAI.normalize(noSignals).data);
check("«Сырые_сигналы»-сыз нәтиже бірдей", Math.abs(base2.totals.result - base.totals.result) < 1e-6);

console.log("6. Сценарий ±10% (кейстің базалық ережесі)");
const s1 = PAI.compute(norm.data, { op_id: "OP-004", pct: 10 });
comparePnl(s1, ref.scenario_OP004_plus10, "OP-004 +10%:");
check("сценарийде жанама шығын бәрібір 500 000 000 ₸", close(s1.totals.overhead, 500000000, 1));
const s2 = PAI.compute(norm.data, { op_id: "OP-012", pct: -10 });
comparePnl(s2, ref.scenario_OP012_minus10, "OP-012 −10%:");

console.log("7. Ақаулы деректе база бұзылмайды");
const broken = JSON.parse(JSON.stringify(fixture));
broken["Прямые_затраты"].push({ cost_id: "DC-BAD", op_id: "OP-777", "категория": "x", "сумма_в_год_тг": 5, _row: 999 });
broken["Контингент"].push({ op_id: "OP-001", "курс": 5, "контракт_полный": "abc", "контракт_со_скидкой": 0, "грант": 0, "тариф_контракт_тг": 1, "финансирование_грант_тг": 1, "скидка_доля": 0, _row: 998 });
const nb = PAI.normalize(broken);
check("ақаулы 2 жол табылды", nb.issues.filter((i) => i.level === "error").length === 2, JSON.stringify(nb.issues));
check("нәтиже өзгерген жоқ", Math.abs(PAI.compute(nb.data).totals.result - base.totals.result) < 1e-6);
const missingSheet = JSON.parse(JSON.stringify(fixture)); delete missingSheet["Драйверы"];
check("жоқ парақ туралы түсінікті хабар", PAI.normalize(missingSheet).issues.some((i) => i.level === "fatal" && i.sheet === "Драйверы"));

console.log("8. Нөлге бөлу жоқ");
const zero = JSON.parse(JSON.stringify(fixture));
zero["Контингент"] = zero["Контингент"].filter((c) => c.op_id !== "OP-007");
zero["Драйверы"].find((d) => d.op_id === "OP-007")["студентов_активных"] = 0;
const z = PAI.compute(PAI.normalize(zero).data).ops.find((o) => o.op_id === "OP-007");
check("табыс 0 → рентабельділік н/д, студент 0 → өзіндік құн н/д", z.margin === null && z.cps === null);

console.log(`\nНәтиже: ${passed} өтті, ${failed} құлады`);
process.exit(failed ? 1 : 0);
