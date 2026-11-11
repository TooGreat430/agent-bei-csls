"""Uji kemampuan Strategist Toolkit: cakupan semua kerangka pptx, panduan, diagram, dan perhitungan keputusan."""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import strategy_diagrams as sd  # noqa: E402
from library_agent.tools import strategy_tools as st  # noqa: E402

# Semua kerangka di "Overnight Strategist – Strategist Toolkit V3" (Define, Split, Analyse, Insight, Story, Decide, Act)
PPTX_FRAMEWORKS = [
    "scq", "htdq", "outcome", "driver_tree", "bucketing", "hypothesis",
    "trend", "comparison", "mix", "distribution", "scatter", "cumulative", "candlestick", "rank", "unit_economics",
    "waterfall", "marginal_return", "cashflow", "roic", "actual_target", "profit_margin", "five_whys", "five_w_h", "yes_no",
    "tabular", "one_pager", "canvas", "tri_column", "chevron", "horizon", "gantt", "continuum", "heat_map", "graph_page",
    "matrix", "from_to", "venn", "positioning", "pyramid", "circular", "journey", "timeline", "capability_map",
    "image_column", "segmentation", "hub_spoke", "three_by_three",
    "minto", "hv_logic", "mece", "scqa", "story_spine", "five_act", "storybrand",
    "eisenhower", "abcd", "decision_tree", "pros_cons", "evaluation", "bezos", "spade", "bull_bear",
    "zero_to_one", "comms_deploy", "decision_grid", "gtm_stack", "execution_plan", "capability_drop",
]


class CoverageTest(unittest.TestCase):
    def test_every_pptx_framework_has_guidance(self):
        sections = st._sections()
        missing = [k for k in PPTX_FRAMEWORKS if k not in sections]
        self.assertEqual(missing, [])

    def test_panduan_tool(self):
        ctx = NS(state={})
        res = st.panduan_kerangka("Driver Tree", ctx)
        self.assertEqual(res["status"], "ok")
        self.assertIn("Active Customer × volume per customer", res["panduan"])
        self.assertIn("angka hanya", res["prinsip"])
        self.assertGreaterEqual(len(st.panduan_kerangka("", ctx)["kerangka"]), len(PPTX_FRAMEWORKS))
        self.assertEqual(st.panduan_kerangka("swot", ctx)["status"], "invalid")


class DecisionMathTest(unittest.TestCase):
    def test_expected_value_percent_and_fraction(self):
        evs, notes = sd.decision_values({"opsi": [
            {"nama": "Display", "hasil": [{"label": "ok", "peluang": 60, "nilai": 120}, {"label": "x", "peluang": 40, "nilai": -20}]},
            {"nama": "Diskon", "hasil": [{"label": "ok", "peluang": 0.5, "nilai": 150}, {"label": "x", "peluang": 0.5, "nilai": -60}]}]})
        self.assertEqual(evs, [("Display", 64.0), ("Diskon", 45.0)])
        self.assertEqual(notes, [])

    def test_probability_warning(self):
        _, notes = sd.decision_values({"opsi": [{"nama": "A", "hasil": [{"label": "x", "peluang": 0.5, "nilai": 1}]}]})
        self.assertIn("berjumlah 50%", notes[0])

    def test_weighted_scores_ranked(self):
        ranked = sd.weighted_scores({"kriteria": [{"nama": "Dampak", "bobot": 40}, {"nama": "Biaya", "bobot": 30},
                                                  {"nama": "Cepat", "bobot": 30}],
                                     "opsi": [{"nama": "Display", "skor": [4, 4, 3]}, {"nama": "Diskon", "skor": [5, 2, 5]}]})
        self.assertEqual([(n, round(s, 2)) for n, s, _ in ranked], [("Diskon", 4.1), ("Display", 3.7)])
        with self.assertRaises(sd.DiagramError):
            sd.weighted_scores({"kriteria": [{"nama": "a", "bobot": 1}], "opsi": [{"nama": "x", "skor": [1, 2]}]})


class RenderTest(unittest.TestCase):
    def test_all_kinds_and_aliases_render(self):
        samples = {
            "panel": {"bagian": [{"judul": "S", "teks": "t"}]},
            "driver_tree": {"akar": "Volume", "cabang": [{"label": "AC", "anak": [{"label": "baru"}]}]},
            "hypothesis_tree": {"akar": "ND turun", "cabang": [{"label": "H1", "status": "terbukti", "catatan": "x"}]},
            "five_whys": {"masalah": "m", "langkah": [{"mengapa": "a", "alasan": "b"}], "akar_masalah": "c"},
            "decision_flow": {"masalah": "m", "langkah": [{"pertanyaan": "q", "ya": "y"}], "akhir": "z"},
            "table": {"kolom": ["a", "b"], "baris": [["1", "2"]]},
            "heat_table": {"kolom": ["a", "b"], "baris": [["x", "TINGGI"]]},
            "one_pager": {"lapisan": [{"judul": "L1", "item": ["a"]}]},
            "columns": {"kolom": [{"judul": "a", "poin": ["b"]}]},
            "chevron": {"tahap": [{"nama": "a", "poin": ["b"]}]},
            "gantt": {"periode": ["Q1", "Q2"], "baris": [{"stream": "s", "aktivitas": "a", "mulai": "Q1", "selesai": "Q2"}]},
            "matrix_2x2": {"kuadran": ["a", "b", "c", "d"], "item": [{"label": "x", "kuadran": 1}]},
            "matrix_3x3": {"item": [{"label": "x", "x": 3, "y": 3}]},
            "from_to": {"dari": ["a"], "ke": ["b"]},
            "pyramid": {"puncak": "p", "argumen": [{"judul": "a", "bukti": ["b"]}]},
            "decision_tree": {"opsi": [{"nama": "A", "hasil": [{"label": "x", "peluang": 1, "nilai": 5}]}]},
            "pros_cons": {"opsi": [{"nama": "A", "pro": ["p"], "kontra": ["k"]}]},
            "evaluation": {"kriteria": [{"nama": "k", "bobot": 1}], "opsi": [{"nama": "A", "skor": [3]}]},
        }
        self.assertEqual(set(samples), set(sd.KINDS))
        for kind, isi in samples.items():
            png, _ = sd.render(kind, "Uji", isi)
            self.assertTrue(png.startswith(b"\x89PNG"), kind)
        png, facts = sd.render("eisenhower", "Prioritas", {"item": [{"label": "Restok", "kuadran": 1}]})
        self.assertIn("DO — kerjakan sekarang: Restok", facts[0])

    def test_errors(self):
        with self.assertRaises(sd.DiagramError):
            sd.render("swot", "x", {})
        with self.assertRaises(sd.DiagramError):
            sd.render("gantt", "x", {"periode": ["Q1"], "baris": [{"stream": "s", "aktivitas": "a", "mulai": "Q9"}]})


class ToolTest(unittest.TestCase):
    def test_buat_diagram_records_for_report(self):
        ctx = NS(state={}, user_id="u", _invocation_context=None)
        with mock.patch("library_agent.tools.chart_insight_tools._upload", return_value="https://x/d.png"):
            res = st.buat_diagram("evaluation", "Diskon paling unggul", {
                "kriteria": [{"nama": "Dampak", "bobot": 50}, {"nama": "Biaya", "bobot": 50}],
                "opsi": [{"nama": "Diskon", "skor": [5, 3]}, {"nama": "Display", "skor": [3, 4]}]}, ctx)
            bad = st.buat_diagram("gantt", "x", {"periode": ["Q1"], "baris": [{"stream": "s", "aktivitas": "a", "mulai": "Q7"}]}, ctx)
        self.assertEqual(res["status"], "ok")
        self.assertIn("Rekomendasi: Diskon (skor berbobot 4,00", res["fakta"][0])
        self.assertEqual(ctx.state["insight_charts"][0]["jenis"], "diagram:evaluation")
        self.assertEqual(bad["status"], "error")

    def test_wired_everywhere(self):
        from library_agent import prompts
        from library_agent.subagents.data import data_agent
        from library_agent.subagents.files import file_agent
        from library_agent.subagents.report import report_agent

        for agent in (data_agent, file_agent, report_agent):
            self.assertTrue({"panduan_kerangka", "buat_diagram"} <= {t.__name__ for t in agent.tools})
        for ins in (prompts.DATA_INSTRUCTION, prompts.FILE_INSTRUCTION, prompts.REPORT_INSTRUCTION):
            self.assertIn("KERANGKA ANALISIS STRATEGIST TOOLKIT", ins)


if __name__ == "__main__":
    unittest.main()
