"""Uji analisis RFM outlet sell-out (mesin hitung, laporan, alat, batas satu laporan berat per pesan)."""
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from library_agent import rfm_engine as eng  # noqa: E402
from library_agent import rfm_report as rep  # noqa: E402

import _rfm_synth  # noqa: E402

_DATA = {}


def synth():
    if not _DATA:
        o, s, a = _rfm_synth.make(n=2500, seed=11)
        _DATA.update(outlets=pd.DataFrame(o), series=pd.DataFrame(s), audit=a)
    return _DATA


def ctx(inv="inv-1", state=None):
    return NS(state={} if state is None else state, invocation_id=inv, user_id="u@x.co")


class ScoringTest(unittest.TestCase):
    def test_window_2026_09(self):
        w = eng.window("2026-09")
        self.assertEqual((len(w["base"]), len(w["ytd"]), len(w["ytd_prev"])), (12, 9, 9))
        self.assertEqual(w["base"][0], (2025, 1))
        self.assertEqual(w["ytd"][-1], (2026, 9))
        with self.assertRaises(ValueError):
            eng.parse_cutoff("Sept 2026")

    def test_r_bands(self):
        months = pd.Series([0, 1, 2, 3, 4, 6, 7, 20])
        self.assertEqual(eng.r_score(months).tolist(), [5, 4, 3, 3, 2, 2, 1, 1])

    def test_threshold_equal_goes_higher(self):
        cuts = eng.thresholds(pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float))
        self.assertEqual(len(cuts), 4)
        scores = eng.quint_score(pd.Series([cuts[0], cuts[0] - 1e-9, cuts[3], 999.0]), cuts)
        self.assertEqual(scores.tolist(), [2, 1, 5, 5])

    def test_125_combinations_first_match(self):
        v = eng.validate_125()
        self.assertEqual((v["tested"], v["unassigned"], v["status"]), (125, 0, "PASS"))
        seg = eng.assign_segments(pd.Series([5, 1, 1, 2, 3, 3, 5, 4, 5, 4]), pd.Series([5, 5, 1, 1, 3, 1, 4, 4, 2, 1]),
                                  pd.Series([5, 5, 5, 1, 3, 1, 1, 3, 5, 5]))
        self.assertEqual(seg.tolist(), ["Champions", "Can't Lose Them", "Lost", "Hibernating", "Need Attention",
                                        "Mid-Recency Watchlist", "Recent Low Monetary", "Loyal Customers",
                                        "Potential Loyalists", "New Customers"])

    def test_region_key(self):
        for raw, key in (("REGION I", "SR1"), ("Region 3", "SR3"), ("SR7", "SR7"), ("Sales Region VI", "SR6"),
                         ("REGION IV", "SR4"), ("sr 2", "SR2")):
            self.assertEqual(eng.region_key(raw), key, raw)


class SqlTest(unittest.TestCase):
    def test_parameterized_and_safe_identifiers(self):
        cfg = {"table": eng.DEFAULT_TABLE, "store_types": eng.DEFAULT_STORE_TYPES, "series_column": "PRODUCT_SEGMENT",
               "exclude_pattern": "MEDITRAN SX BIO", "cutoff": "2026-09"}
        w = eng.window("2026-09")
        sql = eng.outlet_sql(cfg, w)
        self.assertIn("`ptpl-curated-prd.DATAMART.SALES_OUT_DAILY`", sql)
        self.assertIn("@stypes", sql)
        self.assertNotIn("OTO-8", sql)                      # nilai lewat parameter, bukan teks SQL
        self.assertIn("m_2025_01", sql)
        self.assertIn("m_2026_09", sql)
        for bad in ("x`; DROP TABLE y; --", "a.b"):
            with self.assertRaises(ValueError):
                eng._table(bad) if "." not in bad or "`" in bad else eng._ident(bad)
        with self.assertRaises(ValueError):
            eng.outlet_sql({**cfg, "series_column": "PRODUCT_SEGMENT; DROP"}, w)


class ComputeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = synth()
        cls.nat = eng.compute(d["outlets"], d["series"], d["audit"], "2026-09")
        cls.sr3 = eng.compute(d["outlets"], d["series"], d["audit"], "2026-09", scope="SR3")

    def test_checks_pass(self):
        for res in (self.nat, self.sr3):
            c = res["checks"]
            self.assertTrue(c["migration_reconciled"])
            self.assertTrue(c["segments_reconciled"])
            self.assertEqual(c["rules_125"], "PASS")
            self.assertEqual(c["unassigned_outlets"], 0)

    def test_scope_and_thresholds(self):
        self.assertEqual(self.sr3["scope"], "SR3")
        self.assertLess(self.sr3["kpi"]["outlets_valid"], self.nat["kpi"]["outlets_valid"])
        self.assertNotEqual(self.sr3["thresholds"]["M"], self.nat["thresholds"]["M"])   # threshold per region
        self.assertEqual(sorted(self.sr3["thresholds"]["F"]), self.sr3["thresholds"]["F"])
        self.assertIn("regions", self.nat)
        self.assertNotIn("regions", self.sr3)

    def test_baseline_cohort_and_entrants(self):
        k = self.nat["kpi"]
        self.assertEqual(k["outlets_baseline"] + k["outlets_entrants"], k["outlets_valid"])
        self.assertEqual(self.nat["migration"]["total"], k["outlets_baseline"])
        self.assertAlmostEqual(k["vol_cohort_ytd"] + k["vol_entrants_ytd"], k["vol_ytd"], places=4)

    def test_inactive_baseline_outlet_gets_f1_m1(self):
        reg = self.nat["register"]
        inactive = reg[(reg["vol_base"] > 0) & (reg["vol_ytd"] <= 0)]
        self.assertGreater(len(inactive), 0)
        self.assertTrue((inactive["Fs_ytd"] == 1).all())
        self.assertTrue((inactive["Ms_ytd"] == 1).all())

    def test_segment_counts_sum(self):
        self.assertEqual(sum(s["outlets"] for s in self.nat["segments"]), self.nat["kpi"]["outlets_snapshot_ytd"])
        self.assertAlmostEqual(sum(s["vol_share"] or 0 for s in self.nat["segments"]), 100.0, places=3)

    def test_unknown_region(self):
        d = synth()
        with self.assertRaises(ValueError) as e:
            eng.compute(d["outlets"], d["series"], d["audit"], "2026-09", scope="SR9")
        self.assertIn("SR1", str(e.exception))

    def test_register_excel(self):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(eng.register_excel(self.sr3)), read_only=True)
        for name in ("Outlet RFM Master", "Migration Cohort", "125 Rule Validation", "Data Audit"):
            self.assertIn(name, wb.sheetnames)


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = synth()
        cls.res = eng.compute(d["outlets"], d["series"], d["audit"], "2026-09", scope="SR7")

    def test_html_has_8_sections_and_footer(self):
        html_doc = rep.render_html(self.res, rep.fallback_narrative(self.res), credit="Prepared with X")
        for i in range(1, 9):
            self.assertIn(f'id="s0{i}"', html_doc)
        self.assertIn("Marketing Intelligence &amp; Research", html_doc)
        self.assertIn("Sales Region 7", html_doc)
        self.assertIn("Prepared with X", html_doc)
        self.assertIn("#18324B", html_doc.upper())
        self.assertNotIn("<script", html_doc.lower().replace("<script type=\"application/ld+json\"", ""))

    def test_narrative_ungrounded_numbers_dropped(self):
        fake = {"headline": "Volume naik 987.654 KL", "ringkasan": ["Champions mendominasi volume"],
                "interpretasi_overview": "Pertumbuhan 98.765,4% luar biasa", "interpretasi_rfm": "R tinggi",
                "interpretasi_segmen": "ok", "interpretasi_produk": "ok", "interpretasi_momentum": "ok",
                "aksi_segmen": [{"segmen": "Champions", "aksi": "Jaga pasokan"}], "rencana_90_hari": []}
        with mock.patch("library_agent.report_engine._generate_json", return_value=fake):
            out = rep.generate_narrative(self.res, "")
        base = rep.fallback_narrative(self.res)
        self.assertEqual(out["headline"], base["headline"])
        self.assertEqual(out["interpretasi_overview"], base["interpretasi_overview"])
        self.assertEqual(out["ringkasan"], ["Champions mendominasi volume"])
        self.assertGreaterEqual(out["_dropped"], 2)

    def test_narrative_falls_back_on_error(self):
        with mock.patch("library_agent.report_engine._generate_json", side_effect=RuntimeError("429")):
            out = rep.generate_narrative(self.res, "")
        self.assertTrue(out["headline"])


class HeavyTurnTest(unittest.TestCase):
    def setUp(self):
        from library_agent.tools import rfm_tools

        self.t = rfm_tools
        rfm_tools._HEAVY.clear()

    def test_one_heavy_report_per_invocation(self):
        state = {}
        self.assertIsNone(self.t.heavy_turn_guard(ctx("a", state), "laporan 1"))
        blocked = self.t.heavy_turn_guard(ctx("a", state), "laporan 2")
        self.assertEqual(blocked["status"], "deferred")
        self.assertIn("laporan 1", blocked["message"])
        self.assertIsNone(self.t.heavy_turn_guard(ctx("b", state), "laporan 2"))   # pesan berikutnya boleh

    def test_state_guard_without_registry(self):
        state = {}
        self.t.heavy_turn_guard(ctx("a", state), "x")
        self.t._HEAVY.clear()                                                        # proses lain / restart
        self.assertEqual(self.t.heavy_turn_guard(ctx("a", state), "y")["status"], "deferred")

    def test_decorator_releases_when_not_heavy(self):
        calls = []

        @self.t.heavy_turn("uji")
        def tool(tool_context, fmt=""):
            calls.append(fmt)
            return {"status": "needs_input"} if not fmt else {"status": "ok"}

        state = {}
        self.assertEqual(tool(tool_context=ctx("a", state))["status"], "needs_input")
        self.assertEqual(tool(tool_context=ctx("a", state), fmt="pdf")["status"], "ok")
        self.assertEqual(tool(tool_context=ctx("a", state), fmt="pdf")["status"], "deferred")
        self.assertEqual(len(calls), 2)

    def test_custom_reports_guarded_and_rfm_redirected(self):
        from library_agent.tools import report_tools as rt

        with mock.patch("library_agent.usage.heavy_allowed", return_value=(True, "")):
            res = rt.generate_custom_report("Buat laporan RFM outlet SR1 sesuai master prompt", "sellout",
                                            tool_context=ctx("z"), output_format="html")
        self.assertEqual(res["status"], "redirect")
        self.assertIn("analisis_rfm", res["message"])
        self.assertNotIn("z", self.t._HEAVY)                                         # redirect tidak memakai jatah
        st = {}
        self.t.heavy_turn_guard(ctx("q", st), "laporan custom")
        with mock.patch("library_agent.usage.heavy_allowed", return_value=(True, "")):
            res = rt.generate_custom_report("Laporan harga", "retail", tool_context=ctx("q", st), output_format="html")
        self.assertEqual(res["status"], "deferred")

    def test_rfm_detection(self):
        for t in ("Analisis RFM outlet", "segmen Champions dan At Risk", "Recency, Frequency, Monetary"):
            self.assertTrue(self.t.is_rfm_request(t), t)
        self.assertFalse(self.t.is_rfm_request("volume sell-out per distributor Q3"))


class ToolTest(unittest.TestCase):
    def setUp(self):
        from library_agent.tools import rfm_tools

        rfm_tools._HEAVY.clear()
        d = synth()
        self.data = {"outlets": d["outlets"], "series": d["series"], "audit": d["audit"], "cfg": {},
                     "fetched_at": "2026-11-20 03:00 UTC"}
        self.saved = []

    def _save(self, uid, tid, title, data, ext, ctype, record):
        self.saved.append((title, ext, len(data)))
        return {"format": ext, "url": f"https://x/{title}.{ext}", "gcs_uri": f"gs://b/{title}.{ext}"}

    def _run(self, c, live=None, gen=None, **kw):
        from library_agent.tools.rfm_tools import analisis_rfm

        with mock.patch.object(eng, "fetch", return_value=self.data), \
                mock.patch("library_agent.report_engine.save_output", side_effect=self._save), \
                mock.patch("library_agent.report_engine._generate_json", side_effect=gen or RuntimeError("off")), \
                mock.patch("library_agent.config.live", side_effect=lambda k: (live or {}).get(k)):
            return analisis_rfm(tool_context=c, **kw)

    def test_all_regions_in_one_call(self):
        state = {}
        res = self._run(ctx("m1", state), region="semua")
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual([x["cakupan"] for x in res["laporan"]][0], "Nasional")
        self.assertEqual(len(res["laporan"]), 8)
        self.assertIn("halaman_paket", res)
        self.assertEqual(res["belum_dibuat"], [])
        self.assertNotIn("tertunda_batas_waktu", res)
        self.assertEqual(sum(1 for _, ext, _ in self.saved if ext == "xlsx"), 8)
        self.assertTrue(any("Paket" in t for t, _, _ in self.saved))
        self.assertEqual(self._run(ctx("m1", state), region="SR1")["status"], "deferred")   # tetap 1 panggilan/pesan

    def test_region_list_and_time_budget(self):
        res = self._run(ctx("m1"), region="nasional, SR2 dan Region III", live={"rfm_time_budget": 0})
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(len(res["laporan"]), 1)                          # minimal satu laporan selalu jadi
        self.assertEqual(res["tertunda_batas_waktu"], ["SR2", "SR3"])
        self.assertIn("lanjut", res["message"])
        self.assertIn("halaman_paket", self._run(ctx("m2"), region="SR2, SR3"))

    def test_slow_narrative_falls_back(self):
        import time as _t

        def slow(*a, **k):
            _t.sleep(1.5)
            raise RuntimeError("lambat")

        res = self._run(ctx("m1"), region="SR4", gen=slow, live={"rfm_narrative_timeout": 0.3})
        self.assertEqual(res["status"], "ok", res)
        self.assertTrue(res["laporan"][0]["headline"])
        self.assertIn("narasi standar", res["message"])

    def test_parse_scopes(self):
        from library_agent.tools.rfm_tools import parse_scopes

        regs = [f"SR{i}" for i in range(1, 8)]
        self.assertEqual(parse_scopes("", regs), ["NASIONAL"])
        self.assertEqual(parse_scopes("Semua", regs), ["NASIONAL"] + regs)
        self.assertEqual(parse_scopes("semua_region", regs), regs)
        self.assertEqual(parse_scopes("SR1, sr1; Region II / nasional", regs), ["SR1", "SR2", "NASIONAL"])
        with self.assertRaises(ValueError):
            parse_scopes("SR1, SR9", regs)

    def test_region_report_then_deferred_then_next(self):
        state = {}
        res = self._run(ctx("m1", state), region="SR3")
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual({e for _, e, _ in self.saved}, {"html", "xlsx"})
        self.assertIn("SR3", res["sudah_dibuat_di_chat_ini"])
        self.assertIn("NASIONAL", res["belum_dibuat"])
        self.assertEqual(len(res["laporan"]), 1)
        self.assertNotIn("halaman_paket", res)
        self.assertTrue(res["laporan"][0]["ringkasan"]["pemeriksaan"]["migration_reconciled"])
        self.assertEqual(self._run(ctx("m1", state), region="SR4")["status"], "deferred")
        res2 = self._run(ctx("m2", state), region="")
        self.assertEqual(res2["status"], "ok")
        self.assertNotIn("NASIONAL", res2["belum_dibuat"])
        self.assertTrue(any("NASIONAL" in t for t, _, _ in self.saved))

    def test_list_regions_is_light(self):
        state = {}
        res = self._run(ctx("m1", state), region="daftar")
        self.assertEqual(res["region_tersedia"], [f"SR{i}" for i in range(1, 8)])
        self.assertNotIn("_ringan", res)
        self.assertEqual(self._run(ctx("m1", state), region="SR1")["status"], "ok")

    def test_bad_region_and_cutoff(self):
        res = self._run(ctx("m1"), region="SR9")
        self.assertEqual(res["status"], "error")
        self.assertIn("SR1", res["message"])
        res = self._run(ctx("m2"), region="SR1", cutoff="September")
        self.assertEqual(res["status"], "error")

    def test_registered_in_agents(self):
        from library_agent.subagents.data import data_agent
        from library_agent.subagents.files import file_agent
        from library_agent.subagents.report import report_agent
        from library_agent import prompts

        for agent in (data_agent, report_agent, file_agent):
            self.assertIn("analisis_rfm", {t.__name__ for t in agent.tools})
        self.assertIn("SATU LAPORAN BERAT PER PESAN", prompts.REPORT_INSTRUCTION)
        self.assertIn("analisis_rfm", prompts.DATA_INSTRUCTION)


class FetchCacheTest(unittest.TestCase):
    def test_parallel_queries_then_cache(self):
        import gzip
        import time as _time
        import types

        bq = types.ModuleType("google.cloud.bigquery")
        bq.QueryJobConfig = lambda **kw: kw
        bq.ScalarQueryParameter = lambda *a: a
        bq.ArrayQueryParameter = lambda *a: a
        gc = sys.modules.get("google.cloud") or types.ModuleType("google.cloud")
        gc.bigquery = bq
        store = {}

        class Blob:
            def __init__(self, name):
                self.name = name
                self.updated = NS(timestamp=lambda: _time.time())

            def exists(self):
                return self.name in store

            def reload(self):
                pass

            def download_as_bytes(self):
                return store[self.name]

            def upload_from_string(self, data, content_type=None):
                store[self.name] = data

        storage = NS(bucket=lambda b: NS(blob=Blob))
        sent = []

        def query(sql, job_config=None):
            sent.append(sql)
            row = ({"cust": "C1", "region": "REGION I", "stype": "OTO-8", "m_2025_01": 1.5} if "s_prev" in sql else
                   {"series": "ENDURO", "region": "REGION I", "in_cohort": True, "vol_prev": 1.0, "vol_cur": 2.0}
                   if "in_cohort" in sql else {"rows_total": 10})
            return NS(result=lambda page_size=None: [NS(items=lambda r=row: r.items())])

        cfg = {"table": eng.DEFAULT_TABLE, "store_types": ["OTO-8"], "series_column": "PRODUCT_SEGMENT",
               "exclude_pattern": "MEDITRAN SX BIO", "cutoff": "2026-09"}
        with mock.patch.dict(sys.modules, {"google.cloud": gc, "google.cloud.bigquery": bq}), \
                mock.patch("library_agent.clients.bigquery_client", return_value=NS(query=query)), \
                mock.patch("library_agent.clients.storage_client", return_value=storage):
            d1 = eng.fetch(cfg)
            self.assertEqual(len(sent), 3)
            self.assertEqual(len(store), 1)
            self.assertTrue(gzip.decompress(next(iter(store.values()))))
            d2 = eng.fetch(cfg)
            self.assertEqual(len(sent), 3)                          # dari cache, tanpa query ulang
            eng.fetch(cfg, refresh=True)
            self.assertEqual(len(sent), 6)
        self.assertEqual(d1["outlets"].iloc[0]["cust"], "C1")
        self.assertEqual(d2["audit"]["rows_total"], 10)


if __name__ == "__main__":
    unittest.main()
