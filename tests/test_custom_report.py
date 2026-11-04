"""Uji laporan custom: prompt, parsing keluaran model, pemeriksa angka, approve, dan penolakan lampiran."""
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

from library_agent import callbacks  # noqa: E402
from library_agent import custom_report as cr  # noqa: E402

DATA = """### Hasil Planogram Marketing Intelligence
| SR | ND_Q2 | ND_Q3 | CARRY_PTPL |
|---|---|---|---|
| SR1 | 58.1 | 62.4 | 1329 |
| SR2 | 40.2 | 39.5 | 812 |
"""
PAGE = ('<section class="page"><div class="hdr"><div class="hdr-r">Q3 2026<br><span class="draft">DRAFT - menunggu '
        'approval</span></div></div><div class="kpi"><div class="kpi-val">62,4%</div></div>'
        '<p>Carry PTPL 1.329 outlet di SR1.</p>'
        '<div class="chart" data-chart=\'{"type":"bar","labels":["SR1","SR2"],"series":[{"name":"ND","data":[62.4,39.5]}]}\'></div>'
        '<div class="footer"><span>Sumber: x</span></div></section>')


class PromptTest(unittest.TestCase):
    def test_prompts_exist_and_keep_user_rules(self):
        for d in ("retail", "industri", "planogram"):
            text = cr.load_prompt(d)
            self.assertIn("ATURAN ANGKA (WAJIB)", text)
            self.assertIn("SISIPKAN_VARIABEL_Description", text)
        self.assertIn("KNOWLEDGE PLANOGRAM", cr.load_prompt("planogram"))
        self.assertNotIn("KNOWLEDGE RETAIL", cr.load_prompt("umum"))

    def test_build_prompt(self):
        p = cr.build_prompt("planogram", "Laporan ND Q3 vs Q2", DATA)
        self.assertIn("Laporan ND Q3 vs Q2", p)
        self.assertIn("| SR1 | 58.1 | 62.4 | 1329 |", p)
        self.assertNotIn("SISIPKAN_VARIABEL", p)
        self.assertIn("LAPORAN PLANOGRAM — <judul singkat>", p)
        self.assertIn("JANGAN menulis <!DOCTYPE>", p)
        self.assertNotIn("dokumen lengkap dari <!DOCTYPE html> sampai </html>", p)
        self.assertNotIn("function dumbbell", p)   # design system tidak dikirim ke model

    def test_revision_and_fix_sections(self):
        p = cr.build_prompt("retail", "x", DATA, previous_body=PAGE, feedback="tambah grafik tren", problems=["77,1%"])
        self.assertIn("tambah grafik tren", p)
        self.assertIn("77,1%", p)


class ParseCheckTest(unittest.TestCase):
    def test_parse_code_block(self):
        out = cr.parse_output("LAPORAN PLANOGRAM — ND · Q3 2026\n```html\n" + PAGE + "\n```\nData: tabel SR.")
        self.assertEqual(out["title"], "LAPORAN PLANOGRAM — ND · Q3 2026")
        self.assertTrue(out["body"].startswith("<section"))
        self.assertIn("Data: tabel SR.", out["explanation"])

    def test_parse_full_document_strips_scripts(self):
        doc = ("LAPORAN RETAIL ONLY — X · Q3\n```html\n<!DOCTYPE html><html><head><style>x</style></head><body>"
               + PAGE + "<script>alert(1)</script></body></html>\n```")
        body = cr.parse_output(doc)["body"]
        self.assertNotIn("<script", body)
        self.assertNotIn("<style", body)
        self.assertTrue(body.endswith("</section>"))

    def test_no_data(self):
        self.assertTrue(cr.parse_output("DATA TIDAK DITERIMA DARI DATA AGENT. Periksa output node")["no_data"])

    def test_checker_accepts_grounded(self):
        self.assertEqual(cr.check_numbers(PAGE, cr.number_pool(DATA)), [])

    def test_checker_flags_invented(self):
        bad_page = PAGE.replace("62,4%", "71,9%").replace("[62.4,39.5]", "[62.4,48.7]")
        bad = cr.check_numbers(bad_page, cr.number_pool(DATA))
        self.assertIn("71,9%", bad)
        self.assertIn("48.7", bad)

    def test_checker_note_before_footer(self):
        body = cr.add_checker_note(PAGE, ["71,9%"])
        self.assertLess(body.index("Catatan pemeriksa"), body.index('class="footer"'))

    def test_generate_retries_once_then_notes(self):
        bad_page = PAGE.replace("62,4%", "71,9%")
        reply = "LAPORAN PLANOGRAM — X · Q3\n```html\n" + bad_page + "\n```"
        with mock.patch("library_agent.report_engine.generate_text", side_effect=[reply, reply]) as gen:
            res = cr.generate("planogram", "laporan", DATA)
        self.assertEqual(gen.call_count, 2)
        self.assertEqual(res["unverified"], ["71,9%"])
        self.assertIn("Catatan pemeriksa", res["body"])

    def test_generate_fixed_on_retry(self):
        bad = "LAPORAN PLANOGRAM — X · Q3\n```html\n" + PAGE.replace("62,4%", "71,9%") + "\n```"
        good = "LAPORAN PLANOGRAM — X · Q3\n```html\n" + PAGE + "\n```"
        with mock.patch("library_agent.report_engine.generate_text", side_effect=[bad, good]):
            res = cr.generate("planogram", "laporan", DATA)
        self.assertEqual(res["unverified"], [])
        self.assertTrue(res["revised_for_numbers"])


class WrapApproveTest(unittest.TestCase):
    def test_wrap_draft_and_final(self):
        draft = cr.to_html("Judul", PAGE).decode()
        self.assertIn("<body>", draft)
        self.assertIn("PTPL Design System helper - JANGAN DIUBAH", draft)
        final = cr.to_html("Judul", PAGE, cr.approved_label("jason.kusuma@mii.co.id")).decode()
        self.assertIn('<body class="final" data-approved="FINAL · Disetujui jason.kusuma', final)


class UploadRejectTest(unittest.TestCase):
    def _ctx(self, parts):
        return NS(user_content=NS(parts=parts), state={}, _invocation_context=None)

    def test_pdf_rejected(self):
        part = NS(text=None, file_data=None,
                  inline_data=NS(data=b"%PDF-1.4", mime_type="application/pdf", display_name="studi_bei.pdf"))
        out = callbacks.capture_uploads(self._ctx([part]))
        self.assertIsNotNone(out)
        self.assertIn("studi_bei.pdf", out.parts[0].text)
        self.assertIn("CSV atau Excel", out.parts[0].text)

    def test_text_only_passes(self):
        part = NS(text="halo", file_data=None, inline_data=None)
        self.assertIsNone(callbacks.capture_uploads(self._ctx([part])))


if __name__ == "__main__":
    unittest.main()
