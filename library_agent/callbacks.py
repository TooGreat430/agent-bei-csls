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

import json
import logging
import re
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


DATA_MIME_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
DATA_EXTENSIONS = (".csv", ".xlsx", ".xlsm", ".xls")


def _is_data_file(name: str, mime: str) -> bool:
    return (mime or "").lower() in DATA_MIME_TYPES or (name or "").lower().endswith(DATA_EXTENSIONS)


def _store_data_file(part, callback_context: CallbackContext, session_id: str) -> bool:
    """CSV/Excel -> folder data per chat + daftar data_files di state. True jika part ditangani."""
    import hashlib

    from .clients import storage_client
    from .config import settings
    from .ingest import parse_gcs_uri, safe_filename

    if part.inline_data and part.inline_data.data:
        name = getattr(part.inline_data, "display_name", None) or "data.csv"
        mime = part.inline_data.mime_type or ""
        if not _is_data_file(name, mime):
            return False
        data = part.inline_data.data
    elif part.file_data and part.file_data.file_uri and part.file_data.file_uri.startswith("gs://"):
        uri = part.file_data.file_uri
        name = getattr(part.file_data, "display_name", None) or uri.rsplit("/", 1)[-1]
        mime = part.file_data.mime_type or ""
        if not _is_data_file(name, mime):
            return False
        bucket, path = parse_gcs_uri(uri)
        data = storage_client().bucket(bucket).blob(path).download_as_bytes()
    else:
        return False
    files = list(callback_context.state.get("data_files", []))
    digest = hashlib.sha256(data).hexdigest()[:12]
    if any(f.get("hash") == digest for f in files):
        return True
    if not name.lower().endswith(DATA_EXTENSIONS):
        name += ".xlsx" if "sheet" in mime or "excel" in mime else ".csv"
    fname = safe_filename(name)
    path = f"{settings.data_file_prefix}/{session_id}/{digest}_{fname}"
    storage_client().bucket(settings.bucket).blob(path).upload_from_string(data, content_type=mime or "text/csv")
    files.append({"file_id": f"f{len(files) + 1}", "filename": fname, "uri": f"gs://{settings.bucket}/{path}",
                  "mime_type": mime, "size_bytes": len(data), "hash": digest})
    callback_context.state["data_files"] = files
    logger.info("File data disimpan: %s (%d byte)", fname, len(data))
    return True


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
            if _store_data_file(part, callback_context, session_id):
                continue
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
    from .config import live

    if pending and live("chat_inline_chart"):
        # Gemini Enterprise belum menampilkan gambar dari agent ADK (muncul sebagai asc_slot://),
        # jadi lampiran gambar hanya dikirim jika diaktifkan di settings.json.
        try:
            png = storage_client().bucket(pending["bucket"]).blob(pending["path"]).download_as_bytes()
            parts.append(types.Part.from_bytes(data=png, mime_type="image/png"))
        except Exception:  # noqa: BLE001
            logger.exception("Grafik tidak bisa ditampilkan di chat")
    return types.Content(role="model", parts=parts) if parts else None


# ==========================================================================
# Pengecekan angka otomatis (Tahap 0)
# ==========================================================================
def _number_pool(callback_context: CallbackContext) -> list[float]:
    """Angka dari hasil tool di sesi ini + pesan user (dasar verifikasi jawaban)."""
    from .price_dashboard import _MONEY
    from .report_render import parse_number

    ctx = getattr(callback_context, "_invocation_context", None)
    events = list(getattr(getattr(ctx, "session", None), "events", []) or [])[-60:]
    texts = []
    for e in events:
        content = getattr(e, "content", None)
        for part in (getattr(content, "parts", None) or []):
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", "") != "periksa_angka":
                try:
                    texts.append(json.dumps(fr.response, ensure_ascii=False, default=str))
                except Exception:  # noqa: BLE001
                    texts.append(str(fr.response))
            elif getattr(e, "author", "") == "user" and getattr(part, "text", None):
                texts.append(part.text)
    if callback_context.user_content and callback_context.user_content.parts:
        texts += [p.text for p in callback_context.user_content.parts if getattr(p, "text", None)]
    pool = set()
    for t in texts:
        for raw in _MONEY.findall(t):
            v = parse_number(raw)
            if v is not None:
                v = abs(v)
                pool.update({round(v, 2), round(v * 100, 2), round(v / 100, 4)})
        for raw in re.findall(r"-?\d+\.\d+(?:[eE][-+]?\d+)?", t):
            try:
                v = abs(float(raw))
                pool.update({round(v, 2), round(v * 100, 2)})
            except ValueError:
                pass
    return sorted(pool)


def verify_numbers(callback_context: CallbackContext, llm_response):
    """Jawaban akhir yang memuat angka di luar hasil tool -> minta model menulis ulang sekali; jika masih,
    tambahkan catatan transparan."""
    from google.adk.models import LlmResponse

    from .price_dashboard import ungrounded_numbers

    content = getattr(llm_response, "content", None)
    parts = list(getattr(content, "parts", None) or [])
    if not parts or any(getattr(p, "function_call", None) for p in parts):
        return None
    text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
    if not text.strip():
        return None
    pool = _number_pool(callback_context)
    if not pool:
        return None
    bad = sorted(set(ungrounded_numbers(text, pool)))
    if not bad:
        return None
    ctx = getattr(callback_context, "_invocation_context", None)
    key = f"temp:numcheck_{getattr(ctx, 'invocation_id', '')}"
    tries = callback_context.state.get(key, 0)
    logger.warning("Angka tidak terverifikasi (percobaan %d): %s", tries, bad[:10])
    if tries == 0:
        callback_context.state[key] = 1
        call = types.FunctionCall(name="periksa_angka", args={"angka_tidak_terverifikasi": bad[:10]})
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
    note = ("\n\n_Catatan: angka berikut tidak dapat diverifikasi otomatis terhadap data: "
            + ", ".join(bad[:8]) + ". Mohon cek ulang sebelum dipakai._")
    new_parts = [types.Part(text=text + note)]
    return LlmResponse(content=types.Content(role="model", parts=new_parts))
