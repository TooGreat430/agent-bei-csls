"""Uji laporan daya saing harga industri (B2B) dan jalur Data Agent industri."""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import industry_data as idm  # noqa: E402
from library_agent import industry_report as ir  # noqa: E402

try:
    import pptx  # noqa: F401
    import reportlab  # noqa: F401
    HAS_RENDER = True
except ImportError:
    HAS_RENDER = False


def row(per, stage, zone, channel, product, price, htd, brand="SHELL"):
    return {"PERIOD": per, "STAGE": stage, "ZONE": zone, "CHANNEL": channel, "PRODUCT": product,
            "BRAND": brand, "PRICE": price, "HTD_PLUS": htd}


class GapRulesTest(unittest.TestCase):
    def test_gap_sign_positive_means_ptpl_competitive(self):
        rows = [row("A", "EARLY", "Zona 1", "Agro", "TURALIK 52", 110, 100),
                row("A", "EARLY", "Zona 1", "Mining", "TURALIK 52", 90, 100),
                row("B", "EARLY", "Zona 1", "Agro", "TURALIK 52", 105, 100)]
        ds = idm.build_dataset(rows, idm.DEFAULT_FOCUS, ["SHELL"], idm.month_period("2026-08"), idm.month_period("2026-07"))
        cell = ds["stages"]["EARLY"]["table1"]["Turalik 52"]["Zona 1"]
        self.assertAlmostEqual(cell["current"], 0.0)          # (100 - 100)/100
        self.assertAlmostEqual(cell["prev"], 5.0)
        self.assertEqual((cell["max"], cell["min"]), (110, 90))
        agro = ds["stages"]["EARLY"]["table2"]["Agro"]["Turalik 52"]
        self.assertAlmostEqual(agro["current"], 10.0)         # Shell lebih mahal -> PTPL kompetitif (positif)
        self.assertEqual(idm.tone(15), "green")
        self.assertEqual(idm.tone(5), "amber")
        self.assertEqual(idm.tone(-1), "red")

    def test_competitor_filter_and_unmatched(self):
        rows = [row("A", "NEXT", "Zona 2", "Fleet", "MEDITRAN S 40", 120, 100, brand="TOTAL"),
                row("A", "NEXT", "Zona 2", "Fleet", "PRODUK LAIN", 120, 100)]
        ds = idm.build_dataset(rows, idm.DEFAULT_FOCUS, ["SHELL"], idm.month_period("2026-08"), None)
        self.assertFalse(ds["has_data"])
        self.assertEqual(ds["unmatched"], ["PRODUK LAIN"])

    def test_product_matching(self):
        focus = idm.parse_focus(idm.DEFAULT_FOCUS)
        self.assertEqual(idm.match_product("MEDITRAN SX PLUS 15W-40", focus), "Meditran SX Plus 15W40")
        self.assertEqual(idm.match_product("PERTAMINA MEDITRAN S 40", focus), "Meditran S")
        self.assertEqual(idm.match_product("GREASE PERTAMINA SGX-NL 2", focus), "Grease Pertamina SGX-NL 2")
        self.assertIsNone(idm.match_product("FASTRON TECHNO", focus))

    def test_month_period(self):
        self.assertEqual(idm.month_period("2026-08")["label"], "Agustus 2026")
        self.assertEqual(idm.previous_month("2026-01"), "2025-12")
        with self.assertRaises(ValueError):
            idm.month_period("2026-Q3")


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.ds = idm.build_dataset(ir.sample_rows(), idm.DEFAULT_FOCUS, ["SHELL"],
                                    idm.month_period("2026-08"), idm.month_period("2026-07"))

    def test_kpi_cards(self):
        cards = ir.kpi_cards(self.ds["stages"]["EARLY"], "SHELL")
        self.assertEqual(cards[0]["dim"], "CUSTOMER SEGMENT")
        self.assertLessEqual(len(cards), 6)
        self.assertEqual([c["dim"] for c in cards[1:]], ["HDDO", "HYDRAULIC", "GEAR & TRANS", "MARINE", "GREASE"])

    def test_narrative_grounding_numbers(self):
        nums = idm.dataset_numbers(self.ds)
        self.assertTrue(nums)

    @unittest.skipUnless(HAS_RENDER, "library render belum terpasang")
    def test_render_all_formats(self):
        from pptx import Presentation

        meta = {"report_title": "Uji", "company": "PT X", "competitor": "SHELL"}
        html = ir.render_html(self.ds, {}, meta)
        self.assertIn(b"Price Competitiveness Analysis", html)
        self.assertEqual(html.count(b'class="stage-btn'), 2)
        self.assertTrue(ir.render_pdf(self.ds, {}, meta).startswith(b"%PDF"))
        self.assertEqual(len(Presentation(io.BytesIO(ir.render_pptx(self.ds, {}, meta))).slides), 2)


class RoutingTest(unittest.TestCase):
    def test_report_tools_registered(self):
        from library_agent.tools.report_tools import REPORT_TOOLS

        self.assertEqual([t.__name__ for t in REPORT_TOOLS],
                         ["generate_price_dashboard", "preview_price_dashboard",
                          "generate_industry_report", "preview_industry_report"])

    def test_industry_settings_keep_case(self):
        from library_agent import config

        out = config.coerce("industry_focus_products", ["Meditran S|HDDO"])
        self.assertEqual(out, ("Meditran S|HDDO",))
        self.assertEqual(config.coerce("industry_competitors", ["shell"]), ("SHELL",))

    def test_source_labels(self):
        from library_agent import data_agent

        self.assertEqual(data_agent.SOURCE_LABELS["industri"], "Survey Response Report Industry")


class RealDataPatternsTest(unittest.TestCase):
    """Pola dari Data_Industry.csv asli."""

    def test_rows_without_competitor_price_are_excluded(self):
        rows = [row("A", "EARLY", "Zona 3", "Power Plant", "Masri RG 320", 0.0, 43848.0),       # 'tidak ada'
                row("A", "EARLY", "Zona 3", "Power Plant", "Masri RG 320", 48232.8, 43848.0)]
        ds = idm.build_dataset(rows, idm.DEFAULT_FOCUS, ["SHELL"], idm.month_period("2026-09"), None)
        cell = ds["stages"]["EARLY"]["table1"]["Masri RG 320"]["Zona 3"]
        self.assertEqual(cell["n"], 1)
        self.assertAlmostEqual(cell["current"], 10.0)  # bukan rata-rata dengan -100%

    def test_only_focus_segments_and_manufacture_alias(self):
        rows = [row("A", "EARLY", "Zona 3", "Power Plant", "Masri RG 320", 48232.8, 43848.0),
                row("A", "EARLY", "Zona 1", "Manufacture", "Masri RG 320", 46000, 43848.0)]
        ds = idm.build_dataset(rows, idm.DEFAULT_FOCUS, ["SHELL"], idm.month_period("2026-09"), None)
        self.assertEqual(ds["segments"], idm.CHANNELS)
        self.assertNotIn("Power Plant", ds["stages"]["EARLY"]["table2"])
        self.assertIsNotNone(ds["stages"]["EARLY"]["table2"]["Manufacturing"]["Masri RG 320"])

    def test_both_grease_products(self):
        focus = idm.parse_focus(idm.DEFAULT_FOCUS)
        self.assertEqual(idm.match_product("Grease Pertamina EPX NL 2", focus), "Grease Pertamina EPX NL 2")
        self.assertEqual(idm.match_product("Grease Pertamina SGX-NL 2", focus), "Grease Pertamina SGX-NL 2")
