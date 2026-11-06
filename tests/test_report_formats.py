"""Uji format laporan custom: pertanyaan format, HTML/PDF/PPTX sekaligus, konversi, dan approve di semua format."""
import io
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

from library_agent import custom_report as cr  # noqa: E402
from library_agent import html_convert  # noqa: E402

PTPL_BODY = """<section class="page"><div class="hdr"><div class="hdr-l"><div class="logo">PERTAMINA<span>LUBRICANTS</span></div>
<div><div class="kicker">PLANOGRAM · 01</div><div class="hdr-title">ND PTPL naik <span class="tag gold">PLANOGRAM</span></div>
<div class="hdr-sub">Q2 vs Q3 2026</div></div></div><div class="hdr-r">Q3 2026 · Nasional<br><span class="draft">DRAFT - menunggu approval</span></div></div>
<div class="grid g4"><div class="kpi kg"><div class="kpi-lbl">ND PTPL</div><div class="kpi-val">62,4%</div><div class="kpi-mono">Q2 58,1% → Q3 62,4%</div><span class="badge b-g">▲ NAIK</span></div>
<div class="kpi kr"><div class="kpi-lbl">Gap AV</div><div class="kpi-val">-0,12</div></div></div>
<div class="grid g-6040"><div><h2 class="sec">ND per SR <span class="acc">· Q3</span></h2>
<div class="chart lg" data-chart='{"type":"bar","labels":["SR1","SR2"],"series":[{"name":"ND","data":[62.4,39.5]}]}'></div></div>
<div><div class="ins ig"><div class="ins-lbl">SEBARAN</div><div class="ins-title">SR1 tertinggi</div><div class="ins-body">ND 62,4%.</div></div>
<div class="ins ir"><div class="ins-lbl">RISIKO</div><div class="ins-title">SR2 rendah</div><div class="ins-body">ND 39,5%.</div></div></div></div>
<table class="gt"><thead><tr><th>SR</th><th>ND</th></tr></thead><tbody><tr class="seg"><td colspan="2">MCO</td></tr>
<tr class="hl"><td class="nm">SR1</td><td class="up">62,4%</td></tr></tbody></table><p class="note">Catatan data.</p>
<div class="footer"><span>Sumber: Planogram Marketing Intelligence</span><span>PT Pertamina Lubricants · Confidential</span></div></section>"""

GENERIC_BODY = """<header class="mir-hdr"><h1>Mesrania 2T vs Kompetitor</h1><span class="draft">DRAFT - menunggu approval</span></header>
<div class="mir-card"><h3>Harga per liter Q3</h3><p>Mesrania termurah per liter.</p></div>
<table><tr><th>Produk</th><th>HJ /L</th></tr><tr><td>Mesrania</td><td>65.128,73</td></tr></table>
<ul><li>Castrol termahal</li><li>Shell kedua</li></ul>"""


class ConvertTest(unittest.TestCase):
    def test_ptpl_components(self):
        pages = html_convert.to_pages(PTPL_BODY)
        self.assertEqual(len(pages), 1)
        p = pages[0]
        self.assertEqual((p["kicker"], p["title"], p["tag"], p["draft"]), ("PLANOGRAM · 01", "ND PTPL naik", "PLANOGRAM", True))
        self.assertEqual(p["source"], "Planogram Marketing Intelligence")
        types = [b["type"] for b in p["blocks"]]
        self.assertEqual(types, ["kpis", "grid", "table", "note"])
        self.assertEqual(p["blocks"][0]["items"][0]["value"], "62,4%")
        self.assertEqual(p["blocks"][0]["items"][0]["badge"]["tone"], "b-g")
        grid = p["blocks"][1]
        self.assertEqual(grid["cols"], "g-6040")
        self.assertEqual([b["type"] for b in grid["children"][0]], ["sec", "chart"])
        self.assertEqual(len(grid["children"][1][0]["items"]), 2)                # dua insight digabung
        self.assertEqual(p["blocks"][2]["rows"][0]["cls"], "seg")
        self.assertEqual(p["blocks"][2]["rows"][1]["cells"][1]["cls"], "up")

    def test_generic_template_body(self):
        pages = html_convert.to_pages(GENERIC_BODY, title="Summary")
        types = [b["type"] for b in pages[0]["blocks"]]
        self.assertIn("table", types)
        self.assertEqual(pages[0]["title"], "Mesrania 2T vs Kompetitor")
        self.assertTrue(pages[0]["draft"])
        self.assertTrue(any(b.get("text", "").startswith("• Castrol") for b in pages[0]["blocks"]))
        self.assertFalse(any("DRAFT" in b.get("text", "") for b in pages[0]["blocks"]))
        self.assertNotEqual(pages[0]["blocks"][0].get("title"), "Mesrania 2T vs Kompetitor")

    def test_render_pdf_pptx(self):
        from pptx import Presentation

        for body in (PTPL_BODY, GENERIC_BODY):
            pdf = cr.render_format("Uji", body, "pdf")
            self.assertTrue(pdf.startswith(b"%PDF"))
            pptx = cr.render_format("Uji", body, "pptx")
            self.assertGreaterEqual(len(Presentation(io.BytesIO(pptx)).slides), 1)

    def test_parse_formats(self):
        self.assertEqual(cr.parse_formats("PDF dan PowerPoint"), ["pdf", "pptx"])
        self.assertEqual(cr.parse_formats("html, pdf, html"), ["html", "pdf"])
        self.assertEqual(cr.parse_formats(""), [])


class FlowTest(unittest.TestCase):
    def setUp(self):
        from library_agent.tools import report_tools as rt

        self.rt = rt
        self.store, self.saved = {}, []

        def save(user, tid, title, data, ext, ctype, record=None):
            uri = f"gs://b/{len(self.saved)}_{ext}"
            self.store[uri] = data.decode() if ext == "html" else data
            self.saved.append((title, ext, data, record))
            return {"url": f"https://x/{len(self.saved)}.{ext}", "gcs_uri": uri, "format": ext}
        self.patches = [mock.patch("library_agent.report_engine.save_output", side_effect=save),
                        mock.patch.object(rt, "_gcs_text", side_effect=lambda u: self.store[u]),
                        mock.patch.object(rt, "_gcs_put", side_effect=lambda u, t: self.store.__setitem__(u, t)),
                        mock.patch.object(rt, "pull", create=True)]
        for p in self.patches:
            p.start()
        self.ctx = NS(user_id="jason@mii.co.id", _invocation_context=None, state={})

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _result(self):
        return {"status": "ok", "title": "LAPORAN PLANOGRAM — Uji · Q3", "body": PTPL_BODY, "unverified": [],
                "explanation": ""}

    def test_asks_format_before_any_work(self):
        res = self.rt.generate_custom_report("laporan ND", "planogram", self.ctx)
        self.assertEqual(res["status"], "needs_input")
        self.assertEqual(res["available_formats"], ["html", "pdf", "pptx"])
        self.assertEqual(self.saved, [])

    def test_save_multi_then_approve_then_convert(self):
        res = self.rt._save_custom(self.ctx, self._result(), "planogram", "laporan ND", "| a |", "Planogram",
                                   formats=["pdf", "pptx"])
        self.assertEqual(set(res["file"]), {"pdf", "pptx"})
        self.assertEqual([s[1] for s in self.saved], ["html", "pdf", "pptx"])     # HTML induk selalu disimpan
        app = self.rt.approve_report(self.ctx)
        self.assertEqual(app["status_laporan"], "FINAL")
        self.assertEqual(set(app["file"]), {"pdf", "pptx"})
        final_html = next(s for s in self.saved if s[0].endswith("(FINAL)") and s[1] == "html")[2].decode()
        self.assertIn("FINAL · Disetujui jason", final_html)
        conv = self.rt.konversi_laporan_custom("html", self.ctx)
        self.assertEqual(conv["status_laporan"], "FINAL")
        self.assertIn("html", conv["file"])


if __name__ == "__main__":
    unittest.main()
