"""Uji Claude di Vertex AI dengan kode agent yang sebenarnya (jalankan SEBELUM mengaktifkan untuk user).

    python scripts/check_claude.py

1) Panggilan teks sederhana (jalur penulisan laporan).
2) Pemanggilan alat (tool use) memakai konversi ADK -> Claude yang dipakai agent: Claude harus memanggil alat
   'analyze_data' dengan argumen JSON, lalu menjawab setelah menerima hasil alat.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from google.genai import types  # noqa: E402

from library_agent import llm_claude  # noqa: E402
from library_agent.config import settings  # noqa: E402

print(f"Model: {settings.model_claude} @ {settings.claude_region} · project {settings.project_id}")
try:
    text, usage = llm_claude.complete("Jawab satu kalimat: apa ibu kota Indonesia?", max_tokens=100)
    print(f"1) Teks       : OK — {text.strip()[:80]} · token in/out {usage['input']}/{usage['output']}")
except Exception as exc:  # noqa: BLE001
    sys.exit(f"1) Teks       : GAGAL — {str(exc)[:400]}")

fd = types.FunctionDeclaration(
    name="analyze_data", description="Menghitung analisis atas file data user.",
    parameters=types.Schema(type="OBJECT", properties={"plan_json": types.Schema(type="STRING"),
                                                      "question": types.Schema(type="STRING")},
                            required=["plan_json", "question"]))


class Req:
    def __init__(self, contents):
        self.contents = contents
        self.config = types.GenerateContentConfig(system_instruction="Anda analis PTPL. Gunakan alat untuk menghitung.",
                                                  tools=[types.Tool(function_declarations=[fd])])


async def main():
    model = llm_claude.ClaudeVertex(model=settings.model_claude)
    contents = [types.Content(role="user", parts=[types.Part(text="Hitung total volume per outlet dari file f1.")])]
    out = [r async for r in model.generate_content_async(Req(contents))][0]
    call = next((p.function_call for p in out.content.parts if p.function_call), None)
    used = (out.custom_metadata or {}).get("model_used")
    if not call:
        return f"2) Alat       : GAGAL — tidak memanggil alat (model dipakai: {used})"
    contents += [out.content, types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=call.id, name=call.name, response={"status": "ok", "rows": [["A001", 12.5], ["A002", 9.1]]}))])]
    out2 = [r async for r in model.generate_content_async(Req(contents))][0]
    answer = " ".join(p.text for p in out2.content.parts if p.text)
    return (f"2) Alat       : OK — memanggil {call.name}({list(call.args)}) lalu menjawab: {answer.strip()[:100]} "
            f"· model dipakai: {(out2.custom_metadata or {}).get('model_used')}")

print(asyncio.run(main()))
print("\nJika kedua baris OK dan model dipakai = claude-..., Claude siap dipakai agent.")
