"""Uji pengaturan yang bisa diubah lewat settings.json di bucket (tanpa GCP)."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import config  # noqa: E402


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self):
        config._runtime_cache.update(loaded_at=0.0, data={})

    def test_override_from_bucket_file(self):
        data = {"allowed_doc_types": ["bei", "csls", "Audit"], "max_active_docs": "7",
                "company_name": "PT Pertamina Lubricants"}
        with mock.patch.object(config, "_read_runtime_file", return_value=data):
            self.assertEqual(config.live("allowed_doc_types"), ("BEI", "CSLS", "AUDIT"))
            self.assertEqual(config.live("max_active_docs"), 7)
            self.assertEqual(config.live("company_name"), "PT Pertamina Lubricants")

    def test_missing_or_invalid_values_fall_back_to_env(self):
        with mock.patch.object(config, "_read_runtime_file", return_value={"max_active_docs": "sepuluh"}):
            self.assertEqual(config.live("max_active_docs"), config.settings.max_active_docs)
            self.assertEqual(config.live("allowed_doc_types"), config.settings.allowed_doc_types)

    def test_file_is_cached(self):
        with mock.patch.object(config, "_read_runtime_file", return_value={}) as reader:
            config.live("company_name")
            config.live("max_file_mb")
            self.assertEqual(reader.call_count, 1)

    def test_comma_string_for_doc_types(self):
        self.assertEqual(config.coerce("allowed_doc_types", "BEI, CSLS"), ("BEI", "CSLS"))

    def test_config_path_next_to_catalog_folder(self):
        os.environ.pop("LIB_RUNTIME_CONFIG_PATH", None)
        with mock.patch.object(config, "settings", mock.Mock(catalog_path="ge-docs-agent/catalog/index.json")):
            self.assertEqual(config.runtime_config_path(), "ge-docs-agent/config/settings.json")


if __name__ == "__main__":
    unittest.main()
