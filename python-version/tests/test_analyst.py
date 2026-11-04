"""AI analyst: routing, evidence, no invented numbers, Claude layer with a fake client."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from helpers import demo_bytes

from profitai import analyst, llm
from profitai.state import AppState


class RouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = AppState(demo_bytes(), "demo.xlsx")

    def ask(self, q):
        with mock.patch.object(llm, "available", return_value=False):
            return analyst.ask(self.st, q)

    def test_case_questions(self):
        cases = {
            "Какие ОП убыточны?": ("status_list", ["OP-004", "OP-007", "OP-011"]),
            "Почему у прикладной математики такой результат?": ("explain", ["OP-004"]),
            "Где самый высокий ФОТ на студента?": ("rank", None),
            "Қандай ОП шығынды?": ("status_list", None),
            "Қолданбалы математиканың нәтижесі неге осындай?": ("explain", ["OP-004"]),
            "Что если контингент Информатики вырастет на 10%?": ("scenario", ["OP-001"]),
            "Переводческое дело -10%": ("scenario", ["OP-007"]),
            "Сырые_сигналы ішінде қандай қателер бар?": ("anomalies", None),
            "Какой прогноз набора на следующий год?": ("forecast", None),
            "Сравни экономику и менеджмент": ("compare", ["OP-008", "OP-009"]),
            "Как считается доход?": ("methodology", None),
            "Сравни факультеты": ("faculty", None),
            "Финансы": ("op_summary", ["OP-010"]),
            "Какая погода завтра?": ("help", None),
        }
        for q, (intent, ops) in cases.items():
            a = self.ask(q)
            self.assertEqual(a["intent"], intent, q)
            if ops:
                self.assertEqual(a.get("op_ids"), ops, q)

    def test_language(self):
        self.assertEqual(self.ask("Какие ОП убыточны?")["lang"], "ru")
        self.assertEqual(self.ask("Қандай ОП шығынды?")["lang"], "kz")

    def test_fot_per_student_top_is_math(self):
        a = self.ask("Где самый высокий ФОТ на студента?")
        self.assertEqual(a["op_ids"][0], "OP-004")
        self.assertIn("932 208,95 ₸", a["text"])

    def test_scenario_sign(self):
        a = self.ask("Что если контингент Информатики снизится на 10%?")
        self.assertEqual(a["scenario"]["pct"], -10)

    def test_answers_carry_evidence(self):
        for q in ("Какие ОП убыточны?", "Почему у прикладной математики такой результат?", "Где самый высокий ФОТ на студента?"):
            a = self.ask(q)
            self.assertTrue(a["sources"], q)
            self.assertTrue(a["formula"], q)
            self.assertTrue(a["assumptions"], q)

    def test_explain_has_factors_and_options(self):
        for op in self.st.ds.ops:
            a = analyst.tool_explain(self.st, op, "ru")
            ex = a["explain"]
            self.assertTrue(3 <= len(ex["factors"]) <= 5, op)
            self.assertGreaterEqual(len(ex["options"]), 2, op)
            self.assertTrue(all(p["risks"] for p in ex["options"]), op)
            # exact decomposition
            o = next(x for x in self.st.pnl["ops"] if x["op_id"] == op)
            self.assertAlmostEqual(ex["baseline"] + sum(ex["gaps"].values()), o["result"], delta=1)

    def test_numbers_in_text_come_from_pnl(self):
        a = self.ask("Какие ОП убыточны?")
        self.assertEqual(llm.verify(a["text"], [a], ""), [])


class FakeBlock(SimpleNamespace):
    pass


class LlmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = AppState(demo_bytes(), "demo.xlsx")

    def _fake(self, final_text):
        calls = []

        def create(**kw):
            calls.append(kw)
            if len(calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    FakeBlock(type="tool_use", id="t1", name="status_list", input={"status": "loss"})])
            return SimpleNamespace(stop_reason="end_turn", content=[FakeBlock(type="text", text=final_text)])
        return create, calls

    def test_verified_answer_is_used(self):
        create, calls = self._fake("Убыточны 3 ОП: Прикладная математика −42 368 719,21 ₸, Переводческое дело "
                                   "−31 542 911,92 ₸ и Сестринское дело −7 309 124,29 ₸.")
        with mock.patch.object(llm, "_create", side_effect=create):
            a = llm.ask(self.st, "Какие ОП убыточны?")
        self.assertEqual(a["mode"], "claude")
        self.assertEqual(a["tools_used"], ["status_list"])
        tool_result = calls[1]["messages"][-1]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertIn("Прикладная математика", json.loads(tool_result["content"])["text"])

    def test_invented_number_is_rejected(self):
        create, _ = self._fake("Убыток Прикладной математики составляет 55 000 000 ₸.")
        with mock.patch.object(llm, "_create", side_effect=create):
            a = llm.ask(self.st, "Какие ОП убыточны?")
        self.assertEqual(a["mode"], "rules")
        self.assertIn("55000000.0", a["llm_rejected"])

    def test_unknown_tool_input_returns_error_result(self):
        calls = []

        def create(**kw):
            calls.append(kw)
            if len(calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    FakeBlock(type="tool_use", id="t1", name="op_summary", input={"op_id": "OP-999"})])
            return SimpleNamespace(stop_reason="end_turn", content=[FakeBlock(type="text", text="Нет такой ОП.")])
        with mock.patch.object(llm, "_create", side_effect=create):
            a = llm.ask(self.st, "OP-999?")
        self.assertIsNone(a)  # no successful tool -> caller falls back to rules
        self.assertTrue(calls[1]["messages"][-1]["content"][0]["is_error"])


if __name__ == "__main__":
    unittest.main()
