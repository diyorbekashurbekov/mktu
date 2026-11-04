"""Financial correctness: the engine against an independent re-implementation of the case methodology."""
import copy
import unittest
from collections import defaultdict

from helpers import demo_bytes, demo_sheets, make_xlsx

from profitai.engine import acceptance_checks, compute
from profitai.loader import ValidationFailed, load_dataset
from profitai.scenario import break_even, run as run_scenario
from profitai.state import AppState


def reference_pnl(sheets):
    """Straight-line implementation of §4 directly from raw sheet rows (no shared code with engine.py)."""
    def rows(name):
        head, *body = sheets[name]
        return [dict(zip(head, r)) for r in body]

    ops = [r["op_id"] for r in rows("ОП")]
    rev = defaultdict(float)
    for r in rows("Контингент"):
        t = r["тариф_контракт_тг"]
        rev[r["op_id"]] += (r["контракт_полный"] * t + r["контракт_со_скидкой"] * t * (1 - r["скидка_доля"])
                            + r["грант"] * r["финансирование_грант_тг"])
    annual = {r["teacher_id"]: r["зарплата_в_месяц_тг"] * r["месяцев_оплаты"] * (1 + r["начисления_работодателя_доля"])
              for r in rows("Штат_ППС")}
    hours_t = defaultdict(float)
    for r in rows("Нагрузка_ППС"):
        hours_t[r["teacher_id"]] += r["часы_в_год"]
    fot = defaultdict(float)
    for r in rows("Нагрузка_ППС"):
        fot[r["op_id"]] += annual[r["teacher_id"]] * r["часы_в_год"] / hours_t[r["teacher_id"]]
    direct = defaultdict(float)
    for r in rows("Прямые_затраты"):
        direct[r["op_id"]] += r["сумма_в_год_тг"]
    col = {"students": "студентов_активных", "area_m2": "площадь_м2", "lab_hours": "лабораторные_часы"}
    drv = {r["op_id"]: r for r in rows("Драйверы")}
    oh = defaultdict(float)
    for c in rows("Общие_затраты"):
        k = col[c["драйвер_распределения"]]
        tot = sum(drv[o][k] for o in ops)
        for o in ops:
            oh[o] += c["сумма_в_год_тг"] * drv[o][k] / tot
    out = {}
    for o in ops:
        total = fot[o] + direct[o] + oh[o]
        res = rev[o] - total
        out[o] = {"revenue": rev[o], "fot": fot[o], "direct": direct[o], "overhead": oh[o], "total_cost": total,
                  "result": res, "margin": res / rev[o] * 100, "cost_per_student": total / drv[o]["студентов_активных"]}
    return out, sum(annual.values())


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(demo_bytes(), "demo.xlsx")
        cls.pnl = compute(cls.ds)
        cls.ref, cls.staff_fot = reference_pnl(demo_sheets())

    def test_all_12_ops_loaded(self):
        self.assertEqual(len(self.pnl["ops"]), 12)
        self.assertEqual([i for i in self.ds.issues if i["level"] == "error"], [])

    def test_metrics_match_reference_within_tolerance(self):
        for o in self.pnl["ops"]:
            ref = self.ref[o["op_id"]]
            for k in ("revenue", "fot", "direct", "overhead", "total_cost", "result", "cost_per_student"):
                self.assertLessEqual(abs(o[k] - ref[k]), 1, f"{o['op_id']} {k}")
            self.assertLessEqual(abs(o["margin"] - ref["margin"]), 0.01, o["op_id"])

    def test_fot_allocated_equals_staff_fot(self):
        self.assertLessEqual(abs(self.pnl["totals"]["fot"] - self.staff_fot), 1)
        self.assertAlmostEqual(self.staff_fot, 736_465_200, delta=1)

    def test_overhead_allocated_equals_500m(self):
        self.assertLessEqual(abs(self.pnl["totals"]["overhead"] - 500_000_000), 1)

    def test_known_values(self):
        by = {o["op_id"]: o for o in self.pnl["ops"]}
        self.assertAlmostEqual(by["OP-001"]["revenue"], 380_067_000, delta=0.01)
        self.assertAlmostEqual(by["OP-004"]["result"], -42_368_719.21, delta=0.01)
        self.assertEqual(sorted(o for o, v in by.items() if v["result"] < 0), ["OP-004", "OP-007", "OP-011"])

    def test_acceptance_checks_pass(self):
        checks = acceptance_checks(self.ds, self.pnl)
        self.assertTrue(all(c["pass"] for c in checks), [c for c in checks if not c["pass"]])

    def test_zero_students_gives_na_not_division_error(self):
        ds = copy.deepcopy(self.ds)
        ds.drivers["OP-004"]["students"] = 0
        o = next(x for x in compute(ds)["ops"] if x["op_id"] == "OP-004")
        self.assertIsNone(o["cost_per_student"])
        self.assertIsNone(o["fot_per_student"])

    def test_zero_revenue_margin_na(self):
        ds = copy.deepcopy(self.ds)
        ds.contingent = [r for r in ds.contingent if r["op_id"] != "OP-007"]
        o = next(x for x in compute(ds)["ops"] if x["op_id"] == "OP-007")
        self.assertEqual(o["revenue"], 0)
        self.assertIsNone(o["margin"])


class ScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(demo_bytes(), "demo.xlsx")
        cls.pnl = compute(cls.ds)

    def test_plus_10_base_model(self):
        sc = run_scenario(self.ds, self.pnl, "OP-004", 10)
        s = sc["selected"]
        self.assertAlmostEqual(s["after"]["revenue"], s["before"]["revenue"] * 1.1, delta=0.01)
        self.assertAlmostEqual(s["after"]["fot"], s["before"]["fot"], delta=0.01)
        self.assertAlmostEqual(s["after"]["direct"], s["before"]["direct"], delta=0.01)
        self.assertTrue(sc["overhead_preserved"])
        self.assertAlmostEqual(sc["totals"]["after"]["overhead"], 500_000_000, delta=1)
        # only students-driven pools move: other ОП absorb less overhead
        self.assertGreater(s["delta"]["overhead"], 0)
        self.assertGreater(sc["others_result_delta"], 0)
        self.assertAlmostEqual(sc["others_result_delta"], s["delta"]["overhead"], delta=1)

    def test_minus_10(self):
        sc = run_scenario(self.ds, self.pnl, "OP-001", -10)
        self.assertAlmostEqual(sc["selected"]["after"]["revenue"], 380_067_000 * 0.9, delta=0.01)
        self.assertLess(sc["selected"]["delta"]["result"], 0)

    def test_variable_cost_share(self):
        sc = run_scenario(self.ds, self.pnl, "OP-001", 10, fot_var=0.5)
        s = sc["selected"]
        self.assertAlmostEqual(s["after"]["fot"], s["before"]["fot"] * 1.05, delta=0.01)

    def test_break_even_zeroes_result(self):
        be = break_even(self.ds, "OP-011")
        self.assertTrue(be["reachable"])
        out = compute(self.ds, {"OP-011": 1 + be["pct"] / 100})
        self.assertLess(abs(next(o for o in out["ops"] if o["op_id"] == "OP-011")["result"]), 1)


class QualityTest(unittest.TestCase):
    def test_six_anomalies_detected_and_isolated(self):
        st = AppState(demo_bytes(), "demo.xlsx")
        q = st.quality
        self.assertEqual(q["count"], 6)
        found = {(a["source_row_id"], a["type"]) for a in q["anomalies"]}
        self.assertEqual(found, {("SRC-004", "duplicate_id"), ("SRC-901", "unknown_op"), ("SRC-902", "negative_value"),
                                 ("SRC-903", "pct_out_of_range"), ("SRC-904", "missing_value"),
                                 ("SRC-905", "invalid_period")})
        self.assertEqual({a["excel_row"] for a in q["anomalies"]}, {26, 27, 28, 29, 30, 31})
        self.assertTrue(q["pnl_isolated"])
        self.assertTrue(all(c["pass"] for c in st.checks))

    def test_detection_ignores_comment_column(self):
        sheets = demo_sheets()
        sig = sheets["Сырые_сигналы"]
        for row in sig[1:]:
            row[5] = "OK"
        st = AppState(make_xlsx(sheets), "nocomment.xlsx")
        self.assertEqual(st.quality["count"], 6)


class LoaderTest(unittest.TestCase):
    def test_roundtrip_generated_workbook(self):
        st = AppState(make_xlsx(demo_sheets()), "copy.xlsx")
        self.assertEqual(len(st.pnl["ops"]), 12)
        self.assertAlmostEqual(st.pnl["totals"]["overhead"], 500_000_000, delta=1)

    def test_missing_sheet_blocks(self):
        sheets = demo_sheets()
        del sheets["Контингент"]
        with self.assertRaises(ValidationFailed) as cm:
            load_dataset(make_xlsx(sheets))
        self.assertTrue(any("Контингент" in i["message"] for i in cm.exception.issues))

    def test_missing_column_blocks(self):
        sheets = demo_sheets()
        sheets["Штат_ППС"] = [r[:4] for r in sheets["Штат_ППС"]]
        with self.assertRaises(ValidationFailed):
            load_dataset(make_xlsx(sheets))

    def test_bad_row_excluded_not_fatal(self):
        sheets = demo_sheets()
        sheets["Прямые_затраты"].append(["DC-BAD", "OP-001", "Ошибка", "abc", ""])
        sheets["Прямые_затраты"].append(["DC-NEG", "OP-002", "Ошибка", -5, ""])
        ds = load_dataset(make_xlsx(sheets))
        excluded = [i for i in ds.issues if i["code"] == "row_excluded"]
        self.assertEqual(len(excluded), 2)
        base = compute(load_dataset(demo_bytes()))
        self.assertAlmostEqual(compute(ds)["totals"]["direct"], base["totals"]["direct"], delta=0.01)

    def test_unknown_op_in_pnl_sheet_excluded(self):
        sheets = demo_sheets()
        sheets["Прямые_затраты"].append(["DC-X", "OP-777", "Оборудование", 1_000_000, ""])
        ds = load_dataset(make_xlsx(sheets))
        self.assertTrue(any(i["code"] == "unknown_op" for i in ds.issues))
        self.assertEqual(len(compute(ds)["ops"]), 12)

    def test_not_an_xlsx(self):
        from profitai.xlsx import XlsxError
        with self.assertRaises(XlsxError):
            load_dataset(b"hello world")


if __name__ == "__main__":
    unittest.main()
