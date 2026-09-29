"""Impor dokumen dari folder bucket ke perpustakaan (dipakai scripts/import_folder.py).

Alur:
    scan  -> baca folder, klasifikasi file, Gemini mengekstrak metadata, tulis CSV untuk dicek
    run   -> impor baris CSV berstatus IMPORT ke data store + katalog
    prune -> (opsional) hapus dari perpustakaan dokumen yang file sumbernya sudah tidak ada

Impor ulang berkala aman dijalankan: file yang sudah pernah diimpor (isi sama) dilewati,
file yang isinya berubah dicatat sebagai versi baru, dan dokumen yang pernah dihapus user
lewat chat tidak dimasukkan lagi.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
from typing import Any, Iterable

from . import catalog, ingest, metadata
from .config import SUPPORTED_MIME_TYPES, settings

logger = logging.getLogger(__name__)

IMPORT_UPLOADER = "impor-folder"
EXT_TO_MIME = {ext: mime for mime, ext in SUPPORTED_MIME_TYPES.items()}
EXT_TO_MIME[".htm"] = "text/html"

CSV_COLUMNS = [
    "action", "title", "doc_type", "version", "doc_date",
    "note", "file_name", "size_mb", "source_uri", "sha256", "mime_type",
]


# ==========================================================================
# Logika murni (bisa diuji tanpa GCP)
# ==========================================================================
def mime_for(name: str) -> str | None:
    return EXT_TO_MIME.get(os.path.splitext(name)[1].lower())


def classify(files: list[dict[str, Any]], records: list[dict[str, Any]], max_mb: float) -> list[dict[str, Any]]:
    """Tentukan nasib setiap file sebelum ekstraksi metadata.

    files: [{source_uri, file_name, size_bytes, sha256}]
    records: semua record katalog, termasuk yang dihapus.
    Hasil: file + {"plan": "new"|"new_version"|"skip", "note": str, "previous_doc_key": str|None}
    """
    active_by_hash = {r["content_hash"]: r for r in records if r.get("status") != "deleted"}
    deleted_hashes = {r["content_hash"] for r in records if r.get("status") == "deleted"}
    active_by_source = {
        r["source_uri"]: r for r in records
        if r.get("source_uri") and r.get("status") != "deleted" and r.get("is_latest")
    }
    seen_in_batch: dict[str, str] = {}
    out = []
    for f in files:
        item = dict(f, plan="skip", note="", previous_doc_key=None, mime_type=mime_for(f["file_name"]))
        size_mb = f["size_bytes"] / 1_048_576
        if not item["mime_type"]:
            item["note"] = "Format tidak didukung (hanya PDF, DOCX, PPTX, HTML, TXT)"
        elif size_mb > max_mb:
            item["note"] = f"Ukuran {size_mb:.1f} MB melebihi batas {max_mb:g} MB"
        elif f["sha256"] in active_by_hash:
            item["note"] = f"Sudah ada di perpustakaan: {active_by_hash[f['sha256']].get('title')}"
        elif f["sha256"] in deleted_hashes:
            item["note"] = "Pernah dihapus user dari perpustakaan, tidak diimpor ulang"
        elif f["sha256"] in seen_in_batch:
            item["note"] = f"Isi sama persis dengan {seen_in_batch[f['sha256']]}"
        elif f["source_uri"] in active_by_source:
            prev = active_by_source[f["source_uri"]]
            item.update(plan="new_version", previous_doc_key=prev["doc_key"],
                        note=f"Isi file berubah sejak impor terakhir: versi baru dari '{prev.get('title')}' v{prev.get('version')}")
        else:
            item["plan"] = "new"
        if item["plan"] != "skip":
            seen_in_batch[f["sha256"]] = f["file_name"]
        out.append(item)
    return out


def annotate_title_collisions(rows: list[dict[str, Any]], records: list[dict[str, Any]]) -> None:
    """Beri catatan jika judul hasil ekstraksi sama dengan dokumen lain (akan jadi versi baru)."""
    latest = {
        (r.get("title_norm"), r.get("doc_type")): r for r in records
        if r.get("is_latest") and r.get("status") != "deleted"
    }
    batch_seen: dict[tuple, str] = {}
    for row in rows:
        if row["action"] != "IMPORT" or not row["title"] or not row["doc_type"]:
            continue
        key = (catalog.normalize_title(row["title"]), row["doc_type"].upper())
        notes = [row["note"]] if row["note"] else []
        if key in latest and "versi baru" not in row["note"]:
            notes.append(f"Judul sama dengan dokumen di perpustakaan (v{latest[key].get('version')}): dicatat sebagai versi baru")
        if key in batch_seen:
            notes.append(f"Judul sama dengan {batch_seen[key]} di impor ini: diurutkan sebagai versi")
        batch_seen.setdefault(key, row["file_name"])
        row["note"] = "; ".join(notes)


def validate_row(row: dict[str, str]) -> list[str]:
    _, missing = metadata.apply_corrections(
        {k: row.get(k, "") for k in ("title", "doc_type", "version", "doc_date")},
        {}, settings.allowed_doc_types,
    )
    return missing


def sort_for_versioning(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Urutkan agar dokumen berjudul sama diimpor dari yang paling lama ke paling baru."""
    return sorted(rows, key=lambda r: (catalog.normalize_title(r["title"]), r["doc_type"].upper(),
                                       r["doc_date"], r["version"]))


def write_csv(rows: Iterable[dict[str, Any]], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in rows]


# ==========================================================================
# Operasi GCS / Gemini
# ==========================================================================
def list_folder(source: str) -> list[dict[str, Any]]:
    """Daftar file di folder gs://bucket/prefix/ (rekursif), beserta hash isinya."""
    from .clients import storage_client

    bucket_name, prefix = ingest.parse_gcs_uri(source.rstrip("/") + "/")
    files = []
    for blob in storage_client().list_blobs(bucket_name, prefix=prefix):
        if blob.name.endswith("/"):
            continue
        name = blob.name.rsplit("/", 1)[-1]
        entry = {"source_uri": f"gs://{bucket_name}/{blob.name}", "file_name": name,
                 "size_bytes": blob.size or 0, "sha256": ""}
        if mime_for(name):
            entry["sha256"] = hashlib.sha256(blob.download_as_bytes()).hexdigest()
        else:
            entry["sha256"] = f"unsupported:{blob.name}"
        files.append(entry)
    return files


def scan(source: str, max_mb: float) -> list[dict[str, Any]]:
    records = catalog.all_records()
    planned = classify(list_folder(source), records, max_mb)
    rows = []
    for i, item in enumerate(planned, 1):
        row = {
            "file_name": item["file_name"], "source_uri": item["source_uri"],
            "size_mb": f"{item['size_bytes'] / 1_048_576:.2f}", "sha256": item["sha256"],
            "mime_type": item["mime_type"] or "", "title": "", "doc_type": "", "version": "",
            "doc_date": "", "note": item["note"],
        }
        if item["plan"] == "skip":
            row["action"] = "SKIP"
            rows.append(row)
            continue
        print(f"  [{i}/{len(planned)}] membaca {item['file_name']} ...", flush=True)
        try:
            suggestion = metadata.suggest({"staged_uri": item["source_uri"],
                                           "filename": item["file_name"], "mime_type": item["mime_type"]})
            row.update(suggestion["metadata"])
            notes = [item["note"]] if item["note"] else []
            if suggestion["uncertain_fields"]:
                notes.append("MOHON DICEK: " + ", ".join(suggestion["uncertain_fields"]))
            if suggestion["defaults_used"]:
                notes.append("tidak tertulis di dokumen (diisi default): " + ", ".join(suggestion["defaults_used"]))
            row["note"] = "; ".join(notes)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ekstraksi gagal: %s", item["file_name"])
            row["note"] = f"Metadata gagal dibaca ({exc}). Isi manual."
        row["action"] = "IMPORT"
        rows.append(row)
    annotate_title_collisions(rows, records)
    return rows


def run(rows: list[dict[str, str]], in_place: bool) -> dict[str, Any]:
    """Impor baris berstatus IMPORT. Mengembalikan ringkasan hasil."""
    to_import, errors = [], []
    for row in rows:
        if row.get("action", "").upper() != "IMPORT":
            continue
        row["doc_type"] = row.get("doc_type", "").upper()
        problems = validate_row(row)
        if problems:
            errors.append({"file": row.get("file_name"), "problem": "field kosong/tidak valid: " + ", ".join(problems)})
            continue
        if catalog.find_by_hash(row["sha256"]):
            errors.append({"file": row.get("file_name"), "problem": "sudah ada di perpustakaan (dilewati)"})
            continue
        to_import.append(row)

    to_import = sort_for_versioning(to_import)
    prepared = []
    for row in to_import:
        doc_key = catalog.new_doc_key()
        filename = ingest.safe_filename(row["file_name"], row["mime_type"])
        gcs_uri = row["source_uri"] if in_place else ingest.promote_to_library(
            row["source_uri"], row["doc_type"], doc_key, filename)
        prepared.append((row, doc_key, gcs_uri))

    created = []
    for start in range(0, len(prepared), 100):
        chunk = prepared[start:start + 100]
        op_name = ingest.import_many([
            {"doc_key": k, "gcs_uri": u, "mime_type": r["mime_type"], "title": r["title"],
             "doc_type": r["doc_type"], "version": r["version"], "doc_date": r["doc_date"]}
            for r, k, u in chunk
        ])
        for row, doc_key, gcs_uri in chunk:
            previous = _previous_for(row)
            version = row["version"]
            if previous and previous.get("version") == version:
                version = metadata.next_version(version)
                logger.info("%s: versi dinaikkan otomatis %s -> %s", row["file_name"], row["version"], version)
            record = catalog.create_version(
                doc_key=doc_key, family_id=previous["family_id"] if previous else doc_key,
                title=row["title"], doc_type=row["doc_type"], version=version,
                doc_date=row["doc_date"], uploader=IMPORT_UPLOADER, gcs_uri=gcs_uri,
                mime_type=row["mime_type"], content_hash=row["sha256"], import_operation=op_name,
                previous_doc_key=previous["doc_key"] if previous else None, source_uri=row["source_uri"],
            )
            created.append(record)
    return {"imported": created, "errors": errors}


def _previous_for(row: dict[str, str]) -> dict[str, Any] | None:
    by_source = next(
        (r for r in catalog.all_records()
         if r.get("source_uri") == row["source_uri"] and r.get("is_latest") and r.get("status") != "deleted"),
        None,
    )
    return by_source or catalog.find_latest_by_title(row["title"], row["doc_type"])


def prune(source: str) -> list[dict[str, Any]]:
    """Hapus dari perpustakaan dokumen hasil impor yang file sumbernya sudah tidak ada di folder."""
    from . import library_admin

    existing = {f["source_uri"] for f in list_folder(source)}
    prefix = source.rstrip("/") + "/"
    removed = []
    for record in catalog.all_records():
        uri = record.get("source_uri") or ""
        if record.get("status") != "deleted" and uri.startswith(prefix) and uri not in existing:
            removed.append(library_admin.delete_document(record["doc_key"], f"{IMPORT_UPLOADER}:prune"))
    return removed


def wait_for_indexing(records: list[dict[str, Any]], timeout_s: int = 1800) -> dict[str, int]:
    """Tunggu impor selesai lalu perbarui status katalog. Mengembalikan jumlah per status."""
    import time

    ops = {}
    for rec in records:
        full = catalog.get(rec["doc_key"])
        if full:
            ops.setdefault(full["import_operation"], []).append(rec["doc_key"])
    deadline = time.time() + timeout_s
    counts = {"ready": 0, "failed": 0, "indexing": 0}
    pending = dict(ops)
    while pending and time.time() < deadline:
        for op_name in list(pending):
            result = ingest.check_import_operation(op_name)
            if result["done"]:
                status = "failed" if result["error"] else "ready"
                for key in pending.pop(op_name):
                    catalog.update_status(key, status)
                    counts[status] += 1
        if pending:
            time.sleep(20)
    counts["indexing"] = sum(len(v) for v in pending.values())
    return counts
