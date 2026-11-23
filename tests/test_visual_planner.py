"""Uji laporan visual otomatis Tahap B (v3.7): perencana storyboard, pemeriksa angka, jalur cadangan, alat ADK."""
import json
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

try:
    import matplotlib  # noqa: F401
    import pptx  # noqa: F401
    import reportlab  # noqa: F401
    HAVE_LIBS = True
except ImportError:  # pragma: no cover
    HAVE_LIBS = False

from library_agent.visual_report import planner as P  # noqa: E402
from library_agent.visual_report import theme as T  # noqa: E402

DATA = """### Hasil Retail — BEI per merek Q3 2026
BEI Fastron 21.04 turun 1.7 dibanding Q2 (22.74). Effective Equity TMO 22.4.

| Merek | BEI | Delta |
|---|---|---|
| Fastron | 21.04 | -1.7 |
| TMO | 14.3 | 0.4 |
| Shell Helix | 13.3 | -0.9 |
| Castrol Magnatec | 8.4 | 0.2 |
"""
CHAT = ["Fastron memimpin BEI 4W dengan 21.04, unggul 6.74 poin atas TMO (14.3). Awareness 92% pada 2026, oli 10W-40."]
GOOD = {
    "judul": "Fastron memimpin BEI 4W (21,04) tetapi turun 1,7 poin", "format_angka": "id",
    "slides": [
        {"komponen": "kartu", "judul": "Fastron unggul 6,74 poin atas TMO", "kartu": [
            {"angka": "21,04", "label": "BEI Fastron", "delta": "−1,7", "tone": "neg"},
            {"angka": "14,3", "label": "BEI TMO"}, {"angka": "92%", "label": "Awareness"}]},
        {"komponen": "papan_skor", "judul": "Fastron #1 dengan BEI 21,04, TMO di 14,3", "panel": [
            {"judul_panel": "BEI 4W", "kategori": ["Fastron", "TMO", "Shell Helix", "Castrol Magnatec"],
             "nilai": [21.04, 14.3, 13.3, 8.4], "sorot": ["Fastron"]}]},
        {"komponen": "perbandingan", "judul": "Delta BEI: Fastron turun 1,7, TMO naik 0,4", "panel": [
            {"judul_panel": "Delta vs Q2", "kategori": ["Fastron", "TMO"], "nilai": [-1.7, 0.4]}]},
        {"komponen": "aksi", "judul": "Tiga aksi untuk membalik penurunan BEI 1,7 poin", "baris": [
            {"aksi": "Perbaiki stok bengkel", "pemilik": "Sales", "waktu": "Q1 2027", "kpi": "BEI naik"}]},
    ]}


class NumberTest(unittest.TestCase):
    def test_fmt_never_rounds(self):
        self.assertEqual(T.fmt(3.14159), "3,14159")
        self.assertEqual(T.fmt(21, 1), "21,0")                 # dec = minimum (penyeragaman), bukan pembulatan
        self.assertEqual(T.fmt(2.345, 1), "2,345")
        self.assertEqual(T.fmt(0.1 + 0.2), "0,3")               # derau float dibuang
        self.assertEqual(T.fmt(97389.25, None, "", "en"), "97,389.25")

    def test_key_numbers_skip_years_codes_and_small_counts(self):
        keys = P.key_numbers(CHAT)
        got = [k["angka"] for k in keys]
        self.assertEqual(got, ["21.04", "6.74", "14.3", "92%"])
        self.assertIn("Fastron memimpin", keys[0]["konteks"])

    def test_pool_flags_fabricated_and_rounded_but_allows_differences(self):
        pool = P.Pool([DATA])
        self.assertEqual(pool.status(21.04), "ok")
        self.assertEqual(pool.status(6.74), "ok")               # selisih 21.04 − 14.3
        self.assertEqual(pool.status(21.0), "bulat")            # 21.04 dibulatkan -> diminta ditulis persis
        self.assertEqual(pool.status(97.389), "tidak")
        bad, rounded = P.check_storyboard({"slides": [{"komponen": "kartu", "judul": "BEI 21,0 dan 97,389",
                                                       "kartu": [{"angka": 14.3}]}]}, pool)
        self.assertEqual(bad, ["97,389"])
        self.assertEqual(rounded, ["21,0"])

    def test_parse_storyboard(self):
        self.assertEqual(P.parse_storyboard("```json\n" + json.dumps(GOOD) + "\n```")["judul"], GOOD["judul"])
        for bad in ("", "bukan json", '{"slides": []}', "[1,2]", '{"judul": "x"}'):
            self.assertIsNone(P.parse_storyboard(bad), bad)

    def test_prompt_lists_key_numbers_and_rules(self):
        prompt = P.build_prompt("buat laporan", "Retail", DATA, P.key_numbers(CHAT))
        self.assertIn("21.04", prompt)
        self.assertIn("TANPA PEMBULATAN", prompt)
        self.assertIn("papan_skor", prompt)

    def test_parse_blocks_reads_tables(self):
        b = P.parse_blocks(DATA)
        self.assertEqual(b[0]["tabel"][0]["kolom"], ["Merek", "BEI", "Delta"])
        self.assertEqual(len(b[0]["tabel"][0]["baris"]), 4)


@unittest.skipUnless(HAVE_LIBS, "matplotlib/python-pptx/reportlab belum terpasang")
class MakeReportTest(unittest.TestCase):
    def _make(self, side_effect, **kw):
        with mock.patch("library_agent.report_engine.generate_text", side_effect=side_effect) as gen:
            out = P.make_report("buat laporan", DATA, P.key_numbers(CHAT), ("pptx", "pdf", "html"), label="Retail",
                                **kw)
        return out, gen

    def test_claude_storyboard_renders_all_formats(self):
        out, gen = self._make([json.dumps(GOOD)])
        self.assertEqual(sorted(out["files"]), ["html", "pdf", "pptx"])
        self.assertEqual(out["sumber_storyboard"], "claude")
        self.assertGreaterEqual(out["stats"]["chart"], 2)
        self.assertEqual(out["angka_hilang"], [])
        self.assertEqual(out["angka_tidak_terverifikasi"], [])

    def test_model_error_uses_code_storyboard_with_charts(self):
        out, _ = self._make(RuntimeError("Claude & Argon penuh"))
        self.assertEqual(out["sumber_storyboard"], "cadangan")
        self.assertEqual(sorted(out["files"]), ["html", "pdf", "pptx"])
        self.assertGreaterEqual(out["stats"]["chart"], 1)
        self.assertEqual(out["angka_hilang"], [])               # angka kunci tetap masuk

    def test_garbage_reply_uses_code_storyboard(self):
        out, _ = self._make(["maaf saya tidak bisa", "masih bukan json"])
        self.assertEqual(out["sumber_storyboard"], "cadangan")
        self.assertTrue(out["files"])

    def test_timeout_falls_back_quickly(self):
        def slow(*a, **k):
            time.sleep(4)
            return json.dumps(GOOD)
        t0 = time.monotonic()
        out, _ = self._make(slow, budget=P.RENDER_RESERVE + 1.5)
        self.assertEqual(out["sumber_storyboard"], "cadangan")
        self.assertLess(time.monotonic() - t0, P.RENDER_RESERVE)
        self.assertTrue(out["files"])

    def test_one_revision_when_numbers_wrong(self):
        bad = json.loads(json.dumps(GOOD))
        bad["slides"][0]["kartu"][0]["angka"] = "97,389"         # angka karangan
        out, gen = self._make([json.dumps(bad), json.dumps(GOOD)])
        self.assertEqual(gen.call_count, 2)
        self.assertTrue(out["revisi"])
        self.assertEqual(out["angka_tidak_terverifikasi"], [])

    def test_missing_key_numbers_land_in_appendix(self):
        thin = {"judul": "Fastron #1", "slides": [{"komponen": "papan_skor", "judul": "Fastron memimpin 21,04", "panel": [
            {"kategori": ["Fastron", "TMO"], "nilai": [21.04, 14.3]}]}]}
        out, _ = self._make([json.dumps(thin), json.dumps(thin)])
        self.assertEqual(out["angka_hilang"], [])
        text = out["deck"].all_text()
        self.assertIn("6.74", text)
        self.assertIn("92%", text)

    def test_unfixable_wrong_number_gets_checker_page(self):
        bad = json.loads(json.dumps(GOOD))
        bad["slides"][0]["kartu"][0]["angka"] = "97,389"
        out, _ = self._make([json.dumps(bad), json.dumps(bad)])
        self.assertEqual(out["angka_tidak_terverifikasi"], ["97,389"])
        self.assertIn("perlu dicek ulang", out["deck"].all_text())

    def test_feedback_revision_keeps_previous_when_model_fails(self):
        out, gen = self._make(RuntimeError("penuh"), previous=GOOD, feedback="tambah halaman SWOT")
        self.assertTrue(out["files"])


def ctx(inv="v1", state=None):
    return NS(state={} if state is None else state, invocation_id=inv, user_id="u@x.co")


@unittest.skipUnless(HAVE_LIBS, "matplotlib/python-pptx/reportlab belum terpasang")
class ToolTest(unittest.TestCase):
    def setUp(self):
        from library_agent.tools import rfm_tools
        rfm_tools._HEAVY.clear()
        self.saved = []

        def save(user, tid, title, data, ext, ctype, record=None):
            self.saved.append(ext)
            return {"url": f"https://x/{ext}", "gcs_uri": f"gs://b/r/{len(self.saved)}.{ext}"}
        self.patches = [
            mock.patch("library_agent.report_engine.save_output", side_effect=save),
            mock.patch("library_agent.tools.report_tools._gcs_put"),
            mock.patch("library_agent.tools.report_tools._gather_source",
                       return_value={"status": "ok", "data_text": DATA, "domain": "retail", "label": "Retail"}),
            mock.patch("library_agent.usage.heavy_allowed", return_value=(True, "")),
            mock.patch("library_agent.config.live", return_value=None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_asks_format_only(self):
        from library_agent.tools.visual_report_tools import buat_laporan_visual
        res = buat_laporan_visual(tool_context=ctx(), permintaan="buat laporan", sumber="retail")
        self.assertEqual(res["status"], "needs_input")
        self.assertIn("format", res["message"])

    def test_creates_report_and_records_it(self):
        from library_agent.tools.visual_report_tools import VISUAL_KEY, buat_laporan_visual
        c = ctx()
        with mock.patch("library_agent.report_engine.generate_text", return_value=json.dumps(GOOD)):
            res = buat_laporan_visual(tool_context=c, permintaan="buat laporan", sumber="retail",
                                      output_format="pptx, pdf")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(sorted(res["file"]), ["pdf", "pptx"])
        self.assertTrue(res["alur_halaman"])
        self.assertEqual(c.state[VISUAL_KEY][-1]["report_id"], res["report_id"])
        self.assertTrue(c.state[VISUAL_KEY][-1]["storyboard_uri"].endswith(".storyboard.json"))

    def test_planner_crash_still_delivers_files(self):
        from library_agent.tools.visual_report_tools import buat_laporan_visual
        real = P.make_report
        calls = []

        def flaky(*a, **k):
            calls.append(k.get("use_model", True))
            if k.get("use_model", True):
                raise RuntimeError("bug tak terduga")
            return real(*a, **k)
        with mock.patch("library_agent.visual_report.planner.make_report", side_effect=flaky):
            res = buat_laporan_visual(tool_context=ctx("v2"), permintaan="x", sumber="retail", output_format="pdf")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(calls, [True, False])

    def test_total_failure_is_polite_without_technical_text(self):
        from library_agent.tools.visual_report_tools import buat_laporan_visual
        with mock.patch("library_agent.visual_report.planner.make_report", side_effect=RuntimeError("Traceback xyz")):
            res = buat_laporan_visual(tool_context=ctx("v3"), permintaan="x", sumber="retail", output_format="pdf")
        self.assertEqual(res["status"], "retry")
        self.assertNotIn("xyz", res["message"])
        self.assertNotIn("Traceback", res["message"])

    def test_auto_source_and_revision(self):
        from library_agent.tools import visual_report_tools as V
        self.assertEqual(V.auto_source({"documents": [{"doc_id": "d1", "text_uri": "gs://x"}]}), "dokumen")
        self.assertEqual(V.auto_source({"bq_pulls": [{"domain": "industri"}], "documents": []}), "industri")
        self.assertEqual(V.auto_source({}), "")
        c = ctx("v4", {V.VISUAL_KEY: [{"report_id": "v1", "storyboard_uri": "gs://b/r/1.storyboard.json",
                                       "data_uri": "gs://b/r/1.data.txt", "formats": ["html"], "request": "x"}]})
        store = {"gs://b/r/1.storyboard.json": json.dumps({"storyboard": GOOD, "keys": []}),
                 "gs://b/r/1.data.txt": DATA}
        with mock.patch("library_agent.tools.report_tools._gcs_text", side_effect=store.get), \
                mock.patch("library_agent.report_engine.generate_text", return_value=json.dumps(GOOD)) as gen:
            res = V.revisi_laporan_visual(masukan="tambah SWOT", tool_context=c)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(list(res["file"]), ["html"])
        self.assertIn("tambah SWOT", gen.call_args[0][0])

    def test_one_heavy_report_per_message(self):
        from library_agent.tools.visual_report_tools import buat_laporan_visual
        c = ctx("same")
        with mock.patch("library_agent.report_engine.generate_text", return_value=json.dumps(GOOD)):
            buat_laporan_visual(tool_context=c, permintaan="x", sumber="retail", output_format="html")
            res = buat_laporan_visual(tool_context=c, permintaan="y", sumber="retail", output_format="html")
        self.assertEqual(res["status"], "deferred")


class BatchVisualTest(unittest.TestCase):
    def test_parse_visual_item(self):
        from library_agent.tools import batch_tools as bt
        self.assertEqual(bt.parse_item("visual | sumber=retail | permintaan=deck harga"),
                         ("visual", {"sumber": "retail", "permintaan": "deck harga"}))
        self.assertEqual(bt.parse_item("deck | deck temuan Q3")[1], {"permintaan": "deck temuan Q3"})


if __name__ == "__main__":
    unittest.main()
