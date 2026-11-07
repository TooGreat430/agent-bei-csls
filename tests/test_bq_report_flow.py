"""Uji laporan dari data BigQuery yang sudah ditarik: data disimpan per chat, laporan memakai data itu tanpa menarik
ulang, agent data punya alat laporan, dan tidak ada laporan teks/TXT."""
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

from library_agent import prompts  # noqa: E402
from library_agent.tools import data_tools  # noqa: E402
from library_agent.tools import report_tools as rt  # noqa: E402

RESULT = {"answer": "Gap HTO Product Hero Zona 1 Q3 2026.", "tables": [{"columns": ["Produk", "Gap HTO"],
                                                                         "rows": [["Enduro Matic-S", -5200]], "total_rows": 1}]}
BODY = ('<section class="page"><div class="hdr"><div class="hdr-r"><span class="draft">DRAFT - menunggu approval</span>'
        '</div></div><p>Gap HTO Enduro Matic-S -5.200.</p><div class="footer"><span>Sumber: x</span></div></section>')


class BqReportTest(unittest.TestCase):
    def setUp(self):
        self.ctx = NS(user_id="u", _invocation_context=None, state={})
        self.saved = []

    def _save(self, user, tid, title, data, ext, ctype, record=None):
        self.saved.append(ext)
        return {"url": f"https://x/r.{ext}", "gcs_uri": f"gs://b/r.{ext}", "format": ext}

    def test_pull_is_remembered(self):
        data_tools.remember_pull(self.ctx, "retail", "gap HTO zona 1", RESULT)
        self.assertEqual(self.ctx.state["bq_pulls"][0]["domain"], "retail")
        self.assertIn("Enduro Matic-S", "\n".join(rt._pull_blocks(self.ctx, ("retail",))))
        self.assertEqual(rt._pull_blocks(self.ctx, ("industri",)), [])

    def _generate(self, **kw):
        with mock.patch.object(rt, "_gcs_put"), mock.patch.object(rt, "_gcs_text", return_value=""), \
                mock.patch("library_agent.report_engine.save_output", side_effect=self._save), \
                mock.patch("library_agent.tools.data_tools.pull", return_value={"status": "ok", **RESULT}) as pull, \
                mock.patch("library_agent.report_engine.generate_text",
                           return_value="LAPORAN RETAIL ONLY — Gap · Q3\n```html\n" + BODY + "\n```") as gen:
            res = rt.generate_custom_report("Laporan gap HTO Zona 1", "retail", self.ctx, output_format="html", **kw)
        return res, pull, gen

    def test_report_uses_pulled_data_without_repulling(self):
        data_tools.remember_pull(self.ctx, "retail", "gap HTO zona 1", RESULT)
        res, pull, gen = self._generate()
        self.assertEqual(res["status"], "ok", res)
        pull.assert_not_called()
        self.assertIn("Data yang sudah ditarik di chat", gen.call_args[0][0])
        self.assertEqual(self.saved, ["html"])

    def test_fresh_pull_when_nothing_pulled(self):
        res, pull, _ = self._generate()
        self.assertEqual(res["status"], "ok", res)
        pull.assert_called_once()

    def test_extra_questions_pull_more(self):
        data_tools.remember_pull(self.ctx, "retail", "gap HTO zona 1", RESULT)
        _, pull, _ = self._generate(data_questions=["tren gap Q1-Q3"])
        pull.assert_called_once()

    def test_data_agent_has_report_tools_and_rules(self):
        from library_agent.subagents.data import data_agent

        names = {t.__name__ for t in data_agent.tools}
        self.assertTrue({"generate_custom_report", "approve_report", "konversi_laporan_custom",
                         "generate_price_dashboard"} <= names)
        ins = prompts.DATA_INSTRUCTION
        self.assertIn("Apakah Anda ingin saya buatkan laporan", ins)
        self.assertIn("DILARANG menulis laporan sebagai teks", ins)
        self.assertNotIn("transfer ke report_agent", ins)


if __name__ == "__main__":
    unittest.main()
