"""Uji katalog & insight di atas GCS palsu (tanpa GCP), termasuk konflik tulis."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from google.api_core.exceptions import NotFound, PreconditionFailed  # noqa: E402

from library_agent import catalog, insights, store  # noqa: E402


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name, self.generation = bucket, name, None

    def reload(self):
        if self.name not in self.bucket.files:
            raise NotFound("x")
        self.generation = self.bucket.files[self.name][1]

    def download_as_bytes(self, if_generation_match=None):
        if self.name not in self.bucket.files:
            raise NotFound("x")
        data, gen = self.bucket.files[self.name]
        if if_generation_match is not None and gen != if_generation_match:
            raise PreconditionFailed("x")
        return data

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        current = self.bucket.files.get(self.name, (None, 0))[1]
        if if_generation_match is not None and current != if_generation_match:
            raise PreconditionFailed("x")
        if self.bucket.interfere_once:  # simulasikan user lain menulis di antaranya
            self.bucket.interfere_once = False
            self.bucket.files[self.name] = (self.bucket.files.get(self.name, (b'{"documents": {}}', 0))[0], current + 1)
            raise PreconditionFailed("x")
        payload = data.encode() if isinstance(data, str) else data
        self.bucket.files[self.name] = (payload, current + 1)


class FakeBucket:
    def __init__(self):
        self.files, self.interfere_once = {}, False

    def blob(self, name):
        return FakeBlob(self, name)


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.bucket = FakeBucket()
        client = mock.Mock()
        client.bucket.return_value = self.bucket
        self.patch = mock.patch.object(store, "storage_client", return_value=client)
        self.patch.start()
        mock.patch.object(store.time, "sleep", lambda s: None).start()

    def tearDown(self):
        mock.patch.stopall()

    def _add(self, title, version, previous=None, content_hash=None):
        key = catalog.new_doc_key()
        catalog.create_version(
            doc_key=key, family_id=previous or key, title=title, doc_type="csls", version=version,
            doc_date="2026-09-01", uploader="a@klien.co.id", gcs_uri=f"gs://b/{key}.pdf",
            mime_type="application/pdf", content_hash=content_hash or key, import_operation="op",
            previous_doc_key=previous,
        )
        return key

    def test_catalog_versioning(self):
        v1 = self._add("Studi CSLS 2026", "1")
        v2 = self._add("Studi  csls 2026", "2", previous=v1)
        latest = catalog.find_latest_by_title("studi CSLS 2026", "CSLS")
        self.assertEqual(latest["doc_key"], v2)
        self.assertEqual(len(catalog.list_documents()), 1)
        self.assertEqual(len(catalog.list_documents(include_old_versions=True)), 2)
        self.assertFalse(catalog.get(v1)["is_latest"])

    def test_catalog_hash_and_status(self):
        key = self._add("Laporan BEI", "1", content_hash="abc")
        self.assertEqual(catalog.find_by_hash("abc")["doc_key"], key)
        catalog.update_status(key, "ready")
        self.assertEqual(catalog.get(key)["status"], "ready")

    def test_write_conflict_is_retried(self):
        self._add("Dok A", "1")
        self.bucket.interfere_once = True
        self._add("Dok B", "1")
        titles = {d["title"] for d in catalog.list_documents()}
        self.assertIn("Dok B", titles)

    def test_insights_are_per_user(self):
        item = insights.save("a@klien.co.id", "BEI 2026", "Temuan", "Isi", ["[Dok, v1, hal. 2]"], ["doc-1"])
        self.assertEqual(len(insights.list_for("a@klien.co.id", "BEI 2026")), 1)
        self.assertEqual(insights.list_for("b@klien.co.id", "BEI 2026"), [])
        self.assertEqual(insights.get_many("b@klien.co.id", [item["insight_id"]]), [])
        updated = insights.update("a@klien.co.id", item["insight_id"], None, "Isi baru")
        self.assertEqual(updated["content"], "Isi baru")
        self.assertTrue(insights.delete("a@klien.co.id", item["insight_id"]))
        self.assertFalse(insights.delete("a@klien.co.id", item["insight_id"]))


if __name__ == "__main__":
    unittest.main()
