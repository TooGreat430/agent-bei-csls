"""Uji penguncian versi requirements saat deploy (insiden 22 Nov: beda versi ADK .venv vs Agent Engine)."""
import os
import sys
import unittest
from importlib import metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from pin_requirements import pin_requirements  # noqa: E402

VERSIONS = {"google-adk": "1.18.0", "google-cloud-aiplatform": "1.120.0", "anthropic": "0.70.0", "pypdf": "5.1.0"}


def fake_version(name):
    if name not in VERSIONS:
        raise metadata.PackageNotFoundError(name)
    return VERSIONS[name]


class PinTest(unittest.TestCase):
    def test_pins_installed_versions_keeps_extras(self):
        lines = ["google-adk>=1.10.0", "google-cloud-aiplatform[agent_engines,adk]>=1.110.0", "",
                 "# komentar", "anthropic[vertex]>=0.40", "pypdf>=4.0  # baca PDF"]
        pinned, missing = pin_requirements(lines, fake_version)
        self.assertEqual(pinned, ["google-adk==1.18.0", "google-cloud-aiplatform[agent_engines,adk]==1.120.0",
                                  "anthropic[vertex]==0.70.0", "pypdf==5.1.0"])
        self.assertEqual(missing, [])

    def test_missing_package_left_as_is(self):
        pinned, missing = pin_requirements(["xlrd>=2.0"], fake_version)
        self.assertEqual(pinned, ["xlrd>=2.0"])
        self.assertEqual(missing, ["xlrd"])

    def test_real_requirements_all_parse(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        pinned, _ = pin_requirements(lines, lambda n: "9.9.9")
        self.assertTrue(pinned)
        self.assertTrue(all(p.endswith("==9.9.9") for p in pinned), pinned)
        self.assertIn("google-adk==9.9.9", pinned)


if __name__ == "__main__":
    unittest.main()
