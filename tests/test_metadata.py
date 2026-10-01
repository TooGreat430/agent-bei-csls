"""Uji logika metadata otomatis (tanpa memanggil Gemini)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import metadata  # noqa: E402

TYPES = ("BEI", "CSLS")


class FinalizeTest(unittest.TestCase):
    def test_all_confident_needs_no_question(self):
        raw = {"title": "Studi CSLS 2026", "title_confident": True, "doc_type": "CSLS",
               "doc_type_confident": True, "version": "Versi 2", "doc_date": "2026-08-15", "summary": "x"}
        out = metadata.finalize(raw, "file.pdf", TYPES, today="2026-09-29")
        self.assertEqual(out["uncertain_fields"], [])
        self.assertEqual(out["metadata"], {"title": "Studi CSLS 2026", "doc_type": "CSLS",
                                           "version": "2", "doc_date": "2026-08-15"})

    def test_missing_version_and_date_use_defaults_not_questions(self):
        raw = {"title": "Laporan BEI", "title_confident": True, "doc_type": "BEI",
               "doc_type_confident": True, "version": "", "doc_date": "", "summary": ""}
        out = metadata.finalize(raw, "f.pdf", TYPES, today="2026-09-29")
        self.assertEqual(out["uncertain_fields"], [])
        self.assertEqual(out["defaults_used"], ["version", "doc_date"])
        self.assertEqual(out["metadata"]["version"], "1")
        self.assertEqual(out["metadata"]["doc_date"], "2026-09-29")

    def test_unsure_type_is_asked(self):
        raw = {"title": "Ringkasan Survei", "title_confident": True, "doc_type": "TIDAK_YAKIN",
               "doc_type_confident": False, "version": "1", "doc_date": "2026", "summary": ""}
        out = metadata.finalize(raw, "f.pdf", TYPES)
        self.assertEqual(out["uncertain_fields"], ["doc_type"])
        self.assertEqual(out["metadata"]["doc_type"], "")
        self.assertEqual(out["metadata"]["doc_date"], "2026")

    def test_missing_title_falls_back_to_filename(self):
        raw = {"title": "", "title_confident": False, "doc_type": "BEI", "doc_type_confident": True,
               "version": "", "doc_date": "15 Agustus 2026", "summary": ""}
        out = metadata.finalize(raw, "Laporan_BEI_Q3.pdf", TYPES, today="2026-09-29")
        self.assertIn("title", out["uncertain_fields"])
        self.assertEqual(out["metadata"]["title"], "Laporan BEI Q3")
        self.assertIn("doc_date", out["defaults_used"])

    def test_confirm_without_corrections_keeps_extraction(self):
        suggested = {"title": "Studi CSLS 2026", "doc_type": "CSLS", "version": "2", "doc_date": "2026-08-15"}
        final, missing = metadata.apply_corrections(suggested, {}, TYPES)
        self.assertEqual(final, suggested)
        self.assertEqual(missing, [])

    def test_only_corrected_fields_change(self):
        suggested = {"title": "Studi CSLS 2026", "doc_type": "CSLS", "version": "1", "doc_date": "2026-09-29"}
        final, missing = metadata.apply_corrections(suggested, {"version": "3", "title": ""}, TYPES)
        self.assertEqual(final["version"], "3")
        self.assertEqual(final["title"], "Studi CSLS 2026")
        self.assertEqual(missing, [])

    def test_unfilled_or_invalid_fields_reported(self):
        suggested = {"title": "Ringkasan", "doc_type": "", "version": "1", "doc_date": "2026-09-29"}
        _, missing = metadata.apply_corrections(suggested, {}, TYPES)
        self.assertEqual(missing, ["doc_type"])
        _, missing = metadata.apply_corrections(suggested, {"doc_type": "lain", "doc_date": "kemarin"}, TYPES)
        self.assertEqual(missing, ["doc_date", "doc_type"])
        final, missing = metadata.apply_corrections(suggested, {"doc_type": "bei"}, TYPES)
        self.assertEqual((final["doc_type"], missing), ("BEI", []))

    def test_clean_version_prefixes(self):
        cases = {"Version 1": "1", "Versi 2": "2", "v3": "3", "Ver. 4": "4", "V 5": "5",
                 "Rev 2": "2", "2026-Q1": "2026-Q1", "1.2": "1.2", "Vol 2": "Vol 2"}
        for raw, expected in cases.items():
            self.assertEqual(metadata.clean_version(raw), expected, raw)

    def test_finalize_version_one(self):
        raw = {"title": "Studi", "title_confident": True, "doc_type": "BEI", "doc_type_confident": True,
               "version": "Version 1", "doc_date": "2026-06", "summary": ""}
        self.assertEqual(metadata.finalize(raw, "f.pdf", TYPES)["metadata"]["version"], "1")

    def test_next_version(self):
        self.assertEqual(metadata.next_version("2"), "3")
        self.assertEqual(metadata.next_version("1.4"), "1.5")
        self.assertEqual(metadata.next_version("2026-Q1"), "2026-Q2")
        self.assertEqual(metadata.next_version("final"), "final-rev")


if __name__ == "__main__":
    unittest.main()
