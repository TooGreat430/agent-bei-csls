"""Uji: file hasil PivotTable (header bertingkat), harga per liter, data file umum untuk laporan custom,
dan laporan custom yang dibangun di dalam TEMPLATE HTML milik user."""
import io
import json
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

import pandas as pd  # noqa: E402

from library_agent import custom_report as cr  # noqa: E402
from library_agent import data_engine as de  # noqa: E402

M = ["Average of HTO", "Average of HARGA_JUAL"]
PIVOT = [
    [None, None, None, "Quarters", "SURVEY_WAVE", "Values", None, None],
    [None, None, None, "Qtr1", None, None, "Qtr3", None],
    ["SEGMENT", "KIMAP", "QNR"] + M + [None] + M,
    ["MCO", "A070115425", "PERTAMINA MESRANIA 2T SUPER 1 LITER", 45700, 51685.2, None, 58545.4, 65128.73],
    [None, None, "CASTROL ACTIV 2T 0.7 LITER", 38400, 45986.3, None, 56511.65, 64099.76],
    [None, None, "SHELL ADVANCE SX 2T 0.7 LITER", 38258, 45656.25, None, 50244.9, 62078.68],
]
# kolom kosong di tengah (indeks 5) mensimulasikan kolom pemisah; dibuang oleh pembaca


def _xlsx(rows):
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    return buf.getvalue()


class PivotTest(unittest.TestCase):
    def test_excel_and_csv_same(self):
        x, _ = de.read_bytes(_xlsx(PIVOT), "mesrania.xlsx")
        c, _ = de.read_bytes(pd.DataFrame(PIVOT).to_csv(header=False, index=False).encode(), "mesrania.csv")
        self.assertEqual(list(x.columns), list(c.columns))
        self.assertEqual(list(x.columns)[:5], ["SEGMENT", "KIMAP", "QNR", "Qtr1 · HTO (rata-rata)",
                                                "Qtr1 · HARGA_JUAL (rata-rata)"])
        self.assertIn("Qtr3 · HARGA_JUAL (rata-rata)", x.columns)

    def test_group_filled_down_and_numeric(self):
        x, _ = de.read_bytes(_xlsx(PIVOT), "m.xlsx")
        self.assertEqual(x["KIMAP"].tolist(), ["A070115425"] * 3)
        self.assertTrue(pd.api.types.is_numeric_dtype(x["Qtr1 · HTO (rata-rata)"]))
        self.assertEqual(x.attrs["tata_letak"]["baris_header"], 3)

    def test_normal_file_untouched(self):
        df = pd.DataFrame({"Customer Code": [1, 2], "Grand Total": [1.5, 2.0]})
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        out, _ = de.read_bytes(buf.getvalue(), "n.xlsx")
        self.assertEqual(list(out.columns), ["Customer Code", "Grand Total"])
        self.assertNotIn("tata_letak", out.attrs)

    def test_per_liter(self):
        x, _ = de.read_bytes(_xlsx(PIVOT), "m.xlsx")
        out, notes = de.prepare(x, "lainnya")
        self.assertIn("harga_per_liter", notes)
        col = "Qtr3 · HARGA_JUAL (rata-rata) /L"
        self.assertEqual(out[col].tolist(), [65128.73, 91571.09, 88683.83])   # Mesrania termurah per liter
        self.assertEqual(de.pack_liters("OLI 800 ML"), 0.8)


class FrameBlockTest(unittest.TestCase):
    def test_small_full_large_sample(self):
        from library_agent.tools import report_tools as rt

        small = rt._frame_block(pd.DataFrame({"a": [1.234, 2.0], "b": ["x", None]}))
        self.assertIn("Data lengkap file", small)
        self.assertIn("1.23", small)
        big = rt._frame_block(pd.DataFrame({"a": range(1000), "b": ["x"] * 1000}))
        self.assertIn("Contoh 100 baris pertama dari 1000 baris", big)
        self.assertIn("Ringkasan angka seluruh baris", big)


TEMPLATE = """<!DOCTYPE html><html><head><title>MIR Template</title><style>.mir-card{border:1px solid #ccc}</style></head>
<body class="mir"><style>.inbody{color:red}</style><header class="mir-hdr"><h1>Judul Contoh</h1></header>
<div class="mir-card"><span class="kpi">12.345</span></div><script>console.log('chart')</script></body></html>"""


class TemplateModeTest(unittest.TestCase):
    def test_parts(self):
        p = cr.template_parts(TEMPLATE)
        self.assertTrue(p["head"].endswith('<body class="mir">'))
        self.assertIn("console.log", p["scripts"])
        self.assertIn(".inbody", p["styles"])
        self.assertIn("mir-card", p["example"])
        self.assertNotIn("<script", p["example"])
        self.assertIsNone(cr.template_parts("<div>tanpa body</div>"))

    def test_prompt_uses_template_contract(self):
        p = cr.build_prompt("umum", "Summary Mesrania", "| a |\\n|---|\\n| 1 |",
                            template_example=cr.template_parts(TEMPLATE)["example"])
        self.assertIn("TEMPLATE DESAIN DARI USER", p)
        self.assertIn("mir-card", p)
        self.assertNotIn("Lalu SATU blok kode ```html berisi HANYA rangkaian <section", p)

    def test_wrap_and_approve(self):
        body = '<header class="mir-hdr"><h1>Mesrania 2T</h1><span class="draft">DRAFT - menunggu approval</span></header>'
        parsed = cr.parse_output("LAPORAN DATA — X · Q3\\n```html\\n<html><body>" + body + "</body></html>\\n```",
                                 template_mode=True)
        self.assertEqual(parsed["body"], body)
        html = cr.to_html("Summary Mesrania", parsed["body"], template_html=TEMPLATE).decode()
        self.assertIn("<title>Summary Mesrania</title>", html)
        self.assertIn(".mir-card", html)
        self.assertIn("console.log", html)
        self.assertIn("Mesrania 2T", html)
        self.assertNotIn("PTPL Design System helper", html)
        final = cr.to_html("S", body, approved_label="FINAL · Disetujui jason", template_html=TEMPLATE).decode()
        self.assertIn("FINAL · Disetujui jason", final)
        self.assertNotIn("DRAFT - menunggu approval", final)


class CustomFromGenericFileTest(unittest.TestCase):
    def test_end_to_end_with_template(self):
        from library_agent.tools import report_tools as rt

        frame, _ = de.read_bytes(_xlsx(PIVOT), "MIR_Mesrania2T.xlsx")
        prepared, notes = de.prepare(frame, "lainnya")
        saved = {}
        body = ('<header><h1>Mesrania 2T</h1><span class="draft">DRAFT - menunggu approval</span></header>'
                '<div class="mir-card">Harga jual Q3 Mesrania Rp 65.128,73/L vs Castrol Rp 91.571,09/L</div>')

        def save(user, tid, title, data, ext, ctype, record=None):
            saved["html"] = data.decode()
            return {"url": "https://x/r.html", "gcs_uri": "gs://b/r.html", "format": "html"}
        ctx = NS(user_id="u", _invocation_context=None, state={
            "data_files": [{"file_id": "f1", "filename": "MIR_Mesrania2T.xlsx", "uri": "gs://b/f1"}],
            "documents": [{"doc_id": "d1", "filename": "MIR_Master_HTML_Report_Template.html", "jenis": "HTML",
                           "uri": "gs://b/tpl.html", "text_uri": "gs://b/tpl.txt"}]})
        with mock.patch("library_agent.tools.file_tools._prepared", return_value=(prepared, notes, "lainnya")), \
                mock.patch.object(rt, "_gcs_text", return_value=TEMPLATE), mock.patch.object(rt, "_gcs_put"), \
                mock.patch("library_agent.report_engine.save_output", side_effect=save), \
                mock.patch("library_agent.report_engine.generate_text",
                           return_value="LAPORAN DATA — Mesrania · Q1–Q3 2026\\n```html\\n" + body + "\\n```") as gen:
            res = rt.generate_custom_report("Summary Mesrania 2T vs kompetitor Q1–Q3 2026", "file", ctx,
                                            instruction_doc_id="d1", output_format="html")
        self.assertEqual(res["status"], "ok", res)
        prompt = gen.call_args[0][0]
        self.assertIn("Data lengkap file", prompt)
        self.assertIn("/L", prompt)
        self.assertIn("TEMPLATE DESAIN DARI USER", prompt)
        self.assertIn(".mir-card", saved["html"])
        self.assertEqual(res["angka_tidak_terverifikasi"], [])


if __name__ == "__main__":
    unittest.main()
