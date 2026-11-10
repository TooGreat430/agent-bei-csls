"""Uji Data Agent Selling Out Intelligence: domain, alat tanya-jawab, deteksi file, laporan custom, larangan gabung."""
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

from library_agent import config, custom_report as cr, data_agent, data_engine as de, knowledge  # noqa: E402

SO = "projects/ptpl-land-dev/locations/global/dataAgents/agent_e188b55c-e61b-4c3f-9f91-3c97a54a6d4a"


class DomainTest(unittest.TestCase):
    def test_registered(self):
        self.assertEqual(config.settings.data_agent_sellout, SO)
        for alias in ("sellout", "Sell-out", "selling out", "Selling Out Intelligence"):
            self.assertEqual(data_agent.normalize_domain(alias), "sellout", alias)
        self.assertIn("sellout", data_agent.DOMAINS)
        self.assertIn("sellout", knowledge.DOMAINS)
        self.assertEqual(data_agent.agent_for("sellout"), SO)

    def test_data_tool_and_rules(self):
        from library_agent import prompts
        from library_agent.subagents.data import data_agent as agent

        self.assertIn("ask_sellout_intelligence", {t.__name__ for t in agent.tools})
        self.assertIn("BERDIRI SENDIRI", prompts.DATA_INSTRUCTION)


class FileDetectionTest(unittest.TestCase):
    def test_match_and_generic_prepare(self):
        cols = ["DISTRIBUTOR", "REGION", "CHANNEL", "PRODUCT", "VOLUME", "PERIODE"]
        with mock.patch.object(knowledge, "table_columns", return_value={"DISTRIBUTOR", "REGION", "CHANNEL",
                                                                          "PRODUCT", "VOLUME", "BULAN"}):
            score, hit = knowledge.match_score("sellout", cols)
        self.assertEqual(hit, 5)
        self.assertGreaterEqual(score, 0.8)
        df = pd.DataFrame({"DISTRIBUTOR": ["A", "B", None], "VOLUME": [1.0, 2.0, 3.0]})
        out, notes = de.prepare(df, "sellout")
        self.assertEqual(len(out), 2)                                       # baris total dikeluarkan

    def test_set_data_type_accepts_sellout(self):
        from library_agent.tools import file_tools

        ctx = NS(state={"data_files": [{"file_id": "f1", "filename": "so.xlsx"}]})
        with mock.patch.object(file_tools, "absorb_knowledge", return_value={}):
            res = file_tools.set_data_type("f1", "sell out", ctx)
        self.assertEqual(res["jenis_data"], "sellout")


class ReportTest(unittest.TestCase):
    def test_prompt_with_agent_and_mir_knowledge(self):
        with mock.patch.object(knowledge, "get", return_value={"instruction": "Fulfillment = kirim / order."}), \
                mock.patch.object(knowledge, "extra_knowledge", return_value="Laporan wajib per distributor."):
            p = cr.build_prompt("sellout", "Laporan sell-out SR3 Q3", "| a |\n|---|\n| 1 |")
        self.assertIn('cabang workflow "Sell-out"', p)
        self.assertIn("Fulfillment = kirim / order.", p)
        self.assertIn("Laporan wajib per distributor.", p)
        self.assertIn("LAPORAN SELL-OUT — <judul singkat>", p)
        self.assertNotIn("SISIPKAN_", p)

    def test_combination_refused(self):
        from library_agent.tools import report_tools as rt

        res = rt.generate_custom_report("gabungan", "sellout+planogram", NS(state={}, user_id="u",
                                                                            _invocation_context=None),
                                        output_format="pdf")
        self.assertEqual(res["status"], "invalid")
        self.assertIn("berdiri sendiri", res["message"])


if __name__ == "__main__":
    unittest.main()


class TableRefTest(unittest.TestCase):
    def test_full_refs_from_definition(self):
        published = {"datasourceReferences": {"bq": {"tableReferences": [
            {"projectId": "ptpl-curated-prd", "datasetId": "SALES", "tableId": "SALES_OUT_DAILY"},
            {"projectId": "ptpl-curated-prd", "datasetId": "SALES", "tableId": "AC_PARAMETER"}]}}}
        self.assertEqual(knowledge.table_refs(published), ["ptpl-curated-prd.SALES.AC_PARAMETER",
                                                           "ptpl-curated-prd.SALES.SALES_OUT_DAILY"])
