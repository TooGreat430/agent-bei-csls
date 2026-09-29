"""POC: apakah Gemini Enterprise meneruskan lampiran chat ke agent ADK custom?

Agent ini sengaja minimal. Ia TIDAK memakai model untuk menjawab: callback
langsung membalas dengan laporan struktur pesan yang diterima, sehingga hasil
uji tidak dipengaruhi perilaku model.

Cara uji di Gemini Enterprise:
1. Deploy agent ini ke Agent Engine dan daftarkan ke GE (lihat README, bagian POC).
2. Kirim pesan teks biasa -> harus muncul 1 part "text".
3. Kirim pesan + lampiran PDF -> perhatikan apakah muncul part "inline_data"
   atau "file_data", beserta ukuran/URI-nya.
4. Ulangi dengan DOCX dan file besar (mis. 20 MB) untuk melihat batasnya.

Interpretasi:
- inline_data dengan bytes > 0     -> upload via chat BISA (jalur utama).
- file_data dengan URI gs://...    -> BISA, agent perlu izin baca ke URI tsb.
- file_data dengan URI lain        -> perlu adaptasi (catat URI-nya).
- hanya part "text"                -> lampiran TIDAK diteruskan; pakai jalur cadangan.
"""
import json
import logging
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("upload_probe")


def _describe(content: types.Content) -> list[dict]:
    out = []
    for part in content.parts or []:
        if part.text:
            out.append({"kind": "text", "chars": len(part.text), "preview": part.text[:80]})
        elif part.inline_data:
            out.append({
                "kind": "inline_data",
                "mime_type": part.inline_data.mime_type,
                "display_name": getattr(part.inline_data, "display_name", None),
                "bytes": len(part.inline_data.data or b""),
            })
        elif part.file_data:
            out.append({
                "kind": "file_data",
                "mime_type": part.file_data.mime_type,
                "display_name": getattr(part.file_data, "display_name", None),
                "file_uri": part.file_data.file_uri,
            })
        else:
            fields = [f for f in ("function_call", "function_response", "executable_code") if getattr(part, f, None)]
            out.append({"kind": "other", "fields": fields})
    return out


def probe(callback_context: CallbackContext) -> Optional[types.Content]:
    content = callback_context.user_content
    parts = _describe(content) if content else []
    user_id = getattr(callback_context, "user_id", None) or getattr(
        getattr(callback_context, "_invocation_context", None), "user_id", None
    )
    report = {"user_id": user_id, "part_count": len(parts), "parts": parts}
    logger.info("UPLOAD_PROBE %s", json.dumps(report, ensure_ascii=False))

    has_file = any(p["kind"] in ("inline_data", "file_data") for p in parts)
    verdict = ("Lampiran DITERIMA agent." if has_file
               else "Tidak ada lampiran yang diterima agent (hanya teks).")
    text = f"{verdict}\n\n```json\n{json.dumps(report, indent=2, ensure_ascii=False)}\n```"
    # Mengembalikan Content dari before_agent_callback = agent tidak memanggil model.
    return types.Content(role="model", parts=[types.Part(text=text)])


root_agent = LlmAgent(
    name="upload_probe",
    model="gemini-2.5-flash",
    description="POC: menampilkan struktur pesan (termasuk lampiran) yang diterima agent.",
    instruction="Balas singkat.",
    before_agent_callback=probe,
)
