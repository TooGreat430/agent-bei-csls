"""Uji jawaban cadangan: agent berhenti tanpa jawaban akhir (mis. setelah pemeriksa angka meminta revisi)."""
import os
import sys
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import callbacks  # noqa: E402


def ev(author, **part):
    return NS(author=author, content=NS(parts=[NS(text=part.get("text"), thought=False,
                                                  function_response=part.get("fr"))]))


def fr(name, response):
    return NS(name=name, response=response)


SCREENSHOT_FLOW = [
    ev("user", text="Berapa gap harga jual PTPL vs kompetitor per SR untuk Product Hero di Q3 2026?"),
    ev("data_agent", text="Baik, saya tarik datanya dulu."),                                  # kalimat pembuka
    ev("data_agent", fr=fr("ask_retail_intelligence", {"status": "ok", "answer": "Gap HJ Product Hero Q3 2026 per SR: ...",
                                                       "tables": []})),
    ev("data_agent", fr=fr("create_chart", {"status": "ok", "link": "https://x/old.png"})),
    ev("data_agent", fr=fr("daftar_data", {"status": "ok", "data": []})),
    ev("data_agent", fr=fr("buat_insight", {"status": "ok", "chart": [
        {"status": "ok", "judul": "Gap harga didominasi negatif", "fakta": ["Tertinggi FASTRON: 1.158 IDR/L"],
         "link": "https://x/1.png"},
        {"status": "ok", "judul": "Peta: SR1 × ENDURO -38.056", "fakta": ["1 sel ekstrem"], "link": "https://x/2.png",
         "otomatis": True},
        {"status": "error", "judul": "x", "message": "kolom salah"}]})),
    ev("data_agent", fr=fr("save_data_insight", {"status": "ok", "insight_id": "i1"})),
    ev("data_agent", fr=fr("periksa_angka", {"status": "perlu_revisi", "message": "Angka berikut tidak ada di hasil tool"})),
]


class FallbackTest(unittest.TestCase):
    def test_screenshot_flow_gets_useful_answer(self):
        text = callbacks.fallback_reply(SCREENSHOT_FLOW, "data_agent")
        self.assertIn("Gap HJ Product Hero Q3 2026 per SR", text)
        self.assertIn("Gap harga didominasi negatif", text)
        self.assertIn("https://x/2.png", text)
        self.assertNotIn("perlu_revisi", text)
        self.assertNotIn("Angka berikut tidak ada", text)
        self.assertNotIn("kolom salah", text)

    def test_final_answer_present_no_fallback(self):
        flow = SCREENSHOT_FLOW + [ev("data_agent", text="Kesimpulan: PTPL lebih murah di 5 dari 7 SR ...")]
        self.assertEqual(callbacks.fallback_reply(flow, "data_agent"), "")

    def test_report_files_listed(self):
        flow = [ev("user", text="buat laporan"),
                ev("report_agent", fr=fr("generate_custom_report", {"status": "ok", "file": {"pdf": "https://x/r.pdf"}}))]
        self.assertIn("PDF: https://x/r.pdf", callbacks.fallback_reply(flow, "report_agent"))


if __name__ == "__main__":
    unittest.main()


class RoundingTest(unittest.TestCase):
    def test_reasonable_rounding_accepted_fabrication_rejected(self):
        from library_agent.price_dashboard import ungrounded_numbers

        pool = [91571.0, 5985.0, 65128.73]
        self.assertEqual(ungrounded_numbers("Castrol sekitar Rp 91.000/L", pool), [])       # dipotong ke ribuan
        self.assertEqual(ungrounded_numbers("selisih sekitar Rp 6.000/L", pool), [])         # dibulatkan
        self.assertEqual(ungrounded_numbers("Mesrania Rp 65.129/L", pool), [])
        self.assertTrue(ungrounded_numbers("Shell Rp 97.389/L", pool))                      # angka karangan tetap ditolak
        self.assertTrue(ungrounded_numbers("harga Rp 80.000", pool))                        # bulat tapi jauh dari data

    def test_image_note_forbids_copying(self):
        from library_agent import custom_report as cr

        self.assertIn("DILARANG menyalin angka apa pun dari gambar", cr.IMAGE_NOTE)
