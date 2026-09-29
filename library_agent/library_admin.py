"""Operasi pengelolaan perpustakaan yang dipakai bersama oleh agent dan script impor."""
from __future__ import annotations

import logging
from typing import Any

from . import catalog, ingest

logger = logging.getLogger(__name__)


def delete_document(doc_key: str, deleted_by: str) -> dict[str, Any]:
    """Hapus dokumen dari perpustakaan.

    - Dihapus dari data store (tidak bisa ditemukan lagi saat tanya-jawab).
    - Ditandai "deleted" di katalog (agar impor folder berikutnya tidak memasukkannya lagi).
    - Salinan file di folder perpustakaan agent dihapus. File asli di folder sumber TIDAK dihapus.
    - Jika yang dihapus adalah versi terbaru, versi sebelumnya otomatis menjadi terbaru.
    """
    result = catalog.mark_deleted(doc_key, deleted_by)
    if not result:
        return {"status": "not_found"}
    record = result["record"]
    try:
        ingest.delete_from_datastore(doc_key)
    except Exception:  # noqa: BLE001
        logger.exception("Gagal menghapus %s dari data store", doc_key)
    try:
        ingest.delete_library_copy(record.get("gcs_uri", ""))
    except Exception:  # noqa: BLE001
        logger.exception("Gagal menghapus salinan file %s", record.get("gcs_uri"))
    promoted = catalog.get(result["promoted"]) if result["promoted"] else None
    return {
        "status": "ok",
        "deleted": catalog.public_view(record),
        "promoted_version": catalog.public_view(promoted) if promoted else None,
    }
