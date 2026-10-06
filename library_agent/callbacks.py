"""Callback yang menangkap lampiran file dari chat.

Dipasang sebagai before_agent_callback di root agent DAN sub-agent, karena
setelah transfer, pesan user berikutnya bisa langsung diterima sub-agent yang
terakhir aktif (tanpa melewati root). Duplikasi dicegah dengan hash konten.

Dijalankan sebelum agent memproses setiap pesan user. Jika pesan berisi
file (inline_data atau file_data), file disimpan ke GCS staging dan dicatat di
state `pending_uploads`. Research agent kemudian mengekstrak metadata, meminta konfirmasi user, dan
memasukkan file ke perpustakaan lewat `extract_upload_metadata` dan `confirm_upload`.

Callback ini juga menulis log struktur pesan yang diterima. Log ini adalah
bukti utama POC "apakah Gemini Enterprise meneruskan lampiran ke agent custom".
"""
from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from . import ingest
from .clients import storage_client, get_session_id
from .config import SUPPORTED_MIME_TYPES

logger = logging.getLogger(__name__)

PENDING_KEY = "pending_uploads"


def _describe_parts(content: types.Content) -> list[dict]:
    summary = []
    for part in content.parts or []:
        if part.text:
            summary.append({"kind": "text", "chars": len(part.text)})
        elif part.inline_data:
            summary.append({
                "kind": "inline_data",
                "mime_type": part.inline_data.mime_type,
                "display_name": getattr(part.inline_data, "display_name", None),
                "bytes": len(part.inline_data.data or b""),
            })
        elif part.file_data:
            summary.append({
                "kind": "file_data",
                "mime_type": part.file_data.mime_type,
                "display_name": getattr(part.file_data, "display_name", None),
                "file_uri": part.file_data.file_uri,
            })
        else:
            summary.append({"kind": "other"})
    return summary


def capture_uploads(callback_context: CallbackContext) -> Optional[types.Content]:
    content = callback_context.user_content
    if not content or not content.parts:
        return None

    logger.info("user_content parts: %s", _describe_parts(content))

    session_id = get_session_id(callback_context)
    pending = list(callback_context.state.get(PENDING_KEY, []))
    known_hashes = {p["content_hash"] for p in pending}
    rejected = []

    for part in content.parts:
        try:
            if part.inline_data and part.inline_data.data:
                mime = part.inline_data.mime_type or ""
                name = getattr(part.inline_data, "display_name", None) or "dokumen"
                if mime not in SUPPORTED_MIME_TYPES:
                    rejected.append({"file": name, "mime_type": mime})
                    continue
                if ingest.md5_b64(part.inline_data.data) in known_hashes:
                    continue  # sudah ditangkap (callback juga terpasang di sub-agent)
                staged = ingest.stage_bytes(part.inline_data.data, name, mime, session_id)
            elif part.file_data and part.file_data.file_uri:
                uri = part.file_data.file_uri
                mime = part.file_data.mime_type or ""
                name = getattr(part.file_data, "display_name", None) or uri.rsplit("/", 1)[-1]
                if mime not in SUPPORTED_MIME_TYPES:
                    rejected.append({"file": name, "mime_type": mime})
                    continue
                if not uri.startswith("gs://"):
                    # Mis. URI Drive: belum didukung, dicatat untuk analisis POC.
                    logger.warning("file_data non-GCS belum didukung: %s", uri)
                    rejected.append({"file": name, "reason": "sumber file belum didukung", "uri": uri})
                    continue
                staged = ingest.stage_gcs_uri(uri, name, mime, session_id)
            else:
                continue
        except Exception:  # noqa: BLE001
            logger.exception("Gagal menyimpan lampiran ke staging")
            continue

        if staged["content_hash"] in known_hashes:
            continue
        staged["upload_id"] = f"up{len(pending) + 1}"
        pending.append(staged)
        known_hashes.add(staged["content_hash"])

    callback_context.state[PENDING_KEY] = pending
    if rejected:
        callback_context.state["temp:rejected_uploads"] = rejected
    return None


# ==========================================================================
# Setelah sub-agent selesai: jawaban tidak boleh kosong + grafik di chat
# ==========================================================================
def summarize_result(resp: dict) -> str:
    """Teks pengganti dari hasil tool terakhir jika model tidak menulis jawaban."""
    if not isinstance(resp, dict):
        return ""
    if resp.get("status") == "ok" and resp.get("url"):
        title = resp.get("report_title") or "Laporan"
        return f"{title} sudah siap: {resp['url']}"
    if resp.get("message"):
        return str(resp["message"])
    if resp.get("status") == "ok":
        return "Permintaan sudah diproses."
    return ""


def _invocation_events(callback_context: CallbackContext) -> list:
    ctx = getattr(callback_context, "_invocation_context", None)
    if ctx is None or getattr(ctx, "session", None) is None:
        return []
    return [e for e in ctx.session.events if getattr(e, "invocation_id", None) == ctx.invocation_id]


def fallback_reply(events: list, agent_name: str) -> str:
    """Jika TIDAK ADA agent yang menulis teks di giliran ini, ambil pesan dari hasil tool terakhir."""
    last_response = None
    for event in events:
        content = getattr(event, "content", None)
        for part in (getattr(content, "parts", None) or []):
            if getattr(event, "author", "") not in ("", "user") and getattr(part, "text", None) \
                    and not getattr(part, "thought", False) and part.text.strip():
                return ""
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "response", None):
                last_response = fr.response
    return summarize_result(last_response) if last_response else ""


def ensure_reply(callback_context: CallbackContext) -> Optional[types.Content]:
    """after_agent_callback: pastikan user selalu menerima jawaban."""
    try:
        text = fallback_reply(_invocation_events(callback_context), callback_context.agent_name)
    except Exception:  # noqa: BLE001
        logger.exception("Pemeriksaan jawaban kosong gagal")
        return None
    return types.Content(role="model", parts=[types.Part(text=text)]) if text else None


def data_after_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    """after_agent_callback agent data: jawaban tidak kosong + tampilkan grafik PNG di chat."""
    parts: list = []
    reply = ensure_reply(callback_context)
    if reply:
        parts.extend(reply.parts)
    pending = callback_context.state.get("bq_pending_chart")
    if pending:
        callback_context.state["bq_pending_chart"] = None
        try:
            png = storage_client().bucket(pending["bucket"]).blob(pending["path"]).download_as_bytes()
            parts.append(types.Part.from_bytes(data=png, mime_type="image/png"))
        except Exception:  # noqa: BLE001
            logger.exception("Grafik tidak bisa ditampilkan di chat")
    return types.Content(role="model", parts=parts) if parts else None
