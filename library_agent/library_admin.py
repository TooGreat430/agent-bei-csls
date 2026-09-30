"""Operasi pengelolaan perpustakaan yang dipakai agent."""
from __future__ import annotations

import logging
from typing import Any

from . import catalog, ingest

logger = logging.getLogger(__name__)


def delete_document(doc_key: str) -> dict[str, Any]:
    """Hapus dokumen dari perpustakaan: file di folder dokumen, data store, dan katalog.

    Karena folder dokumen adalah sumber kebenaran, file ikut dihapus dari folder.
    Jika yang dihapus adalah versi terbaru, versi sebelumnya otomatis menjadi terbaru.
    """
    record = catalog.get(doc_key)
    if not record:
        return {"status": "not_found"}
    try:
        ingest.delete_source_file(record.get("source_uri", ""))
    except Exception:  # noqa: BLE001
        logger.exception("Gagal menghapus file %s", record.get("source_uri"))
        return {"status": "error", "message": "File di folder dokumen tidak bisa dihapus."}
    try:
        ingest.delete_from_datastore(doc_key)
    except Exception:  # noqa: BLE001
        logger.exception("Gagal menghapus %s dari data store", doc_key)
    result = catalog.remove(doc_key) or {"record": record, "promoted": None}
    promoted = catalog.get(result["promoted"]) if result["promoted"] else None
    return {
        "status": "ok",
        "deleted": catalog.public_view(result["record"]),
        "promoted_version": catalog.public_view(promoted) if promoted else None,
    }
