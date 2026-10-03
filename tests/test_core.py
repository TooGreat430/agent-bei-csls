"""Uji unit tanpa Google Cloud. Jalankan: python -m unittest discover tests"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["LIB_TEMPLATE_SOURCE"] = "local"

sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import report_engine, search  # noqa: E402
from library_agent.ingest import parse_gcs_uri, safe_filename  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sample_content.json")

try:
    import jsonschema  # noqa: F401
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class FilterTest(unittest.TestCase):
    def test_filter_lists_only_active_docs(self):
        self.assertEqual(search.build_doc_filter(["doc-a", "doc-b"]), 'doc_key: ANY("doc-a", "doc-b")')

    def test_filter_rejects_empty(self):
        with self.assertRaises(ValueError):
            search.build_doc_filter([])

    def test_filter_rejects_injection(self):
        with self.assertRaises(ValueError):
            search.build_doc_filter(['doc-a") OR doc_key: ANY("x'])

    def test_citation_label(self):
        self.assertEqual(search.citation_label("Studi CSLS", "2", 12), "[Studi CSLS, v2, hal. 12]")
        self.assertEqual(search.citation_label("Studi CSLS", "v3", None), "[Studi CSLS, v3]")

    def test_doc_id_from_chunk_name(self):
        name = "projects/p/locations/global/collections/default_collection/dataStores/d/branches/0/documents/doc-123/chunks/c1"
        self.assertEqual(search._doc_id_from_chunk_name(name), "doc-123")


class DatastoreSchemaTest(unittest.TestCase):
    def test_datastore_schema_rules(self):
        with open(os.path.join(ROOT, "setup", "datastore_schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        for name, prop in schema["properties"].items():
            if "keyPropertyMapping" in prop:
                self.assertNotIn("searchable", prop, name)
                self.assertNotIn("indexable", prop, name)
        self.assertTrue(schema["properties"]["doc_key"]["indexable"])  # dipakai untuk filter dokumen aktif


class IngestHelperTest(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(safe_filename("Laporan BEI (final).pdf", "application/pdf"), "Laporan_BEI_final_.pdf")
        self.assertTrue(safe_filename("tanpa ekstensi", "application/pdf").endswith(".pdf"))

    def test_parse_gcs_uri(self):
        self.assertEqual(parse_gcs_uri("gs://b/a/c.pdf"), ("b", "a/c.pdf"))


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.template = report_engine.load_template("laporan_studi")
        with open(FIXTURE, encoding="utf-8") as fh:
            self.content = json.load(fh)

    def test_template_listed(self):
        ids = [t["template_id"] for t in report_engine.list_templates()]
        self.assertIn("laporan_studi", ids)

    def test_render_contains_content_and_citations(self):
        meta = report_engine.build_meta(self.template, "user@klien.co.id", "Laporan Uji")
        html = report_engine.render_html(self.template, self.content, meta)
        self.assertIn("Laporan Uji", html)
        self.assertIn("Ketersediaan produk membaik", html)
        self.assertIn("[Studi CSLS 2026, v2, hal. 8]", html)
        self.assertIn("prio-Tinggi", html)

    def test_render_escapes_html(self):
        content = dict(self.content, keterbatasan="<script>alert(1)</script>")
        meta = report_engine.build_meta(self.template, "u", "t")
        html = report_engine.render_html(self.template, content, meta)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_model_schema_strips_meta_keys(self):
        cleaned = report_engine.schema_for_model(self.template.schema)
        self.assertNotIn("$schema", cleaned)
        self.assertIn("$schema", self.template.schema)

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema belum terpasang")
    def test_sample_content_valid(self):
        self.assertEqual(report_engine.validate_content(self.content, self.template.schema), [])

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema belum terpasang")
    def test_invalid_priority_rejected(self):
        bad = json.loads(json.dumps(self.content))
        bad["rekomendasi"][0]["prioritas"] = "Mendesak"
        self.assertTrue(report_engine.validate_content(bad, self.template.schema))


if __name__ == "__main__":
    unittest.main()
