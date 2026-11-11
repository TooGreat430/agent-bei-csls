"""Uji insight otomatis: angka sorotan per jenis chart, buat_insight, daftar_data, dan aturan korelasi."""
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

from library_agent import insight_charts as ic  # noqa: E402
from library_agent.tools import chart_insight_tools as ct  # noqa: E402

SR = ["SR1", "SR2", "SR3", "SR4", "SR5"]


class FactsTest(unittest.TestCase):
    def test_pareto(self):
        t = {"columns": ["DIST", "VOL"], "rows": [["A", 50], ["B", 30], ["C", 10], ["D", 5], ["E", 5]]}
        _, f = ic.build("cumulative", t, {"x": "DIST", "y": ["VOL"]})
        self.assertIn("2 dari 5 DIST (40,0%) menyumbang ≥80% VOL (tepatnya 80,0%)", f[0])

    def test_waterfall(self):
        t = {"columns": ["SR", "Q2", "Q3"], "rows": [["SR1", 100, 120], ["SR2", 100, 90]]}
        _, f = ic.build("waterfall", t, {"x": "SR", "y": ["Q2", "Q3"], "satuan": "KL"})
        self.assertEqual(f[0], "Total Q2 200 → Q3 210 KL (+10,0)")
        self.assertIn("Pendorong naik terbesar SR1: +20,0 KL; penekan terbesar SR2: -10,0 KL", f[1])

    def test_actual_target_and_mix_and_rank(self):
        t = {"columns": ["SR", "A", "T"], "rows": [["SR1", 90, 100], ["SR2", 110, 100]]}
        self.assertIn("Pencapaian total 100,0%", ic.build("actual_target", t, {"x": "SR", "y": ["A", "T"]})[1][0])
        m = {"columns": ["CH", "Q2", "Q3"], "rows": [["Bengkel", 50, 40], ["Toko", 50, 60]]}
        self.assertIn("Toko +10,0 pp", ic.build("mix", m, {"x": "CH", "y": ["Q2", "Q3"]})[1][0])
        r = {"columns": ["Q", "B", "V"], "rows": [["Q1", "PTPL", 1], ["Q1", "AHM", 2], ["Q2", "PTPL", 3], ["Q2", "AHM", 2]]}
        self.assertIn("PTPL (+1 posisi)", ic.build("rank", r, {"x": "Q", "kategori": "B", "nilai": "V"})[1][0])

    def test_scatter_correlation_and_format(self):
        t = {"columns": ["SR", "X", "Y"], "rows": [[s, i, 2 * i + 1] for i, s in enumerate(SR, 1)]}
        _, f = ic.build("scatter", t, {"x": "X", "y": ["Y"], "label": "SR"})
        self.assertIn("r = 1,00 (sangat kuat positif), n = 5", f[0])
        self.assertEqual(ic.num("1.234.567,8"), 1234567.8)
        self.assertEqual(ic.fmt(65128.73), "65.129")

    def test_unknown_kind_and_bad_column(self):
        t = {"columns": ["A"], "rows": [[1]]}
        with self.assertRaises(ic.ChartError):
            ic.build("pie3d", t, {})
        with self.assertRaises(ic.ChartError):
            ic.build("comparison", t, {"x": "ZZZ", "y": ["A"]})


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.uploads = []
        self.p = mock.patch.object(ct, "_upload", side_effect=lambda ctx, png, title: (self.uploads.append(title),
                                                                                       f"https://x/{title}.png")[1])
        self.p.start()
        self.state = {"bq_pulls": [
            {"id": "p1", "domain": "retail", "question": "gap per SR", "tables": [
                {"columns": ["SR", "GAP_HJ"], "rows": [[s, v] for s, v in zip(SR, [5, -2, 3, 8, 1])]}]},
            {"id": "p2", "domain": "planogram", "question": "ND per SR", "tables": [
                {"columns": ["SALES_REGION", "ND_PTPL"], "rows": [[s, v] for s, v in zip(SR, [60, 40, 55, 70, 45])]}]},
            {"id": "p3", "domain": "sellout", "question": "volume per SR", "tables": [
                {"columns": ["SR", "VOL"], "rows": [[s, v] for s, v in zip(SR, [10, 9, 12, 15, 8])]}]}]}
        self.ctx = NS(state=self.state, user_id="u", _invocation_context=None)

    def tearDown(self):
        self.p.stop()

    def test_daftar_data(self):
        ids = [d["data_id"] for d in ct.daftar_data(self.ctx)["data"]]
        self.assertEqual(ids, ["p1", "p2", "p3"])

    def test_buat_insight_multiple_with_error(self):
        res = ct.buat_insight([{"jenis": "comparison", "data_id": "p1", "x": "SR", "y": ["GAP_HJ"],
                                "judul": "SR4 gap tertinggi"},
                               {"jenis": "cumulative", "data_id": "p3", "x": "SR", "y": ["VOL"], "judul": "Pareto"},
                               {"jenis": "trend", "data_id": "p1", "x": "TIDAK_ADA", "y": ["GAP_HJ"]}], self.ctx)
        self.assertEqual([c["status"] for c in res["chart"]], ["ok", "ok", "error"])
        self.assertIn("Tertinggi SR4: 8,00", res["chart"][0]["fakta"][0])
        self.assertEqual(len(self.state["insight_charts"]), 2)

    def test_korelasi_retail_planogram_allowed(self):
        res = ct.korelasi_data("p1", "p2", "SR", "SALES_REGION", "GAP_HJ", "ND_PTPL", self.ctx)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["pasangan"], 5)
        self.assertIn("r Pearson =", res["fakta"][0])
        self.assertIn("n kecil", res["fakta"][1])

    def test_korelasi_sellout_planogram_refused(self):
        res = ct.korelasi_data("p3", "p2", "SR", "SALES_REGION", "VOL", "ND_PTPL", self.ctx)
        self.assertEqual(res["status"], "not_allowed")

    def test_korelasi_same_source_allowed(self):
        self.state["bq_pulls"].append({"id": "p4", "domain": "sellout", "question": "AC per SR", "tables": [
            {"columns": ["SR", "AC"], "rows": [[s, v] for s, v in zip(SR, [100, 90, 130, 160, 70])]}]})
        res = ct.korelasi_data("p3", "p4", "SR", "SR", "VOL", "AC", self.ctx)
        self.assertEqual(res["status"], "ok")
        self.assertIn("sangat kuat positif", res["fakta"][0])

    def test_report_reuses_charts(self):
        from library_agent.tools import report_tools as rt

        ct.buat_insight([{"jenis": "comparison", "data_id": "p1", "x": "SR", "y": ["GAP_HJ"], "judul": "SR4 tertinggi"}],
                        self.ctx)
        text = "\n".join(rt._chart_blocks(self.ctx))
        self.assertIn("SR4 tertinggi", text)
        self.assertIn("Tertinggi SR4", text)

    def test_tools_and_rules_wired(self):
        from library_agent import prompts
        from library_agent.subagents.data import data_agent
        from library_agent.subagents.files import file_agent

        for agent in (data_agent, file_agent):
            names = {t.__name__ for t in agent.tools}
            self.assertTrue({"buat_insight", "korelasi_data", "daftar_data"} <= names)
        self.assertIn("INSIGHT OTOMATIS", prompts.DATA_INSTRUCTION)
        self.assertIn("INSIGHT OTOMATIS", prompts.FILE_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()


class AutoCompleteTest(unittest.TestCase):
    """Kasus nyata: model hanya meminta 1 chart untuk tabel gap harga per produk × SR."""

    def _state(self, rows):
        return {"bq_pulls": [{"id": "p1", "domain": "retail", "question": "gap", "tables": [
            {"columns": ["SALES_REGION", "PRODUCT_HERO", "GAP_HJ_PER_LITER"], "rows": rows}]}]}

    def test_one_chart_becomes_three(self):
        prods = ["PERTAMINA MEDITRAN SC 5 LITER", "PERTAMINA FASTRON 4 LITER", "PERTAMINA ENDURO 1 LITER"]
        rows = [[f"SR{s}", p, (s * 37 + i * 101) % 900 - 450] for s in range(1, 8) for i, p in enumerate(prods)]
        rows[0][2] = -38056
        ctx = NS(state=self._state(rows), user_id="u", _invocation_context=None)
        with mock.patch.object(ct, "_upload", return_value="https://x/c.png"):
            res = ct.buat_insight([{"jenis": "comparison", "data_id": "p1", "x": "PRODUCT_HERO",
                                    "y": ["GAP_HJ_PER_LITER"], "judul": "Gap harga"}], ctx)
        kinds = [c["jenis"] for c in res["chart"] if c["status"] == "ok"]
        self.assertEqual(kinds, ["comparison", "heatmap", "distribution"])
        self.assertTrue(all(c.get("otomatis") for c in res["chart"][1:]))
        self.assertIn("21 baris → 3 PRODUCT_HERO", res["chart"][0]["fakta"][1])          # duplikat produk digabung
        self.assertIn("-38.056", res["chart"][2]["fakta"][-1])                           # pencilan disebut

    def test_no_autocomplete_for_tiny_table(self):
        ctx = NS(state=self._state([["SR1", "A", 5], ["SR2", "A", 6]]), user_id="u", _invocation_context=None)
        with mock.patch.object(ct, "_upload", return_value="https://x/c.png"):
            res = ct.buat_insight([{"jenis": "comparison", "data_id": "p1", "x": "SALES_REGION",
                                    "y": ["GAP_HJ_PER_LITER"]}], ctx)
        self.assertEqual(len(res["chart"]), 1)

    def test_helpers(self):
        self.assertEqual(ic.strip_common_prefix(["PERTAMINA A 1L", "PERTAMINA B 4L"]), ["A 1L", "B 4L"])
        self.assertEqual(ic.strip_common_prefix(["AHM", "SHELL"]), ["AHM", "SHELL"])
        normal, extreme = ic.outliers([1, 2, 3, 2, 1, 3, 2, 1, 2, -500])
        self.assertEqual(extreme, [-500])
        self.assertTrue(ic.lower_is_better("retail", "GAP_HJ_PER_LITER"))
        self.assertFalse(ic.lower_is_better("industri", "GAP_HARGA_PCT"))
        trend = {"columns": ["BULAN", "SR", "VOL"], "rows": [["Jan", "SR1", 10], ["Jan", "SR2", 20], ["Feb", "SR1", 30],
                                                           ["Feb", "SR2", 40]]}
        spec, facts = ic.build("trend", trend, {"x": "BULAN", "y": ["VOL"]})
        self.assertEqual(spec["x"], ["Jan", "Feb"])
        self.assertEqual(spec["series"][0][1], [15.0, 35.0])
