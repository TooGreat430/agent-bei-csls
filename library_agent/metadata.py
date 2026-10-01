"""Ekstraksi metadata dokumen otomatis dengan Gemini.

User cukup melampirkan file. Gemini membaca dokumen lalu mengusulkan judul,
jenis, versi, dan tanggal. User hanya ditanya untuk field yang tidak yakin.

Aturan pengisian:
- judul    : dari isi dokumen. Jika tidak yakin, pakai nama file dan tandai "perlu konfirmasi".
- jenis    : harus salah satu LIB_DOC_TYPES. Jika tidak yakin, tandai "perlu konfirmasi".
- versi    : dari dokumen. Jika tidak tertulis, default "1" (bukan pertanyaan ke user).
- tanggal  : dari dokumen. Jika tidak tertulis, default tanggal upload (bukan pertanyaan ke user).
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import date
from typing import Any

from .config import settings, live

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 15000
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


# --------------------------------------------------------------------------
# Logika murni (bisa diuji tanpa GCP)
# --------------------------------------------------------------------------
def response_schema(allowed_types: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["title", "title_confident", "doc_type", "doc_type_confident",
                     "version", "doc_date", "summary"],
        "properties": {
            "title": {"type": "string", "description": "Judul resmi dokumen seperti tertulis di sampul/halaman awal."},
            "title_confident": {"type": "boolean", "description": "true jika judul jelas tertulis di dokumen."},
            "doc_type": {"type": "string", "enum": [*allowed_types, "TIDAK_YAKIN"]},
            "doc_type_confident": {"type": "boolean"},
            "version": {"type": "string", "description": "Versi/edisi yang tertulis di dokumen. Kosong jika tidak ada."},
            "doc_date": {"type": "string", "description": "Tanggal dokumen, format YYYY-MM-DD (atau YYYY-MM / YYYY). Kosong jika tidak ada."},
            "summary": {"type": "string", "description": "Satu kalimat tentang isi dokumen."},
        },
    }


_VERSION_PREFIX = re.compile(r"^(?:version|versi|ver|rev|edisi|v)(?=[\s\d.:#-]|$)[\s.:#-]*", re.IGNORECASE)


def clean_version(value: str) -> str:
    """'Version 1' -> '1', 'Versi 2' -> '2', 'v3' -> '3', 'Ver. 4' -> '4'. Lainnya dibiarkan."""
    return _VERSION_PREFIX.sub("", (value or "").strip()).strip()


def finalize(raw: dict[str, Any], filename: str, allowed_types: tuple[str, ...],
             today: str | None = None) -> dict[str, Any]:
    """Rapikan hasil Gemini: isi default dan tentukan field mana yang perlu dikonfirmasi user."""
    today = today or date.today().isoformat()
    uncertain: list[str] = []
    defaults: list[str] = []

    title = (raw.get("title") or "").strip()
    if not title or not raw.get("title_confident", False):
        uncertain.append("title")
        title = title or os.path.splitext(filename)[0].replace("_", " ").strip()

    doc_type = (raw.get("doc_type") or "").strip().upper()
    if doc_type not in allowed_types or not raw.get("doc_type_confident", False):
        uncertain.append("doc_type")
        doc_type = doc_type if doc_type in allowed_types else ""

    version = (raw.get("version") or "").strip()
    version = clean_version(version)
    if not version:
        version = "1"
        defaults.append("version")

    doc_date = (raw.get("doc_date") or "").strip()
    if not DATE_RE.match(doc_date):
        doc_date = today
        defaults.append("doc_date")

    return {
        "metadata": {"title": title, "doc_type": doc_type, "version": version, "doc_date": doc_date},
        "summary": (raw.get("summary") or "").strip(),
        "uncertain_fields": uncertain,
        "defaults_used": defaults,
    }


def apply_corrections(suggested: dict[str, str], corrections: dict[str, str],
                      allowed_types: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    """Gabungkan hasil ekstraksi dengan koreksi user. Mengembalikan (metadata_final, field_yang_masih_kosong)."""
    final = dict(suggested)
    for key in ("title", "doc_type", "version", "doc_date"):
        value = (corrections.get(key) or "").strip()
        if value:
            final[key] = value.upper() if key == "doc_type" else value
    missing = [k for k in ("title", "doc_type", "version", "doc_date") if not final.get(k)]
    if final.get("doc_type") and final["doc_type"] not in allowed_types:
        missing.append("doc_type")
    if final.get("doc_date") and not DATE_RE.match(final["doc_date"]):
        missing.append("doc_date")
    return final, sorted(set(missing))


def next_version(version: str) -> str:
    """Usulan versi berikutnya: "2" -> "3", "1.4" -> "1.5". Lainnya: tambahkan "-rev"."""
    match = re.fullmatch(r"(.*?)(\d+)", version.strip())
    if match:
        return f"{match.group(1)}{int(match.group(2)) + 1}"
    return f"{version}-rev" if version else "2"


# --------------------------------------------------------------------------
# Baca isi dokumen untuk Gemini
# --------------------------------------------------------------------------
def _download(staged_uri: str) -> bytes:
    from .clients import storage_client
    from .ingest import parse_gcs_uri

    bucket, path = parse_gcs_uri(staged_uri)
    return storage_client().bucket(bucket).blob(path).download_as_bytes()


def _office_text(data: bytes, mime_type: str) -> str:
    if mime_type.endswith("wordprocessingml.document"):
        import docx  # python-docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs if p.text.strip())
    if mime_type.endswith("presentationml.presentation"):
        from pptx import Presentation  # python-pptx

        deck = Presentation(io.BytesIO(data))
        return "\n".join(
            shape.text for slide in deck.slides for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text.strip()
        )
    return data.decode("utf-8", errors="ignore")


def _document_part(upload: dict[str, Any]):
    """PDF dikirim langsung dari GCS. Format lain diubah ke teks (bagian awal saja)."""
    from google.genai import types

    mime = upload["mime_type"]
    if mime == "application/pdf":
        return types.Part.from_uri(file_uri=upload["staged_uri"], mime_type=mime)
    text = _office_text(_download(upload["staged_uri"]), mime)
    if mime == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return types.Part.from_text(text=re.sub(r"\s+\n", "\n", text)[:MAX_TEXT_CHARS])


def suggest(upload: dict[str, Any]) -> dict[str, Any]:
    """Minta Gemini mengusulkan metadata untuk satu file yang sudah di-staging."""
    from google.genai import types

    from .clients import genai_client

    hints = live("doc_type_hints") or "(tidak ada penjelasan tambahan)"
    prompt = f"""Baca dokumen terlampir dan tentukan metadatanya untuk katalog perpustakaan perusahaan.

Jenis dokumen yang tersedia: {", ".join(live("allowed_doc_types"))}.
Penjelasan jenis dokumen: {hints}
Nama file (petunjuk tambahan, bisa saja tidak akurat): {upload["filename"]}

Aturan:
- Ambil judul, versi, dan tanggal HANYA dari yang tertulis di dokumen. Jangan menebak.
- Utamakan sampul, halaman judul, header/footer, dan riwayat revisi.
- Jika jenis dokumen tidak jelas, pilih "TIDAK_YAKIN".
- Tandai *_confident = false jika ragu."""

    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=response_schema(live("allowed_doc_types")),
    )
    response = genai_client().models.generate_content(
        model=settings.model_fast, contents=[_document_part(upload), prompt], config=config,
    )
    raw = json.loads(response.text or "{}")
    logger.info("metadata usulan untuk %s: %s", upload["filename"], raw)
    return finalize(raw, upload["filename"], live("allowed_doc_types"))
