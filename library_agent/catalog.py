"""Katalog perpustakaan: cermin dari isi folder dokumen (LIB_SOURCE_FOLDER).

Folder `ge-docs-datastore` adalah SUMBER KEBENARAN. Setiap dokumen di katalog menunjuk
ke satu file di folder itu. Katalog hanya menyimpan metadata (judul, jenis, versi, tanggal)
dan status indexing, sebagai satu file JSON di bucket:

    gs://<LIB_BUCKET>/<LIB_CATALOG_PATH>   (mis. ge-docs-agent/catalog/index.json)

Format:
    {"documents": {"<doc_key>": {record}, ...}}

Field record:
    doc_key, family_id, title, title_norm, doc_type, version, doc_date,
    uploader, uploaded_at, source_uri, source_generation, file_name, mime_type,
    content_hash, is_latest, status ("indexing" | "ready" | "failed"), import_operation,
    collection, needs_review (field yang perlu dicek user), manual_fields (field yang
    sudah dikoreksi user dan tidak boleh ditimpa ekstraksi ulang)

`doc_key` == ID dokumen di data store.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from . import store
from .metadata import next_version
from .config import settings

META_FIELDS = ("title", "doc_type", "version", "doc_date")


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def new_doc_key() -> str:
    # ID data store: [a-zA-Z0-9-_], maks 63 karakter
    return f"doc-{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict[str, Any]:
    return {"documents": {}}


def _load() -> dict[str, dict[str, Any]]:
    return store.read_json(settings.catalog_path, _empty).get("documents", {})


def public_view(record: dict[str, Any]) -> dict[str, Any]:
    """Field yang aman dan berguna untuk ditampilkan ke model/user."""
    keys = (
        "doc_key", "title", "doc_type", "version", "doc_date", "file_name",
        "uploader", "uploaded_at", "status", "is_latest", "needs_review",
    )
    return {k: record.get(k) for k in keys}


# ==========================================================================
# Logika murni (bisa diuji tanpa GCP)
# ==========================================================================
def filter_documents(
    records: list[dict[str, Any]], doc_type: str = "", keyword: str = "",
    include_old_versions: bool = False,
) -> list[dict[str, Any]]:
    out = records
    if doc_type:
        out = [r for r in out if r.get("doc_type") == doc_type.upper()]
    if not include_old_versions:
        out = [r for r in out if r.get("is_latest")]
    if keyword:
        kw = keyword.lower()
        out = [r for r in out if kw in r.get("title_norm", "") or kw in (r.get("file_name") or "").lower()]
    return sorted(out, key=lambda r: (r.get("doc_type", ""), r.get("title_norm", ""), str(r.get("version", ""))))


def latest_by_title(records: list[dict[str, Any]], title: str, doc_type: str) -> dict[str, Any] | None:
    norm, dtype = normalize_title(title), (doc_type or "").upper()
    if not norm or not dtype:
        return None
    for r in records:
        if r.get("title_norm") == norm and r.get("doc_type") == dtype and r.get("is_latest"):
            return r
    return None


def pick_new_latest(records: list[dict[str, Any]], family_id: str, exclude_key: str) -> str | None:
    """Versi yang menjadi terbaru setelah `exclude_key` dihapus: yang paling akhir diunggah."""
    candidates = [r for r in records if r.get("family_id") == family_id and r.get("doc_key") != exclude_key]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("uploaded_at", ""))["doc_key"]


def merge_extracted(record: dict[str, Any], extracted: dict[str, str]) -> dict[str, str]:
    """Metadata baru hasil ekstraksi ulang, TANPA menimpa field yang pernah dikoreksi user."""
    manual = set(record.get("manual_fields") or [])
    return {k: (record.get(k, "") if k in manual else extracted.get(k, record.get(k, ""))) for k in META_FIELDS}


# ==========================================================================
# Baca
# ==========================================================================
def all_records() -> list[dict[str, Any]]:
    return list(_load().values())


def get(doc_key: str) -> dict[str, Any] | None:
    return _load().get(doc_key)


def get_many(doc_keys: list[str]) -> dict[str, dict[str, Any]]:
    docs = _load()
    return {k: docs[k] for k in doc_keys if k in docs}


def list_documents(
    doc_type: str = "", keyword: str = "", include_old_versions: bool = False, limit: int = 100
) -> list[dict[str, Any]]:
    records = filter_documents(all_records(), doc_type, keyword, include_old_versions)
    return [public_view(r) for r in records[:limit]]


def find_by_hash(content_hash: str) -> dict[str, Any] | None:
    if not content_hash:
        return None
    return next((r for r in _load().values() if r.get("content_hash") == content_hash), None)


def find_latest_by_title(title: str, doc_type: str) -> dict[str, Any] | None:
    return latest_by_title(all_records(), title, doc_type)


# ==========================================================================
# Tulis
# ==========================================================================
def create(
    *,
    doc_key: str,
    title: str,
    doc_type: str,
    version: str,
    doc_date: str,
    uploader: str,
    source_uri: str,
    file_name: str,
    mime_type: str,
    content_hash: str,
    source_generation: str | None = None,
    needs_review: list[str] | None = None,
    collection: str = "umum",
    version_is_default: bool = False,
) -> dict[str, Any] | None:
    """Tambah dokumen. Jika judul+jenis sama dengan dokumen terbaru, dicatat sebagai versi baru
    (versi dinaikkan otomatis jika versinya tidak tertulis atau sama dengan versi sebelumnya).

    Mengembalikan record baru, atau None jika file (source_uri) sudah tercatat
    (mencegah dobel saat dua proses berjalan bersamaan).
    """
    def mutate(index: dict[str, Any]) -> dict[str, Any] | None:
        docs = index.setdefault("documents", {})
        if any(r.get("source_uri") == source_uri for r in docs.values()):
            return None
        previous = latest_by_title(list(docs.values()), title, doc_type)
        final_version = version
        if previous and (version_is_default or version == previous.get("version")):
            final_version = next_version(previous.get("version") or "1")
        record = {
            "doc_key": doc_key,
            "family_id": previous["family_id"] if previous else doc_key,
            "title": title.strip(),
            "title_norm": normalize_title(title),
            "doc_type": (doc_type or "").upper(),
            "version": final_version,
            "doc_date": doc_date,
            "uploader": uploader,
            "uploaded_at": _now(),
            "source_uri": source_uri,
            "source_generation": source_generation,
            "file_name": file_name,
            "mime_type": mime_type,
            "content_hash": content_hash,
            "is_latest": True,
            "status": "indexing",
            "import_operation": "",
            "collection": collection,
            "needs_review": needs_review or [],
            "manual_fields": [],
        }
        if previous:
            docs[previous["doc_key"]]["is_latest"] = False
        docs[doc_key] = record
        return dict(record)

    return store.update_json(settings.catalog_path, _empty, mutate)


def update_fields(doc_key: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Ubah field teknis (status, generation, import_operation, dll.). Mengembalikan record baru."""
    def mutate(index: dict[str, Any]) -> dict[str, Any] | None:
        doc = index.get("documents", {}).get(doc_key)
        if not doc:
            return None
        doc.update(fields)
        if "title" in fields:
            doc["title_norm"] = normalize_title(doc["title"])
        return dict(doc)

    return store.update_json(settings.catalog_path, _empty, mutate)


def set_import_operation(doc_keys: list[str], op_name: str) -> None:
    def mutate(index: dict[str, Any]) -> None:
        for key in doc_keys:
            doc = index.get("documents", {}).get(key)
            if doc:
                doc["import_operation"] = op_name
                doc["status"] = "indexing"
                doc["last_import_at"] = _now()

    store.update_json(settings.catalog_path, _empty, mutate)


def update_status(doc_key: str, status: str) -> None:
    update_fields(doc_key, {"status": status})


def update_metadata(doc_key: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    """Koreksi metadata oleh user. Field yang dikoreksi tidak akan ditimpa ekstraksi ulang."""
    def mutate(index: dict[str, Any]) -> dict[str, Any] | None:
        doc = index.get("documents", {}).get(doc_key)
        if not doc:
            return None
        manual = set(doc.get("manual_fields") or [])
        review = set(doc.get("needs_review") or [])
        for key, value in changes.items():
            if key in META_FIELDS and value:
                doc[key] = value.upper() if key == "doc_type" else value
                manual.add(key)
                review.discard(key)
        doc["title_norm"] = normalize_title(doc["title"])
        doc["manual_fields"], doc["needs_review"] = sorted(manual), sorted(review)
        return dict(doc)

    return store.update_json(settings.catalog_path, _empty, mutate)


def remove(doc_key: str) -> dict[str, Any] | None:
    """Hapus record. Jika itu versi terbaru, versi sebelumnya naik menjadi terbaru.

    Mengembalikan {"record": record_terhapus, "promoted": doc_key_pengganti | None} atau None.
    """
    def mutate(index: dict[str, Any]) -> dict[str, Any] | None:
        docs = index.get("documents", {})
        doc = docs.pop(doc_key, None)
        if not doc:
            return None
        promoted = None
        if doc.get("is_latest"):
            promoted = pick_new_latest(list(docs.values()), doc.get("family_id", ""), doc_key)
            if promoted:
                docs[promoted]["is_latest"] = True
        return {"record": doc, "promoted": promoted}

    return store.update_json(settings.catalog_path, _empty, mutate)
