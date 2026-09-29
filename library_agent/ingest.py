"""Upload dokumen dari chat ke perpustakaan.

Alur:
1. Callback menyimpan lampiran chat ke GCS `staging/` (stage_bytes / stage_gcs_uri).
2. Setelah metadata dikonfirmasi user, file disalin ke `library/` dan diimpor
   ke data store (import_to_datastore) secara incremental.
3. Status indexing bisa dicek lewat check_import_operation.
"""
from __future__ import annotations

import hashlib
import logging
import re
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    path = f"{settings.staging_prefix}/{session_id}/{sha256(data)[:12]}_{fname}"
    blob = storage_client().bucket(settings.bucket).blob(path)
    blob.upload_from_string(data, content_type=mime_type)
    return {
        "staged_uri": f"gs://{settings.bucket}/{path}",
        "filename": fname,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "content_hash": sha256(data),
    }


def stage_gcs_uri(uri: str, filename: str, mime_type: str, session_id: str) -> dict[str, Any]:
    """Jika GE mengirim lampiran sebagai file_data gs://..., salin ke staging."""
    src_bucket, src_path = parse_gcs_uri(uri)
    data = storage_client().bucket(src_bucket).blob(src_path).download_as_bytes()
    return stage_bytes(data, filename or src_path.rsplit("/", 1)[-1], mime_type, session_id)


# --------------------------------------------------------------------------
# Masuk perpustakaan
# --------------------------------------------------------------------------
def promote_to_library(staged_uri: str, doc_type: str, doc_key: str, filename: str) -> str:
    src_bucket_name, src_path = parse_gcs_uri(staged_uri)
    client = storage_client()
    src_bucket = client.bucket(src_bucket_name)
    dst_path = f"{settings.library_prefix}/{doc_type.upper()}/{doc_key}/{filename}"
    src_bucket.copy_blob(src_bucket.blob(src_path), client.bucket(settings.bucket), dst_path)
    return f"gs://{settings.bucket}/{dst_path}"


def import_to_datastore(
    *, doc_key: str, gcs_uri: str, mime_type: str, title: str, doc_type: str,
    version: str, doc_date: str, collection: str = "umum",
) -> str:
    """Impor satu dokumen (incremental). Mengembalikan nama long-running operation."""
    from google.cloud import discoveryengine_v1 as de

    document = de.Document(
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
    request = de.ImportDocumentsRequest(
        parent=branch_path(),
        inline_source=de.ImportDocumentsRequest.InlineSource(documents=[document]),
        reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
    )
    operation = document_client().import_documents(request=request)
    op_name = operation.operation.name
    logger.info("import started doc_key=%s op=%s", doc_key, op_name)
    return op_name


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
