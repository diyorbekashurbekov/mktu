"use strict";
/* Profitability AI — frontend (vanilla JS, SVG charts, no external dependencies). */

const S = { data: null, filters: { faculty: "", status: "", sort: "result" }, tableSort: { key: "result", dir: -1 },
  opId: null, uploadError: null, scTimer: null, chatInit: false };
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ---------------------------------------------------------------- formatting (2 decimals on screen only)
const NA = "н/д";
function group(intStr) { return intStr.replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function num(x, d = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return NA;
  const neg = x < 0; const s = Math.abs(x).toFixed(d); const [i, f] = s.split(".");
  return (neg ? "−" : "") + group(i) + (d ? "," + f : "");
}
const money = (x, d = 0) => (x === null || x === undefined ? NA : num(x, d) + " ₸");
const pct = (x, d = 2) => (x === null || x === undefined ? NA : num(x, d) + "%");
const signed = (x, d = 0) => (x === null || x === undefined ? NA : (x >= 0 ? "+" : "") + money(x, d));
function short(x) {
  if (x === null || x === undefined) return NA;
  const a = Math.abs(x);
  if (a >= 1e9) return num(x / 1e9, 2) + " млрд ₸";
  if (a >= 1e6) return num(x / 1e6, 1) + " млн ₸";
  if (a >= 1e3) return num(x / 1e3, 0) + " мың ₸";
  return money(x);
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
function shortName(name) { return name.length > 22 ? name.slice(0, 21) + "…" : name; }

// ---------------------------------------------------------------- api
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch (_) { /* non-json */ }
  if (!res.ok) { const e = new Error((body && body.error) || res.statusText); e.body = body; e.status = res.status; throw e; }
  return body;
}
const post = (path, payload) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast on" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), err ? 6000 : 3200);
}

// ---------------------------------------------------------------- tooltip
const tip = $("#tooltip");
function showTip(evt, html) {
  tip.innerHTML = html; tip.classList.add("on");
  const pad = 14; let x = evt.clientX + pad, y = evt.clientY + pad;
  const r = tip.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { tip.classList.remove("on"); }
function tipRows(title, rows) {
  return `<div class="t">${esc(title)}</div>` + rows.map(([k, v, c]) =>
    `<div class="r"><span>${c ? `<i style="background:${c}"></i>` : ""}${esc(k)}</span><span>${esc(v)}</span></div>`).join("");
}
function bindTips(root, fn) {
  $$("[data-tip]", root).forEach(el => {
    el.addEventListener("mousemove", e => showTip(e, fn(el.dataset.tip)));
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("click", () => { hideTip(); openOp(el.dataset.tip); });
  });
}
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ---------------------------------------------------------------- data helpers
const ops = () => S.data.pnl.ops;
const opById = id => ops().find(o => o.op_id === id);
function filtered() {
  const f = S.filters;
  let list = ops().filter(o => (!f.faculty || o.faculty === f.faculty) && (!f.status || o.status === f.status));
  const k = f.sort; list = [...list].sort((a, b) => (b[k] ?? -Infinity) - (a[k] ?? -Infinity));
  return list;
}
function opTip(id) {
  const o = opById(id);
  return tipRows(`${o.op_id} · ${o.name}`, [
    ["Кіріс", money(o.revenue)], ["ФОТ", money(o.fot), css("--s1")], ["Тікелей", money(o.direct), css("--s2")],
    ["Жанама", money(o.overhead), css("--s3")], ["Жалпы шығын", money(o.total_cost)], ["Нәтиже", money(o.result)],
    ["Рентабельділік", pct(o.margin)], ["Құн / студент", money(o.cost_per_student)], ["Студенттер", num(o.students, 0)]]);
}
// horizontal bar path with 4px rounding on the data end only
function hbar(x0, x1, y, h, r = 4) {
  const left = Math.min(x0, x1), right = Math.max(x0, x1), w = right - left;
  r = Math.min(r, w / 2, h / 2);
  if (w <= 0) return "";
  if (x1 >= x0) return `M${left},${y}H${right - r}Q${right},${y} ${right},${y + r}V${y + h - r}Q${right},${y + h} ${right - r},${y + h}H${left}Z`;
  return `M${right},${y}H${left + r}Q${left},${y} ${left},${y + r}V${y + h - r}Q${left},${y + h} ${left + r},${y + h}H${right}Z`;
}
function niceTicks(min, max, n = 5) {
  const span = max - min || 1; const step0 = span / n; const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || mag * 10;
  const out = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

// ---------------------------------------------------------------- render: header & KPIs
function renderHeader() {
  const d = S.data.dataset;
  $("#file-name").textContent = `${d.filename} · ${d.ops} ОП · ${d.teachers} оқытушы`;
  $("#file-dot").className = "dot" + (d.warnings ? " warn" : "");
  $("#file-chip").title = `Жүктелді: ${d.loaded_at} · SHA ${d.sha} · ескерту: ${d.warnings}`;
  $("#study-year").textContent = d.study_year || "2025–2026";
  $("#badge-quality").textContent = S.data.quality.count || "";
}
function renderKpis() {
  const t = S.data.pnl.totals;
  const k = [
    ["Жалпы кіріс", short(t.revenue), `${num(t.students, 0)} белсенді студент`],
    ["Жалпы шығын", short(t.total_cost), `ФОТ ${pct(t.fot / t.total_cost * 100, 0)} · жанама ${pct(t.overhead / t.total_cost * 100, 0)}`],
    ["Қаржылық нәтиже", short(t.result), "кассалық қалдық емес", t.result < 0],
    ["Рентабельділік", pct(t.margin), "нәтиже / кіріс"],
    ["Шығынды ОП", `${t.loss_count} / ${t.op_count}`, "нәтиже < 0", t.loss_count > 0],
    ["Құн / студент", short(t.cost_per_student), `кіріс / студент ${short(t.revenue_per_student)}`],
  ];
  $("#kpis").innerHTML = k.map(([l, v, h, neg]) =>
    `<div class="kpi"><div class="label">${l}</div><div class="value${neg ? " neg" : ""}">${v}</div><div class="hint">${h}</div></div>`).join("");
}

// ---------------------------------------------------------------- charts
function chartResult(list) {
  const el = $("#chart-result"), W = Math.max(320, el.clientWidth || 640), L = Math.min(150, W * 0.32), R = 78, rowH = 26, barH = 16, top = 8;
  const H = top + list.length * rowH + 26;
  const vals = list.map(o => o.result); const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const LN = min < 0 ? 72 : 0; // room for labels of negative bars
  const x = v => L + LN + (v - min) / (max - min || 1) * (W - L - LN - R);
  const ticks = niceTicks(min, max, 4);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="ОП бойынша қаржылық нәтиже">`;
  ticks.forEach(t => { s += `<line class="gridline" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H - 22}"/><text class="axis-label" x="${x(t)}" y="${H - 6}" text-anchor="middle">${short(t).replace(" ₸", "")}</text>`; });
  list.forEach((o, i) => {
    const y = top + i * rowH, by = y + (rowH - barH) / 2, pos = o.result >= 0;
    const vx = pos ? x(o.result) + 6 : x(o.result) - 6;
    s += `<g class="row" data-tip="${o.op_id}"><rect class="bg" x="0" y="${y}" width="${W}" height="${rowH}" rx="4"/>
      <text x="${L - 10}" y="${y + rowH / 2 + 4}" text-anchor="end">${esc(shortName(o.name))}</text>
      <path d="${hbar(x(0), x(o.result), by, barH)}" fill="${pos ? css("--pos") : css("--neg")}"/>
      <text class="val" x="${vx}" y="${y + rowH / 2 + 4}" text-anchor="${pos ? "start" : "end"}">${short(o.result)}</text></g>`;
  });
  s += `<line class="baseline" x1="${x(0)}" x2="${x(0)}" y1="${top}" y2="${H - 22}"/></svg>`;
  el.innerHTML = list.length ? s : `<p class="empty">Сүзгіге сай ОП жоқ</p>`; bindTips(el, opTip);
}
function chartCost(list) {
  const el = $("#chart-cost"), W = Math.max(320, el.clientWidth || 640), L = Math.min(150, W * 0.32), R = 20, rowH = 26, barH = 16, top = 8, gap = 2;
  const H = top + list.length * rowH + 26;
  const max = Math.max(...list.map(o => Math.max(o.total_cost, o.revenue)), 1);
  const x = v => L + v / max * (W - L - R);
  const ticks = niceTicks(0, max, 4);
  const cols = [["fot", css("--s1")], ["direct", css("--s2")], ["overhead", css("--s3")]];
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Шығын құрылымы">`;
  ticks.forEach(t => { s += `<line class="gridline" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H - 22}"/><text class="axis-label" x="${x(t)}" y="${H - 6}" text-anchor="middle">${short(t).replace(" ₸", "")}</text>`; });
  list.forEach((o, i) => {
    const y = top + i * rowH, by = y + (rowH - barH) / 2; let acc = 0;
    s += `<g class="row" data-tip="${o.op_id}"><rect class="bg" x="0" y="${y}" width="${W}" height="${rowH}" rx="4"/>
      <text x="${L - 10}" y="${y + rowH / 2 + 4}" text-anchor="end">${esc(shortName(o.name))}</text>`;
    cols.forEach(([k, c], j) => {
      const x0 = x(acc) + (j ? gap / 2 : 0), x1 = x(acc + o[k]) - (j < 2 ? gap / 2 : 0); acc += o[k];
      s += j === 2 ? `<path d="${hbar(x0, x1, by, barH)}" fill="${c}"/>` : `<rect x="${x0}" y="${by}" width="${Math.max(0, x1 - x0)}" height="${barH}" fill="${c}"/>`;
    });
    s += `<rect x="${x(o.revenue) - 1.5}" y="${y + 2}" width="3" height="${rowH - 4}" rx="1.5" fill="${css("--ink")}"/></g>`;
  });
  s += `<line class="baseline" x1="${x(0)}" x2="${x(0)}" y1="${top}" y2="${H - 22}"/></svg>`;
  el.innerHTML = list.length ? s : `<p class="empty">Сүзгіге сай ОП жоқ</p>`; bindTips(el, opTip);
  $("#legend-cost").innerHTML = `<span><i style="background:${css("--s1")}"></i>ФОТ</span><span><i style="background:${css("--s2")}"></i>Тікелей</span>
    <span><i style="background:${css("--s3")}"></i>Жанама</span><span><i class="tick"></i>Кіріс</span>`;
}
function chartScatter(list) {
  const el = $("#chart-scatter"), W = Math.max(320, el.clientWidth || 900), H = 360, L = 70, R = 24, T = 14, B = 40;
  const pts = list.filter(o => o.revenue_per_student != null && o.cost_per_student != null);
  const all = pts.flatMap(o => [o.revenue_per_student, o.cost_per_student]);
  const lo = Math.max(0, Math.min(...all) * 0.85), hi = Math.max(...all) * 1.08;
  const x = v => L + (v - lo) / (hi - lo) * (W - L - R), y = v => H - B - (v - lo) / (hi - lo) * (H - T - B);
  const ticks = niceTicks(lo, hi, 5);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Бір студентке кіріс пен шығын">`;
  ticks.forEach(t => {
    s += `<line class="gridline" x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${H - B}"/><text class="axis-label" x="${x(t)}" y="${H - B + 16}" text-anchor="middle">${short(t).replace(" ₸", "")}</text>`;
    s += `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text class="axis-label" x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${short(t).replace(" ₸", "")}</text>`;
  });
  s += `<line x1="${x(lo)}" y1="${y(lo)}" x2="${x(hi)}" y2="${y(hi)}" stroke="${css("--muted")}" stroke-dasharray="5 4" stroke-width="1.5"/>`;
  s += `<text class="axis-label" x="${x(hi) - 6}" y="${y(hi) + 16}" text-anchor="end">шығынсыздық: құн = кіріс</text>`;
  s += `<text class="axis-label" x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">Бір студентке кіріс →</text>`;
  s += `<text class="axis-label" transform="translate(14 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Бір студенттің өзіндік құны →</text>`;
  pts.forEach(o => {
    const cx = x(o.revenue_per_student), cy = y(o.cost_per_student), c = o.status === "loss" ? css("--neg") : css("--pos");
    s += `<g data-tip="${o.op_id}" style="cursor:pointer"><circle cx="${cx}" cy="${cy}" r="14" fill="transparent"/>
      <circle cx="${cx}" cy="${cy}" r="6" fill="${c}" stroke="${css("--surface")}" stroke-width="2"/>
      <text x="${cx + 10}" y="${cy - 8}">${esc(shortName(o.name))}</text></g>`;
  });
  s += `</svg>`;
  el.innerHTML = pts.length ? s : `<p class="empty">Сүзгіге сай ОП жоқ</p>`; bindTips(el, opTip);
}

// ---------------------------------------------------------------- P&L table
const COLS = [
  ["name", "ОП", false], ["students", "Студент", true], ["revenue", "Кіріс", true], ["fot", "ФОТ", true],
  ["direct", "Тікелей", true], ["overhead", "Жанама", true], ["total_cost", "Жалпы шығын", true],
  ["result", "Нәтиже", true], ["margin", "Рентаб.", true], ["cost_per_student", "Құн/студент", true], ["status", "Статус", false]];
function renderTable(list) {
  const { key, dir } = S.tableSort;
  const rows = [...list].sort((a, b) => key === "name" ? dir * a.name.localeCompare(b.name) : dir * ((a[key] ?? -Infinity) - (b[key] ?? -Infinity)));
  const maxAbs = Math.max(...ops().map(o => Math.abs(o.margin || 0)), 1);
  const th = COLS.map(([k, l, n]) => `<th class="sortable${n ? " num" : ""}" data-k="${k}">${l}${key === k ? (dir > 0 ? " ↑" : " ↓") : ""}</th>`).join("");
  const body = rows.map(o => {
    const w = Math.abs(o.margin || 0) / maxAbs * 35;
    const bar = `<span style="left:${o.margin >= 0 ? 35 : 35 - w}px;width:${w}px;background:${o.margin >= 0 ? css("--pos") : css("--neg")}"></span>`;
    return `<tr class="click" data-op="${o.op_id}">
      <td><div class="opname">${esc(o.name)}</div><div class="fac">${o.op_id} · ${esc(o.faculty)}</div></td>
      <td class="num">${num(o.students, 0)}</td><td class="num">${money(o.revenue)}</td><td class="num">${money(o.fot)}</td>
      <td class="num">${money(o.direct)}</td><td class="num">${money(o.overhead)}</td><td class="num">${money(o.total_cost)}</td>
      <td class="num ${o.result < 0 ? "neg" : ""}"><b>${money(o.result)}</b></td>
      <td class="num"><div class="bar-cell"><span class="${o.margin < 0 ? "neg" : ""}">${pct(o.margin)}</span><div class="minibar">${bar}</div></div></td>
      <td class="num">${money(o.cost_per_student)}</td>
      <td><span class="pill ${o.status}">${o.status === "loss" ? "▼ шығынды" : "▲ пайдалы"}</span></td></tr>`;
  }).join("");
  const sum = k => list.reduce((a, o) => a + o[k], 0);
  const rev = sum("revenue"), res = sum("result"), st = sum("students"), tc = sum("total_cost");
  const foot = `<tr><td>Жиыны (${list.length} ОП)</td><td class="num">${num(st, 0)}</td><td class="num">${money(rev)}</td><td class="num">${money(sum("fot"))}</td>
    <td class="num">${money(sum("direct"))}</td><td class="num">${money(sum("overhead"))}</td><td class="num">${money(tc)}</td>
    <td class="num ${res < 0 ? "neg" : ""}">${money(res)}</td><td class="num">${pct(rev ? res / rev * 100 : null)}</td><td class="num">${money(st ? tc / st : null)}</td><td></td></tr>`;
  const t = $("#pnl-table");
  t.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${body}</tbody><tfoot>${foot}</tfoot>`;
  $$("th.sortable", t).forEach(h => h.addEventListener("click", () => {
    const k = h.dataset.k; S.tableSort = { key: k, dir: S.tableSort.key === k ? -S.tableSort.dir : (k === "name" ? 1 : -1) }; renderTable(filtered());
  }));
  $$("tr.click", t).forEach(r => r.addEventListener("click", () => openOp(r.dataset.op)));
}

function renderDashboard() {
  renderKpis();
  const list = filtered();
  const n = ops().length;
  $("#filter-note").textContent = list.length === n ? `${n} ОП көрсетілген` : `${list.length} / ${n} ОП көрсетілген`;
  chartResult(list); chartCost(list); chartScatter(list); renderTable(list);
}

// ---------------------------------------------------------------- OP detail
function openOp(id) { S.opId = id; $("#op-select").value = id; switchTab("op"); renderOp(); }
function waterfall(o) {
  const W = 640, L = 120, R = 110, rowH = 30, barH = 18, top = 6;
  const steps = [["Кіріс", 0, o.revenue, css("--pos")], ["− ФОТ", o.revenue, o.revenue - o.fot, css("--s1")],
    ["− Тікелей", o.revenue - o.fot, o.revenue - o.fot - o.direct, css("--s2")],
    ["− Жанама", o.revenue - o.fot - o.direct, o.result, css("--s3")], ["= Нәтиже", 0, o.result, o.result < 0 ? css("--neg") : css("--pos")]];
  const vals = steps.flatMap(s => [s[1], s[2]]); const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const x = v => L + (v - min) / (max - min || 1) * (W - L - R);
  const H = top + steps.length * rowH + 4;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Кірістен нәтижеге">`;
  steps.forEach(([lab, a, b, c], i) => {
    const y = top + i * rowH, by = y + (rowH - barH) / 2;
    s += `<text x="${L - 10}" y="${y + rowH / 2 + 4}" text-anchor="end">${lab}</text>
      <rect x="${Math.min(x(a), x(b))}" y="${by}" width="${Math.max(1, Math.abs(x(b) - x(a)))}" height="${barH}" rx="3" fill="${c}"/>
      <text class="val" x="${Math.max(x(a), x(b)) + 6}" y="${y + rowH / 2 + 4}">${i === 0 || i === 4 ? short(b) : "−" + short(Math.abs(b - a))}</text>`;
  });
  s += `<line class="baseline" x1="${x(0)}" x2="${x(0)}" y1="${top}" y2="${H}"/></svg>`;
  return s;
}
function renderOp() {
  const o = opById(S.opId) || ops()[0]; S.opId = o.op_id; $("#op-select").value = o.op_id;
  const t = S.data.pnl.totals;
  const m = (l, v, cls = "") => `<div class="metric"><div class="label">${l}</div><div class="value ${cls}">${v}</div></div>`;
  const revRows = o.revenue_rows.map(r => `<tr><td>${r.row}</td><td class="num">${r.course}</td><td class="num">${r.full}</td><td class="num">${r.disc}</td>
    <td class="num">${r.grant}</td><td class="num">${money(r.tariff)}</td><td class="num">${pct(r.discount * 100, 0)}</td><td class="num">${money(r.grant_fin)}</td><td class="num"><b>${money(r.revenue)}</b></td></tr>`).join("");
  const tRows = o.teachers.map(tc => `<tr><td>${tc.teacher_id}</td><td class="num">${money(tc.salary)}</td><td class="num">${tc.months}</td><td class="num">${pct(tc.charges * 100, 0)}</td>
    <td class="num">${money(tc.annual_fot)}</td><td class="num">${num(tc.hours_op, 0)} / ${num(tc.hours_total, 0)}</td><td class="num">${pct(tc.share * 100)}</td>
    <td class="num"><b>${money(tc.allocated, 2)}</b></td><td class="src">${tc.shared ? '<span class="pill info">ортақ</span> ' : ""}Штат!${tc.staff_row} · Нагрузка!${tc.load_rows.join(",")}</td></tr>`).join("");
  const dRows = o.direct_rows.map(r => `<tr><td>${r.row}</td><td>${r.cost_id}</td><td>${esc(r.category)}</td><td class="num"><b>${money(r.amount)}</b></td></tr>`).join("");
  const ohRows = o.overhead_rows.map(r => `<tr><td>${r.row}</td><td>${r.center_id} ${esc(r.name)}</td><td class="num">${money(r.amount)}</td><td>${r.driver} ↔ ${r.driver_label}</td>
    <td class="num">${num(r.op_driver, 0)} / ${num(r.total_driver, 0)}</td><td class="num">${pct(r.share * 100, 3)}</td><td class="num"><b>${money(r.allocated, 2)}</b></td></tr>`).join("");
  $("#op-detail").innerHTML = `
    <div class="card">
      <div class="op-head">
        <div><h2>${esc(o.name)}</h2><p class="muted">${o.op_id} · ${esc(o.faculty)} · ${esc(o.level || "")} · ${o.years || "—"} жыл · ОП!${o.source_row}</p></div>
        <span class="pill ${o.status}">${o.status === "loss" ? "▼ шығындарын жаппайды" : "▲ шығындарын жабады"}</span>
      </div>
      <div class="op-metrics">
        ${m("Кіріс", money(o.revenue, 2))}${m("Жалпы шығын", money(o.total_cost, 2))}
        ${m("Қаржылық нәтиже", money(o.result, 2), o.result < 0 ? "neg" : "")}${m("Рентабельділік", pct(o.margin) + ` <span class="muted">(ун-т ${pct(t.margin)})</span>`, o.margin < 0 ? "neg" : "")}
        ${m("ФОТ", money(o.fot, 2))}${m("Тікелей шығындар", money(o.direct, 2))}${m("Жанама шығындар", money(o.overhead, 2))}
        ${m("Бір студенттің құны", money(o.cost_per_student, 2) + ` <span class="muted">· ${num(o.students, 0)} студ.</span>`)}
      </div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Кірістен нәтижеге</h3><div class="chart">${waterfall(o)}</div></div>
      <div class="card"><h3>Бір студентке (университетпен салыстыру)</h3>
        <table class="data"><thead><tr><th>Көрсеткіш</th><th class="num">ОП</th><th class="num">Университет</th></tr></thead><tbody>
        ${[["Кіріс", "revenue_per_student"], ["ФОТ", "fot_per_student"], ["Тікелей", "direct_per_student"], ["Жанама", "overhead_per_student"], ["Өзіндік құн", "cost_per_student"]]
          .map(([l, k]) => `<tr><td>${l}</td><td class="num">${money(o[k])}</td><td class="num">${money(t[k])}</td></tr>`).join("")}
        <tr><td>Оқытушы сағаты / студент</td><td class="num">${num(o.hours_per_student, 1)}</td><td class="num">${num(t.hours_per_student, 1)}</td></tr>
        <tr><td>Грант үлесі</td><td class="num">${pct((o.grant_share || 0) * 100, 1)}</td><td class="num">${pct((t.grant_share || 0) * 100, 1)}</td></tr>
        </tbody></table></div>
    </div>
    <div class="card" id="explain-box"><div class="card-head"><h3>ИИ түсіндірмесі: факторлар және басқарушылық нұсқалар</h3>
      <span class="muted">«ОП-ны түсіндіру» батырмасын басыңыз</span></div></div>
    <div class="card">
      <h3>Есептеудің толық ізі (формулалар мен дереккөз жолдары)</h3>
      <details class="block" open><summary><span class="s-left">Кіріс — Контингент (${o.revenue_rows.length} жол)</span><b>${money(o.revenue, 2)}</b></summary>
        <div class="formula">Кіріс = Σ(контракт_полный × тариф + контракт_со_скидкой × тариф × (1 − скидка) + грант × финансирование_грант)
= ${money(o.revenue_full, 2)} (толық) + ${money(o.revenue_discount, 2)} (жеңілдікті) + ${money(o.revenue_grant, 2)} (грант)</div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Жол</th><th class="num">Курс</th><th class="num">Толық</th><th class="num">Жеңілд.</th><th class="num">Грант</th>
        <th class="num">Тариф</th><th class="num">Жеңілдік</th><th class="num">Грант қарж.</th><th class="num">Кіріс</th></tr></thead><tbody>${revRows}</tbody></table></div></details>
      <details class="block"><summary><span class="s-left">ФОТ — Штат_ППС × Нагрузка_ППС (${o.teachers.length} оқытушы, ${o.shared_teachers} ортақ)</span><b>${money(o.fot, 2)}</b></summary>
        <div class="formula">Жылдық ФОТ = жалақы × ай × (1 + аударымдар);  ОП үлесі = жылдық ФОТ × ОП сағаты / оқытушының барлық сағаты</div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Оқытушы</th><th class="num">Жалақы/ай</th><th class="num">Ай</th><th class="num">Аудар.</th><th class="num">Жылдық ФОТ</th>
        <th class="num">Сағат ОП / барлығы</th><th class="num">Үлес</th><th class="num">ОП-ға</th><th>Дереккөз</th></tr></thead><tbody>${tRows}</tbody></table></div></details>
      <details class="block"><summary><span class="s-left">Тікелей шығындар — Прямые_затраты (${o.direct_rows.length} жол)</span><b>${money(o.direct, 2)}</b></summary>
        <div class="formula">Тікелей = Σ сумма_в_год_тг (op_id = ${o.op_id})</div>
        <table class="data"><thead><tr><th>Жол</th><th>cost_id</th><th>Санат</th><th class="num">Сома</th></tr></thead><tbody>${dRows}</tbody></table></details>
      <details class="block"><summary><span class="s-left">Жанама шығындар — Общие_затраты × Драйверы (${o.overhead_rows.length} орталық)</span><b>${money(o.overhead, 2)}</b></summary>
        <div class="formula">Жанама = Σ орталық сомасы × ОП драйвері / 12 ОП драйверлерінің қосындысы  (Драйверы!${o.driver_row}: студент ${num(o.students, 0)}, ${num(o.area_m2, 0)} м², ${num(o.lab_hours, 0)} зерт. сағ.)</div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Жол</th><th>Орталық</th><th class="num">Сома</th><th>Драйвер</th><th class="num">ОП / барлығы</th><th class="num">Үлес</th><th class="num">ОП-ға</th></tr></thead><tbody>${ohRows}</tbody></table></div></details>
      <div class="formula">Жалпы шығын = ФОТ + тікелей + жанама = ${money(o.total_cost, 2)}
Нәтиже = кіріс − жалпы шығын = ${money(o.result, 2)};  Рентабельділік = нәтиже / кіріс × 100% = ${pct(o.margin)}
Бір студенттің құны = жалпы шығын / студентов_активных (${num(o.students, 0)}) = ${money(o.cost_per_student, 2)}</div>
    </div>`;
}
async function explainCurrent() {
  const box = $("#explain-box");
  box.innerHTML = `<p class="typing">Факторлар есептелуде…</p>`;
  try {
    const ex = await api(`/api/explain?op=${encodeURIComponent(S.opId)}&lang=kz`);
    box.innerHTML = renderExplain(ex);
  } catch (e) { box.innerHTML = `<p class="neg">${esc(e.message)}</p>`; }
}
function renderExplain(ex) {
  const f = ex.factors.map((x, i) => `<div class="factor"><div class="n">${i + 1}</div><div><b>${esc(x.title)}</b><div>${esc(x.text)}</div>
    <div class="src">Дереккөз: <code>${esc(x.source)}</code></div></div><div class="imp ${x.direction || ""}">${x.impact_display || "масштаб"}</div></div>`).join("");
  const o = ex.options.map(p => `<div class="option"><h4>${esc(p.title)}</h4><div>${esc(p.effect)}</div><div class="risk"><b>Тәуекелдер:</b> ${esc(p.risks)}</div></div>`).join("");
  return `<div class="card-head"><h3>ИИ түсіндірмесі: ${esc(ex.name)}</h3><span class="mode">сандар — код есебі</span></div>
    <p>${md(ex.summary)}</p><div class="formula">${esc(ex.formula || "")}</div>
    <h4 class="mt">Нәтижені түсіндіретін факторлар</h4><div class="factors">${f}</div>
    <h4 class="mt">Басқарушылық нұсқалар және тәуекелдер</h4><div class="options">${o}</div>
    <div class="ethics">⚠ ${esc(ex.ethics)}</div>`;
}

// ---------------------------------------------------------------- quality
function renderQuality() {
  const d = S.data.dataset, q = S.data.quality, checks = S.data.checks;
  const issues = d.issues;
  const sheetNames = { ops: "ОП", contingent: "Контингент", staff: "Штат_ППС", load: "Нагрузка_ППС", direct: "Прямые_затраты",
    overhead: "Общие_затраты", drivers: "Драйверы", history: "История_набора", signals: "Сырые_сигналы" };
  const sheets = Object.entries(sheetNames).map(([k, n]) => {
    const s = d.sheets[k];
    return `<div class="sheet"><b>${n}</b>${s ? `${s.rows} жол · ${k === "signals" ? "P&L-ге кірмейді" : s.valid + " жарамды"}` : '<span class="neg">жоқ</span>'}</div>`;
  }).join("");
  const err = S.uploadError ? `<div class="card" style="border-color:var(--crit)"><h3 class="neg">Соңғы жүктеу қабылданбады</h3>
    <p>${esc(S.uploadError.error)}</p><ul>${(S.uploadError.issues || []).filter(i => i.level === "error").map(i => `<li>${esc(i.sheet)}${i.row ? "!" + i.row : ""}: ${esc(i.message)}</li>`).join("")}</ul></div>` : "";
  const chk = checks.map(c => `<div class="check"><div class="icon ${c.pass ? "ok" : "bad"}">${c.pass ? "✓" : "✗"}</div>
    <div><b>${esc(c.title)}</b><div class="muted">${esc(c.detail)}</div></div>
    <div class="v">${c.unit === "₸" ? `күтілген ${money(c.expected, 2)}<br>нақты ${money(c.actual, 2)}<br>айырма ${money(c.diff, 2)} (±${c.tolerance} ₸)` :
      c.unit === "hash" ? `${esc(String(c.actual))}` : `${num(c.actual, 0)} ${c.unit}`}</div></div>`).join("");
  const iss = issues.length ? `<table class="data"><thead><tr><th>Деңгей</th><th>Парақ</th><th>Жол</th><th>Хабарлама</th></tr></thead><tbody>${issues.map(i =>
    `<tr><td><span class="pill ${i.level === "error" ? "loss" : "warn"}">${i.level === "error" ? "қате" : "ескерту"}</span></td><td>${esc(i.sheet)}</td><td>${i.row || "—"}</td><td>${esc(i.message)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="pos-ink">✓ Құрылым, типтер және сілтемелік тұтастық бойынша ескерту жоқ. Барлық P&L жолдары есепке алынды.</p>`;
  const an = q.anomalies.map((a, i) => `<tr><td>${i + 1}</td><td><b>${esc(a.source_row_id || "—")}</b></td><td class="num">${a.excel_row}</td>
    <td><span class="pill ${a.severity === "high" ? "loss" : "warn"}">${esc(a.type_label)}</span></td><td>${esc(a.op_id || "—")}</td><td>${esc(a.metric || "—")}</td>
    <td>${esc(a.year || "—")}</td><td class="num">${a.value === null ? "<i>бос</i>" : esc(a.value)}</td><td>${esc(a.why)}</td><td>${esc(a.action)}</td>
    <td class="muted">${esc(a.source_comment || "")}</td></tr>`).join("");
  const rec = q.reconciliation.length ? `<div class="card"><div class="card-head"><h3>Ақпарат: сыртқы сигнал мен История_набора сәйкессіздігі</h3>
    <span class="muted">Аномалия деп саналмайды — әртүрлі жүйелер; P&L-ге әсері жоқ</span></div>
    <div class="table-wrap"><table class="data"><thead><tr><th>ID</th><th>ОП</th><th class="num">Сигнал (applications)</th><th class="num">История_набора (заявок)</th><th class="num">Айырма</th></tr></thead><tbody>
    ${q.reconciliation.map(r => `<tr><td>${esc(r.source_row_id)} (жол ${r.excel_row})</td><td>${r.op_id}</td><td class="num">${num(r.signal, 0)}</td><td class="num">${num(r.history, 0)} (жол ${r.history_row})</td><td class="num">${num(r.diff, 0)}</td></tr>`).join("")}
    </tbody></table></div></div>` : "";
  $("#quality").innerHTML = `${err}
    <div class="grid2">
      <div class="card"><div class="card-head"><h3>Файл құрылымы</h3><span class="muted">${esc(d.filename)} · ${num(d.size / 1024, 1)} КБ · SHA ${d.sha}</span></div>
        <div class="sheet-grid">${sheets}</div><h4 class="mt">Құрылым мен типтерді тексеру</h4>${iss}</div>
      <div class="card"><h3>Қабылдау тексерістері (кейс §7)</h3>${chk}</div>
    </div>
    <div class="card"><div class="card-head"><h3>«Сырые_сигналы» аномалиялары: ${q.count} табылды / ${q.rows_checked} жол тексерілді</h3>
      <span class="pill ${q.pnl_isolated ? "profit" : "loss"}">${q.pnl_isolated ? "✓ базалық P&L-ге әсер етпейді" : "✗ әсер етеді"}</span></div>
      <p class="muted">Анықтау тек мәндерге қойылған ережелермен жүреді (ID бірегейлігі, op_id ∈ ОП, applications ≥ 0, 0 ≤ conversion_pct ≤ 100, бос мән, кезең датасет жылдарында).
      Соңғы баған — дерек көзінің өз түсініктемесі, тек салыстыру үшін көрсетілген, анықтауда қолданылмайды.</p>
      <div class="table-wrap"><table class="data"><thead><tr><th>#</th><th>source_row_id</th><th class="num">Excel жолы</th><th>Қате түрі</th><th>ОП</th><th>Көрсеткіш</th>
      <th>Кезең</th><th class="num">Мән</th><th>Неге күдікті</th><th>Ұсынылатын әрекет</th><th>Көз түсініктемесі</th></tr></thead><tbody>${an}</tbody></table></div></div>
    ${rec}`;
}

// ---------------------------------------------------------------- scenario
function scParams() {
  return { op_id: $("#sc-op").value, pct: +$("#sc-pct").value, fot_var: +$("#sc-fot").value / 100, direct_var: +$("#sc-dir").value / 100 };
}
function scLabels() {
  const p = +$("#sc-pct").value;
  $("#sc-pct-label").textContent = (p > 0 ? "+" : p < 0 ? "−" : "") + Math.abs(p) + "%";
  $("#sc-fot-label").textContent = $("#sc-fot").value + "%"; $("#sc-dir-label").textContent = $("#sc-dir").value + "%";
  $$("#sc-quick button").forEach(b => b.classList.toggle("on", +b.dataset.v === p));
}
function queueScenario() { scLabels(); clearTimeout(S.scTimer); S.scTimer = setTimeout(runScenario, 180); }
async function runScenario() {
  try { renderScenario(await post("/api/scenario", scParams())); } catch (e) { toast(e.message, true); }
}
function renderScenario(sc) {
  const s = sc.selected, b = s.before, a = s.after, d = s.delta;
  const card = (l, bv, av, dv, fmtf, good, dfmt = fmtf) => {
    const cls = dv === null || Math.abs(dv) < 0.005 ? "muted" : ((dv > 0) === good ? "pos-ink" : "neg");
    return `<div class="metric"><div class="label">${l}</div><div class="value">${fmtf(av)}</div>
      <div class="muted">бұрын: ${fmtf(bv)}</div><div class="delta ${cls}">${dv === null ? NA : (dv >= 0 ? "+" : "") + dfmt(dv)}</div></div>`;
  };
  const tb = sc.totals.before, ta = sc.totals.after;
  const others = sc.rows.filter(r => !r.selected).sort((x, y) => y.delta.result - x.delta.result);
  const be = sc.break_even;
  const beText = be.reachable ? (Math.abs(be.pct) < 0.05 ? "ОП қазір шығынсыздық нүктесінде" :
    `Нәтиже 0-ге контингент <b>${be.pct >= 0 ? "+" : ""}${num(be.pct, 1)}%</b> өзгергенде жетеді (≈${num(be.students, 0)} студент, қазір ${num(be.base_students, 0)}) — сол модельде.`) : esc(be.note || "");
  $("#scenario").innerHTML = `
    <div class="card"><div class="card-head"><h3>${esc(sc.name)}: контингент ${sc.pct > 0 ? "+" : ""}${num(sc.pct, 0)}%</h3>
      <span class="pill ${sc.overhead_preserved ? "profit" : "loss"}">${sc.overhead_preserved ? "✓ жанама шығын жиыны сақталды: " + money(ta.overhead) : "✗ жанама жиыны өзгерді"}</span></div>
      <div class="compare">
        ${card("Кіріс", b.revenue, a.revenue, d.revenue, money, true)}
        ${card("Жанама шығын", b.overhead, a.overhead, d.overhead, money, false)}
        ${card("Қаржылық нәтиже", b.result, a.result, d.result, money, true)}
        ${card("Рентабельділік", b.margin, a.margin, d.margin, x => pct(x), true, x => num(x, 2) + " п.п.")}
        ${card("ФОТ", b.fot, a.fot, d.fot, money, false)}
        ${card("Тікелей шығын", b.direct, a.direct, d.direct, money, false)}
        ${card("Студенттер", b.students, a.students, d.students, x => num(x, 1), true)}
        ${card("Бір студенттің құны", b.cost_per_student, a.cost_per_student, d.cost_per_student, money, false)}
      </div>
      <div class="formula">Университет нәтижесі: ${money(tb.result)} → ${money(ta.result)} (${signed(ta.result - tb.result)}) · рентабельділік ${pct(tb.margin)} → ${pct(ta.margin)}
Басқа 11 ОП-ның нәтижесі жанама шығынның қайта бөлінуінен: ${signed(sc.others_result_delta)}
Шығынсыздық: ${beText.replace(/<[^>]+>/g, "")}</div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Модель ережелері (болжамдар)</h3><ol class="assumptions">${sc.assumptions.map(x => `<li>${esc(x)}</li>`).join("")}</ol></div>
      <div class="card"><h3>Басқа ОП-ларға әсер (жанама шығынды қайта бөлу)</h3>
        <div class="table-wrap"><table class="data"><thead><tr><th>ОП</th><th class="num">Жанама Δ</th><th class="num">Нәтиже Δ</th><th class="num">Жаңа нәтиже</th></tr></thead><tbody>
        ${others.map(r => `<tr><td>${esc(r.name)}</td><td class="num">${signed(r.delta.overhead)}</td><td class="num ${r.delta.result < 0 ? "neg" : "pos-ink"}">${signed(r.delta.result)}</td><td class="num">${money(r.after.result)}</td></tr>`).join("")}
        </tbody></table></div></div>
    </div>`;
}

// ---------------------------------------------------------------- forecast
function spark(i) {
  const W = 170, H = 40, P = 4; const hist = i.history; const n = hist.length;
  const vals = hist.flatMap(h => [h.enrolled, h.plan]).concat([i.low, i.high]);
  const lo = Math.min(...vals) * 0.9, hi = Math.max(...vals) * 1.05;
  const x = k => P + k / n * (W - 2 * P), y = v => H - P - (v - lo) / (hi - lo || 1) * (H - 2 * P);
  const line = hist.map((h, k) => `${k ? "L" : "M"}${x(k)},${y(h.enrolled)}`).join("");
  const plan = hist.map((h, k) => `${k ? "L" : "M"}${x(k)},${y(h.plan)}`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">
    <path d="${plan}" fill="none" stroke="${css("--muted")}" stroke-width="1.5" stroke-dasharray="3 3"/>
    <path d="${line}" fill="none" stroke="${css("--s1")}" stroke-width="2"/>
    <rect x="${x(n) - 3}" y="${y(i.high)}" width="6" height="${Math.max(2, y(i.low) - y(i.high))}" rx="3" fill="${css("--s1")}" opacity=".25"/>
    <path d="M${x(n - 1)},${y(hist[n - 1].enrolled)}L${x(n)},${y(i.point)}" stroke="${css("--s1")}" stroke-width="1.5" stroke-dasharray="2 2"/>
    <circle cx="${x(n)}" cy="${y(i.point)}" r="3.5" fill="${css("--s1")}"/></svg>`;
}
function renderForecast() {
  const fc = S.data.forecast;
  if (!fc.items.length) { $("#forecast").innerHTML = `<div class="card empty">История_набора парағы жоқ</div>`; return; }
  const total = fc.items.reduce((a, i) => a + i.point, 0);
  $("#forecast").innerHTML = `
    <div class="grid2">
      <div class="card"><h3>Әдіс</h3><p>${esc(fc.method)}</p>
        <p class="mt">Келесі жылға 12 ОП бойынша жиынтық болжам: <b>≈ ${num(total, 0)} студент</b> (жоспар ${num(fc.items.reduce((a, i) => a + i.last_plan, 0), 0)}).</p></div>
      <div class="card" style="background:var(--warn-soft)"><h3>Неге 3 бақылау дәл болжам үшін жеткіліксіз</h3>
        <ul class="assumptions">${fc.caveats.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>
    </div>
    <div class="card"><div class="card-head"><h3>ОП бойынша болжам (${esc(fc.items[0].next_year)})</h3>
      <span class="legend"><span><i style="background:${css("--s1")}"></i>зачислено</span><span><i style="background:${css("--muted")}"></i>жоспар (үзік)</span><span>● болжам, жолақ — диапазон</span></span></div>
      <div class="table-wrap"><table class="data"><thead><tr><th>ОП</th><th>Динамика</th><th class="num">Заявок</th><th class="num">Зачислено</th><th class="num">План</th>
      <th class="num">Орт. конверсия</th><th class="num">Болжам</th><th class="num">Диапазон</th><th class="num">±</th><th class="num">Әдістер: тренд / соңғы / өтінім×конв.</th></tr></thead><tbody>
      ${fc.items.map(i => `<tr><td><div class="opname">${esc(i.name)}</div><div class="fac">${i.op_id} · История_набора!${i.history.map(h => h.row).join(",")}</div></td>
        <td>${spark(i)}</td><td class="num">${i.history.map(h => h.applications).join(" · ")}</td><td class="num">${i.history.map(h => h.enrolled).join(" · ")}</td>
        <td class="num">${i.history.map(h => h.plan).join(" · ")}</td><td class="num">${pct(i.avg_conversion, 1)}</td><td class="num"><b>${num(i.point, 0)}</b></td>
        <td class="num">${num(i.low, 0)}–${num(i.high, 0)}</td><td class="num">${pct(i.spread_pct / 2, 0)}</td>
        <td class="num">${num(i.methods.trend, 0)} / ${num(i.methods.last, 0)} / ${num(i.methods.applications_x_conversion, 0)}</td></tr>`).join("")}
      </tbody></table></div></div>`;
}

// ---------------------------------------------------------------- AI chat
function renderAnswer(a) {
  const facts = a.facts && a.facts.length ? `<div class="facts">${a.facts.map(f => `<div class="fact">${esc(f.label)}<b>${esc(f.value)}</b></div>`).join("")}</div>` : "";
  const table = a.table ? `<div class="table-wrap"><table class="data"><thead><tr>${a.table.columns.map((c, i) => `<th${i ? ' class="num"' : ""}>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${a.table.rows.map(r => `<tr>${r.map((c, i) => `<td${i && a.intent !== "anomalies" ? ' class="num"' : ""}>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
  const ev = `<details class="evidence"><summary>Дәлелдер: формула, дереккөз, болжамдар</summary>
    ${a.formula ? `<div class="formula">${esc(a.formula)}</div>` : ""}
    ${a.sources && a.sources.length ? `<div><b>Дереккөз:</b><ul>${a.sources.map(s => `<li><code>${esc(s)}</code></li>`).join("")}</ul></div>` : ""}
    ${a.assumptions && a.assumptions.length ? `<div><b>Болжамдар:</b><ul>${a.assumptions.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${a.llm_rejected ? `<div class="neg">LLM жауабында тексерілмеген сандар болды (${esc(a.llm_rejected.join(", "))}) — детерминирленген жауап көрсетілді.</div>` : ""}
    ${a.llm_error ? `<div class="muted">LLM қолжетімсіз: ${esc(a.llm_error)} — ережелік жауап.</div>` : ""}</details>`;
  const mode = a.mode === "claude" ? `Claude · ${esc(a.model || "")} · құралдар: ${esc((a.tools_used || []).join(", "))}` : "ережелік талдаушы · офлайн";
  const follow = a.followups && a.followups.length ? `<div class="follow">${a.followups.map(f => `<button class="chip" data-q="${esc(f)}">${esc(f)}</button>`).join("")}</div>` : "";
  const openBtn = a.op_ids && a.op_ids.length === 1 ? `<button class="chip" data-open="${a.op_ids[0]}">ОП картасын ашу →</button>` : "";
  return `<h4>${esc(a.title)}</h4><div class="text">${md(a.text)}</div>${facts}${table}${ev}
    <div class="follow">${openBtn}<span class="muted" style="align-self:center">${mode}</span></div>${follow}`;
}
function addMsg(cls, html) {
  const log = $("#chat-log"); const div = document.createElement("div"); div.className = "msg " + cls; div.innerHTML = html;
  log.appendChild(div); log.scrollTop = log.scrollHeight;
  $$("[data-q]", div).forEach(b => b.addEventListener("click", () => ask(b.dataset.q)));
  $$("[data-open]", div).forEach(b => b.addEventListener("click", () => openOp(b.dataset.open)));
  return div;
}
async function ask(q) {
  q = (q || "").trim(); if (!q) return;
  switchTab("ai");
  addMsg("user", esc(q)); const wait = addMsg("bot", `<span class="typing">Есептеп жатырмын…</span>`);
  try { wait.innerHTML = ""; wait.remove(); addMsg("bot", renderAnswer(await post("/api/ask", { question: q, op_id: S.opId }))); }
  catch (e) { wait.innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
}
function initChat() {
  const ex = S.data.examples;
  const chips = [...ex.kz.slice(0, 5), ...ex.ru.slice(0, 3)];
  $("#chips").innerHTML = chips.map(c => `<button class="chip" data-q="${esc(c)}">${esc(c)}</button>`).join("");
  $$("#chips .chip").forEach(b => b.addEventListener("click", () => ask(b.dataset.q)));
  const llm = S.data.llm;
  $("#ai-mode").textContent = llm.enabled ? `Claude қосулы · ${llm.model}` : "Офлайн режим: ережелік талдаушы (ANTHROPIC_API_KEY жоқ)";
  if (!S.chatInit) {
    addMsg("bot", `<h4>Сәлеметсіз бе!</h4><div class="text">Мен жүктелген Excel бойынша есептелген P&L-ге сүйеніп жауап беремін. Қазақ немесе орыс тілінде сұраңыз. Әр жауапта нақты сома, формула және дереккөз жолдары болады — ойдан сан шығармаймын.</div>`);
    S.chatInit = true;
  }
}

// ---------------------------------------------------------------- method
function renderMethod() {
  const t = S.data.pnl.totals;
  $("#method").innerHTML = `<div class="grid2 method">
    <div class="card"><h3>Міндетті әдістеме (кейс §4)</h3>
      <div class="formula">Кіріс ОП = Σ(контракт_полный × тариф + контракт_со_скидкой × тариф × (1 − скидка) + грант × финансирование_грант)</div>
      <div class="formula">Оқытушының жылдық ФОТ = жалақы × ай × (1 + аударымдар)
ОП-ға ФОТ = жылдық ФОТ × ОП сағаты / оқытушының барлық ОП бойынша сағаты</div>
      <div class="formula">Тікелей = Σ Прямые_затраты (op_id бойынша)</div>
      <div class="formula">Жанама = Σ_орталық сомасы × ОП драйвері / 12 ОП драйверінің қосындысы
students ↔ студентов_активных · area_m2 ↔ площадь_м2 · lab_hours ↔ лабораторные_часы</div>
      <div class="formula">Жалпы шығын = ФОТ + тікелей + жанама;  Нәтиже = кіріс − жалпы шығын
Рентабельділік = нәтиже / кіріс × 100%;  Бір студенттің құны = жалпы шығын / белсенді студенттер
Бөлгіш 0 болса — «н/д»</div>
      <p class="muted">Барлық сомалар — теңге, бір жыл; дөңгелектеу 2 таңбаға дейін тек экранда. CSV экспорт толық дәлдікпен.</p></div>
    <div class="card"><h3>Шекаралар мен болжамдар</h3><ul>
      <li>Қаржылық нәтиже кассалық қалдық емес; табыс салығы, инвестициялық бюджет, амортизация, кредиттер, зерттеулер және стипендиялар модельденбейді.</li>
      <li>Кіріс — оқу жылына есептелген (начисленный), нақты төлемдер емес.</li>
      <li>Жанама шығынды бөлу ережесі — оқу моделі; нақты жүйеде оны университеттің қаржы-экономикалық қызметі бекітеді.</li>
      <li>ИИ сомаларды есептемейді: барлық сандарды тексерілетін Python коды есептейді, LLM тек құралды таңдап, түсіндіреді; мәтіндегі әр сан құрал нәтижесімен салыстырылады.</li>
      <li>ОП-ны тек қаржылық нәтиже бойынша жабу ұсынылмайды — академиялық, кадрлық, стратегиялық және әлеуметтік негіздер қажет.</li>
      <li>Деректер толығымен синтетикалық; ЖСН, студенттердің дербес деректері немесе нақты жалақылар жиналмайды.</li></ul>
      <h3 class="mt">Нақты енгізу үшін қажет деректер</h3><ul>
      <li>Бухгалтерлік есептен нақты кірістер (төлемдер, қарыздар, қайтарулар) және ай сайынғы контингент қозғалысы (оқудан шығу, академ. демалыс).</li>
      <li>Платонус/ЖОО АЖ-дан оқу жоспарлары, ағындар және нақты сағаттар; HR жүйесінен ставкалар мен ФОТ (дербес деректерсіз, агрегатталған).</li>
      <li>Бекітілген жанама шығын бөлу әдістемесі, аудитория қоры мен зертхана кестесі.</li>
      <li>Грант квоталары, бәсекелестер тарифтері, 5–7 жылдық қабылдау тарихы.</li></ul></div>
    </div>
    <div class="card"><h3>Ағымдағы файл бойынша бақылау сомалары</h3>
      <div class="formula">Σ кіріс = ${money(t.revenue, 2)} · Σ ФОТ = ${money(t.fot, 2)} (Штат_ППС бойынша ${money(t.staff_fot, 2)})
Σ тікелей = ${money(t.direct, 2)} · Σ жанама = ${money(t.overhead, 2)} (Общие_затраты ${money(t.overhead_pool, 2)})
Σ нәтиже = ${money(t.result, 2)} · рентабельділік = ${pct(t.margin)}</div></div>`;
}

// ---------------------------------------------------------------- tabs & wiring
function switchTab(name) {
  $$("#tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  if (name === "scenario" && !$("#scenario").innerHTML) runScenario();
}
function fillSelects() {
  const opts = ops().map(o => `<option value="${o.op_id}">${o.op_id} · ${esc(o.name)}</option>`).join("");
  const scPrev = $("#sc-op").value;
  $("#op-select").innerHTML = opts; $("#sc-op").innerHTML = opts;
  if (!S.opId || !opById(S.opId)) S.opId = [...ops()].sort((a, b) => a.result - b.result)[0].op_id;
  $("#op-select").value = S.opId;
  $("#sc-op").value = opById(scPrev) ? scPrev : ops()[0].op_id;
  const f = $("#f-faculty"), cur = S.filters.faculty;
  f.innerHTML = `<option value="">Барлық факультеттер</option>` + S.data.faculties.map(x => `<option>${esc(x)}</option>`).join("");
  f.value = S.data.faculties.includes(cur) ? cur : ""; S.filters.faculty = f.value;
}
function renderAll() {
  renderHeader(); fillSelects(); renderDashboard(); renderOp(); renderQuality(); renderForecast(); renderMethod(); initChat();
  $("#scenario").innerHTML = ""; if ($("#tab-scenario").classList.contains("active")) runScenario();
}
async function load() {
  S.data = await api("/api/state");
  renderAll();
}
async function upload(file) {
  if (!file) return;
  toast(`«${file.name}» жүктелуде…`);
  try {
    const r = await api("/api/upload", { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) } });
    S.uploadError = null; await load();
    toast(`✓ ${r.filename}: ${r.ops} ОП есептелді${r.warnings ? ` · ${r.warnings} ескерту` : ""}`);
  } catch (e) {
    S.uploadError = e.body || { error: e.message, issues: [] }; renderQuality(); switchTab("quality");
    toast(e.message, true);
  } finally { $("#file-input").value = ""; }
}

function wire() {
  $$("#tabs button").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#file-input").addEventListener("change", e => upload(e.target.files[0]));
  document.addEventListener("dragover", e => e.preventDefault());
  document.addEventListener("drop", e => { e.preventDefault(); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
  $("#btn-demo").addEventListener("click", async () => { await post("/api/reset", {}); S.uploadError = null; await load(); toast("Демо деректер қайта жүктелді"); });
  $("#f-faculty").addEventListener("change", e => { S.filters.faculty = e.target.value; renderDashboard(); });
  $("#f-sort").addEventListener("change", e => { S.filters.sort = e.target.value; S.tableSort = { key: e.target.value, dir: -1 }; renderDashboard(); });
  $$("#f-status button").forEach(b => b.addEventListener("click", () => {
    $$("#f-status button").forEach(x => x.classList.toggle("on", x === b)); S.filters.status = b.dataset.v; renderDashboard();
  }));
  $("#op-select").addEventListener("change", e => { S.opId = e.target.value; renderOp(); });
  $("#btn-explain").addEventListener("click", explainCurrent);
  $("#btn-op-scenario").addEventListener("click", () => { $("#sc-op").value = S.opId; $("#sc-pct").value = 10; switchTab("scenario"); queueScenario(); });
  $("#sc-op").addEventListener("change", queueScenario);
  ["#sc-pct", "#sc-fot", "#sc-dir"].forEach(id => $(id).addEventListener("input", queueScenario));
  $$("#sc-quick button").forEach(b => b.addEventListener("click", () => { $("#sc-pct").value = b.dataset.v; queueScenario(); }));
  $("#chat-form").addEventListener("submit", e => { e.preventDefault(); const q = $("#chat-q").value; $("#chat-q").value = ""; ask(q); });
  addEventListener("hashchange", () => { const h = location.hash.slice(1); if (S.data && $("#tab-" + h)) switchTab(h); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => S.data && renderAll());
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => S.data && renderDashboard(), 200); });
}

wire();
load().then(() => { const h = location.hash.slice(1); if (h && $("#tab-" + h)) switchTab(h); })
  .catch(e => toast("Деректер жүктелмеді: " + e.message, true));
