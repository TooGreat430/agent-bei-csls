"""Katalog perpustakaan, disimpan sebagai satu file JSON di Cloud Storage.

Lokasi: gs://<LIB_BUCKET>/<LIB_CATALOG_PATH>   (default: catalog/index.json)

Format:
    {"documents": {"<doc_key>": {record}, ...}}

Satu record = satu versi dokumen. `doc_key` == ID dokumen di data store.
Field record:
    doc_key, family_id, title, title_norm, doc_type, version, doc_date,
    uploader, uploaded_at, gcs_uri, mime_type, content_hash,
    is_latest, status ("indexing" | "ready" | "failed" | "deleted"), import_operation,
    collection, source_uri (asal file jika hasil impor folder), deleted_by, deleted_at

Dokumen yang dihapus tidak dibuang dari indeks, tetapi ditandai status "deleted"
(tombstone). Tujuannya agar impor folder berkala tidak memasukkan ulang dokumen
yang sengaja dihapus user.

Satu file indeks cukup untuk ratusan sampai beberapa ribu dokumen (sekitar 0,5 KB
per record), dan daftar katalog cukup dibaca sekali.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from . import store
from .config import settings


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def new_doc_key() -> str:
    # ID data store: [a-zA-Z0-9-_], maks 63 karakter
    return f"doc-{uuid.uuid4().hex}"


def _empty() -> dict[str, Any]:
    return {"documents": {}}


def _load() -> dict[str, dict[str, Any]]:
    return store.read_json(settings.catalog_path, _empty).get("documents", {})


def public_view(record: dict[str, Any]) -> dict[str, Any]:
    """Field yang aman dan berguna untuk ditampilkan ke model/user."""
    keys = (
        "doc_key", "title", "doc_type", "version", "doc_date",
        "uploader", "uploaded_at", "status", "is_latest", "collection",
    )
    return {k: record.get(k) for k in keys}


# --------------------------------------------------------------------------
# Logika murni (bisa diuji tanpa GCP)
# --------------------------------------------------------------------------
def is_active(record: dict[str, Any]) -> bool:
    return record.get("status") != "deleted"


def filter_documents(
    records: list[dict[str, Any]], doc_type: str = "", keyword: str = "",
    include_old_versions: bool = False,
) -> list[dict[str, Any]]:
    out = [r for r in records if is_active(r)]
    if doc_type:
        out = [r for r in out if r.get("doc_type") == doc_type.upper()]
    if not include_old_versions:
        out = [r for r in out if r.get("is_latest")]
    if keyword:
        kw = keyword.lower()
        out = [r for r in out if kw in r.get("title_norm", "")]
    return sorted(out, key=lambda r: (r.get("doc_type", ""), r.get("title_norm", ""), str(r.get("version", ""))))


def latest_by_title(records: list[dict[str, Any]], title: str, doc_type: str) -> dict[str, Any] | None:
    norm, dtype = normalize_title(title), doc_type.upper()
    for r in records:
        if (r.get("title_norm") == norm and r.get("doc_type") == dtype
                and r.get("is_latest") and is_active(r)):
            return r
    return None


def pick_new_latest(records: list[dict[str, Any]], family_id: str, exclude_key: str) -> str | None:
    """Versi yang menjadi terbaru setelah `exclude_key` dihapus: yang paling akhir diunggah."""
    candidates = [
        r for r in records
        if r.get("family_id") == family_id and r.get("doc_key") != exclude_key and is_active(r)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("uploaded_at", ""))["doc_key"]


# --------------------------------------------------------------------------
# Baca
# --------------------------------------------------------------------------
def all_records() -> list[dict[str, Any]]:
    """Semua record, termasuk yang sudah dihapus (untuk script impor)."""
    return list(_load().values())


def get(doc_key: str) -> dict[str, Any] | None:
    record = _load().get(doc_key)
    return record if record and is_active(record) else None


def get_many(doc_keys: list[str]) -> dict[str, dict[str, Any]]:
    docs = _load()
    return {k: docs[k] for k in doc_keys if k in docs and is_active(docs[k])}


def list_documents(
    doc_type: str = "", keyword: str = "", include_old_versions: bool = False, limit: int = 50
) -> list[dict[str, Any]]:
    records = filter_documents(list(_load().values()), doc_type, keyword, include_old_versions)
    return [public_view(r) for r in records[:limit]]


def find_by_hash(content_hash: str) -> dict[str, Any] | None:
    return next(
        (r for r in _load().values() if r.get("content_hash") == content_hash and is_active(r)), None
    )


def find_latest_by_title(title: str, doc_type: str) -> dict[str, Any] | None:
    return latest_by_title(list(_load().values()), title, doc_type)


# --------------------------------------------------------------------------
# Tulis
# --------------------------------------------------------------------------
def create_version(
    *,
    doc_key: str,
    family_id: str,
    title: str,
    doc_type: str,
    version: str,
    doc_date: str,
    uploader: str,
    gcs_uri: str,
    mime_type: str,
    content_hash: str,
    import_operation: str,
    previous_doc_key: str | None = None,
    collection: str = "umum",
    source_uri: str | None = None,
) -> dict[str, Any]:
    """Simpan versi baru dan (jika ada) turunkan versi sebelumnya dari status terbaru."""
    record = {
        "doc_key": doc_key,
        "family_id": family_id,
        "title": title.strip(),
        "title_norm": normalize_title(title),
        "doc_type": doc_type.upper(),
        "version": version,
        "doc_date": doc_date,
        "uploader": uploader,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gcs_uri": gcs_uri,
        "mime_type": mime_type,
        "content_hash": content_hash,
        "is_latest": True,
        "status": "indexing",
        "import_operation": import_operation,
        "collection": collection,
        "source_uri": source_uri,
    }

    def mutate(index: dict[str, Any]) -> None:
        docs = index.setdefault("documents", {})
        docs[doc_key] = record
        if previous_doc_key and previous_doc_key in docs:
            docs[previous_doc_key]["is_latest"] = False

    store.update_json(settings.catalog_path, _empty, mutate)
    return public_view(record)


def update_status(doc_key: str, status: str) -> None:
    def mutate(index: dict[str, Any]) -> None:
        doc = index.get("documents", {}).get(doc_key)
        if doc:
            doc["status"] = status

    store.update_json(settings.catalog_path, _empty, mutate)


def update_metadata(doc_key: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    """Ubah judul/jenis/versi/tanggal satu dokumen. Mengembalikan record baru atau None."""
    allowed = {"title", "doc_type", "version", "doc_date"}

    def mutate(index: dict[str, Any]) -> dict[str, Any] | None:
        doc = index.get("documents", {}).get(doc_key)
        if not doc or not is_active(doc):
            return None
        for key, value in changes.items():
            if key in allowed and value:
                doc[key] = value.upper() if key == "doc_type" else value
        doc["title_norm"] = normalize_title(doc["title"])
        return dict(doc)

    return store.update_json(settings.catalog_path, _empty, mutate)


def mark_deleted(doc_key: str, deleted_by: str) -> dict[str, Any] | None:
    """Tandai dokumen terhapus. Jika itu versi terbaru, versi sebelumnya naik menjadi terbaru.

    Mengembalikan {"record": record_terhapus, "promoted": doc_key_versi_pengganti | None}.
    """
    def mutate(index: dict[str, Any]) -> dict[str, Any] | None:
        docs = index.get("documents", {})
        doc = docs.get(doc_key)
        if not doc or not is_active(doc):
            return None
        was_latest = doc.get("is_latest")
        doc.update({
            "status": "deleted", "is_latest": False, "deleted_by": deleted_by,
            "deleted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        promoted = None
        if was_latest:
            promoted = pick_new_latest(list(docs.values()), doc.get("family_id", ""), doc_key)
            if promoted:
                docs[promoted]["is_latest"] = True
        return {"record": dict(doc), "promoted": promoted}

    return store.update_json(settings.catalog_path, _empty, mutate)
