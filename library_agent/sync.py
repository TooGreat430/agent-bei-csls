"""Sinkronisasi katalog dengan isi folder dokumen (ge-docs-datastore).

Dipanggil otomatis setiap kali user membuka katalog atau memilih dokumen, sehingga katalog
selalu sama dengan isi folder:
- File baru di folder         -> metadata diekstrak Gemini, lalu ditambahkan ke katalog.
- File yang isinya diganti    -> metadata diekstrak ulang (koreksi user tetap dipertahankan),
                                 lalu diindeks ulang.
- File yang dihapus dari folder -> dihapus dari katalog dan data store.

Pemeriksaan folder hanya membaca daftar file (tanpa mengunduh), jadi cepat jika tidak ada
perubahan. Hanya file baru/berubah yang dibaca Gemini.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import catalog, ingest, metadata
from .config import SUPPORTED_MIME_TYPES, live

logger = logging.getLogger(__name__)

FOLDER_UPLOADER = "folder"
EXT_TO_MIME = {ext: mime for mime, ext in SUPPORTED_MIME_TYPES.items()}
EXT_TO_MIME[".htm"] = "text/html"


def mime_for(name: str) -> str | None:
    dot = name.rfind(".")
    return EXT_TO_MIME.get(name[dot:].lower()) if dot >= 0 else None


# ==========================================================================
# Logika murni (bisa diuji tanpa GCP)
# ==========================================================================
def plan_sync(files: list[dict[str, Any]], records: list[dict[str, Any]], max_mb: float) -> dict[str, list]:
    """Bandingkan isi folder dengan katalog.

    files: [{source_uri, file_name, size_bytes, generation, content_hash}]
    Hasil: new, changed (pasangan file+record), removed (record), skipped ({file_name, reason}).
    """
    by_uri = {r["source_uri"]: r for r in records if r.get("source_uri")}
    file_uris = {f["source_uri"] for f in files}
    hash_owner = {r.get("content_hash"): r for r in records if r.get("content_hash")}
    plan: dict[str, list] = {"new": [], "changed": [], "removed": [], "skipped": []}
    seen_hashes: dict[str, str] = {}

    for f in files:
        mime = mime_for(f["file_name"])
        size_mb = f["size_bytes"] / 1_048_576
        record = by_uri.get(f["source_uri"])
        if not mime:
            plan["skipped"].append({"file_name": f["file_name"], "reason": "format tidak didukung (hanya PDF, DOCX, PPTX, HTML, TXT)"})
            continue
        if size_mb > max_mb:
            plan["skipped"].append({"file_name": f["file_name"], "reason": f"ukuran {size_mb:.1f} MB melebihi batas {max_mb:g} MB"})
            continue
        item = dict(f, mime_type=mime)
        if record:
            if record.get("source_generation") in (None, ""):
                continue  # sedang diproses upload lewat chat
            if record.get("source_generation") != f["generation"]:
                plan["changed"].append({"file": item, "record": record})
            continue
        owner = hash_owner.get(f["content_hash"])
        if owner and owner.get("source_uri") in file_uris:
            plan["skipped"].append({"file_name": f["file_name"], "reason": f"isi sama persis dengan {owner.get('file_name')}"})
            continue
        if f["content_hash"] in seen_hashes:
            plan["skipped"].append({"file_name": f["file_name"], "reason": f"isi sama persis dengan {seen_hashes[f['content_hash']]}"})
            continue
        seen_hashes[f["content_hash"]] = f["file_name"]
        plan["new"].append(item)

    plan["removed"] = [
        r for uri, r in by_uri.items()
        if uri not in file_uris and r.get("source_generation") not in (None, "")
    ]
    return plan


def order_new(extracted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Urutkan agar dokumen berjudul sama ditambahkan dari yang paling lama (jadi versi berurutan)."""
    return sorted(extracted, key=lambda e: (catalog.normalize_title(e["meta"]["title"]),
                                            e["meta"]["doc_type"], e["meta"]["doc_date"],
                                            e["meta"]["version"]))


# ==========================================================================
# Sinkronisasi
# ==========================================================================
def _extract(item: dict[str, Any]) -> dict[str, Any]:
    try:
        s = metadata.suggest({"staged_uri": item["source_uri"], "filename": item["file_name"],
                              "mime_type": item["mime_type"]})
        return {"file": item, "meta": s["metadata"], "uncertain": s["uncertain_fields"],
                "defaults": s["defaults_used"], "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ekstraksi gagal: %s", item["file_name"])
        base = item["file_name"].rsplit(".", 1)[0].replace("_", " ")
        return {"file": item, "meta": {"title": base, "doc_type": "", "version": "1", "doc_date": ""},
                "uncertain": ["title", "doc_type", "doc_date"], "defaults": ["version"], "error": str(exc)}


def sync_folder() -> dict[str, Any]:
    """Samakan katalog dengan isi folder. Aman dipanggil berulang dan bersamaan."""
    try:
        ingest.cleanup_staging()
    except Exception:  # noqa: BLE001
        logger.exception("Pembersihan staging gagal")

    files = ingest.list_source_files()
    plan = plan_sync(files, catalog.all_records(), live("max_file_mb"))
    summary: dict[str, Any] = {"added": [], "updated": [], "removed": [], "skipped": plan["skipped"],
                               "remaining": 0, "in_sync": False}

    for record in plan["removed"]:
        try:
            ingest.delete_from_datastore(record["doc_key"])
        except Exception:  # noqa: BLE001
            logger.exception("Gagal menghapus %s dari data store", record["doc_key"])
        if catalog.remove(record["doc_key"]):
            summary["removed"].append({k: record.get(k) for k in ("title", "version", "file_name")})

    limit = live("folder_batch_size")
    work = [("changed", c["file"], c["record"]) for c in plan["changed"]] + [("new", f, None) for f in plan["new"]]
    summary["remaining"] = max(0, len(work) - limit)
    work = work[:limit]
    if not work:
        summary["in_sync"] = not plan["removed"]
        return summary

    with ThreadPoolExecutor(max_workers=5) as pool:
        extracted = list(pool.map(lambda w: dict(_extract(w[1]), kind=w[0], record=w[2]), work))

    to_index: list[dict[str, Any]] = []
    for e in [x for x in extracted if x["kind"] == "changed"]:
        rec, f = e["record"], e["file"]
        merged = catalog.merge_extracted(rec, e["meta"])
        manual = set(rec.get("manual_fields") or [])
        updated = catalog.update_fields(rec["doc_key"], {
            **merged, "source_generation": f["generation"], "content_hash": f["content_hash"],
            "file_name": f["file_name"], "mime_type": f["mime_type"], "status": "indexing",
            "needs_review": sorted(set(e["uncertain"]) - manual),
        })
        if updated:
            to_index.append(updated)
            summary["updated"].append(catalog.public_view(updated))

    for e in order_new([x for x in extracted if x["kind"] == "new"]):
        f, m = e["file"], e["meta"]
        created = catalog.create(
            doc_key=catalog.new_doc_key(), title=m["title"], doc_type=m["doc_type"], version=m["version"],
            doc_date=m["doc_date"], uploader=FOLDER_UPLOADER, source_uri=f["source_uri"],
            file_name=f["file_name"], mime_type=f["mime_type"], content_hash=f["content_hash"],
            source_generation=f["generation"], needs_review=e["uncertain"],
            version_is_default="version" in e["defaults"],
        )
        if created:
            to_index.append(created)
            summary["added"].append(catalog.public_view(created))

    for start in range(0, len(to_index), 100):
        chunk = to_index[start:start + 100]
        try:
            op_name = ingest.import_many([
                {"doc_key": r["doc_key"], "gcs_uri": r["source_uri"], "mime_type": r["mime_type"],
                 "title": r["title"], "doc_type": r["doc_type"], "version": r["version"], "doc_date": r["doc_date"]}
                for r in chunk
            ])
            catalog.set_import_operation([r["doc_key"] for r in chunk], op_name)
        except Exception:  # noqa: BLE001
            logger.exception("Impor ke data store gagal")
            for r in chunk:
                catalog.update_status(r["doc_key"], "failed")
    return summary
