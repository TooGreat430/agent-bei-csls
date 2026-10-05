"""Uji grafik di chat, grafik di laporan, dan pengaman jawaban kosong (tanpa GCP)."""
import os
import sys
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()
os.environ["LIB_TEMPLATE_SOURCE"] = "local"

from library_agent import callbacks, chart_image, report_engine  # noqa: E402

try:
    import matplotlib  # noqa: F401
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

TABLE = {"columns": ["HERO_PRODUCT", "GAP_HET_PER_LITER", "GAP_HTO_PER_LITER", "ZONE"],
         "rows": [["ENDURO MATIC-S", -4847.97, -5406.65, "Zona 1"], ["FASTRON 5W-30", -19349.1, -6226.0, "Zona 1"],
                  ["MEDITRAN SC", 666.2, 1189.4, "Zona 1"]]}


class BuildChartTest(unittest.TestCase):
    def test_values_come_from_table(self):
        chart, err = chart_image.build_chart(TABLE, "hero_product", ["GAP_HET_PER_LITER", "gap_hto_per_liter"],
                                             "bar", "Gap pricelist", "IDR/L")
        self.assertEqual(err, "")
        self.assertEqual(chart["kategori"], ["ENDURO MATIC-S", "FASTRON 5W-30", "MEDITRAN SC"])
        self.assertEqual(chart["seri"][0]["nilai"], [-4847.97, -19349.1, 666.2])

    def test_unknown_column_lists_available(self):
        chart, err = chart_image.build_chart(TABLE, "PRODUK", ["GAP"])
        self.assertIsNone(chart)
        self.assertIn("HERO_PRODUCT", err)

    def test_text_column_as_y_rejected(self):
        chart, err = chart_image.build_chart(TABLE, "HERO_PRODUCT", ["ZONE"])
        self.assertIsNone(chart)

    @unittest.skipUnless(HAS_MPL, "matplotlib belum terpasang")
    def test_png_rendered(self):
        chart, _ = chart_image.build_chart(TABLE, "HERO_PRODUCT", ["GAP_HET_PER_LITER"])
        png = chart_image.render_png(chart)
        self.assertTrue(png.startswith(b"\x89PNG"))


class ReportChartsTest(unittest.TestCase):
    def setUp(self):
        self.t = report_engine.load_template("daya_saing_harga_bq")
        self.content = {"grafik": [{"judul": "dari model"}], "judul_utama": "x"}
        chart, _ = chart_image.build_chart(TABLE, "HERO_PRODUCT", ["GAP_HET_PER_LITER"])
        self.items = [{"source": "bigquery", "chart": dict(chart, question="q")}, {"source": "bigquery"}]

    def test_saved_chart_replaces_model_chart(self):
        out = report_engine.apply_insight_charts(self.t, self.content, self.items, True)
        self.assertEqual(len(out["grafik"]), 1)
        self.assertNotIn("question", out["grafik"][0])
        self.assertEqual(out["grafik"][0]["seri"][0]["nilai"][0], -4847.97)

    def test_exclude_charts(self):
        out = report_engine.apply_insight_charts(self.t, self.content, self.items, False)
        self.assertEqual(out["grafik"], [])

    def test_no_saved_chart_keeps_model_chart(self):
        out = report_engine.apply_insight_charts(self.t, self.content, [{"source": "bigquery"}], True)
        self.assertEqual(out["grafik"], [{"judul": "dari model"}])


def _event(author, text=None, response=None):
    parts = []
    if text is not None:
        parts.append(NS(text=text, thought=False, function_response=None))
    if response is not None:
        parts.append(NS(text=None, thought=False, function_response=NS(response=response)))
    return NS(author=author, content=NS(parts=parts))


class FallbackReplyTest(unittest.TestCase):
    def test_silent_agent_gets_tool_message(self):
        events = [_event("report_agent", response={"status": "needs_input", "message": "Belum ada insight data BigQuery."})]
        self.assertEqual(callbacks.fallback_reply(events, "report_agent"), "Belum ada insight data BigQuery.")

    def test_report_link_used(self):
        events = [_event("report_agent", response={"status": "ok", "report_title": "Uji", "url": "https://x/y.pdf"})]
        self.assertIn("https://x/y.pdf", callbacks.fallback_reply(events, "report_agent"))

    def test_agent_that_replied_is_left_alone(self):
        events = [_event("report_agent", response={"status": "ok", "message": "m"}),
                  _event("report_agent", text="Laporan siap.")]
        self.assertEqual(callbacks.fallback_reply(events, "report_agent"), "")


if __name__ == "__main__":
    unittest.main()
