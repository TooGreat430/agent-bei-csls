"""Uji integrasi Claude (Vertex AI): konversi ADK <-> Anthropic, cadangan Gemini 4 Argon, saklar, meteran."""
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

from google.genai import types  # noqa: E402

from library_agent import config, llm, llm_claude, report_engine, usage  # noqa: E402


def request():
    fd = NS(name="analyze_data", description="Analisis file", parameters_json_schema=None,
            parameters={"type": "OBJECT", "properties": {"plan_json": {"type": "STRING"}}, "required": ["plan_json"]})
    contents = [
        types.Content(role="user", parts=[types.Part(text="Hitung volume per outlet"),
                                          types.Part(inline_data=NS(data=b"\x89PNG", mime_type="image/png"))]),
        types.Content(role="model", parts=[types.Part(function_call=NS(id="adk-1", name="analyze_data",
                                                                       args={"plan_json": "{}"}))]),
        types.Content(role="user", parts=[types.Part(function_response=NS(id="adk-1", name="analyze_data",
                                                                          response={"status": "ok", "rows": [[1, 2]]}))]),
    ]
    return NS(contents=contents, model="claude-opus-5-5",
              config=NS(system_instruction="Anda analis PTPL.", tools=[NS(function_declarations=[fd])]),
              model_copy=lambda deep=True: request())


class ConvertTest(unittest.TestCase):
    def test_messages(self):
        msgs = llm_claude.messages_param(request())
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"][1]["type"], "image")
        self.assertEqual(msgs[1]["content"][0], {"type": "tool_use", "id": "adk-1", "name": "analyze_data",
                                                 "input": {"plan_json": "{}"}})
        self.assertEqual(msgs[2]["content"][0]["type"], "tool_result")
        self.assertEqual(msgs[2]["content"][0]["tool_use_id"], "adk-1")

    def test_tools_schema_lowercase(self):
        tools = llm_claude.tools_param(request())
        self.assertEqual(tools[0]["name"], "analyze_data")
        self.assertEqual(tools[0]["input_schema"]["type"], "object")
        self.assertEqual(tools[0]["input_schema"]["properties"]["plan_json"]["type"], "string")

    def test_starts_with_user_and_merges(self):
        req = NS(contents=[types.Content(role="model", parts=[types.Part(text="halo")]),
                           types.Content(role="model", parts=[types.Part(text="lagi")])], config=NS())
        msgs = llm_claude.messages_param(req)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(len(msgs[1]["content"]), 2)

    def test_response(self):
        msg = NS(content=[NS(type="text", text="Selesai."), NS(type="tool_use", id="toolu_1", name="ekspor_excel",
                                                               input={"nama_file": "RFM"})],
                 usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=500))
        resp = llm_claude.to_llm_response(msg, "claude-opus-5-5")
        self.assertEqual(resp.content.parts[0].text, "Selesai.")
        self.assertEqual(resp.content.parts[1].function_call.name, "ekspor_excel")
        self.assertEqual(resp.usage_metadata.prompt_token_count, 1500)
        self.assertEqual(resp.custom_metadata["model_used"], "claude-opus-5-5")


class FakeMessages:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return NS(content=[NS(type="text", text="Jawaban Claude")], usage=NS(input_tokens=10, output_tokens=5))


class ModelTest(unittest.TestCase):
    def setUp(self):
        config._runtime_cache["loaded_at"] = 0

    def tearDown(self):
        config._runtime_cache["loaded_at"] = 0

    def _run(self, fake, runtime=None):
        base = llm.PinnedGemini.__mro__[1]

        async def argon(self, req, stream=False):
            yield NS(content=types.Content(role="model", parts=[types.Part(text="Jawaban Argon")]))
        with mock.patch.object(config, "_read_runtime_file", return_value=runtime or {}), \
                mock.patch.object(llm_claude, "anthropic_client", return_value=NS(messages=fake)), \
                mock.patch.object(base, "generate_content_async", argon, create=True):
            m = llm_claude.ClaudeVertex(model="claude-opus-5-5")

            async def go():
                return [r async for r in m.generate_content_async(request())]
            return asyncio.run(go())

    def test_claude_answers(self):
        fake = FakeMessages()
        out = self._run(fake)
        self.assertEqual(out[0].content.parts[0].text, "Jawaban Claude")
        self.assertEqual(fake.calls[0]["system"], "Anda analis PTPL.")
        self.assertEqual(fake.calls[0]["tools"][0]["name"], "analyze_data")

    def test_capacity_falls_back_to_argon_with_note(self):
        err = RuntimeError("Error code: 529 - overloaded_error")
        out = self._run(FakeMessages(err))
        texts = [p.text for p in out[0].content.parts]
        self.assertEqual(texts[0], "Jawaban Argon")
        self.assertIn("Claude sedang padat", texts[-1])

    def test_switch_to_gemini_without_note(self):
        fake = FakeMessages()
        out = self._run(fake, {"heavy_model": "gemini"})
        self.assertEqual([p.text for p in out[0].content.parts], ["Jawaban Argon"])
        self.assertEqual(fake.calls, [])


class ReportWritingTest(unittest.TestCase):
    def setUp(self):
        config._runtime_cache["loaded_at"] = 0
        report_engine.RETRY_SECONDS = 0
        usage._BUFFER.update(ops=[], usd=0.0, last_flush=10 ** 12)

    def test_claude_writes_and_is_metered(self):
        with mock.patch.object(llm_claude, "complete", return_value=("<section>ok</section>",
                                                                    {"input": 1000, "output": 500, "cached": 0})):
            self.assertEqual(report_engine.generate_text("tulis"), "<section>ok</section>")
        self.assertAlmostEqual(usage._BUFFER["usd"], (1000 * 4 + 500 * 20) / 1e6)

    def test_json_from_claude(self):
        with mock.patch.object(llm_claude, "complete", return_value=('Berikut:\n{"judul_utama": "x"}', {"input": 1,
                                                                                                   "output": 1, "cached": 0})):
            self.assertEqual(report_engine._generate_json("p", {"type": "object"}), {"judul_utama": "x"})

    def test_claude_full_then_argon(self):
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        with mock.patch.object(llm_claude, "complete", side_effect=boom), \
                mock.patch.object(report_engine, "_with_fallback", return_value=NS(text="argon", usage_metadata=None)):
            self.assertEqual(report_engine.generate_text("tulis"), "argon")
        self.assertEqual(len(calls), 2)                       # coba ulang sekali, lalu Argon

    def test_meter_prices_claude(self):
        _, usd = usage.model_cost("file_agent", 1_000_000, 0, 0, "claude-opus-5-5")
        self.assertAlmostEqual(usd, 4.0)


if __name__ == "__main__":
    unittest.main()


class SdkCompatTest(unittest.TestCase):
    def test_unknown_kwarg_dropped_and_none_not_sent(self):
        calls = []

        class Api:
            def create(self, *, model, max_tokens, messages, system=None, tools=None):
                calls.append({"system": system, "tools": tools})
                return NS(content=[NS(type="text", text="ok")], usage=None)
        out = llm_claude.create_sync(Api(), model="m", max_tokens=10, temperature=0.2, system="", tools=[],
                                     messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(out.content[0].text, "ok")
        self.assertEqual(calls, [{"system": None, "tools": None}])        # temperature dibuang, kosong tidak dikirim

    def test_async_variant(self):
        class Api:
            async def create(self, *, model, max_tokens, messages):
                return NS(content=[NS(type="text", text="ok")], usage=None)
        out = asyncio.run(llm_claude.create_async(Api(), model="m", max_tokens=10, messages=[], temperature=1,
                                                  system="sys"))
        self.assertEqual(out.content[0].text, "ok")
