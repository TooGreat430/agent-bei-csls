"""Konfigurasi terpusat. Semua nilai dibaca dari environment variable.

Lihat .env.example untuk daftar lengkap dan contoh nilai.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Environment variable {name} wajib diisi.")
    return value or ""


@dataclass(frozen=True)
class Settings:
    # --- Project & region -------------------------------------------------
    project_id: str = field(
        default_factory=lambda: _env("LIB_PROJECT_ID") or _env("GOOGLE_CLOUD_PROJECT", "")
    )
    # Lokasi Discovery Engine / data store GE: "global", "us", atau "eu"
    search_location: str = field(default_factory=lambda: _env("LIB_SEARCH_LOCATION", "global"))
    # Lokasi Vertex AI untuk model Gemini (dipakai composer laporan)
    gemini_location: str = field(default_factory=lambda: _env("LIB_GEMINI_LOCATION", "global"))

    # --- Data store perpustakaan -----------------------------------------
    datastore_id: str = field(default_factory=lambda: _env("LIB_DATASTORE_ID", "perpustakaan-dokumen"))
    serving_config_id: str = field(default_factory=lambda: _env("LIB_SERVING_CONFIG", "default_config"))
    # "CHUNKS" (butuh chunking/layout parser di data store) atau "DOCUMENTS"
    search_result_mode: str = field(default_factory=lambda: _env("LIB_SEARCH_RESULT_MODE", "CHUNKS"))

    # --- Cloud Storage ------------------------------------------------------
    bucket: str = field(default_factory=lambda: _env("LIB_BUCKET", ""))
    library_prefix: str = field(default_factory=lambda: _env("LIB_LIBRARY_PREFIX", "library"))
    staging_prefix: str = field(default_factory=lambda: _env("LIB_STAGING_PREFIX", "staging"))
    template_prefix: str = field(default_factory=lambda: _env("LIB_TEMPLATE_PREFIX", "templates"))
    report_prefix: str = field(default_factory=lambda: _env("LIB_REPORT_PREFIX", "reports"))

    # "gcs" (produksi) atau "local" (pengembangan: baca dari folder ./templates)
    template_source: str = field(default_factory=lambda: _env("LIB_TEMPLATE_SOURCE", "gcs"))
    local_template_dir: str = field(
        default_factory=lambda: _env(
            "LIB_LOCAL_TEMPLATE_DIR",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        )
    )

    # Bucket terpisah untuk laporan (disarankan): user diberi izin baca HANYA di bucket ini,
    # sehingga katalog dan insight milik user lain di bucket utama tidak ikut terbuka.
    report_bucket: str = field(default_factory=lambda: _env("LIB_REPORT_BUCKET") or _env("LIB_BUCKET", ""))

    # --- Penyimpanan data aplikasi di GCS (pengganti database) --------------
    catalog_path: str = field(default_factory=lambda: _env("LIB_CATALOG_PATH", "catalog/index.json"))
    insight_prefix: str = field(default_factory=lambda: _env("LIB_INSIGHT_PREFIX", "insights"))

    # --- Model ------------------------------------------------------------------
    model_fast: str = field(default_factory=lambda: _env("LIB_MODEL_FAST", "gemini-3.5-flash"))
    model_pro: str = field(default_factory=lambda: _env("LIB_MODEL_PRO", "gemini-3.5-flash"))

    # --- Aturan perpustakaan -------------------------------------------------
    allowed_doc_types: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            t.strip().upper() for t in _env("LIB_DOC_TYPES", "BEI,CSLS").split(",") if t.strip()
        )
    )
    # Penjelasan singkat tiap jenis dokumen, membantu Gemini mengklasifikasi saat upload.
    # Contoh: "BEI: <penjelasan>; CSLS: <penjelasan>"
    doc_type_hints: str = field(default_factory=lambda: _env("LIB_DOC_TYPE_HINTS", ""))
    max_active_docs: int = field(default_factory=lambda: int(_env("LIB_MAX_ACTIVE_DOCS", "10")))
    company_name: str = field(default_factory=lambda: _env("LIB_COMPANY_NAME", "Nama Perusahaan"))


SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

settings = Settings()
