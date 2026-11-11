"""Tool dokumen unggahan (PDF, Word, PowerPoint, teks, HTML, gambar, dll.) di chat ini."""
from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

DOCS_KEY = "documents"
PAGE_CHARS = 30000


def _docs(tool_context: ToolContext) -> list[dict]:
    return list(tool_context.state.get(DOCS_KEY, []))


def list_documents(tool_context: ToolContext) -> dict[str, Any]:
    """Daftar dokumen non-data (PDF, Word, PowerPoint, teks, HTML, gambar, dll.) yang diunggah di chat ini."""
    docs = _docs(tool_context)
    if not docs:
        return {"status": "ok", "documents": [], "message": "Belum ada dokumen yang diunggah di chat ini."}
    return {"status": "ok", "documents": [
        {k: d.get(k) for k in ("doc_id", "filename", "jenis", "pages", "chars", "readable", "note")} for d in docs]}


def read_document(doc_id: str, tool_context: ToolContext, offset: int = 0) -> dict[str, Any]:
    """Membaca isi teks dokumen unggahan (per potongan 30.000 karakter).

    Args:
        doc_id: ID dokumen (mis. "d1"); kosongkan untuk dokumen terakhir.
        offset: Posisi karakter awal (0 untuk awal; pakai next_offset dari hasil sebelumnya untuk lanjutan).
    """
    from ..callbacks import _doc_text

    docs = _docs(tool_context)
    doc = next((d for d in docs if d["doc_id"] == doc_id.strip()), None) if doc_id.strip() else (docs[-1] if docs else None)
    if not doc:
        return {"status": "error", "message": "Dokumen tidak ditemukan di chat ini.", "documents": [d["doc_id"] for d in docs]}
    if not doc.get("text_uri"):
        return {"status": "unreadable", "doc_id": doc["doc_id"], "filename": doc["filename"],
                "message": doc.get("note") or "Isi dokumen tidak bisa dibaca sebagai teks."}
    text = _doc_text(doc["text_uri"])
    offset = max(0, int(offset or 0))
    chunk = text[offset:offset + PAGE_CHARS]
    nxt = offset + PAGE_CHARS if offset + PAGE_CHARS < len(text) else None
    return {"status": "ok", "doc_id": doc["doc_id"], "filename": doc["filename"], "jenis": doc.get("jenis"),
            "total_chars": len(text), "offset": offset, "next_offset": nxt, "text": chunk}


def document_instructions(doc_id: str, state, limit: int = 20000) -> str:
    """Teks dokumen untuk dipakai sebagai instruksi tambahan laporan (dipotong)."""
    from ..callbacks import _doc_text

    doc = next((d for d in state.get(DOCS_KEY, []) if d["doc_id"] == doc_id), None)
    if not doc or not doc.get("text_uri"):
        return ""
    return _doc_text(doc["text_uri"])[:limit]


def lihat_gambar(doc_ids: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Menampilkan gambar unggahan (JPG/PNG/WhatsApp Image, dll.) agar bisa Anda LIHAT pada langkah berikutnya.

    Gambar yang baru diunggah pada pesan ini sudah otomatis terlihat. Pakai tool ini untuk gambar dari pesan
    sebelumnya (mis. "seperti gambar tadi") atau bila perlu melihat ulang.

    Args:
        doc_ids: ID dokumen gambar, mis. ["d2", "d3"] (lihat list_documents; jenis "Gambar").
    """
    from .. import vision

    docs = vision.images_for(tool_context.state, doc_ids)
    if not docs:
        return {"status": "error", "message": "Gambar tidak ditemukan di chat ini.",
                "gambar_tersedia": [d["doc_id"] for d in tool_context.state.get(DOCS_KEY, []) if vision.is_image(d)]}
    tool_context.state[vision.SHOW_KEY] = [d["doc_id"] for d in docs]
    return {"status": "ok", "message": "Gambar dilampirkan; Anda akan melihatnya pada langkah berikutnya.",
            "gambar": [{"doc_id": d["doc_id"], "filename": d["filename"]} for d in docs]}


DOC_TOOLS = [list_documents, read_document, lihat_gambar]
