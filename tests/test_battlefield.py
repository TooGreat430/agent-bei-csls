"""Uji analisis silang Retail × Planogram (Competitive Battlefield): klasifikasi, perhitungan, dan template."""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

import pandas as pd  # noqa: E402

from library_agent import battlefield_data as bd  # noqa: E402
from library_agent import battlefield_report as br  # noqa: E402
from library_agent import custom_report as cr  # noqa: E402
from library_agent import data_engine as de  # noqa: E402
from library_agent import planogram_data as pdm  # noqa: E402
from library_agent import ptpl_design, sample_planogram, sample_retail  # noqa: E402
from test_planogram import TINY  # noqa: E402

PA, PB = pdm.parse_period("2026-Q3"), pdm.parse_period("2026-Q2")


def retail_row(brand, hj, marg, date="2026-08-20", kimap="K1", qnr=None):
    return {"SURVEY_DATE": date, "SALES_REGION_CUSTOMER": 5, "QNR": qnr or f"{brand} PRODUK 0.8 LITER",
            "SEGMENT": "MCO", "HARGA_TEBUS": hj - marg, "HARGA_JUAL": hj, "HTO": hj - marg, "HET": hj, "USED_FOR": "Automatic",
            "VISCOSITY": "10W-30", "BRAND": brand, "CONTENT": 0.8, "KIMAP": kimap, "OUTLIER_HTO": "DATA USE",
            "OUTLIER_HET": "DATA USE", "MARGIN_SURVEY": marg, "AVAILABILITY": "1", "DT_PR": date}


class ClassifyTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(bd.classify(True, True, True), "Pemenang Kompetitif")
        self.assertEqual(bd.classify(True, None, True), "Pemenang Kompetitif")
        self.assertEqual(bd.classify(True, False, True), "Gap Ekonomi")
        self.assertEqual(bd.classify(True, True, False), "Gap Eksekusi")
        self.assertEqual(bd.classify(True, False, False), "Gap Ekonomi + Eksekusi")
        self.assertEqual(bd.classify(False, True, True), "Gap Harga")
        self.assertEqual(bd.classify(False, True, False), "Double Jeopardy")
        self.assertEqual(bd.classify(None, True, True), "Data harga belum tersedia")

    def test_threat_types(self):
        self.assertEqual(bd._threat(5, 0.1), "TRUE THREAT")
        self.assertEqual(bd._threat(5, -0.1), "DISTRIBUTION THREAT")
        self.assertEqual(bd._threat(-5, -0.1), "CONVERSION WINDOW")
        self.assertEqual(bd._threat(-5, 0.1), "MONITOR")


class TinyDatasetTest(unittest.TestCase):
    def setUp(self):
        prep, _ = de.prepare(TINY, "planogram")
        plan = pdm.to_rows(prep, PA, PB)
        retail = pd.DataFrame([retail_row("PERTAMINA", 40000, 6000), retail_row("PERTAMINA", 40000, 6000),
                               retail_row("AHM", 44000, 5000), retail_row("AHM", 44000, 5000),
                               retail_row("PERTAMINA", 42000, 6000, "2026-05-20"), retail_row("AHM", 44000, 5000, "2026-05-20")])
        rprep, _ = de.prepare(retail, "retail")
        self.ds = bd.build_dataset(plan, bd.retail_rows_from_frame(rprep, PA, PB), PA, PB, 70, min_price_n=1)

    def test_pair_numbers(self):
        p = self.ds["pairs"][0]
        self.assertEqual((p["kimap"], p["h2h"], p["out_ptpl"], p["out_comp"]), ("K1", "AHM", 2, 2))
        self.assertEqual(p["hj_ptpl"], 50000)                  # 40.000 / 0,8 L
        self.assertEqual(p["hj_comp"], 55000)
        self.assertEqual(p["price_adv"], 9.1)                  # (55.000 − 50.000) / 55.000
        self.assertEqual(p["eco_gap"], 1250)                   # (6.000 − 5.000) / 0,8
        self.assertEqual((p["ratio"], p["av_gap"]), (100.0, 1.0))
        self.assertEqual(p["status"], "Pemenang Kompetitif")
        self.assertEqual(p["price_adv_b"], 4.5)                # Q2: (55.000 − 52.500) / 55.000
        self.assertEqual(p["price_adv_delta"], 4.6)

    def test_categories(self):
        c = self.ds["categories"][0]
        self.assertEqual((c["label"], c["exposure"], c["ptpl_carry"], c["white_space"]), ("MCO Automatic 10W-30", 4, 2, False))

    def test_missing_price(self):
        prep, _ = de.prepare(TINY, "planogram")
        ds = bd.build_dataset(pdm.to_rows(prep, PA, PB), pd.DataFrame(columns=bd.PRICE_COLS), PA, PB)
        self.assertEqual(ds["pairs"][0]["status"], "Data harga belum tersedia")
        self.assertFalse(ds["has_price"])


class SampleTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prep, _ = de.prepare(sample_planogram.rows(), "planogram")
        rprep, _ = de.prepare(sample_retail.rows(), "retail")
        cls.ds = bd.build_dataset(pdm.to_rows(prep, PA, PB), bd.retail_rows_from_frame(rprep, PA, PB), PA, PB)
        cls.pages = br.build_pages(cls.ds, br.fallback_narrative(cls.ds))

    def test_variety_and_white_space(self):
        found = {s for s, n in self.ds["status_counts"].items() if n}
        self.assertGreaterEqual(len(found), 3)
        self.assertTrue(self.ds["white_space"])
        self.assertTrue(self.ds["threats"])

    def test_pages(self):
        self.assertEqual(len(self.pages), 6)
        kick = " ".join(p["kicker"] for p in self.pages)
        for part in ("RINGKASAN", "KATEGORI", "HEAD-TO-HEAD", "MOMENTUM", "SALES REGION", "ACTION MATRIX"):
            self.assertIn(part, kick)
        self.assertTrue(all(not p["draft"] for p in self.pages))

    def test_fallback_grounded(self):
        _, dropped = br.clean_narrative(br.fallback_narrative(self.ds), bd.dataset_numbers(self.ds), br.CARD_KEYS)
        self.assertEqual(dropped, 0)

    def test_render_all_formats(self):
        from pptx import Presentation

        html = ptpl_design.render_html(self.pages, "Uji").decode()
        self.assertEqual(html.count('<section class="page">'), 6)
        self.assertIn("RETAIL × PLANOGRAM", html)
        self.assertTrue(ptpl_design.render_pdf(self.pages, "Uji").startswith(b"%PDF"))
        self.assertEqual(len(Presentation(io.BytesIO(ptpl_design.render_pptx(self.pages, "Uji"))).slides), 6)

    def test_custom_input_block(self):
        block = cr.battlefield_block(self.ds)
        self.assertIn("Analisis silang Retail × Planogram (dihitung kode)", block)
        self.assertIn("Keunggulan harga %", block)
        pool = cr.number_pool(block)
        p = self.ds["pairs"][0]
        self.assertTrue(any(abs(n - p["out_ptpl"]) < 0.01 for n in pool))


if __name__ == "__main__":
    unittest.main()
