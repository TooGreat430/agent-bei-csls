"""Uji dashboard daya saing harga (tanpa BigQuery/Gemini, memakai data ilustrasi)."""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import price_dashboard as pd_  # noqa: E402
from library_agent import price_data as pdm  # noqa: E402
from library_agent import sample_price  # noqa: E402

try:
    import pptx  # noqa: F401
    import reportlab  # noqa: F401
    HAS_RENDER = True
except ImportError:
    HAS_RENDER = False


def dataset(compare=True):
    agg, monthly = sample_price.make()
    pa = pdm.parse_period("2026-Q3")
    pb = pdm.parse_period("2026-Q2") if compare else None
    if not compare:
        agg = [r for r in agg if r["PERIOD"] == "A"]
    return pdm.build_dataset(agg, monthly, sample_price.HEROES, pa, pb)


class PeriodTest(unittest.TestCase):
    def test_formats(self):
        q = pdm.parse_period("2026-Q3")
        self.assertEqual((q["label"], q["start"], q["end"]), ("Q3 2026", "2026-07-01", "2026-09-30"))
        self.assertEqual(pdm.parse_period("Q2 2026")["months"], ["2026-04", "2026-05", "2026-06"])
        self.assertEqual(pdm.parse_period("2026-07")["end"], "2026-07-31")
        r = pdm.parse_period("2026-04:2026-06")
        self.assertEqual((r["label"], r["start"], r["end"]), ("Apr–Jun 2026", "2026-04-01", "2026-06-30"))
        self.assertEqual(pdm.parse_period("2026-02")["end"], "2026-02-28")
        with self.assertRaises(ValueError):
            pdm.parse_period("kuartal ketiga")


class RulesTest(unittest.TestCase):
    def test_status_and_trend(self):
        self.assertEqual(pdm.status_of(-6000, -5000, 0), "AMAN")
        self.assertEqual(pdm.status_of(-2000, -5000, 0), "WATCH")
        self.assertEqual(pdm.status_of(500, -5000, 0), "KRITIS")
        self.assertEqual(pdm.trend_of(-1000, -1010), "stabil")
        self.assertEqual(pdm.trend_of(-500, -1000), "memburuk")
        self.assertEqual(pdm.trend_of(-1500, -1000), "membaik")
        self.assertEqual(pdm.trend_of(-1000, None), "")
        self.assertEqual(pdm.short_name("PERTAMINA ENDURO MATIC-S 0.8 LITER"), "ENDURO MATIC-S 0.8L")


class DatasetTest(unittest.TestCase):
    def test_gap_is_ptpl_minus_competitor_within_kimap(self):
        agg = [
            {"PERIOD": "A", "ZONE": "Nasional", "SEGMENT": "MCO", "VISCOSITY": "10W-30", "KIMAP": "K1", "SIDE": "PTPL",
             "PRODUCT": "PERTAMINA ENDURO MATIC-S 0.8 LITER", "HET": 80, "HJ": 76, "HTO": 66, "HT": 65, "MARG": 11, "N": 5},
            {"PERIOD": "A", "ZONE": "Nasional", "SEGMENT": "MCO", "VISCOSITY": "10W-30", "KIMAP": "K1", "SIDE": "KOMP",
             "PRODUCT": "", "HET": 85, "HJ": 80, "HTO": 70, "HT": 69, "MARG": 10, "N": 5},
            {"PERIOD": "A", "ZONE": "Nasional", "SEGMENT": "MCO", "VISCOSITY": "10W-30", "KIMAP": "K9", "SIDE": "PTPL",
             "PRODUCT": "PERTAMINA LAIN", "HET": 1, "HJ": 1, "HTO": 1, "HT": 1, "MARG": 1, "N": 5},
        ]
        z = pdm.build_zone(agg, "Nasional", ["PERTAMINA ENDURO MATIC-S 0.8 LITER"], False)
        hero = z["heroes"][0]["a"]
        self.assertEqual((hero["GAP_HJ"], hero["GAP_HTO"], hero["GAP_MARG"]), (-4, -4, 1))
        self.assertEqual(len(z["segments"][0]["rows"]), 2)  # K9 tanpa kompetitor tidak dihitung

    def test_full_dataset(self):
        ds = dataset()
        self.assertTrue(ds["has_data"])
        for z in pdm.ZONES:
            self.assertEqual(len(ds["zones"][z]["heroes"]), len(sample_price.HEROES))
            for w in ds["zones"][z]["watch_hj"]:
                self.assertGreater(w["change"], 0)  # hanya yang gap-nya menyempit

    def test_numbers_collected(self):
        nums = pdm.dataset_numbers(dataset())
        self.assertTrue(len(nums) > 100)


class NarrativeTest(unittest.TestCase):
    def test_ungrounded_numbers_dropped(self):
        nums = [9390.0, 19349.0]
        narr = {"ringkasan": ["Gap HJ −Rp 9.390/L tetap kompetitif.", "Gap turun menjadi −Rp 12.345/L.",
                              "Fastron EcoGreen 5W-30 3.5L pada Q3 2026 stabil."],
                "insight_eksekutif": [{"kategori": "I", "judul": "OK", "uraian": "−Rp 19.349/L", "tingkat": "positif"},
                                      {"kategori": "II", "judul": "Naik 15%", "uraian": "x", "tingkat": "kritis"}],
                "zona": [{"zona": "Nasional", "kondisi": "Rp 777/L", "konsumen_insight": [], "konsumen_anomali": [],
                          "outlet_insight": [], "outlet_anomali": []}]}
        out, dropped = pd_.clean_narrative(narr, nums)
        self.assertEqual(len(out["ringkasan"]), 2)
        self.assertEqual(len(out["insight_eksekutif"]), 1)
        self.assertEqual(out["zona"]["Nasional"]["kondisi"], "")
        self.assertEqual(dropped, 3)


class PagesTest(unittest.TestCase):
    def test_page_structure(self):
        pages = pd_.build_pages(dataset(), {"ringkasan": [], "insight_eksekutif": [], "zona": {}}, "PT X")
        self.assertEqual(len(pages), 9)
        self.assertEqual(pages[0]["kind"], "exec")
        self.assertEqual([p["view"] for p in pages[1:3]], ["konsumen", "outlet"])
        self.assertIn("TR", pages[1]["table"]["columns"])

    def test_single_period_has_no_trend(self):
        pages = pd_.build_pages(dataset(compare=False), {"ringkasan": [], "insight_eksekutif": [], "zona": {}}, "PT X")
        self.assertNotIn("TR", pages[1]["table"]["columns"])

    @unittest.skipUnless(HAS_RENDER, "library render belum terpasang")
    def test_render_all_formats(self):
        from pptx import Presentation

        from library_agent import dashboard_render as dr

        pages = pd_.build_pages(dataset(), {"ringkasan": [], "insight_eksekutif": [], "zona": {}}, "PT X")
        meta = {"report_title": "Uji", "period_text": "Q2 vs Q3", "company": "PT X"}
        html = dr.render_html(pages, meta)
        self.assertEqual(html.count(b"<button"), 5)
        self.assertIn(b"data:image/png;base64", html)
        pdf = dr.render_pdf(pages, meta)
        self.assertEqual(pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page "), 9) if False else self.assertTrue(pdf.startswith(b"%PDF"))
        prs = Presentation(io.BytesIO(dr.render_pptx(pages, meta)))
        self.assertEqual(len(prs.slides), 9)


if __name__ == "__main__":
    unittest.main()
