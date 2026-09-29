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
from .clients import get_session_id
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
                if ingest.sha256(part.inline_data.data) in known_hashes:
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
