"""Tool ADK untuk Research sub-agent.

Setiap fungsi publik di file ini menjadi tool yang bisa dipanggil agent.
Docstring dibaca oleh model sebagai deskripsi tool, jadi tulis dengan jelas.
"""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import catalog, ingest, insights, library_admin, metadata, search
from ..callbacks import PENDING_KEY
from ..clients import get_user_id
from ..config import settings

logger = logging.getLogger(__name__)

ACTIVE_KEY = "active_docs"
WORKSPACE_KEY = "workspace"
DEFAULT_WORKSPACE = "umum"


def _active(tool_context: ToolContext) -> list[str]:
    return list(tool_context.state.get(ACTIVE_KEY, []))


def _workspace(tool_context: ToolContext) -> str:
    return tool_context.state.get(WORKSPACE_KEY, DEFAULT_WORKSPACE)


def _active_summary(doc_keys: list[str]) -> list[dict[str, Any]]:
    meta = catalog.get_many(doc_keys) if doc_keys else {}
    return [catalog.public_view(meta[k]) for k in doc_keys if k in meta]


# ==========================================================================
# Katalog perpustakaan
# ==========================================================================
def list_library(
    doc_type: str = "", keyword: str = "", include_old_versions: bool = False
) -> dict[str, Any]:
    """Menampilkan katalog dokumen di perpustakaan bersama.

    Args:
        doc_type: Filter jenis dokumen, misalnya "BEI" atau "CSLS". Kosongkan untuk semua.
        keyword: Kata kunci pada judul dokumen. Kosongkan untuk semua.
        include_old_versions: True untuk ikut menampilkan versi lama.

    Returns:
        Daftar dokumen beserta doc_key, judul, jenis, versi, tanggal, pengunggah, dan status.
    """
    docs = catalog.list_documents(doc_type, keyword, include_old_versions)
    return {"status": "ok", "count": len(docs), "documents": docs}


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
    """Mengganti seluruh daftar dokumen aktif di chat ini.

    Gunakan saat user memilih sekumpulan dokumen sebagai sumber utama.

    Args:
        doc_keys: Daftar doc_key dari katalog (lihat list_library).
    """
    keys = list(dict.fromkeys(doc_keys))
    if len(keys) > settings.max_active_docs:
        return {"status": "error",
                "message": f"Maksimal {settings.max_active_docs} dokumen aktif per chat."}
    meta = catalog.get_many(keys)
    missing = [k for k in keys if k not in meta]
    if missing:
        return {"status": "error", "message": "Dokumen tidak ditemukan di katalog.", "missing": missing}
    tool_context.state[ACTIVE_KEY] = keys
    return {"status": "ok", "active_documents": _active_summary(keys)}


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
    keys = _active(tool_context)
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
                 version: str, doc_date: str, previous: dict[str, Any] | None) -> dict[str, Any]:
    """Simpan file staging ke perpustakaan: GCS library/, data store, dan katalog."""
    doc_key = catalog.new_doc_key()
    family_id = previous["family_id"] if previous else doc_key
    gcs_uri = ingest.promote_to_library(upload["staged_uri"], doc_type, doc_key, upload["filename"])
    op_name = ingest.import_to_datastore(
        doc_key=doc_key, gcs_uri=gcs_uri, mime_type=upload["mime_type"], title=title,
        doc_type=doc_type, version=version, doc_date=doc_date,
    )
    record = catalog.create_version(
        doc_key=doc_key, family_id=family_id, title=title, doc_type=doc_type,
        version=version, doc_date=doc_date, uploader=get_user_id(tool_context),
        gcs_uri=gcs_uri, mime_type=upload["mime_type"], content_hash=upload["content_hash"],
        import_operation=op_name, previous_doc_key=previous["doc_key"] if previous else None,
    )
    tool_context.state[PENDING_KEY] = [
        p for p in tool_context.state.get(PENDING_KEY, []) if p["upload_id"] != upload["upload_id"]
    ]
    return record


SAVED_MESSAGE = ("Dokumen masuk perpustakaan dan sedang diindeks (biasanya beberapa menit). "
                 "Selama indexing, isi file masih bisa dibaca langsung dari lampiran di chat ini.")


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
        settings.allowed_doc_types,
    )
    if missing:
        return {"status": "needs_input", "missing_or_invalid": missing, "current": final,
                "message": (f"Tanyakan ke user nilai untuk: {', '.join(missing)}. Jenis harus salah satu "
                            f"dari {', '.join(settings.allowed_doc_types)}; tanggal berformat YYYY-MM-DD.")}

    existing = catalog.find_latest_by_title(final["title"], final["doc_type"])
    if existing and not as_new_version:
        return {"status": "needs_input", "missing_or_invalid": ["title"],
                "existing_document": catalog.public_view(existing),
                "message": "Judul sudah dipakai dokumen lain. Minta user memberi judul yang berbeda."}

    record = _save_upload(tool_context, upload, final["title"], final["doc_type"],
                          final["version"], final["doc_date"], previous=existing)
    return {"status": "ok", "document": record, "message": SAVED_MESSAGE}


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
    if doc_type and doc_type.strip().upper() not in settings.allowed_doc_types:
        return {"status": "error",
                "message": f"Jenis dokumen harus salah satu dari: {', '.join(settings.allowed_doc_types)}"}

    updated = catalog.update_metadata(
        doc_key,
        {"title": title.strip(), "doc_type": doc_type.strip(), "version": version.strip(),
         "doc_date": doc_date.strip()},
    )
    if not updated:
        return {"status": "error", "message": "Dokumen tidak ditemukan."}
    # Perbarui metadata di data store juga (impor ulang dengan ID yang sama).
    ingest.import_to_datastore(
        doc_key=doc_key, gcs_uri=updated["gcs_uri"], mime_type=updated["mime_type"],
        title=updated["title"], doc_type=updated["doc_type"], version=updated["version"],
        doc_date=updated["doc_date"], collection=updated.get("collection", "umum"),
    )
    return {"status": "ok", "document": catalog.public_view(updated)}


def delete_document(doc_key: str, tool_context: ToolContext, confirmed: bool = False) -> dict[str, Any]:
    """Menghapus dokumen dari perpustakaan bersama. Semua user boleh menghapus.

    WAJIB dua langkah: panggil dulu dengan confirmed=False untuk menampilkan dokumen yang akan
    dihapus, lalu panggil lagi dengan confirmed=True HANYA setelah user menjawab ya.
    File asli di folder sumber tidak ikut terhapus.

    Args:
        doc_key: doc_key dokumen yang akan dihapus.
        confirmed: True hanya jika user sudah mengonfirmasi penghapusan.
    """
    record = catalog.get(doc_key)
    if not record:
        return {"status": "error", "message": "Dokumen tidak ditemukan."}
    if not confirmed:
        return {"status": "needs_confirmation", "document": catalog.public_view(record),
                "message": ("Tanyakan ke user: yakin menghapus dokumen ini dari perpustakaan? "
                            "Dokumen tidak akan bisa dipakai oleh semua user.")}
    result = library_admin.delete_document(doc_key, get_user_id(tool_context))
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
    result = ingest.check_import_operation(record["import_operation"])
    if not result["done"]:
        return {"status": "ok", "indexing_status": "indexing"}
    new_status = "failed" if result["error"] else "ready"
    catalog.update_status(doc_key, new_status)
    return {"status": "ok", "indexing_status": new_status, "error": result["error"]}


# ==========================================================================
# Workspace & insight
# ==========================================================================
def set_workspace(name: str, tool_context: ToolContext) -> dict[str, Any]:
    """Memilih workspace, misalnya "BEI Study 2026". Insight di workspace bisa dilihat semua user.

    Args:
        name: Nama workspace.
    """
    tool_context.state[WORKSPACE_KEY] = name.strip() or DEFAULT_WORKSPACE
    items = insights.list_for(_workspace(tool_context))
    return {"status": "ok", "workspace": _workspace(tool_context), "insight_count": len(items)}


def save_insight(title: str, content: str, citations: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Menyimpan insight penting dari diskusi ke workspace aktif (terlihat oleh semua user di workspace).

    Args:
        title: Judul singkat insight.
        content: Isi insight, ditulis lengkap dan berdiri sendiri.
        citations: Label sitasi pendukung, misalnya ["[Studi CSLS 2026, v2, hal. 12]"].
    """
    item = insights.save(
        owner=get_user_id(tool_context), workspace=_workspace(tool_context),
        title=title, content=content, citations=citations, doc_keys=_active(tool_context),
    )
    return {"status": "ok", "workspace": _workspace(tool_context), "insight": item}


def list_insights(tool_context: ToolContext) -> dict[str, Any]:
    """Menampilkan semua insight di workspace aktif, dari semua user, beserta pembuatnya."""
    items = insights.list_for(_workspace(tool_context))
    return {"status": "ok", "workspace": _workspace(tool_context), "insights": items}


def update_insight(insight_id: str, tool_context: ToolContext, title: str = "", content: str = "") -> dict[str, Any]:
    """Mengubah judul dan/atau isi insight. Hanya pembuat insight yang boleh mengubah.

    Args:
        insight_id: ID insight.
        title: Judul baru (kosongkan jika tidak diubah).
        content: Isi baru (kosongkan jika tidak diubah).
    """
    result = insights.update(get_user_id(tool_context), _workspace(tool_context),
                             insight_id, title or None, content or None)
    if result["status"] == "forbidden":
        result["message"] = f"Hanya pembuat insight ({result.get('owner')}) yang bisa mengubahnya."
    return result


def delete_insight(insight_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """Menghapus insight. Hanya pembuat insight yang boleh menghapus.

    Args:
        insight_id: ID insight.
    """
    result = insights.delete(get_user_id(tool_context), _workspace(tool_context), insight_id)
    if result["status"] == "forbidden":
        result["message"] = f"Hanya pembuat insight ({result.get('owner')}) yang bisa menghapusnya."
    return result


RESEARCH_TOOLS = [
    list_library,
    get_active_documents,
    set_active_documents,
    add_active_documents,
    remove_active_documents,
    search_active_documents,
    list_pending_uploads,
    extract_upload_metadata,
    confirm_upload,
    update_document_metadata,
    delete_document,
    check_indexing_status,
    set_workspace,
    save_insight,
    list_insights,
    update_insight,
    delete_insight,
]
