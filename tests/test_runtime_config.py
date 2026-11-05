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
        data = {"industry_competitors": ["shell", "Castrol"], "planogram_min_carry": "25",
                "company_name": "PT Pertamina Lubricants", "planogram_default_period": "2026-Q4"}
        with mock.patch.object(config, "_read_runtime_file", return_value=data):
            self.assertEqual(config.live("industry_competitors"), ("SHELL", "CASTROL"))
            self.assertEqual(config.live("planogram_min_carry"), 25)
            self.assertEqual(config.live("company_name"), "PT Pertamina Lubricants")
            self.assertEqual(config.live("planogram_default_period"), "2026-Q4")

    def test_missing_or_invalid_values_fall_back_to_env(self):
        with mock.patch.object(config, "_read_runtime_file", return_value={"planogram_min_carry": "tiga puluh"}):
            self.assertEqual(config.live("planogram_min_carry"), config.settings.planogram_min_carry)
            self.assertEqual(config.live("planogram_table"), config.settings.planogram_table)

    def test_file_is_cached(self):
        with mock.patch.object(config, "_read_runtime_file", return_value={}) as reader:
            config.live("company_name")
            config.live("max_file_mb")
            self.assertEqual(reader.call_count, 1)

    def test_comma_string_for_competitors(self):
        self.assertEqual(config.coerce("industry_competitors", "shell, castrol"), ("SHELL", "CASTROL"))

    def test_config_path_in_internal_folder(self):
        os.environ.pop("LIB_RUNTIME_CONFIG_PATH", None)
        os.environ.pop("LIB_INTERNAL_FOLDER", None)
        self.assertEqual(config.runtime_config_path(), "ge-docs-agent/config/settings.json")

    def test_library_settings_removed(self):
        for name in ("allowed_doc_types", "max_active_docs", "source_folder", "doc_type_hints"):
            self.assertNotIn(name, config.RUNTIME_KEYS)
            self.assertFalse(hasattr(config.settings, name))

    def test_model_locations(self):
        from library_agent import clients

        self.assertEqual(config.settings.model_pro, "gemini-4-argon")
        self.assertEqual(clients.location_for(config.settings.model_pro), config.settings.gemini_location_pro)
        self.assertEqual(clients.location_for(config.settings.model_fast), config.settings.gemini_location)


class AgentNameTest(unittest.TestCase):
    def setUp(self):
        config._runtime_cache.update(loaded_at=0.0, data={})

    def test_instruction_uses_live_name(self):
        from library_agent import prompts

        provider = prompts.with_agent_name(prompts.ROOT_INSTRUCTION)
        with mock.patch.object(config, "_read_runtime_file", return_value={}):
            text = provider(None)
        self.assertIn("Marketing Insight Assistant", text)
        self.assertNotIn("__AGENT_NAME__", text)
        self.assertNotIn("Document Insight Agent", text)
        config._runtime_cache.update(loaded_at=0.0, data={})
        with mock.patch.object(config, "_read_runtime_file", return_value={"agent_name": "Asisten Marketing PTPL"}):
            self.assertIn("Asisten Marketing PTPL", provider(None))

    def test_all_instructions_have_no_leftover_old_name(self):
        from library_agent import prompts

        for const in ("ROOT_INSTRUCTION", "DATA_INSTRUCTION", "REPORT_INSTRUCTION", "FILE_INSTRUCTION"):
            self.assertNotIn("Document Insight Agent", getattr(prompts, const))


if __name__ == "__main__":
    unittest.main()


class SettingsReferenceTest(unittest.TestCase):
    """Regresi: setiap settings.<nama> yang dipakai kode harus ada (bug 'report_prefix' tidak boleh terulang)."""

    def test_all_settings_attributes_exist(self):
        import glob
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        missing = set()
        for f in glob.glob(os.path.join(root, "library_agent", "**", "*.py"), recursive=True):
            for name in re.findall(r"\bsettings\.([a-z_]+)\b", open(f, encoding="utf-8").read()):
                if name != "json" and not hasattr(config.settings, name):
                    missing.add(f"{os.path.basename(f)}: settings.{name}")
        self.assertEqual(sorted(missing), [])

    def test_live_keys_registered(self):
        import glob
        import re

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        keys = set()
        for f in glob.glob(os.path.join(root, "library_agent", "**", "*.py"), recursive=True):
            keys.update(re.findall(r'live\("([a-z_]+)"\)', open(f, encoding="utf-8").read()))
        self.assertEqual(sorted(k for k in keys if k not in config.RUNTIME_KEYS), [])
