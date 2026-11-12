"""Uji ketahanan kapasitas model: 429 di endpoint utama -> cadangan -> pesan 'layanan padat' (tanpa error)."""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _stubs  # noqa: E402

_stubs.install()

from library_agent import config, llm  # noqa: E402

CALLS = []


def fake_base(full: set):
    async def gen(self, llm_request, stream=False):
        CALLS.append((self.model, self.location))
        if (self.model, self.location) in full:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. Resource exhausted. Please try again later.")
        yield NS(text=f"ok dari {self.model}@{self.location}")
    return gen


class FallbackTest(unittest.TestCase):
    def setUp(self):
        CALLS.clear()
        self.p = mock.patch.object(config, "_read_runtime_file", return_value={
            "model_fallbacks": ["gemini-4-argon@global", "gemini-3.5-flash@global"]})
        self.p.start()
        config._runtime_cache["loaded_at"] = 0

    def tearDown(self):
        self.p.stop()
        config._runtime_cache["loaded_at"] = 0

    def _run(self, full):
        base = llm.PinnedGemini.__mro__[1]
        with mock.patch.object(base, "generate_content_async", fake_base(full), create=True):
            m = llm.PinnedGemini(model="gemini-4-argon", location="asia-southeast1")
            req = NS(model="gemini-4-argon")

            async def collect():
                return [r async for r in m.generate_content_async(req)]
            return asyncio.run(collect())

    def test_primary_ok(self):
        out = self._run(set())
        self.assertEqual(out[0].text, "ok dari gemini-4-argon@asia-southeast1")
        self.assertEqual(CALLS, [("gemini-4-argon", "asia-southeast1")])

    def test_regional_full_uses_global(self):
        out = self._run({("gemini-4-argon", "asia-southeast1")})
        self.assertEqual(out[0].text, "ok dari gemini-4-argon@global")

    def test_all_full_returns_busy_message(self):
        out = self._run({("gemini-4-argon", "asia-southeast1"), ("gemini-4-argon", "global"),
                         ("gemini-3.5-flash", "global")})
        self.assertIn("sedang sangat padat", out[0].content.parts[0].text)
        self.assertEqual(len(CALLS), 3)

    def test_other_errors_become_error_response(self):
        """v3.5.3: error non-kapasitas (mis. 400) tidak lagi mematikan run -> respons berkode error, tanpa
        mencoba cadangan, supaya ensure_reply tetap mengirim jawaban dari hasil tool."""
        base = llm.PinnedGemini.__mro__[1]

        async def bad(self, req, stream=False):
            CALLS.append((self.model, self.location))
            raise ValueError("400 INVALID_ARGUMENT: function call is missing a thought_signature")
            yield  # pragma: no cover

        with mock.patch.object(base, "generate_content_async", bad, create=True):
            m = llm.PinnedGemini(model="gemini-4-argon", location="asia-southeast1")

            async def collect():
                return [r async for r in m.generate_content_async(NS(model="x"))]
            out = asyncio.run(collect())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].error_code, llm.MODEL_ERROR_CODE)
        self.assertIn("thought_signature", out[0].error_message)
        self.assertEqual(len(CALLS), 1)

    def test_error_after_partial_stream_still_raises(self):
        base = llm.PinnedGemini.__mro__[1]

        async def half(self, req, stream=False):
            yield NS(text="sebagian")
            raise ValueError("400 putus")

        with mock.patch.object(base, "generate_content_async", half, create=True):
            m = llm.PinnedGemini(model="gemini-4-argon", location="asia-southeast1")

            async def collect():
                return [r async for r in m.generate_content_async(NS(model="x"))]
            with self.assertRaises(ValueError):
                asyncio.run(collect())

    def test_missing_signature_filled_before_call(self):
        """Panggilan sintetis periksa_angka di riwayat diberi thought_signature sebelum dikirim ke Gemini."""
        seen = []
        base = llm.PinnedGemini.__mro__[1]

        async def gen(self, req, stream=False):
            seen.extend(p.thought_signature for c in req.contents for p in c.parts if p.function_call)
            yield NS(text="ok")

        own = NS(function_call=NS(name="ask_retail_intelligence"), thought_signature=b"asli")
        synth = NS(function_call=NS(name="periksa_angka"), thought_signature=None)
        text = NS(function_call=None, text="halo")
        req = NS(model="x", contents=[NS(parts=[own]), NS(parts=[synth, text])])
        with mock.patch.object(base, "generate_content_async", gen, create=True):
            m = llm.PinnedGemini(model="gemini-3.5-flash", location="global")

            async def collect():
                return [r async for r in m.generate_content_async(req)]
            asyncio.run(collect())
        self.assertEqual(seen, [b"asli", llm.SKIP_SIGNATURE])
        self.assertFalse(hasattr(text, "thought_signature"))

    def test_targets_skip_primary(self):
        self.assertEqual(llm.fallback_targets("gemini-4-argon", "global"), [("gemini-3.5-flash", "global")])


if __name__ == "__main__":
    unittest.main()


class AliasTest(unittest.TestCase):
    def test_pro_fast_aliases(self):
        with mock.patch.object(config, "_read_runtime_file", return_value={"model_fallbacks": ["pro@global", "fast@global"]}):
            config._runtime_cache["loaded_at"] = 0
            out = llm.fallback_targets(config.settings.model_pro, "asia-southeast1")
        config._runtime_cache["loaded_at"] = 0
        self.assertEqual(out, [(config.settings.model_pro, "global"), (config.settings.model_fast, "global")])
