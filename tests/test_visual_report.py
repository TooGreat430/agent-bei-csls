"""Uji mesin laporan visual (v3.7 Tahap A): semua komponen, 3 format, jaring pengaman, kelengkapan angka."""
import io
import os
import sys
import unittest
import zipfile
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

ALL_KINDS = {
    "slides": [
        {"komponen": "ringkasan", "judul": "Pertamina memimpin di 4W tetapi kalah di titik beli",
         "kolom": [{"nama": "Fastron", "sub": "4W", "baris": [{"label": "Posisi", "teks": "BEI 21.0"}]},
                   {"nama": "Enduro", "sub": "2W", "baris": [{"label": "Posisi", "teks": "BEI 7.4"}]}],
         "benang_merah": "pengaruh mekanik naik 22 poin"},
        {"komponen": "kartu", "judul": "BEI Fastron turun 1.7", "kartu": [{"angka": 21.0, "label": "BEI"},
                                                                           {"angka": "−1.98", "label": "ME", "tone": "neg"}]},
        {"komponen": "papan_skor", "judul": "Fastron unggul 6.7 poin", "kategori": ["Fastron", "TMO"],
         "nilai": [21.0, 14.3], "sorot": ["Fastron"]},
        {"komponen": "perbandingan", "judul": "Mekanik naik 26 poin", "panel": [
            {"judul_panel": "4W", "kategori": ["Fastron", "TMO"], "seri": [{"nama": "Q2", "nilai": [30, 53]},
                                                                         {"nama": "Q3", "nilai": [56, 67]}]}]},
        {"komponen": "tren", "judul": "Volume naik 12% sejak Januari", "kategori": ["Jan", "Feb", "Mar"],
         "seri": [{"nama": "Volume", "nilai": [100, 105, 112]}]},
        {"komponen": "waterfall", "judul": "Market Effect memangkas equity", "langkah": [
            {"label": "Desire", "nilai": 23.8, "total": True}, {"label": "ME", "nilai": -1.98},
            {"label": "Equity", "nilai": 21.8, "total": True}]},
        {"komponen": "funnel", "judul": "Fastron bocor di consider", "tahap": ["Aware", "Consider", "BUMO"],
         "seri": [{"nama": "Fastron", "nilai": [92, 36, 21], "delta": [0, -1, -1]}, {"nama": "TMO", "nilai": [61, 26, 23]}],
         "satuan": "%"},
        {"komponen": "heatmap", "judul": "Kecocokan kendaraan jadi hambatan utama", "kolom": ["Cocok", "Mekanik"],
         "baris": [{"label": "Fastron", "nilai": [35, 28]}, {"label": "Meditran", "nilai": [51, 39]}], "satuan": "%"},
        {"komponen": "tabel", "judul": "Rincian harga per liter naik 3%", "kolom": ["Produk", "Harga"],
         "baris": [["Fastron", 91571], ["Shell", 97389]]},
        {"komponen": "pemisah", "nomor": "02", "judul": "Arah 2027"},
        {"komponen": "swot", "judul": "Fastron unggul di ekuitas namun lemah di titik beli",
         "kuadran": {"S": ["BEI 21.0"], "W": ["ME −1.98"], "O": ["irit BBM"], "T": ["TMO naik"]}},
        {"komponen": "smart", "judul": "Visi SMART menjadi terukur hingga Q4 2027", "kolom": ["Fastron"],
         "baris": {"S": ["Pemimpin 4W"], "M": ["BEI ≥ 24.0"]}},
        {"komponen": "target_kpi", "judul": "BEI perlu naik ke 24.0", "kolom": ["KPI", "Q3", "Target"],
         "baris": [["BEI", "21.0", "≥ 24.0"]], "poin": ["Zero OOS"]},
        {"komponen": "roadmap", "judul": "Roadmap 2027 dimulai dari stok", "tahap": [
            {"waktu": "Q1", "item": ["Audit stok"]}, {"waktu": "Q2", "item": ["Sertifikasi"]}]},
        {"komponen": "aksi", "judul": "Tiga aksi prioritas perlu dimulai Q1", "baris": [
            {"aksi": "Realokasi anggaran", "pemilik": "Brand", "waktu": "Q1", "kpi": "ME > 0"}]},
        {"komponen": "benang_merah", "judul": "Mekanik menjadi penentu", "teks": "Mekanik menentukan pilihan",
         "poin": [{"angka": "+26", "teks": "Fastron"}]},
        {"komponen": "poin", "judul": "Tiga temuan utama naik signifikan", "poin": ["a", "b"],
         "chart": {"kategori": ["A", "B"], "nilai": [1, 2]}},
    ]
}


@unittest.skipUnless(HAVE_LIBS, "butuh python-pptx, reportlab, matplotlib")
class ComponentsTest(unittest.TestCase):
    def test_all_components_three_formats(self):
        from library_agent.visual_report import render_report

        out = render_report(ALL_KINDS)
        self.assertEqual(set(out["files"]), {"pptx", "pdf", "html"})
        self.assertFalse([m for m in out["masalah"] if "gagal" in m], out["masalah"])
        self.assertEqual(out["stats"]["slide_tanpa_visual"], [])
        self.assertGreaterEqual(out["stats"]["chart"], 5)
        prs = __import__("pptx").Presentation(io.BytesIO(out["files"]["pptx"]))
        self.assertEqual(len(prs.slides), out["stats"]["slide"])
        native = sum(1 for s in prs.slides for sh in s.shapes if sh.has_chart)
        self.assertEqual(native, out["stats"]["chart"])               # chart PPTX = chart native, bukan gambar
        self.assertTrue(out["files"]["pdf"].startswith(b"%PDF"))
        self.assertIn(b"<section class=\"slide\"", out["files"]["html"])

    def test_number_labels_formatted_in_pptx(self):
        from library_agent.visual_report import render_report

        spec = {"format_angka": "id", "slides": [{"komponen": "papan_skor", "judul": "Harga naik 2%",
                                                   "kategori": ["A", "B"], "nilai": [1234.5, 99.25]}]}
        data = render_report(spec, ("pptx",))["files"]["pptx"]
        xml = b"".join(zipfile.ZipFile(io.BytesIO(data)).read(n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist()
                       if n.startswith("ppt/charts/chart"))
        self.assertIn("1.234,50".encode(), xml)                         # format Indonesia di label chart


@unittest.skipUnless(HAVE_LIBS, "butuh python-pptx, reportlab, matplotlib")
class SafetyNetTest(unittest.TestCase):
    def test_broken_component_keeps_all_numbers(self):
        from library_agent.visual_report import render_report

        spec = {"slides": [{"komponen": "waterfall", "judul": "Waterfall rusak namun angka tetap ada",
                            "langkah": "rusak", "nilai_kunci": [77.7, 33.3], "catatan": "n"}]}
        out = render_report(spec, angka_wajib=[77.7, 33.3])
        self.assertEqual(set(out["files"]), {"pptx", "pdf", "html"})
        self.assertTrue(any("gagal" in m for m in out["masalah"]))
        self.assertEqual(out["angka_hilang"], [])                       # isi tidak hilang walau komponen gagal

    def test_unknown_component_and_garbage(self):
        from library_agent.visual_report import render_report

        out = render_report({"slides": [{"komponen": "hologram", "judul": "X", "isi": "angka 42"}, "teks", None, 5]})
        self.assertEqual(set(out["files"]), {"pptx", "pdf", "html"})
        self.assertEqual(out["angka_hilang"], [])
        for bad in (None, "bukan dict", [], {"slides": "x"}):
            res = render_report(bad)
            self.assertEqual(set(res["files"]), {"pptx", "pdf", "html"}, bad)

    def test_renderer_crash_falls_back(self):
        from library_agent import visual_report as vr
        from library_agent.visual_report import render_pptx

        calls = {"n": 0}
        real = render_pptx.render

        def flaky(deck):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulasi crash")
            return real(deck)
        with mock.patch.object(render_pptx, "render", flaky):
            out = vr.render_report(ALL_KINDS, ("pptx",))
        self.assertIn("pptx", out["files"])                             # deck darurat tetap terkirim
        self.assertTrue(any("render utama gagal" in m for m in out["masalah"]))

    def test_chart_element_failure_becomes_table(self):
        from library_agent.visual_report import build_deck, render_pptx
        from library_agent.visual_report.prims import Chart

        deck = build_deck({"slides": [{"komponen": "papan_skor", "judul": "Harga turun 5%", "kategori": ["A"],
                                       "nilai": [5.5]}]})

        def boom(*_a, **_k):
            raise RuntimeError("chart rusak")
        with mock.patch.dict(render_pptx.DRAW, {Chart: boom}):
            data = render_pptx.render(deck)
        prs = __import__("pptx").Presentation(io.BytesIO(data))
        self.assertTrue(any(sh.has_table for s in prs.slides for sh in s.shapes))


@unittest.skipUnless(HAVE_LIBS, "butuh python-pptx, reportlab, matplotlib")
class CompletenessTest(unittest.TestCase):
    def test_long_table_continues_not_truncated(self):
        from library_agent.visual_report import render_report

        rows = [[f"Outlet {i}", 1000 + i * 7] for i in range(60)]
        out = render_report({"slides": [{"komponen": "tabel", "judul": "60 outlet dengan volume naik", "kolom": ["Outlet", "Volume"],
                                         "baris": rows}]}, ("pdf",), angka_wajib=[r[1] for r in rows])
        self.assertEqual(out["angka_hilang"], [])
        self.assertGreater(out["stats"]["slide"], 2)
        titles = [s.title for s in out["deck"].slides]
        self.assertTrue(any(s.kind == "tabel" for s in out["deck"].slides[2:]), titles)

    def test_truncated_chart_goes_to_appendix(self):
        from library_agent.visual_report import render_report

        cats = [f"SR{i}" for i in range(30)]
        vals = [round(10 + i * 1.37, 2) for i in range(30)]
        out = render_report({"slides": [{"komponen": "papan_skor", "judul": "30 SR dengan gap naik", "kategori": cats,
                                         "nilai": vals}]}, ("html",), angka_wajib=vals)
        self.assertEqual(out["angka_hilang"], [])
        self.assertTrue(any(s.kind == "lampiran" for s in out["deck"].slides))

    def test_coverage_detects_missing_and_accepts_rounding(self):
        from library_agent.visual_report import build_deck, coverage

        deck = build_deck({"slides": [{"komponen": "poin", "judul": "Harga Rp 91.571/L naik 2,5%", "poin": ["BEI 21.0"]}]})
        self.assertEqual(coverage(deck, [91571, 2.5, 21.0]), [])
        self.assertEqual(coverage(deck, [33.3]), ["33,3"])

    def test_review_flags_topic_titles_and_missing_visuals(self):
        from library_agent.visual_report import build_deck, review

        deck = build_deck({"slides": [{"komponen": "poin", "judul": "Analisis SWOT", "poin": ["x"]}]})
        msgs = " ".join(review(deck)["masalah"])
        self.assertIn("bukan kesimpulan", msgs)
        self.assertIn("tidak ada visual", msgs)

    def test_overflow_flagged_not_hidden(self):
        from library_agent.visual_report import build_deck, review

        long = "kata " * 400
        deck = build_deck({"slides": [{"komponen": "swot", "judul": "SWOT naik", "kuadran": {"S": [long], "W": ["a"],
                                                                                          "O": ["b"], "T": ["c"]}}]})
        self.assertTrue(deck.stats()["teks_meluap"])
        self.assertTrue(any("terlalu panjang" in m for m in review(deck)["masalah"]))


class ThemeTest(unittest.TestCase):
    def test_number_parsing_and_format(self):
        from library_agent.visual_report import theme as T

        self.assertEqual(T.to_num("1.234,5"), 1234.5)
        self.assertEqual(T.to_num("−1.98"), -1.98)
        self.assertEqual(T.to_num("35%"), 35.0)
        self.assertEqual(T.to_num("1,234.5"), 1234.5)
        self.assertEqual(T.fmt(1234.5), "1.234,5")
        self.assertEqual(T.fmt(-1.98, style="en"), "−1.98")
        self.assertEqual(T.fmt(0.22, sign=True, style="en"), "+0.22")
        self.assertEqual(T.fmt(65129, unit="Rp"), "Rp 65.129")


if __name__ == "__main__":
    unittest.main()
