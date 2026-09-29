"""Uji logika impor folder (tanpa GCP)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import folder_import as fi  # noqa: E402

SRC = "gs://ptpl-ge-bucket/ge-docs-datastore/"


def f(name, sha, mb=1.0):
    return {"source_uri": SRC + name, "file_name": name, "size_bytes": int(mb * 1_048_576), "sha256": sha}


def rec(key, sha, status="ready", source=None, title="Dok", version="1", latest=True):
    return {"doc_key": key, "content_hash": sha, "status": status, "source_uri": source,
            "title": title, "title_norm": title.lower(), "doc_type": "BEI", "version": version,
            "is_latest": latest, "family_id": key}


class ClassifyTest(unittest.TestCase):
    def test_all_cases(self):
        files = [
            f("baru.pdf", "s1"),
            f("tabel.xlsx", "s2"),
            f("besar.pdf", "s3", mb=150),
            f("sudah_ada.pdf", "s4"),
            f("pernah_dihapus.pdf", "s5"),
            f("kembar.pdf", "s1"),
            f("berubah.pdf", "s6-baru"),
        ]
        records = [
            rec("d4", "s4"),
            rec("d5", "s5", status="deleted", latest=False),
            rec("d6", "s6-lama", source=SRC + "berubah.pdf", title="Studi Berubah", version="2"),
        ]
        out = {r["file_name"]: r for r in fi.classify(files, records, max_mb=100)}
        self.assertEqual(out["baru.pdf"]["plan"], "new")
        self.assertIn("tidak didukung", out["tabel.xlsx"]["note"])
        self.assertIn("melebihi", out["besar.pdf"]["note"])
        self.assertIn("Sudah ada", out["sudah_ada.pdf"]["note"])
        self.assertIn("dihapus", out["pernah_dihapus.pdf"]["note"])
        self.assertIn("sama persis", out["kembar.pdf"]["note"])
        self.assertEqual(out["berubah.pdf"]["plan"], "new_version")
        self.assertEqual(out["berubah.pdf"]["previous_doc_key"], "d6")
        self.assertEqual(sum(r["plan"] == "skip" for r in out.values()), 5)


class RowsTest(unittest.TestCase):
    def test_title_collision_notes(self):
        rows = [
            {"action": "IMPORT", "title": "Dok", "doc_type": "BEI", "note": "", "file_name": "a.pdf"},
            {"action": "IMPORT", "title": "Laporan X", "doc_type": "BEI", "note": "", "file_name": "b.pdf"},
            {"action": "IMPORT", "title": "laporan  x", "doc_type": "bei", "note": "", "file_name": "c.pdf"},
        ]
        fi.annotate_title_collisions(rows, [rec("d1", "h", title="Dok")])
        self.assertIn("versi baru", rows[0]["note"])
        self.assertEqual(rows[1]["note"], "")
        self.assertIn("b.pdf", rows[2]["note"])

    def test_validate_and_sort(self):
        ok = {"title": "A", "doc_type": "BEI", "version": "1", "doc_date": "2026-01-01"}
        self.assertEqual(fi.validate_row(ok), [])
        self.assertEqual(fi.validate_row(dict(ok, doc_type="XYZ", doc_date="")), ["doc_date", "doc_type"])
        rows = [dict(ok, doc_date="2026-05-01", version="2"), dict(ok, doc_date="2026-01-01")]
        self.assertEqual([r["doc_date"] for r in fi.sort_for_versioning(rows)], ["2026-01-01", "2026-05-01"])

    def test_csv_roundtrip_and_semicolon(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.csv")
            fi.write_csv([{"action": "IMPORT", "title": "Studi, CSLS", "doc_type": "CSLS", "version": "1",
                           "doc_date": "2026-01-01", "note": "", "file_name": "a.pdf"}], path)
            self.assertEqual(fi.read_csv(path)[0]["title"], "Studi, CSLS")
            semi = os.path.join(tmp, "s.csv")
            with open(semi, "w", encoding="utf-8-sig") as fh:
                fh.write("action;title;doc_type\nIMPORT;Laporan BEI;BEI\n")
            self.assertEqual(fi.read_csv(semi)[0]["doc_type"], "BEI")


if __name__ == "__main__":
    unittest.main()
