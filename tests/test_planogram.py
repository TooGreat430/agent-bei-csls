"""Uji planogram: deteksi & aturan file, perhitungan ND/AV/whitespace, preset, dan render template."""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

import pandas as pd  # noqa: E402

from library_agent import data_engine as de  # noqa: E402
from library_agent import planogram_data as pdm  # noqa: E402
from library_agent import planogram_report as pr  # noqa: E402
from library_agent import ptpl_design, sample_planogram  # noqa: E402


def row(outlet, brand, series, kimap, av, date, region="REGION V", seg="MCO", usage="AUTOMATIC", visc="10W-30"):
    return {"OUTLET_ID": outlet, "SURVEY_DATE": date, "REGION": region, "PAIR_KIMAP": kimap, "BRAND": brand,
            "SERIES": series, "VISCOSITY": visc, "VOLUME": 0.8, "SEGMENT": seg, "USAGE": usage,
            "AVAILABILITY_SCORE": av, "VISIBILITY_SCORE": av, "AV_SCORE": av, "DT_PR": date}


Q3, Q2 = "2026-08-15", "2026-05-15"
TINY = pd.DataFrame([
    row("O1", "PERTAMINA", "ENDURO MATIC", "K1", 3.0, Q3), row("O1", "PERTAMINA", "ENDURO MATIC", "K1", 3.0, Q3),
    row("O1", "AHM", "SPX 2", "K1", 2.0, Q3), row("O2", "AHM", "SPX 2", "K1", 1.0, Q3),
    row("O3", "PERTAMINA", "ENDURO MATIC", "K1", 2.0, Q3), row("O4", "YAMALUBE", "MATIC", None, 1.0, Q3),
    row("O4", "PERTAMINA", "RADIATOR COOLANT", None, 1.0, Q3, seg="PCO", usage="GASOLINE", visc="NO VISCOSITY"),
    row("O1", "PERTAMINA", "ENDURO MATIC", "K1", 2.0, Q2), row("O1", "AHM", "SPX 2", "K1", 2.0, Q2),
    row("O2", "AHM", "SPX 2", "K1", 2.0, Q2), row("O3", "AHM", "SPX 2", "K1", 2.0, Q2),
])


class DetectPrepareTest(unittest.TestCase):
    def test_detect_planogram(self):
        self.assertEqual(de.detect_kind(TINY), "planogram")

    def test_rules(self):
        out, notes = de.prepare(TINY, "planogram")
        self.assertEqual(notes["excluded"].get("NO VISCOSITY di PCO/Commercial (bukan oli mesin)"), 1)
        self.assertEqual(set(out["SR"]), {"SR5"})
        self.assertEqual(set(out["ZONA"]), {"Zona 1"})
        self.assertEqual(set(out["KUARTAL"]), {"2026-Q3", "2026-Q2"})
        self.assertTrue(out["IS_OLI_MESIN"].all())

    def test_2t_normalized(self):
        df = pd.DataFrame([row("A", "PERTAMINA", "MESRANIA 2T SUPER", "K9", 2.0, Q3, seg="MCO", usage="MANUAL", visc="20"),
                           row("A", "AHM", "2T", "K9", 2.0, Q3, seg="MCO", usage="MANUAL", visc="NO VISCOSITY")])
        out, notes = de.prepare(df, "planogram")
        self.assertEqual(set(out["VISCOSITY"]), {"2T"})
        self.assertEqual(notes["viskositas_2T_dinormalisasi"], 2)

    def test_region_number(self):
        s = de.region_number(pd.Series(["REGION I", "REGION VII", "SR3", "5", "x"]))
        self.assertEqual(list(s), ["1", "7", "3", "5", ""])


class DatasetTest(unittest.TestCase):
    def setUp(self):
        prep, _ = de.prepare(TINY, "planogram")
        self.pa, self.pb = pdm.parse_period("2026-Q3"), pdm.parse_period("2026-Q2")
        self.ds = pdm.build_dataset(pdm.to_rows(prep, self.pa, self.pb), self.pa, self.pb, 70, 30)

    def test_previous_quarter(self):
        self.assertEqual(pdm.previous_period(pdm.parse_period("2026-Q1"))["label"], "Q4 2025")
        self.assertIsNone(pdm.previous_period(pdm.parse_period("2026-07")))

    def test_nd_and_momentum(self):
        n = self.ds["national"]
        self.assertEqual(n["a"]["nd"], 40.0)          # PTPL 2 dari total carry 5
        self.assertEqual(n["b"]["nd"], 25.0)          # PTPL 1 dari total carry 4
        self.assertEqual(n["nd_delta"], 15.0)
        self.assertEqual(n["nd_momentum"], "NAIK")
        self.assertEqual(n["a"]["carry_ptpl"], 2)
        self.assertEqual(n["a"]["outlets"], 4)

    def test_av_one_outlet_one_vote(self):
        a = self.ds["national"]["a"]
        self.assertEqual(a["av_ptpl"], 2.5)            # bukan 2,67 (baris O1 yang dobel tidak dihitung dua kali)
        self.assertEqual(a["av_komp"], 1.5)
        self.assertEqual(a["av_gap"], 1.0)

    def test_whitespace(self):
        self.assertEqual(self.ds["national"]["a"]["ws_outlets"], 1)   # O2: AHM ada, PTPL tidak, di K1
        self.assertEqual(self.ds["national"]["b"]["ws_outlets"], 2)
        k = self.ds["kimaps"][0]
        self.assertEqual((k["kimap"], k["carry_ptpl"], k["leader"], k["leader_carry"], k["ratio"]), ("K1", 2, "AHM", 2, 100.0))
        self.assertEqual(k["quadrant"], "DEFEND")

    def test_small_sample_flag(self):
        self.assertTrue(self.ds["viscosities"][0]["small"])

    def test_dataset_numbers(self):
        nums = pdm.dataset_numbers(self.ds)
        self.assertIn(40.0, nums)
        self.assertIn(15.0, nums)


class PresetTest(unittest.TestCase):
    def test_presets_match_template_logic(self):
        prep, _ = de.prepare(TINY, "planogram")
        nd = de.run_plan({"f": prep}, {"file": "f", "preset": "planogram_nd", "preset_args": {"group_by": ["SR"]}})
        rec = dict(zip(nd["columns"], nd["rows"][-1]))
        self.assertEqual((rec["KUARTAL"], rec["ND_PTPL_PCT"], rec["OUTLET_CARRY_PTPL"]), ("2026-Q3", 40.0, 2))
        av = de.run_plan({"f": prep}, {"file": "f", "preset": "planogram_av"})
        rec = dict(zip(av["columns"], av["rows"][-1]))
        self.assertEqual(rec["GAP_AV"], 1.0)
        ws = de.run_plan({"f": prep}, {"file": "f", "preset": "planogram_whitespace"})
        self.assertEqual(dict(zip(ws["columns"], ws["rows"][-1]))["OUTLET_WHITESPACE"], 1)

    def test_bad_group_rejected(self):
        prep, _ = de.prepare(TINY, "planogram")
        with self.assertRaises(de.PlanError):
            de.run_plan({"f": prep}, {"file": "f", "preset": "planogram_nd", "preset_args": {"group_by": ["HARGA"]}})


class TemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prep, notes = de.prepare(sample_planogram.rows(), "planogram")
        pa, pb = pdm.parse_period("2026-Q3"), pdm.parse_period("2026-Q2")
        cls.ds = pdm.build_dataset(pdm.to_rows(prep, pa, pb), pa, pb, 70, 30,
                                   {"viskositas_2T_dinormalisasi": notes.get("viskositas_2T_dinormalisasi")})
        cls.pages = pr.build_pages(cls.ds, pr.fallback_narrative(cls.ds))

    def test_six_pages_with_required_sections(self):
        self.assertEqual(len(self.pages), 6)
        kickers = " ".join(p["kicker"] for p in self.pages)
        for part in ("RINGKASAN", "SEBARAN OUTLET", "VISKOSITAS", "AVAILABILITY & VISIBILITY", "WHITESPACE", "REKOMENDASI"):
            self.assertIn(part, kickers)

    def test_fallback_narrative_is_grounded(self):
        narr, dropped = pr.clean_narrative(pr.fallback_narrative(self.ds), pdm.dataset_numbers(self.ds))
        self.assertEqual(dropped, 0)
        self.assertTrue(narr["rekomendasi"])
        self.assertTrue({r["owner"] for r in narr["rekomendasi"]} <= set(pr.OWNERS))

    def test_ungrounded_narrative_dropped(self):
        raw = pr.fallback_narrative(self.ds)
        raw["ringkasan"].append({"label": "X", "judul": "ND naik ke 97,3%", "isi": "angka karangan", "nada": "info"})
        narr, dropped = pr.clean_narrative(raw, pdm.dataset_numbers(self.ds))
        self.assertEqual(dropped, 1)

    def test_no_market_share_wording(self):
        html = ptpl_design.render_html(self.pages, "Uji").decode()
        self.assertNotIn("market share</", html.lower())
        self.assertIn("bukan market share", html)

    def test_html_uses_design_system(self):
        html = ptpl_design.render_html(self.pages, "Uji").decode()
        self.assertIn("PTPL Design System helper - JANGAN DIUBAH", html)
        self.assertEqual(html.count('<section class="page">'), 6)
        self.assertNotIn("ISI_LAPORAN_HTML", html)
        self.assertIn("data-chart=", html)

    def test_pdf_and_pptx(self):
        from pptx import Presentation

        pdf = ptpl_design.render_pdf(self.pages, "Uji")
        self.assertTrue(pdf.startswith(b"%PDF"))
        prs = Presentation(io.BytesIO(ptpl_design.render_pptx(self.pages, "Uji")))
        self.assertEqual(len(prs.slides), 6)

    def test_no_comparison_period(self):
        prep, _ = de.prepare(sample_planogram.rows(), "planogram")
        pa = pdm.parse_period("2026-Q3")
        ds = pdm.build_dataset(pdm.to_rows(prep, pa, None), pa, None)
        pages = pr.build_pages(ds, pr.fallback_narrative(ds))
        self.assertEqual(len(pages), 6)
        self.assertIn(b"n/a", ptpl_design.render_html(pages, "x"))


if __name__ == "__main__":
    unittest.main()
