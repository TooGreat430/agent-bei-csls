"""Uji batas pemakaian harian/bulanan: peringatan sekali, penghentian laporan, cakupan 'semua'."""
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

from google.genai import types  # noqa: E402

from library_agent import config, usage  # noqa: E402


class BudgetTest(unittest.TestCase):
    def _setup(self, day, month, **cfg):
        config._runtime_cache["loaded_at"] = 0
        usage._CACHE.update(at=0.0, data=None)
        usage._BUFFER.update(ops=[], usd=0.0)
        self.p = [mock.patch.object(config, "_read_runtime_file", return_value=cfg),
                  mock.patch.object(usage, "read_day", side_effect=lambda key=None: {"total_usd": month if key and
                                                                                    len(key) == 7 else day})]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in getattr(self, "p", []):
            x.stop()
        config._runtime_cache["loaded_at"] = 0
        usage._CACHE.update(at=0.0, data=None)

    def test_no_caps_means_ok(self):
        self._setup(50, 900)
        self.assertEqual(usage.budget_overview()["level"], "ok")
        self.assertEqual(usage.heavy_allowed(), (True, ""))

    def test_warn_then_exceeded(self):
        self._setup(8.5, 40, budget_daily_usd=10, budget_monthly_usd=150)
        ov = usage.budget_overview()
        self.assertEqual((ov["level"], ov["periode"]), ("warn", "harian"))
        self.assertIn("85%", usage.warn_text(ov))
        self.tearDown()
        self._setup(3, 151, budget_daily_usd=10, budget_monthly_usd=150)
        ok, msg = usage.heavy_allowed()
        self.assertFalse(ok)
        self.assertIn("bulanan", msg)
        self.assertIn("awal bulan depan", msg)
        self.assertIn("Pertanyaan data dan analisis biasa tetap bisa dijawab", msg)

    def test_notice_once_per_day(self):
        self._setup(9, 40, budget_daily_usd=10)
        ctx = NS(state={})
        resp = NS(content=types.Content(role="model", parts=[types.Part(text="Jawaban data.")]))
        usage.budget_notice(ctx, resp)
        self.assertIn("90%", resp.content.parts[-1].text)
        resp2 = NS(content=types.Content(role="model", parts=[types.Part(text="Jawaban lain.")]))
        usage.budget_notice(ctx, resp2)
        self.assertEqual(len(resp2.content.parts), 1)                       # tidak diulang di chat yang sama

    def test_notice_skips_tool_calls(self):
        self._setup(9, 40, budget_daily_usd=10)
        resp = NS(content=types.Content(role="model", parts=[types.Part(function_call=NS(name="x"))]))
        usage.budget_notice(NS(state={}), resp)
        self.assertEqual(len(resp.content.parts), 1)

    def test_guard_only_in_scope_semua(self):
        self._setup(11, 40, budget_daily_usd=10)
        self.assertIsNone(usage.budget_guard(NS(state={}), NS()))
        self.tearDown()
        self._setup(11, 40, budget_daily_usd=10, budget_block_scope="semua")
        out = usage.budget_guard(NS(state={}), NS())
        self.assertIn("Agent tidak dapat memproses permintaan", out.content.parts[0].text)

    def test_report_tool_blocked(self):
        from library_agent.tools import report_tools as rt

        self._setup(11, 40, budget_daily_usd=10)
        res = rt.generate_custom_report("laporan", "retail", NS(state={}, user_id="u", _invocation_context=None),
                                        output_format="pdf")
        self.assertEqual(res["status"], "budget_limit")
        self.assertIn("besok pukul 00.00 WIB", res["message"])


if __name__ == "__main__":
    unittest.main()
