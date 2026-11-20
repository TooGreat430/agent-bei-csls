"""Uji paket laporan sekaligus (beberapa laporan berbeda dalam satu pesan, paralel + batas waktu)."""
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

from library_agent.tools import batch_tools as bt  # noqa: E402
from library_agent.tools import rfm_tools  # noqa: E402


def ctx(inv="b1", state=None):
    return NS(state={} if state is None else state, invocation_id=inv, user_id="u@x.co")


def fake_tool(name, delay=0.0, writes=None, status="ok"):
    def tool(tool_context, **kw):
        time.sleep(delay)
        for k, v in (writes or {}).items():
            cur = list(tool_context.state.get(k) or [])
            cur.append(v)
            tool_context.state[k] = cur
        return {"status": status, "laporan": name, "args": kw}
    return tool


class ParseTest(unittest.TestCase):
    def test_parse_items(self):
        self.assertEqual(bt.parse_item("harga | period=2026-Q3 | compare_period=2026-Q2"),
                         ("harga", {"period": "2026-Q3", "compare_period": "2026-Q2"}))
        k, p = bt.parse_item("custom | source=retail | request=Analisis Fastron | data_questions=a; b")
        self.assertEqual((k, p["source"], p["data_questions"]), ("custom", "retail", ["a", "b"]))
        self.assertEqual(bt.parse_item("Dashboard Harga | format=pdf")[0], "harga")
        self.assertEqual(bt.parse_item("rfm | region=semua"), ("rfm", {"region": "semua"}))
        for bad in ("cuaca | x=1", "harga | region=SR1", "custom | source=retail", "rfm | format=pdf"):
            with self.assertRaises(ValueError, msg=bad):
                bt.parse_item(bad)


class BatchTest(unittest.TestCase):
    def setUp(self):
        rfm_tools._HEAVY.clear()

    def _run(self, c, tools, live=None, **kw):
        with mock.patch.object(bt, "_raw", side_effect=lambda kind: tools[kind]), \
                mock.patch("library_agent.config.live", side_effect=lambda k: (live or {}).get(k)):
            return bt.buat_laporan_sekaligus(tool_context=c, **kw)

    def test_parallel_all_done_and_state_merged(self):
        state = {"custom_reports": [{"id": "old"}]}
        tools = {"harga": fake_tool("harga", 0.4, {"custom_reports": {"id": "r-harga"}}),
                 "planogram": fake_tool("planogram", 0.4, {"custom_reports": {"id": "r-plano"}}),
                 "rfm": fake_tool("rfm", 0.4, {"rfm_reports": {"scope": "NASIONAL"}})}
        t0 = time.monotonic()
        res = self._run(ctx("a", state), tools, laporan=["harga | period=2026-Q3", "planogram | period=2026-Q3",
                                                          "rfm | region=semua"], output_format="pdf")
        self.assertLess(time.monotonic() - t0, 1.0)                    # paralel, bukan 1,2 detik berurutan
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual([h["laporan"] for h in res["hasil"]], ["harga", "planogram", "rfm"])
        self.assertEqual(res["hasil"][0]["args"]["output_format"], "pdf")
        self.assertNotIn("output_format", res["hasil"][2]["args"])     # RFM tanpa format
        self.assertEqual([r["id"] for r in state["custom_reports"]], ["old", "r-harga", "r-plano"])
        self.assertEqual(state["rfm_reports"], [{"scope": "NASIONAL"}])
        again = self._run(ctx("a", state), tools, laporan=["harga"], output_format="pdf")
        self.assertEqual(again["status"], "deferred")                   # tetap satu panggilan berat per pesan

    def test_time_budget_returns_finished_and_pending(self):
        tools = {"harga": fake_tool("harga", 0.1), "industri": fake_tool("industri", 3.0)}
        with mock.patch.object(bt, "MIN_WAIT", 0):
            res = self._run(ctx("b"), tools, laporan=["harga", "industri | period=Agustus 2026"],
                            output_format="html", live={"batch_time_budget": 0.6})
        self.assertEqual([h["jenis"] for h in res["hasil"]], ["harga"])
        self.assertEqual(res["tertunda_batas_waktu"], ["industri | period=Agustus 2026"])
        self.assertIn("lanjut", res["message"])

    def test_format_asked_once_and_errors_reported(self):
        res = self._run(ctx("c"), {}, laporan=["harga", "planogram"])
        self.assertEqual(res["status"], "needs_input")
        self.assertNotIn("c", rfm_tools._HEAVY)                         # bertanya tidak memakai jatah
        res = self._run(ctx("d"), {}, laporan=["harga", "cuaca"], output_format="pdf")
        self.assertEqual(res["status"], "invalid")
        self.assertIn("laporan 2", res["message"])

        def boom(tool_context, **kw):
            raise RuntimeError("kuota")
        res = self._run(ctx("e"), {"harga": boom, "planogram": fake_tool("planogram")},
                        laporan=["harga", "planogram"], output_format="pdf")
        self.assertEqual([h["status"] for h in res["hasil"]], ["error", "ok"])

    def test_pull_ids_renumbered_on_merge(self):
        state = {"bq_pulls": [{"id": "p1"}], "bq_pull_seq": 1}
        base = {"bq_pulls": [{"id": "p1"}]}
        layers = [{"bq_pulls": [{"id": "p1"}, {"id": "p2", "q": "a"}], "bq_pull_seq": 2},
                  {"bq_pulls": [{"id": "p1"}, {"id": "p2", "q": "b"}], "bq_pull_seq": 2}]
        bt.merge_states(state, base, layers)
        self.assertEqual([p["id"] for p in state["bq_pulls"]], ["p1", "p2", "p3"])
        self.assertEqual(state["bq_pull_seq"], 3)

    def test_registered_everywhere(self):
        from library_agent import prompts
        from library_agent.subagents.data import data_agent
        from library_agent.subagents.files import file_agent
        from library_agent.subagents.report import report_agent

        for agent in (data_agent, report_agent, file_agent):
            self.assertIn("buat_laporan_sekaligus", {t.__name__ for t in agent.tools})
        self.assertIn("buat_laporan_sekaligus", prompts.REPORT_INSTRUCTION)
        self.assertIn("buat_laporan_sekaligus", prompts.DATA_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
