"""Konfigurasi terpusat. Semua nilai dibaca dari environment variable.

Lihat .env.example untuk daftar lengkap dan contoh nilai.
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
import time
from dataclasses import dataclass, field
from typing import Any


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Environment variable {name} wajib diisi.")
    return value or ""


def _internal(sub: str) -> str:
    """Lokasi di dalam folder kerja agent (LIB_INTERNAL_FOLDER, default: ge-docs-agent)."""
    root = _env("LIB_INTERNAL_FOLDER", "ge-docs-agent").strip("/")
    return f"{root}/{sub}" if root else sub


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
    staging_prefix: str = field(default_factory=lambda: _env("LIB_STAGING_PREFIX") or _internal("staging"))
    data_file_prefix: str = field(default_factory=lambda: _env("LIB_DATA_FILE_PREFIX") or _internal("data-files"))
    template_prefix: str = field(default_factory=lambda: _env("LIB_TEMPLATE_PREFIX") or _internal("templates"))
    report_prefix: str = field(default_factory=lambda: _env("LIB_REPORT_PREFIX") or _internal("reports"))

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
    catalog_path: str = field(default_factory=lambda: _env("LIB_CATALOG_PATH") or _internal("catalog/index.json"))
    insight_prefix: str = field(default_factory=lambda: _env("LIB_INSIGHT_PREFIX") or _internal("insights"))

    # --- Data Agent BigQuery (Conversational Analytics) -----------------------
    data_agent: str = field(default_factory=lambda: _env(
        "LIB_DATA_AGENT",
        "projects/ptpl-land-dev/locations/global/dataAgents/agent_4df3074b-9d7e-4f9f-993b-b3969b8a2095"))
    data_agent_billing_project: str = field(default_factory=lambda: _env(
        "LIB_DATA_AGENT_BILLING_PROJECT") or _env("LIB_PROJECT_ID") or _env("GOOGLE_CLOUD_PROJECT", ""))
    data_agent_location: str = field(default_factory=lambda: _env("LIB_DATA_AGENT_LOCATION", "global"))
    # Data BigQuery dipanggil atas nama user (OAuth Gemini Enterprise) atau service account agent.
    # data_auth_mode: "user" | "service_account". data_auth_id: ID Authorization di GE.
    data_auth_mode: str = field(default_factory=lambda: _env("LIB_DATA_AUTH_MODE", "service_account"))
    data_auth_id: str = field(default_factory=lambda: _env("LIB_DATA_AUTH_ID", "mia-bigquery"))

    # --- Data Agent industri (B2B) & laporan industri ------------------------------
    data_agent_industry: str = field(default_factory=lambda: _env(
        "LIB_DATA_AGENT_INDUSTRY",
        "projects/ptpl-land-dev/locations/global/dataAgents/agent_04f517f4-e06b-44e8-b0af-d55792ef5222"))
    industry_table: str = field(default_factory=lambda: _env(
        "LIB_INDUSTRY_TABLE", "ptpl-curated-prd.DATAMART.survey_industry"))
    industry_htd_column: str = field(default_factory=lambda: _env("LIB_INDUSTRY_HTD_COLUMN", "htd_ptpl_plus"))
    industry_segment_column: str = field(default_factory=lambda: _env("LIB_INDUSTRY_SEGMENT_COLUMN", "channel"))
    industry_focus_products: tuple = field(default_factory=lambda: (
        "Meditran SX Plus 15W40|HDDO", "Meditran S|HDDO", "Turalik 52|Hydraulic", "Rored HDA 90|Gear & Trans",
        "Masri RG 320|Gear & Trans", "Medripal 412|Marine", "Grease Pertamina SGX-NL 2|Grease",
        "Grease Pertamina EPX NL 2|Grease"))
    industry_segments: tuple = field(default_factory=lambda: (
        "Agro", "Construction", "Fleet", "Manufacturing", "Marine", "Mining"))
    industry_competitors: tuple = field(default_factory=lambda: tuple(
        p.strip().upper() for p in _env("LIB_INDUSTRY_COMPETITORS", "SHELL").split(",") if p.strip()))

    # --- Dashboard daya saing harga (query BigQuery langsung) -------------------
    price_table: str = field(default_factory=lambda: _env(
        "LIB_PRICE_TABLE", "ptpl-curated-prd.DATAMART.SURVEY_PRODUCTS"))
    hero_products: tuple = field(default_factory=lambda: tuple(
        p.strip().upper() for p in _env("LIB_HERO_PRODUCTS", ",".join([
            "PERTAMINA ENDURO MATIC-S 0.8 LITER", "PERTAMINA ENDURO 4T RACING 0.8 LITER",
            "PERTAMINA ENDURO MATIC-G 0.8 LITER", "PERTAMINA ENDURO 4T 1 LITER",
            "PERTAMINA MESRANIA 2T SUPER 1 LITER", "PERTAMINA FASTRON ECOGREEN 0W-20 3.5 LITER",
            "PERTAMINA FASTRON ECOGREEN 5W-30 3.5 LITER", "PERTAMINA FASTRON TECHNO 10W-40 4 LITER",
            "PERTAMINA FASTRON TECHNO 15W-40 4 LITER", "PERTAMINA PRIMA XP 20W-50 4 LITER",
            "RORED EPA 90 4 LITER", "PERTAMINA MEDITRAN SC DIESEL 15W-40 5 LITER",
            "PERTAMINA MEDITRAN S 40 5 LITER"])).split(",") if p.strip()))
    # Status gap (Rp/L): AMAN jika gap < status_aman_below; KRITIS jika gap > status_kritis_above; selain itu WATCH.
    status_aman_below: float = field(default_factory=lambda: float(_env("LIB_STATUS_AMAN_BELOW", "-5000")))
    status_kritis_above: float = field(default_factory=lambda: float(_env("LIB_STATUS_KRITIS_ABOVE", "0")))

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
    # Folder dokumen: SATU-SATUNYA tempat file dokumen perpustakaan (mis. ge-docs-datastore).
    source_folder: str = field(default_factory=lambda: _env("LIB_SOURCE_FOLDER", ""))
    folder_batch_size: int = field(default_factory=lambda: int(_env("LIB_FOLDER_BATCH_SIZE", "20")))
    max_file_mb: float = field(default_factory=lambda: float(_env("LIB_MAX_FILE_MB", "100")))
    max_active_docs: int = field(default_factory=lambda: int(_env("LIB_MAX_ACTIVE_DOCS", "10")))
    company_name: str = field(default_factory=lambda: _env("LIB_COMPANY_NAME", "Nama Perusahaan"))
    # Nama agent yang dipakai saat memperkenalkan diri (bisa diubah lewat settings.json tanpa deploy).
    agent_name: str = field(default_factory=lambda: _env("LIB_AGENT_NAME", "Marketing Insight Assistant"))


SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

settings = Settings()


# ==========================================================================
# Pengaturan yang bisa diubah TANPA redeploy
# ==========================================================================
# Nilai di bawah bisa ditimpa lewat file JSON di bucket, misalnya
#   gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json
# Cukup edit/upload file itu lewat Konsol web Cloud Storage. Agent membaca ulang
# file tersebut setiap 5 menit. Jika file tidak ada atau rusak, nilai .env dipakai.
logger = logging.getLogger(__name__)

class CaseList(list):
    """Penanda tipe: daftar yang mempertahankan huruf besar/kecil (mis. nama produk fokus industri)."""


RUNTIME_KEYS: dict[str, type] = {
    "agent_name": str,
    "data_agent": str,
    "data_agent_industry": str,
    "industry_table": str,
    "industry_htd_column": str,
    "industry_segment_column": str,
    "industry_focus_products": CaseList,
    "industry_segments": CaseList,
    "industry_competitors": list,
    "hero_products": list,
    "status_aman_below": float,
    "status_kritis_above": float,
    "price_table": str,
    "data_auth_mode": str,
    "data_auth_id": str,
    "allowed_doc_types": list,
    "doc_type_hints": str,
    "company_name": str,
    "max_active_docs": int,
    "source_folder": str,
    "folder_batch_size": int,
    "max_file_mb": float,
}
RUNTIME_TTL_SECONDS = 300
_runtime_cache: dict[str, Any] = {"loaded_at": 0.0, "data": {}}


def runtime_config_path() -> str:
    explicit = os.getenv("LIB_RUNTIME_CONFIG_PATH")
    if explicit:
        return explicit
    root = posixpath.dirname(posixpath.dirname(settings.catalog_path))
    return posixpath.join(root, "config", "settings.json") if root else "config/settings.json"


def _read_runtime_file() -> dict[str, Any]:
    from google.api_core.exceptions import NotFound

    from .clients import storage_client

    try:
        raw = storage_client().bucket(settings.bucket).blob(runtime_config_path()).download_as_text()
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except NotFound:
        return {}
    except Exception:  # noqa: BLE001
        logger.exception("settings.json tidak bisa dibaca, memakai nilai .env")
        return {}


def coerce(name: str, value: Any) -> Any:
    """Ubah nilai dari JSON ke tipe yang benar. Nilai tidak valid -> None (pakai .env)."""
    kind = RUNTIME_KEYS.get(name)
    try:
        if kind is CaseList:
            items = value.split(",") if isinstance(value, str) else list(value)
            out = tuple(str(v).strip() for v in items if str(v).strip())
            return out or None
        if kind is list:
            items = value.split(",") if isinstance(value, str) else list(value)
            out = tuple(str(v).strip().upper() for v in items if str(v).strip())
            return out or None
        if kind is int:
            return int(value)
        if kind is float:
            return float(value)
        if kind is str:
            return str(value)
    except (TypeError, ValueError):
        logger.warning("Nilai %s di settings.json tidak valid: %r", name, value)
    return None


def live(name: str) -> Any:
    """Nilai pengaturan terkini: settings.json di bucket jika ada, selain itu dari .env."""
    if name not in RUNTIME_KEYS:
        return getattr(settings, name)
    now = time.time()
    if now - _runtime_cache["loaded_at"] > RUNTIME_TTL_SECONDS:
        _runtime_cache["data"] = _read_runtime_file()
        _runtime_cache["loaded_at"] = now
    if name in _runtime_cache["data"]:
        value = coerce(name, _runtime_cache["data"][name])
        if value is not None:
            return value
    return getattr(settings, name)
