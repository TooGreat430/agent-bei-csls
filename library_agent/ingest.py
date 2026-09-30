"""Operasi file dan data store.

- Lampiran chat disimpan SEMENTARA di `staging/` sampai user mengonfirmasi metadata,
  lalu DIPINDAHKAN ke folder dokumen (LIB_SOURCE_FOLDER, mis. ge-docs-datastore).
  File staging yang tidak pernah dikonfirmasi dibersihkan otomatis setelah 24 jam.
- Semua dokumen perpustakaan berada di folder dokumen. Tidak ada salinan di folder lain.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .clients import branch_path, document_client, storage_client
from .config import SUPPORTED_MIME_TYPES, settings

logger = logging.getLogger(__name__)


def safe_filename(name: str, mime_type: str = "") -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._") or "dokumen"
    ext = SUPPORTED_MIME_TYPES.get(mime_type, "")
    if ext and not base.lower().endswith(ext):
        base += ext
    return base[:120]


def md5_b64(data: bytes) -> str:
    """Hash isi file dengan format yang sama seperti `md5_hash` di Cloud Storage."""
    return base64.b64encode(hashlib.md5(data).digest()).decode()  # noqa: S324 (bukan untuk keamanan)


def source_folder_parts() -> tuple[str, str]:
    """(bucket, prefix/) dari folder dokumen."""
    from .config import live

    folder = live("source_folder")
    if not folder:
        raise RuntimeError("Folder dokumen belum dikonfigurasi (source_folder).")
    bucket, prefix = parse_gcs_uri(folder.rstrip("/") + "/")
    return bucket, prefix


def unique_name(existing: set[str], filename: str) -> str:
    """Nama file yang belum dipakai di folder: laporan.pdf -> laporan-2.pdf -> laporan-3.pdf."""
    if filename not in existing:
        return filename
    stem, dot, ext = filename.rpartition(".")
    stem, ext = (stem, f".{ext}") if dot else (filename, "")
    n = 2
    while f"{stem}-{n}{ext}" in existing:
        n += 1
    return f"{stem}-{n}{ext}"


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Bukan URI GCS: {uri}")
    bucket, _, path = uri[5:].partition("/")
    return bucket, path


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------
def stage_bytes(data: bytes, filename: str, mime_type: str, session_id: str) -> dict[str, Any]:
    fname = safe_filename(filename, mime_type)
    digest = hashlib.sha256(data).hexdigest()[:12]
    path = f"{settings.staging_prefix}/{session_id}/{digest}_{fname}"
    blob = storage_client().bucket(settings.bucket).blob(path)
    blob.upload_from_string(data, content_type=mime_type)
    return {
        "staged_uri": f"gs://{settings.bucket}/{path}",
        "filename": fname,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "content_hash": md5_b64(data),
    }


def stage_gcs_uri(uri: str, filename: str, mime_type: str, session_id: str) -> dict[str, Any]:
    """Jika GE mengirim lampiran sebagai file_data gs://..., salin ke staging."""
    src_bucket, src_path = parse_gcs_uri(uri)
    data = storage_client().bucket(src_bucket).blob(src_path).download_as_bytes()
    return stage_bytes(data, filename or src_path.rsplit("/", 1)[-1], mime_type, session_id)


# --------------------------------------------------------------------------
# Folder dokumen
# --------------------------------------------------------------------------
def list_source_files() -> list[dict[str, Any]]:
    """Semua file di folder dokumen (rekursif), tanpa mengunduh isinya."""
    bucket, prefix = source_folder_parts()
    files = []
    for blob in storage_client().list_blobs(bucket, prefix=prefix):
        if blob.name.endswith("/"):
            continue
        files.append({
            "source_uri": f"gs://{bucket}/{blob.name}",
            "file_name": blob.name.rsplit("/", 1)[-1],
            "size_bytes": blob.size or 0,
            "generation": str(blob.generation),
            "content_hash": blob.md5_hash or f"crc32c:{blob.crc32c}",
        })
    return files


def plan_destination(filename: str) -> dict[str, str]:
    """Tentukan lokasi file baru di folder dokumen (nama belum dipakai)."""
    bucket_name, prefix = source_folder_parts()
    existing = {b.name[len(prefix):] for b in storage_client().list_blobs(bucket_name, prefix=prefix)
                if "/" not in b.name[len(prefix):]}
    name = unique_name(existing, filename)
    return {"source_uri": f"gs://{bucket_name}/{prefix}{name}", "file_name": name}


def copy_staged_to(staged_uri: str, dest_uri: str) -> str:
    """Salin file staging ke lokasi tujuan (tidak menimpa file yang sudah ada), lalu hapus staging.

    Mengembalikan generation file tujuan. Error PreconditionFailed jika tujuan sudah ada.
    """
    client = storage_client()
    src_bucket_name, src_path = parse_gcs_uri(staged_uri)
    dst_bucket_name, dst_path = parse_gcs_uri(dest_uri)
    src_bucket = client.bucket(src_bucket_name)
    new_blob = src_bucket.copy_blob(src_bucket.blob(src_path), client.bucket(dst_bucket_name), dst_path,
                                    if_generation_match=0)
    src_bucket.blob(src_path).delete()
    return str(new_blob.generation)


def delete_source_file(source_uri: str) -> bool:
    """Hapus file dari folder dokumen. Hanya berlaku untuk file DI DALAM folder dokumen."""
    from google.api_core.exceptions import NotFound

    bucket_name, prefix = source_folder_parts()
    bucket, path = parse_gcs_uri(source_uri)
    if bucket != bucket_name or not path.startswith(prefix):
        return False
    try:
        storage_client().bucket(bucket).blob(path).delete()
    except NotFound:
        pass
    return True


def cleanup_staging(max_age_hours: int = 24) -> int:
    """Hapus lampiran chat yang tidak pernah dikonfirmasi (lebih dari `max_age_hours`)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    removed = 0
    for blob in storage_client().list_blobs(settings.bucket, prefix=settings.staging_prefix.rstrip("/") + "/"):
        if blob.time_created and blob.time_created < cutoff:
            blob.delete()
            removed += 1
    return removed


def _build_document(*, doc_key: str, gcs_uri: str, mime_type: str, title: str, doc_type: str,
                    version: str, doc_date: str, collection: str = "umum"):
    from google.cloud import discoveryengine_v1 as de

    return de.Document(
        id=doc_key,
        struct_data={
            "doc_key": doc_key,
            "title": title,
            "doc_type": doc_type.upper(),
            "version": version,
            "doc_date": doc_date,
            "collection": collection,
        },
        content=de.Document.Content(uri=gcs_uri, mime_type=mime_type),
    )


def import_many(documents: list[dict[str, Any]]) -> str:
    """Impor beberapa dokumen sekaligus (incremental, maks 100 per panggilan).

    Setiap item berisi: doc_key, gcs_uri, mime_type, title, doc_type, version, doc_date,
    dan opsional collection. Mengembalikan nama long-running operation.
    """
    from google.cloud import discoveryengine_v1 as de

    if not documents:
        raise ValueError("Tidak ada dokumen untuk diimpor.")
    if len(documents) > 100:
        raise ValueError("Maksimal 100 dokumen per impor.")
    request = de.ImportDocumentsRequest(
        parent=branch_path(),
        inline_source=de.ImportDocumentsRequest.InlineSource(
            documents=[_build_document(**d) for d in documents]
        ),
        reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
    )
    operation = document_client().import_documents(request=request)
    op_name = operation.operation.name
    logger.info("import started docs=%d op=%s", len(documents), op_name)
    return op_name


def import_to_datastore(
    *, doc_key: str, gcs_uri: str, mime_type: str, title: str, doc_type: str,
    version: str, doc_date: str, collection: str = "umum",
) -> str:
    """Impor satu dokumen (incremental). Mengembalikan nama long-running operation."""
    return import_many([{
        "doc_key": doc_key, "gcs_uri": gcs_uri, "mime_type": mime_type, "title": title,
        "doc_type": doc_type, "version": version, "doc_date": doc_date, "collection": collection,
    }])


def delete_from_datastore(doc_key: str) -> None:
    """Hapus dokumen dari data store. Tidak error jika dokumen sudah tidak ada."""
    from google.api_core.exceptions import NotFound

    try:
        document_client().delete_document(name=f"{branch_path()}/documents/{doc_key}")
    except NotFound:
        logger.info("doc %s sudah tidak ada di data store", doc_key)


def check_import_operation(op_name: str) -> dict[str, Any]:
    """Cek status operasi impor. Hasil: {"done": bool, "error": str | None}."""
    from google.longrunning import operations_pb2

    op = document_client().get_operation(operations_pb2.GetOperationRequest(name=op_name))
    if not op.done:
        return {"done": False, "error": None}
    if op.HasField("error") and op.error.code != 0:
        return {"done": True, "error": op.error.message}
    # Operasi bisa "sukses" tetapi dokumennya gagal diproses (mis. file rusak).
    if op.HasField("response"):
        from google.cloud import discoveryengine_v1 as de

        try:
            resp = de.ImportDocumentsResponse.deserialize(op.response.value)
            if resp.error_samples:
                return {"done": True, "error": resp.error_samples[0].message}
        except Exception:  # noqa: BLE001
            logger.debug("Tidak bisa membaca ImportDocumentsResponse", exc_info=True)
    return {"done": True, "error": None}
