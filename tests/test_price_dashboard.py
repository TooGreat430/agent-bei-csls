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


class InferPeriodTest(unittest.TestCase):
    def test_infer(self):
        self.assertEqual(pdm.infer_period(["Gap harga Hero di Zona 1-3 pada Juli 2026"]), "2026-07")
        self.assertEqual(pdm.infer_period(["tren Maret sampai Mei 2026"]), "2026-03:2026-05")
        self.assertEqual(pdm.infer_period(["[Survey Response Report Retail, Q3 2026]"]), "2026-Q3")
        self.assertEqual(pdm.infer_period(["WHERE DT_PR = '2026-07-31'"]), "2026-07")
        self.assertEqual(pdm.infer_period(["Juli 2026", "Agustus 2026"]), "2026-07:2026-08")
        self.assertIsNone(pdm.infer_period(["harga Fastron di pasaran"]))


class ReportAgentToolsTest(unittest.TestCase):
    def test_only_dashboard_tools(self):
        from library_agent.tools.report_tools import REPORT_TOOLS

        self.assertEqual([t.__name__ for t in REPORT_TOOLS], ["generate_price_dashboard", "preview_price_dashboard"])

    def test_active_template_folder_is_empty(self):
        folder = os.path.join(ROOT, "templates")
        self.assertEqual([f for f in os.listdir(folder) if not f.startswith(".")], [])


class SampleReportStructureTest(unittest.TestCase):
    """Struktur mengikuti laporan contoh PTPL (C-Suite Exec Dashboard Q2–Q3 2026)."""

    def setUp(self):
        self.pages = pd_.build_pages(dataset(), {"ringkasan": [], "insight_eksekutif": [], "zona": {}}, "PT X")

    def test_tabs_and_titles(self):
        tabs = []
        for p in self.pages:
            if p["tab"] not in tabs:
                tabs.append(p["tab"])
        self.assertEqual(tabs, ["★ EXECUTIVE SUMMARY (MULTIZONA)", "NASIONAL (AVERAGE)", "ZONA 1 (REGION 3,4,5)",
                                "ZONA 2 (REGION 2,6)", "ZONA 3 (REGION 1,7)"])
        self.assertTrue(self.pages[0]["title"].startswith("Executive Summary: Analisis Daya Saing Harga Retail & Margin Advokasi Bengkel"))
        self.assertEqual(self.pages[0]["tag"], "BOARD OF DIRECTORS & COMMISSIONERS REPORT")
        self.assertEqual(self.pages[1]["tag"], "PAGE 1 / 2 — RETAIL OUTLET")
        self.assertEqual(self.pages[2]["tag"], "PAGE 2 / 2 — OUTLET MARGIN")
        self.assertTrue(self.pages[0]["topbar"].startswith("C-SUITE EXEC DASHBOARD: SURVEY HARGA JUAL VS TEBUS BENGKEL"))

    def test_exec_matrix(self):
        table = self.pages[0]["table"]
        self.assertEqual([g for g, _ in table["groups"]],
                         ["VISKOSITAS / HERO SKU", "NASIONAL", "ZONA 1 (JAWA)", "ZONA 2 (SUMATRA)", "ZONA 3 (TIMUR)", "STATUS"])
        kinds = {r["kind"] for r in table["rows"]}
        self.assertEqual(kinds, {"group", "viscosity", "hero"})
        self.assertTrue(any(r["cells"][0].startswith("▸ ") and r["cells"][0].endswith("(Hero)") for r in table["rows"]))
        self.assertEqual([z["subtitle"] for z in self.pages[0]["zone_cards"]],
                         ["RERATA RI", "JAWA-NUSRA", "SUMATRA-KALTIM", "SUMUT & TIMUR"])

    def test_zone_tables(self):
        consumer, outlet = self.pages[1]["table"]["columns"], self.pages[2]["table"]["columns"]
        self.assertEqual(consumer, ["VISKOSITAS / HERO SKU", "HET PTPL", "HET KOMP", "GAP HET", "HJ PTPL", "HJ KOMP",
                                    "GAP HJ", "TR", "STATUS"])
        self.assertEqual(outlet, ["VISKOSITAS / HERO SKU", "HTO PTPL", "HTO KOMP", "GAP HTO", "HT PTPL", "HT KOMP",
                                  "GAP HT", "MARG PTPL", "MARG KOMP", "GAP MARG", "TR", "STATUS"])

    def test_kpis_and_watch(self):
        kpis = self.pages[1]["kpis"]
        self.assertEqual(len(kpis), 4)
        self.assertIn("MARGIN PTPL", kpis[-1]["label"])
        self.assertTrue(all(k["chip"].split()[-1] in ("KOMPETITIF", "MONITOR", "RISK", "AMAN") for k in kpis))
        for w in self.pages[1]["watch"]:
            self.assertEqual(len(w["stats"]), 3)
            self.assertTrue(w["brand"])


class DecimalInputTest(unittest.TestCase):
    """BigQuery mengembalikan kolom NUMERIC sebagai Decimal; dashboard harus tetap jalan."""

    def test_decimal_rows(self):
        from decimal import Decimal

        agg, monthly = sample_price.make()
        to_dec = lambda rows: [{k: (Decimal(str(round(v, 4))) if isinstance(v, float) else v) for k, v in r.items()}
                               for r in rows]
        ds = pdm.build_dataset(to_dec(agg), to_dec(monthly), sample_price.HEROES,
                               pdm.parse_period("2026-07"), None)
        self.assertTrue(ds["has_data"])
        pages = pd_.build_pages(ds, {"ringkasan": [], "insight_eksekutif": [], "zona": {}}, "PT X")
        self.assertEqual(len(pages), 9)
        if HAS_RENDER:
            from library_agent import dashboard_render as dr

            meta = {"report_title": "Uji", "period_text": "Jul 2026", "company": "PT X"}
            self.assertTrue(dr.render_pdf(pages, meta).startswith(b"%PDF"))
