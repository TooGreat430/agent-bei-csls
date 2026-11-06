"""Uji ekspor Excel: semua baris (bukan batas tampilan), multi-sheet, sheet Keterangan, nama sheet aman."""
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
from openpyxl import load_workbook  # noqa: E402

from library_agent import data_engine as de  # noqa: E402
from library_agent.tools import export_tools, file_tools  # noqa: E402

N_OUTLET = 300
RAW = pd.DataFrame({"Customer Code": [i // 3 for i in range(N_OUTLET * 3)],
                    "date": ["2025-01-31", "2025-02-28", "2026-01-31"] * N_OUTLET,
                    "Grand Total": [1.0, 2.0, 0.5] * N_OUTLET})


class ExportTest(unittest.TestCase):
    def setUp(self):
        prepared, notes = de.prepare(RAW, "lainnya")
        self.saved = {}
        self.patches = [mock.patch.object(file_tools, "_prepared", return_value=(prepared, notes, "lainnya")),
                        mock.patch("library_agent.report_engine.save_output", side_effect=self._save)]
        for p in self.patches:
            p.start()
        self.ctx = NS(user_id="u@x", state={"data_files": [{"file_id": "f1", "filename": "SORetail_SR1.csv",
                                                           "uri": "gs://b/x.csv"}]}, _invocation_context=None)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _save(self, user, template_id, title, data, ext, ctype, record=None):
        self.saved = {"title": title, "data": data, "ext": ext}
        return {"url": "https://storage.cloud.google.com/b/x.xlsx", "format": ext, "gcs_uri": "gs://b/x.xlsx"}

    def _analyze(self, plan, q):
        return file_tools.analyze_data(json.dumps(plan), q, self.ctx)

    def test_full_rows_and_sheets(self):
        r1 = self._analyze({"file": "f1", "group_by": ["Customer Code"], "limit": 50,
                            "metrics": [{"column": "Grand Total", "agg": "sum", "name": "VOLUME"},
                                        {"column": "date", "agg": "nunique", "name": "BULAN_AKTIF"}],
                            "sort": [{"column": "VOLUME", "desc": True}]}, "RFM per outlet")
        self.assertEqual(len(r1["rows"]), 50)                                   # chat hanya menampilkan 50
        self._analyze({"file": "f1", "metrics": [{"column": "Grand Total", "agg": "sum", "name": "TOTAL"}]}, "Audit")
        res = export_tools.ekspor_excel(self.ctx, nama_file="Analisa RFM SR1", nama_sheet=["RFM [2025]/2026", "Audit Data"])
        self.assertEqual(res["status"], "ok")
        wb = load_workbook(io.BytesIO(self.saved["data"]))
        self.assertEqual(wb.sheetnames, ["Keterangan", "RFM 2025 2026", "Audit Data"])
        rfm = wb["RFM 2025 2026"]
        self.assertEqual(rfm.max_row - 1, N_OUTLET)                             # SEMUA outlet, bukan 50/200
        self.assertEqual(rfm["A1"].value, "Customer Code")
        self.assertTrue(rfm["A1"].font.bold)
        self.assertEqual(wb["Keterangan"]["A1"].value, "Analisa RFM SR1")
        self.assertEqual(res["sheet"][0]["baris"], N_OUTLET)
        self.assertEqual(self.saved["ext"], "xlsx")

    def test_select_by_id(self):
        a = self._analyze({"file": "f1", "metrics": [{"column": "Grand Total", "agg": "sum", "name": "T"}]}, "A")
        self._analyze({"file": "f1", "group_by": ["date"], "metrics": [{"column": "Grand Total", "agg": "sum",
                                                                          "name": "T"}]}, "B")
        res = export_tools.ekspor_excel(self.ctx, analisis=[a["analisis_id"]])
        self.assertEqual(len(res["sheet"]), 1)
        self.assertEqual(export_tools.ekspor_excel(self.ctx, analisis=["a99"])["status"], "invalid")

    def test_no_analysis_yet(self):
        self.assertEqual(export_tools.ekspor_excel(self.ctx)["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
