"""Katalog perpustakaan, disimpan sebagai satu file JSON di Cloud Storage.

Lokasi: gs://<LIB_BUCKET>/<LIB_CATALOG_PATH>   (default: catalog/index.json)

Format:
    {"documents": {"<doc_key>": {record}, ...}}

Satu record = satu versi dokumen. `doc_key` == ID dokumen di data store.
Field record:
    doc_key, family_id, title, title_norm, doc_type, version, doc_date,
    uploader, uploaded_at, gcs_uri, mime_type, content_hash,
    is_latest, status ("indexing" | "ready" | "failed"), import_operation, collection

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
        out = [r for r in out if kw in r.get("title_norm", "")]
    return sorted(out, key=lambda r: (r.get("doc_type", ""), r.get("title_norm", ""), str(r.get("version", ""))))


def latest_by_title(records: list[dict[str, Any]], title: str, doc_type: str) -> dict[str, Any] | None:
    norm, dtype = normalize_title(title), doc_type.upper()
    for r in records:
        if r.get("title_norm") == norm and r.get("doc_type") == dtype and r.get("is_latest"):
            return r
    return None


# --------------------------------------------------------------------------
# Baca
# --------------------------------------------------------------------------
def get(doc_key: str) -> dict[str, Any] | None:
    return _load().get(doc_key)


def get_many(doc_keys: list[str]) -> dict[str, dict[str, Any]]:
    docs = _load()
    return {k: docs[k] for k in doc_keys if k in docs}


def list_documents(
    doc_type: str = "", keyword: str = "", include_old_versions: bool = False, limit: int = 50
) -> list[dict[str, Any]]:
    records = filter_documents(list(_load().values()), doc_type, keyword, include_old_versions)
    return [public_view(r) for r in records[:limit]]


def find_by_hash(content_hash: str) -> dict[str, Any] | None:
    return next((r for r in _load().values() if r.get("content_hash") == content_hash), None)


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
        if not doc:
            return None
        for key, value in changes.items():
            if key in allowed and value:
                doc[key] = value.upper() if key == "doc_type" else value
        doc["title_norm"] = normalize_title(doc["title"])
        return dict(doc)

    return store.update_json(settings.catalog_path, _empty, mutate)
