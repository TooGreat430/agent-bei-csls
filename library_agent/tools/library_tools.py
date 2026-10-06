"""Tool ADK untuk Research sub-agent.

Setiap fungsi publik di file ini menjadi tool yang bisa dipanggil agent.
Docstring dibaca oleh model sebagai deskripsi tool, jadi tulis dengan jelas.
"""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import catalog, ingest, insights, library_admin, metadata, search, sync
from ..callbacks import PENDING_KEY
from ..clients import get_user_id
from ..config import settings, live

logger = logging.getLogger(__name__)

ACTIVE_KEY = "active_docs"


def _active(tool_context: ToolContext) -> list[str]:
    return list(tool_context.state.get(ACTIVE_KEY, []))


def _active_summary(doc_keys: list[str]) -> list[dict[str, Any]]:
    meta = catalog.get_many(doc_keys) if doc_keys else {}
    return [catalog.public_view(meta[k]) for k in doc_keys if k in meta]


def _prune_active(tool_context: ToolContext) -> list[str]:
    """Buang dokumen aktif yang sudah tidak ada di katalog (mis. file dihapus dari folder)."""
    keys = _active(tool_context)
    valid = [k for k in keys if k in catalog.get_many(keys)]
    if valid != keys:
        tool_context.state[ACTIVE_KEY] = valid
    return valid


# ==========================================================================
# Katalog perpustakaan
# ==========================================================================
def _sync() -> dict[str, Any]:
    """Samakan katalog dengan folder dokumen. Kegagalan sinkronisasi tidak menghentikan proses."""
    try:
        summary = sync.sync_folder()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sinkronisasi folder gagal")
        return {"error": f"Folder dokumen tidak bisa diperiksa: {exc}"}
    if summary.get("in_sync") and not summary["skipped"]:
        return {"in_sync": True}
    return summary


def list_library(
    doc_type: str = "", keyword: str = "", include_old_versions: bool = False
) -> dict[str, Any]:
    """Menampilkan katalog perpustakaan. Katalog OTOMATIS disamakan dulu dengan isi folder dokumen.

    Args:
        doc_type: Filter jenis dokumen, misalnya "BEI" atau "CSLS". Kosongkan untuk semua.
        keyword: Kata kunci pada judul atau nama file. Kosongkan untuk semua.
        include_old_versions: True untuk ikut menampilkan versi lama.

    Returns:
        folder_sync (perubahan dari folder sejak terakhir dicek) dan daftar dokumen.
    """
    sync_result = _sync()
    docs = catalog.list_documents(doc_type, keyword, include_old_versions)
    return {"status": "ok", "folder_sync": sync_result, "count": len(docs), "documents": docs}


def sync_library() -> dict[str, Any]:
    """Menyamakan katalog dengan isi folder dokumen sekarang juga (mis. "cek dokumen baru di folder")."""
    return {"status": "ok", "folder_sync": _sync()}


# ==========================================================================
# Dokumen aktif (sentralisasi chat)
# ==========================================================================
def get_active_documents(tool_context: ToolContext) -> dict[str, Any]:
    """Menampilkan dokumen yang sedang aktif di chat ini.

    Semua jawaban di chat ini hanya boleh bersumber dari dokumen aktif.
    """
    keys = _active(tool_context)
    return {"status": "ok", "count": len(keys), "active_documents": _active_summary(keys)}


def set_active_documents(doc_keys: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Mengganti seluruh daftar dokumen aktif di chat ini. Katalog disamakan dulu dengan folder.

    Gunakan saat user memilih sekumpulan dokumen sebagai sumber utama.

    Args:
        doc_keys: Daftar doc_key dari katalog (lihat list_library).
    """
    sync_result = _sync()
    keys = list(dict.fromkeys(doc_keys))
    if len(keys) > live("max_active_docs"):
        return {"status": "error",
                "message": f"Maksimal {live("max_active_docs")} dokumen aktif per chat."}
    meta = catalog.get_many(keys)
    missing = [k for k in keys if k not in meta]
    if missing:
        return {"status": "error", "folder_sync": sync_result, "missing": missing,
                "message": "Sebagian dokumen tidak ada lagi di folder/katalog. Tampilkan katalog terbaru ke user."}
    tool_context.state[ACTIVE_KEY] = keys
    return {"status": "ok", "folder_sync": sync_result, "active_documents": _active_summary(keys)}


def add_active_documents(doc_keys: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Menambahkan dokumen ke daftar aktif tanpa menghapus dokumen yang sudah aktif.

    Args:
        doc_keys: doc_key yang ingin ditambahkan.
    """
    current = _active(tool_context)
    return set_active_documents(current + [k for k in doc_keys if k not in current], tool_context)


def remove_active_documents(doc_keys: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Mengeluarkan dokumen dari daftar aktif.

    Args:
        doc_keys: doc_key yang ingin dikeluarkan.
    """
    keys = [k for k in _active(tool_context) if k not in set(doc_keys)]
    tool_context.state[ACTIVE_KEY] = keys
    return {"status": "ok", "active_documents": _active_summary(keys)}


def search_active_documents(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """Mencari informasi HANYA di dokumen aktif chat ini.

    Wajib dipakai untuk menjawab pertanyaan tentang isi dokumen.

    Args:
        query: Pertanyaan atau kata kunci pencarian.

    Returns:
        Potongan isi dokumen beserta label sitasi, misalnya "[Studi CSLS 2026, v2, hal. 12]".
    """
    keys = _prune_active(tool_context)
    if not keys:
        return {"status": "no_active_documents",
                "message": "Belum ada dokumen aktif. Minta user memilih dokumen dari katalog."}
    try:
        results = search.search_documents(query, keys)
    except Exception as exc:  # noqa: BLE001
        logger.exception("search gagal")
        return {"status": "error", "message": str(exc)}
    if not results:
        return {"status": "not_found",
                "message": "Tidak ditemukan di dokumen aktif. Sampaikan ini ke user, jangan mengarang."}
    return {"status": "ok", "results": results}


# ==========================================================================
# Upload ke perpustakaan
# ==========================================================================
def list_pending_uploads(tool_context: ToolContext) -> dict[str, Any]:
    """Menampilkan file yang dilampirkan user di chat dan belum dimasukkan ke perpustakaan."""
    pending = tool_context.state.get(PENDING_KEY, [])
    rejected = tool_context.state.get("temp:rejected_uploads", [])
    view = [{k: p[k] for k in ("upload_id", "filename", "mime_type", "size_bytes")} for p in pending]
    return {"status": "ok", "pending_uploads": view, "rejected_uploads": rejected}


def _find_upload(tool_context: ToolContext, upload_id: str) -> dict[str, Any] | None:
    return next((p for p in tool_context.state.get(PENDING_KEY, []) if p["upload_id"] == upload_id), None)


def _save_upload(tool_context: ToolContext, upload: dict[str, Any], title: str, doc_type: str,
                 version: str, doc_date: str) -> dict[str, Any]:
    """Simpan lampiran ke folder dokumen (ge-docs-datastore), katalog, dan data store."""
    from google.api_core.exceptions import PreconditionFailed

    doc_key = catalog.new_doc_key()
    for _ in range(3):
        dest = ingest.plan_destination(upload["filename"])
        record = catalog.create(
            doc_key=doc_key, title=title, doc_type=doc_type, version=version, doc_date=doc_date,
            uploader=get_user_id(tool_context), source_uri=dest["source_uri"], file_name=dest["file_name"],
            mime_type=upload["mime_type"], content_hash=upload["content_hash"], source_generation=None,
        )
        if not record:
            continue
        try:
            generation = ingest.copy_staged_to(upload["staged_uri"], dest["source_uri"])
            break
        except PreconditionFailed:
            catalog.remove(doc_key)
    else:
        raise RuntimeError("Nama file di folder dokumen bentrok, coba lagi.")

    catalog.update_fields(doc_key, {"source_generation": generation})
    op_name = ingest.import_to_datastore(
        doc_key=doc_key, gcs_uri=dest["source_uri"], mime_type=upload["mime_type"], title=record["title"],
        doc_type=record["doc_type"], version=record["version"], doc_date=doc_date,
    )
    catalog.set_import_operation([doc_key], op_name)
    _drop_pending(tool_context, upload["upload_id"])
    return dict(record, source_generation=generation)


SAVED_MESSAGE = ("Dokumen disimpan ke folder ge-docs-datastore, masuk perpustakaan, dan sedang diindeks "
                 "(biasanya beberapa menit). Selama indexing, isi file masih bisa dibaca langsung dari "
                 "lampiran di chat ini.")


def _set_pending_field(tool_context: ToolContext, upload_id: str, key: str, value: Any) -> None:
    pending = list(tool_context.state.get(PENDING_KEY, []))
    for item in pending:
        if item["upload_id"] == upload_id:
            item[key] = value
    tool_context.state[PENDING_KEY] = pending


def _drop_pending(tool_context: ToolContext, upload_id: str) -> None:
    tool_context.state[PENDING_KEY] = [
        p for p in tool_context.state.get(PENDING_KEY, []) if p["upload_id"] != upload_id
    ]


def extract_upload_metadata(upload_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """Membaca lampiran dan mengekstrak judul, jenis, versi, dan tanggal dokumen. BELUM menyimpan.

    Panggil untuk setiap lampiran baru, lalu tampilkan hasilnya ke user untuk dikonfirmasi.
    Dokumen baru disimpan setelah user mengonfirmasi lewat confirm_upload.

    Args:
        upload_id: ID dari list_pending_uploads, misalnya "up1".
    """
    upload = _find_upload(tool_context, upload_id)
    if not upload:
        return {"status": "error", "message": f"upload_id {upload_id} tidak ditemukan."}

    duplicate = catalog.find_by_hash(upload["content_hash"])
    if duplicate:
        _drop_pending(tool_context, upload_id)
        return {"status": "duplicate", "message": "File yang persis sama sudah ada di perpustakaan.",
                "existing": catalog.public_view(duplicate)}

    try:
        suggestion = metadata.suggest(upload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ekstraksi metadata gagal")
        suggestion = {"metadata": {"title": "", "doc_type": "", "version": "1", "doc_date": ""},
                      "summary": "", "uncertain_fields": ["title", "doc_type", "doc_date"],
                      "defaults_used": ["version"], "error": str(exc)}

    meta = suggestion["metadata"]
    result: dict[str, Any] = {
        "status": "needs_confirmation",
        "upload_id": upload_id,
        "filename": upload["filename"],
        "extracted": meta,
        "summary": suggestion["summary"],
        "not_found_in_document": suggestion["defaults_used"],
        "unsure": suggestion["uncertain_fields"],
    }

    existing = catalog.find_latest_by_title(meta["title"], meta["doc_type"]) if meta["doc_type"] else None
    if existing:
        if "version" in suggestion["defaults_used"] or meta["version"] == existing.get("version"):
            meta["version"] = metadata.next_version(existing.get("version", "1"))
        result["existing_document"] = catalog.public_view(existing)
        result["note"] = "Judul ini sudah ada di perpustakaan. Jika dikonfirmasi, dicatat sebagai versi baru."

    _set_pending_field(tool_context, upload_id, "suggested", meta)
    result["message"] = (
        "Tampilkan SEMUA field extracted ke user (judul, jenis, versi, tanggal) dan tanyakan apakah "
        "sudah benar. Tandai field di 'unsure' sebagai perlu diisi/dicek, dan sebutkan field di "
        "'not_found_in_document' sebagai nilai default. Jangan menyimpan sebelum user menjawab."
    )
    return result


def confirm_upload(
    upload_id: str,
    tool_context: ToolContext,
    title: str = "",
    doc_type: str = "",
    version: str = "",
    doc_date: str = "",
    as_new_version: bool = True,
) -> dict[str, Any]:
    """Menyimpan lampiran ke perpustakaan SETELAH user mengonfirmasi hasil ekstraksi.

    Jika user menjawab semua sudah benar, panggil tanpa field tambahan.
    Jika user mengoreksi, isi HANYA field yang dikoreksi. Field lain memakai hasil ekstraksi.

    Args:
        upload_id: ID lampiran.
        title: Judul koreksi dari user (kosongkan jika tidak dikoreksi).
        doc_type: Jenis koreksi dari user (kosongkan jika tidak dikoreksi).
        version: Versi koreksi dari user (kosongkan jika tidak dikoreksi).
        doc_date: Tanggal koreksi dari user, YYYY-MM-DD (kosongkan jika tidak dikoreksi).
        as_new_version: Jika judul sudah ada di perpustakaan, True = simpan sebagai versi baru.
            False jika user menyatakan ini dokumen berbeda (user harus memberi judul lain).
    """
    upload = _find_upload(tool_context, upload_id)
    if not upload:
        return {"status": "error", "message": f"upload_id {upload_id} tidak ditemukan."}
    if "suggested" not in upload:
        return {"status": "error", "message": "Panggil extract_upload_metadata terlebih dahulu."}

    final, missing = metadata.apply_corrections(
        upload["suggested"],
        {"title": title, "doc_type": doc_type, "version": version, "doc_date": doc_date},
        live("allowed_doc_types"),
    )
    if missing:
        return {"status": "needs_input", "missing_or_invalid": missing, "current": final,
                "message": (f"Tanyakan ke user nilai untuk: {', '.join(missing)}. Jenis harus salah satu "
                            f"dari {', '.join(live("allowed_doc_types"))}; tanggal berformat YYYY-MM-DD.")}

    existing = catalog.find_latest_by_title(final["title"], final["doc_type"])
    if existing and not as_new_version:
        return {"status": "needs_input", "missing_or_invalid": ["title"],
                "existing_document": catalog.public_view(existing),
                "message": "Judul sudah dipakai dokumen lain. Minta user memberi judul yang berbeda."}

    record = _save_upload(tool_context, upload, final["title"], final["doc_type"],
                          final["version"], final["doc_date"])
    return {"status": "ok", "document": catalog.public_view(record), "message": SAVED_MESSAGE}


def update_document_metadata(
    doc_key: str, tool_context: ToolContext, title: str = "", doc_type: str = "",
    version: str = "", doc_date: str = "",
) -> dict[str, Any]:
    """Mengoreksi metadata dokumen yang sudah ada di perpustakaan. Semua user boleh mengoreksi.

    Args:
        doc_key: doc_key dokumen.
        title: Judul baru (kosongkan jika tidak diubah).
        doc_type: Jenis baru (kosongkan jika tidak diubah).
        version: Versi baru (kosongkan jika tidak diubah).
        doc_date: Tanggal baru YYYY-MM-DD (kosongkan jika tidak diubah).
    """
    record = catalog.get(doc_key)
    if not record:
        return {"status": "error", "message": "Dokumen tidak ditemukan."}
    if doc_type and doc_type.strip().upper() not in live("allowed_doc_types"):
        return {"status": "error",
                "message": f"Jenis dokumen harus salah satu dari: {', '.join(live("allowed_doc_types"))}"}

    updated = catalog.update_metadata(
        doc_key,
        {"title": title.strip(), "doc_type": doc_type.strip(), "version": version.strip(),
         "doc_date": doc_date.strip()},
    )
    if not updated:
        return {"status": "error", "message": "Dokumen tidak ditemukan."}
    # Perbarui metadata di data store juga (impor ulang dengan ID yang sama).
    ingest.import_to_datastore(
        doc_key=doc_key, gcs_uri=updated["source_uri"], mime_type=updated["mime_type"],
        title=updated["title"], doc_type=updated["doc_type"], version=updated["version"],
        doc_date=updated["doc_date"], collection=updated.get("collection", "umum"),
    )
    return {"status": "ok", "document": catalog.public_view(updated)}


def delete_document(doc_key: str, tool_context: ToolContext, confirmed: bool = False) -> dict[str, Any]:
    """Menghapus dokumen dari perpustakaan bersama. Semua user boleh menghapus.

    WAJIB dua langkah: panggil dulu dengan confirmed=False untuk menampilkan dokumen yang akan
    dihapus, lalu panggil lagi dengan confirmed=True HANYA setelah user menjawab ya.
    File dokumen IKUT DIHAPUS dari folder ge-docs-datastore.

    Args:
        doc_key: doc_key dokumen yang akan dihapus.
        confirmed: True hanya jika user sudah mengonfirmasi penghapusan.
    """
    record = catalog.get(doc_key)
    if not record:
        return {"status": "error", "message": "Dokumen tidak ditemukan."}
    if not confirmed:
        return {"status": "needs_confirmation", "document": catalog.public_view(record),
                "message": ("Tanyakan ke user: yakin menghapus dokumen ini? File-nya juga akan dihapus "
                            "dari folder ge-docs-datastore dan tidak bisa dipakai semua user lagi.")}
    result = library_admin.delete_document(doc_key)
    tool_context.state[ACTIVE_KEY] = [k for k in _active(tool_context) if k != doc_key]
    return result


def check_indexing_status(doc_key: str) -> dict[str, Any]:
    """Mengecek apakah dokumen yang baru di-upload sudah selesai diindeks.

    Args:
        doc_key: doc_key dokumen.
    """
    record = catalog.get(doc_key)
    if not record:
        return {"status": "error", "message": "Dokumen tidak ditemukan."}
    if record.get("status") != "indexing":
        return {"status": "ok", "indexing_status": record.get("status")}
    if not record.get("import_operation"):
        return {"status": "ok", "indexing_status": "indexing"}
    result = ingest.check_import_operation(record["import_operation"])
    if not result["done"]:
        return {"status": "ok", "indexing_status": "indexing"}
    new_status = "failed" if result["error"] else "ready"
    catalog.update_status(doc_key, new_status)
    return {"status": "ok", "indexing_status": new_status, "error": result["error"]}


# ==========================================================================
# Insight (disimpan di dalam chat)
# ==========================================================================
def save_insight(title: str, content: str, citations: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Menyimpan temuan penting dari jawaban DOKUMEN sebagai insight di chat ini (bahan laporan).

    Args:
        title: Judul singkat insight.
        content: Isi insight, ditulis lengkap dan berdiri sendiri.
        citations: Label sitasi pendukung, misalnya ["[Studi CSLS 2026, v2, hal. 12]"].
    """
    item = insights.save(tool_context.state, get_user_id(tool_context), title, content, citations,
                         _active(tool_context))
    return {"status": "ok", "insight": item, "total_insight_di_chat": len(insights.list_for(tool_context.state))}


def list_insights(tool_context: ToolContext) -> dict[str, Any]:
    """Menampilkan insight yang sudah disimpan di chat ini."""
    return {"status": "ok", "insights": insights.list_for(tool_context.state)}


def update_insight(insight_id: str, tool_context: ToolContext, title: str = "", content: str = "") -> dict[str, Any]:
    """Mengubah judul dan/atau isi insight di chat ini.

    Args:
        insight_id: ID insight.
        title: Judul baru (kosongkan jika tidak diubah).
        content: Isi baru (kosongkan jika tidak diubah).
    """
    return insights.update(tool_context.state, insight_id, title or None, content or None)


def delete_insight(insight_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """Menghapus insight dari chat ini.

    Args:
        insight_id: ID insight.
    """
    return insights.delete(tool_context.state, insight_id)


RESEARCH_TOOLS = [
    list_library,
    get_active_documents,
    set_active_documents,
    add_active_documents,
    remove_active_documents,
    search_active_documents,
    sync_library,
    list_pending_uploads,
    extract_upload_metadata,
    confirm_upload,
    update_document_metadata,
    delete_document,
    check_indexing_status,
    save_insight,
    list_insights,
    update_insight,
    delete_insight,
]
