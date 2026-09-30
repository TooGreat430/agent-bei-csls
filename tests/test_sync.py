"""Uji sinkronisasi folder <-> katalog (tanpa GCP)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import ingest, sync  # noqa: E402

SRC = "gs://ptpl-ge-bucket/ge-docs-datastore/"


def f(name, gen="1", h=None, mb=1.0):
    return {"source_uri": SRC + name, "file_name": name, "size_bytes": int(mb * 1_048_576),
            "generation": gen, "content_hash": h or f"h-{name}"}


def rec(name, gen="1", h=None):
    return {"doc_key": f"d-{name}", "source_uri": SRC + name, "file_name": name,
            "source_generation": gen, "content_hash": h or f"h-{name}"}


class PlanSyncTest(unittest.TestCase):
    def test_all_cases(self):
        files = [
            f("baru.pdf"),
            f("tetap.pdf"),
            f("diganti.pdf", gen="2"),
            f("tabel.xlsx"),
            f("besar.pdf", mb=150),
            f("kembar_folder.pdf", h="h-tetap.pdf"),
            f("dua_a.pdf", h="sama"), f("dua_b.pdf", h="sama"),
            f("sedang_upload.pdf"),
        ]
        records = [rec("tetap.pdf"), rec("diganti.pdf", gen="1"), rec("hilang.pdf"),
                   rec("sedang_upload.pdf", gen=None)]
        plan = sync.plan_sync(files, records, max_mb=100)
        self.assertEqual([x["file_name"] for x in plan["new"]], ["baru.pdf", "dua_a.pdf"])
        self.assertEqual([c["file"]["file_name"] for c in plan["changed"]], ["diganti.pdf"])
        self.assertEqual([r["file_name"] for r in plan["removed"]], ["hilang.pdf"])
        reasons = {s["file_name"]: s["reason"] for s in plan["skipped"]}
        self.assertIn("tidak didukung", reasons["tabel.xlsx"])
        self.assertIn("melebihi", reasons["besar.pdf"])
        self.assertIn("tetap.pdf", reasons["kembar_folder.pdf"])
        self.assertIn("dua_a.pdf", reasons["dua_b.pdf"])
        self.assertNotIn("sedang_upload.pdf", reasons)

    def test_reserved_upload_not_removed_before_file_exists(self):
        plan = sync.plan_sync([], [rec("sedang_upload.pdf", gen=None)], max_mb=100)
        self.assertEqual(plan["removed"], [])

    def test_in_sync(self):
        plan = sync.plan_sync([f("a.pdf")], [rec("a.pdf")], max_mb=100)
        self.assertEqual((plan["new"], plan["changed"], plan["removed"], plan["skipped"]), ([], [], [], []))

    def test_order_new_for_versioning(self):
        items = [{"meta": {"title": "Studi", "doc_type": "BEI", "doc_date": "2026-05-01", "version": "2"}},
                 {"meta": {"title": "studi", "doc_type": "BEI", "doc_date": "2026-01-01", "version": "1"}}]
        self.assertEqual([i["meta"]["version"] for i in sync.order_new(items)], ["1", "2"])


class IngestHelperTest(unittest.TestCase):
    def test_unique_name(self):
        self.assertEqual(ingest.unique_name(set(), "laporan.pdf"), "laporan.pdf")
        self.assertEqual(ingest.unique_name({"laporan.pdf"}, "laporan.pdf"), "laporan-2.pdf")
        self.assertEqual(ingest.unique_name({"laporan.pdf", "laporan-2.pdf"}, "laporan.pdf"), "laporan-3.pdf")
        self.assertEqual(ingest.unique_name({"catatan"}, "catatan"), "catatan-2")

    def test_md5_matches_gcs_format(self):
        self.assertEqual(ingest.md5_b64(b"hello"), "XUFAKrxLKna5cZ2REBfFkg==")

    def test_mime(self):
        self.assertEqual(sync.mime_for("A.PDF"), "application/pdf")
        self.assertIsNone(sync.mime_for("tabel.xlsx"))
        self.assertIsNone(sync.mime_for("tanpa_ekstensi"))


if __name__ == "__main__":
    unittest.main()
