"""Uji laporan dari unggahan manual: ditulis Argon dengan cadangan Argon global, hasil sandbox ikut ke laporan,
dan agent analisis file punya alat laporan (bukan .txt)."""
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

from library_agent import config, prompts, report_engine  # noqa: E402


class FakeModels:
    def __init__(self, loc, full, calls):
        self.loc, self.full, self.calls = loc, full, calls

    def generate_content(self, model, contents, config=None):
        self.calls.append((model, self.loc))
        if (model, self.loc) in self.full:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return NS(text='{"ok": true}')


class ArgonFallbackTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        report_engine.RETRY_SECONDS = 0
        self.p = [mock.patch.object(config, "_read_runtime_file", return_value={"model_fallbacks": ["pro@global",
                                                                                                      "fast@global"]}),
                  mock.patch("library_agent.clients.location_for",
                             side_effect=lambda m: "asia-southeast1" if m == config.settings.model_pro else "global")]
        for x in self.p:
            x.start()
        config._runtime_cache["loaded_at"] = 0

    def tearDown(self):
        for x in self.p:
            x.stop()
        config._runtime_cache["loaded_at"] = 0

    def _client(self, full):
        return lambda loc="": NS(models=FakeModels(loc, full, self.calls))

    def test_targets_are_argon_only(self):
        pro = config.settings.model_pro
        self.assertEqual(report_engine._report_targets(pro), [(pro, "asia-southeast1"), (pro, "global")])

    def test_regional_full_uses_argon_global(self):
        pro = config.settings.model_pro
        with mock.patch("library_agent.clients.genai_client", self._client({(pro, "asia-southeast1")})):
            self.assertEqual(report_engine.generate_text("tulis laporan"), '{"ok": true}')
        self.assertEqual(self.calls, [(pro, "asia-southeast1"), (pro, "asia-southeast1"), (pro, "global")])
        self.assertNotIn(config.settings.model_fast, [m for m, _ in self.calls])

    def test_all_full_clear_message(self):
        pro = config.settings.model_pro
        with mock.patch("library_agent.clients.genai_client", self._client({(pro, "asia-southeast1"), (pro, "global")})):
            with self.assertRaises(RuntimeError) as ctx:
                report_engine.generate_text("x")
        self.assertIn("coba lagi", str(ctx.exception).lower().replace("mencoba lagi", "coba lagi"))

    def test_json_path_uses_fallback(self):
        pro = config.settings.model_pro
        with mock.patch("library_agent.clients.genai_client", self._client({(pro, "asia-southeast1")})):
            self.assertEqual(report_engine._generate_json("x", {"type": "object"}), {"ok": True})


class UploadReportFlowTest(unittest.TestCase):
    def test_file_agent_has_report_tools(self):
        from library_agent.subagents.files import file_agent

        names = {t.__name__ for t in file_agent.tools}
        self.assertTrue({"generate_custom_report", "konversi_laporan_custom", "approve_report"} <= names)
        self.assertIn("DILARANG menyerahkan laporan sebagai teks", prompts.FILE_INSTRUCTION)
        self.assertEqual(file_agent.model.model, config.settings.model_claude)

    def test_code_results_feed_report(self):
        from library_agent.tools import report_tools as rt

        store = {"rfm.csv": b"Segmen,Outlet\nChampions,412\nAt Risk,233\n"}

        class Blob:
            def __init__(self, path):
                self.path = path

            def download_as_bytes(self):
                return store[self.path]
        storage = NS(bucket=lambda b: NS(blob=lambda p: Blob(p)))
        ctx = NS(state={"code_results": [{"step": 4, "purpose": "Segmentasi RFM 2025", "stdout": "Total outlet 5129",
                                          "files": [{"name": "rfm_segmen.csv", "url": "u", "gcs_uri": "gs://b/rfm.csv"}]}]})
        with mock.patch("library_agent.clients.storage_client", return_value=storage):
            blocks = rt._code_result_blocks(ctx)
        text = "\n".join(blocks)
        self.assertIn("Segmentasi RFM 2025", text)
        self.assertIn("Total outlet 5129", text)
        self.assertIn("Champions | 412", text)


if __name__ == "__main__":
    unittest.main()


class DocumentSourceTest(unittest.TestCase):
    """Kasus user: hasil analisis berupa TXT dibawa ke chat baru, lalu diminta dibuat laporan."""

    TXT = ("Hasil Analisa RFM SR1 2025\nTotal outlet aktif: 5.129\nChampions: 412 outlet, volume 3.214,55 KL\n"
           "At Risk: 233 outlet\n")
    BODY = ('<section class="page"><div class="hdr"><div class="hdr-r">Q3<br><span class="draft">DRAFT - menunggu approval'
            '</span></div></div><p>Champions 412 outlet dengan volume 3.214,55 KL dari 5.129 outlet aktif.</p>'
            '<div class="footer"><span>Sumber: x</span></div></section>')

    def _run(self, body):
        from library_agent.tools import report_tools as rt

        saved = {}

        def save(user, tid, title, data, ext, ctype, record=None):
            saved[ext] = data
            return {"url": f"https://x/r.{ext}", "gcs_uri": f"gs://b/r.{ext}", "format": ext}
        ctx = NS(user_id="u", _invocation_context=None, state={"documents": [
            {"doc_id": "d1", "filename": "hasil_rfm.txt", "jenis": "Teks", "uri": "gs://b/d1", "text_uri": "gs://b/d1.txt"}]})
        with mock.patch("library_agent.tools.doc_tools.document_instructions", return_value=self.TXT), \
                mock.patch.object(rt, "_gcs_put"), \
                mock.patch("library_agent.report_engine.save_output", side_effect=save), \
                mock.patch("library_agent.report_engine.generate_text",
                           return_value="LAPORAN DATA — RFM SR1 · 2025\n```html\n" + body + "\n```") as gen:
            res = rt.generate_custom_report("one pager RFM SR1 untuk management", "dokumen", ctx, file_id="d1",
                                            output_format="pdf")
        return res, gen, saved

    def test_txt_to_pdf_report(self):
        res, gen, saved = self._run(self.BODY)
        self.assertEqual(res["status"], "ok", res)
        self.assertIn("pdf", res["file"])
        self.assertTrue(saved["pdf"].startswith(b"%PDF"))
        self.assertIn("Champions: 412 outlet", gen.call_args[0][0])
        self.assertEqual(res["angka_tidak_terverifikasi"], [])

    def test_numbers_checked_against_document(self):
        res, _, _ = self._run(self.BODY.replace("3.214,55", "9.999,99"))
        self.assertIn("9.999,99", " ".join(res["angka_tidak_terverifikasi"]))

    def test_no_document(self):
        from library_agent.tools import report_tools as rt

        res = rt.generate_custom_report("laporan", "dokumen", NS(user_id="u", _invocation_context=None, state={}),
                                        output_format="pdf")
        self.assertEqual(res["status"], "needs_input")


class OfferAndNoTxtTest(unittest.TestCase):
    def test_offer_rule_in_instruction(self):
        ins = prompts.FILE_INSTRUCTION
        self.assertIn("hanya menawarkan, tidak memotong analisis", ins)
        self.assertIn("Apakah Anda ingin saya buatkan laporan dari hasil analisis ini?", ins)
        self.assertIn("Jangan pernah membuat laporan sebelum user menyetujui", ins)
        self.assertIn("langsung buat tanpa bertanya lagi", ins)

    def test_sandbox_txt_never_delivered(self):
        from library_agent import code_exec

        self.assertFalse("laporan.txt".endswith(code_exec.DELIVERABLE_EXT))
        self.assertFalse("ringkasan.md".endswith(code_exec.DELIVERABLE_EXT))
        self.assertTrue("rfm_segmen.csv".endswith(code_exec.DELIVERABLE_EXT))


class DocumentSourceTest(unittest.TestCase):
    def test_report_from_txt_analysis(self):
        from library_agent.tools import report_tools as rt

        doc_text = "HASIL ANALISIS RFM SR1\nTotal outlet aktif 2025: 5.129\nChampions: 412 outlet, volume 3.120,55 KL"
        body = ('<section class="page"><div class="hdr"><div class="hdr-r"><span class="draft">DRAFT - menunggu approval'
                '</span></div></div><div class="kpi"><div class="kpi-val">5.129</div></div>'
                '<p>Champions 412 outlet dengan volume 3.120,55 KL.</p><div class="footer"><span>Sumber: x</span></div></section>')
        saved = []

        def save(user, tid, title, data, ext, ctype, record=None):
            saved.append(ext)
            return {"url": f"https://x/r.{ext}", "gcs_uri": f"gs://b/r.{ext}", "format": ext}
        ctx = NS(user_id="u", _invocation_context=None, state={"documents": [
            {"doc_id": "d1", "filename": "hasil_rfm.txt", "jenis": "Teks", "uri": "gs://b/d1", "text_uri": "gs://b/d1.txt"}]})
        with mock.patch("library_agent.tools.doc_tools.document_instructions", return_value=doc_text), \
                mock.patch.object(rt, "_gcs_put"), mock.patch.object(rt, "_gcs_text", return_value=""), \
                mock.patch("library_agent.report_engine.save_output", side_effect=save), \
                mock.patch("library_agent.report_engine.generate_text",
                           return_value="LAPORAN DATA — RFM SR1 · 2025\n```html\n" + body + "\n```") as gen:
            res = rt.generate_custom_report("One pager RFM SR1 untuk management", "dokumen", ctx, output_format="pdf")
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(res["angka_tidak_terverifikasi"], [])
        self.assertIn("HASIL ANALISIS RFM SR1", gen.call_args[0][0])
        self.assertEqual(saved, ["html", "pdf"])
        self.assertNotIn("txt", saved)
