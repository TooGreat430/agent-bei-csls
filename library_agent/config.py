"""Konfigurasi terpusat. Semua nilai dibaca dari environment variable.

Lihat .env.example untuk daftar lengkap dan contoh nilai.
"""
from __future__ import annotations

import json
import logging
import os
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
    # Lokasi Vertex AI untuk model cepat (router, data agent, narasi ringan)
    gemini_location: str = field(default_factory=lambda: _env("LIB_GEMINI_LOCATION", "global"))
    # Lokasi Vertex AI untuk model utama (Gemini 4 Argon) — analisis file & laporan
    gemini_location_pro: str = field(default_factory=lambda: _env("LIB_GEMINI_LOCATION_PRO", "asia-southeast1"))

    # --- Cloud Storage ------------------------------------------------------
    bucket: str = field(default_factory=lambda: _env("LIB_BUCKET", ""))
    data_file_prefix: str = field(default_factory=lambda: _env("LIB_DATA_FILE_PREFIX") or _internal("data-files"))
    # Dokumen unggahan per chat (PDF, Word, PowerPoint, teks, gambar, dll.) + teks hasil ekstraksinya
    doc_file_prefix: str = field(default_factory=lambda: _env("LIB_DOC_FILE_PREFIX") or _internal("doc-files"))
    # Laporan & grafik hasil agent
    report_prefix: str = field(default_factory=lambda: _env("LIB_REPORT_PREFIX") or _internal("reports"))
    # Bucket terpisah untuk laporan (disarankan): user diberi izin baca HANYA di bucket ini,
    # sehingga katalog dan insight milik user lain di bucket utama tidak ikut terbuka.
    report_bucket: str = field(default_factory=lambda: _env("LIB_REPORT_BUCKET") or _env("LIB_BUCKET", ""))

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
    chat_inline_chart: int = field(default_factory=lambda: int(_env("LIB_CHAT_INLINE_CHART", "0")))
    industry_segment_column: str = field(default_factory=lambda: _env("LIB_INDUSTRY_SEGMENT_COLUMN", "channel"))
    industry_focus_products: tuple = field(default_factory=lambda: (
        "Meditran SX Plus 15W40|HDDO", "Meditran S|HDDO", "Turalik 52|Hydraulic", "Rored HDA 90|Gear & Trans",
        "Masri RG 320|Gear & Trans", "Medripal 412|Marine", "Grease Pertamina SGX-NL 2|Grease",
        "Grease Pertamina EPX NL 2|Grease"))
    industry_segments: tuple = field(default_factory=lambda: (
        "Agro", "Construction", "Fleet", "Manufacturing", "Marine", "Mining"))
    industry_competitors: tuple = field(default_factory=lambda: tuple(
        p.strip().upper() for p in _env("LIB_INDUSTRY_COMPETITORS", "SHELL").split(",") if p.strip()))

    # --- Data Agent planogram & laporan planogram ------------------------------------
    data_agent_planogram: str = field(default_factory=lambda: _env(
        "LIB_DATA_AGENT_PLANOGRAM",
        "projects/ptpl-land-dev/locations/global/dataAgents/agent_5f69a707-a240-49ea-9c96-dd12493f659c"))
    planogram_table: str = field(default_factory=lambda: _env(
        "LIB_PLANOGRAM_TABLE", "ptpl-curated-prd.DATAMART.VM_PLANOGRAM"))
    # Periode default template planogram (dibandingkan otomatis dengan kuartal sebelumnya).
    planogram_default_period: str = field(default_factory=lambda: _env("LIB_PLANOGRAM_DEFAULT_PERIOD", "2026-Q3"))
    # Ambang kuadran matriks KIMAP: rasio carry PTPL / leader kompetitor (%).
    planogram_carry_ratio_line: float = field(default_factory=lambda: float(_env("LIB_PLANOGRAM_CARRY_RATIO_LINE", "70")))
    # Laporan gabungan Retail x Planogram (Competitive Battlefield): batas sampel harga per sisi.
    battlefield_min_price_n: int = field(default_factory=lambda: int(_env("LIB_BATTLEFIELD_MIN_PRICE_N", "10")))
    # Sel dengan total carry di bawah angka ini ditandai "sampel kecil".
    planogram_min_carry: int = field(default_factory=lambda: int(_env("LIB_PLANOGRAM_MIN_CARRY", "30")))

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
    # model_fast: router & agent data BigQuery. model_pro: model utama (analisis file, laporan, narasi).
    model_fast: str = field(default_factory=lambda: _env("LIB_MODEL_FAST", "gemini-3.5-flash"))
    model_pro: str = field(default_factory=lambda: _env("LIB_MODEL_PRO", "gemini-4-argon"))
    # Cadangan saat kapasitas model penuh (429/503), urut dicoba: "model@lokasi"
    model_fallbacks: tuple = field(default_factory=lambda: tuple(x.strip() for x in _env(
        "LIB_MODEL_FALLBACKS", "pro@global,fast@global").split(",") if x.strip()))   # "pro"/"fast" = LIB_MODEL_PRO/FAST

    # --- Code Execution (analisis file berbasis kode) — MATI secara default ------------
    code_execution_enabled: bool = field(default_factory=lambda: _env("LIB_CODE_EXECUTION_ENABLED", "false").lower()
                                         in ("1", "true", "ya", "yes", "on"))
    # Daftar user (ID/email Gemini Enterprise) yang boleh memakai fitur ini. Kosong = semua user (jika enabled).
    code_execution_users: tuple = field(default_factory=lambda: tuple(
        u.strip() for u in _env("LIB_CODE_EXECUTION_USERS", "").split(",") if u.strip()))
    code_execution_max_steps: int = field(default_factory=lambda: int(_env("LIB_CODE_EXECUTION_MAX_STEPS", "25")))
    # Batas biaya harian (USD) untuk SEMUA pemakaian model + sandbox yang tercatat meteran; tercapai -> fitur berhenti.
    code_execution_daily_budget_usd: float = field(default_factory=lambda: float(
        _env("LIB_CODE_EXECUTION_DAILY_BUDGET_USD", "5")))
    code_execution_ttl_seconds: int = field(default_factory=lambda: int(_env("LIB_CODE_EXECUTION_TTL_SECONDS", "1800")))
    code_execution_machine: str = field(default_factory=lambda: _env("LIB_CODE_EXECUTION_MACHINE",
                                                                      "MACHINE_CONFIG_VCPU4_RAM4GIB"))
    # Resource Agent Engine induk sandbox (default: agent ini sendiri)
    code_execution_engine: str = field(default_factory=lambda: _env("LIB_CODE_EXECUTION_ENGINE")
                                       or _env("LIB_AGENT_RESOURCE", ""))
    # --- Batas pemakaian agent (dari meteran biaya, USD). 0 = tidak dibatasi --------------------------------------
    budget_daily_usd: float = field(default_factory=lambda: float(_env("LIB_BUDGET_DAILY_USD", "0")))
    budget_monthly_usd: float = field(default_factory=lambda: float(_env("LIB_BUDGET_MONTHLY_USD", "0")))
    budget_warn_pct: float = field(default_factory=lambda: float(_env("LIB_BUDGET_WARN_PCT", "80")))
    # "berat" = saat batas tercapai, laporan & analisis berbasis kode dihentikan (tanya-jawab tetap jalan);
    # "semua" = seluruh agent berhenti menjawab sampai periode berikutnya.
    budget_block_scope: str = field(default_factory=lambda: _env("LIB_BUDGET_BLOCK_SCOPE", "berat"))
    # --- Tarif untuk meteran biaya (USD per 1 juta token / per jam) — ESTIMASI, sesuaikan dengan harga resmi ----
    price_pro_input: float = field(default_factory=lambda: float(_env("LIB_PRICE_PRO_INPUT", "4.0")))
    price_pro_output: float = field(default_factory=lambda: float(_env("LIB_PRICE_PRO_OUTPUT", "20.0")))
    price_pro_cached: float = field(default_factory=lambda: float(_env("LIB_PRICE_PRO_CACHED", "0.2")))
    price_fast_input: float = field(default_factory=lambda: float(_env("LIB_PRICE_FAST_INPUT", "0.5")))
    price_fast_output: float = field(default_factory=lambda: float(_env("LIB_PRICE_FAST_OUTPUT", "3.0")))
    price_fast_cached: float = field(default_factory=lambda: float(_env("LIB_PRICE_FAST_CACHED", "0.05")))
    price_sandbox_vcpu_hour: float = field(default_factory=lambda: float(_env("LIB_PRICE_SANDBOX_VCPU_HOUR", "0.0864")))
    price_sandbox_gib_hour: float = field(default_factory=lambda: float(_env("LIB_PRICE_SANDBOX_GIB_HOUR", "0.009")))
    sandbox_vcpu: float = field(default_factory=lambda: float(_env("LIB_SANDBOX_VCPU", "4")))
    sandbox_gib: float = field(default_factory=lambda: float(_env("LIB_SANDBOX_GIB", "4")))

    # --- Identitas ---------------------------------------------------------------
    max_file_mb: float = field(default_factory=lambda: float(_env("LIB_MAX_FILE_MB", "100")))
    company_name: str = field(default_factory=lambda: _env("LIB_COMPANY_NAME", "Nama Perusahaan"))
    # Nama agent yang dipakai saat memperkenalkan diri (bisa diubah lewat settings.json tanpa deploy).
    agent_name: str = field(default_factory=lambda: _env("LIB_AGENT_NAME", "Marketing Insight Assistant"))


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
    "data_agent_planogram": str,
    "planogram_table": str,
    "planogram_default_period": str,
    "planogram_carry_ratio_line": float,
    "model_fallbacks": CaseList,
    "budget_daily_usd": float,
    "budget_monthly_usd": float,
    "budget_warn_pct": float,
    "budget_block_scope": str,
    "code_execution_enabled": bool,
    "code_execution_users": CaseList,
    "code_execution_max_steps": int,
    "code_execution_daily_budget_usd": float,
    "code_execution_ttl_seconds": int,
    "price_pro_input": float,
    "price_pro_output": float,
    "price_pro_cached": float,
    "price_fast_input": float,
    "price_fast_output": float,
    "price_fast_cached": float,
    "price_sandbox_vcpu_hour": float,
    "price_sandbox_gib_hour": float,
    "planogram_min_carry": int,
    "battlefield_min_price_n": int,
    "industry_table": str,
    "industry_htd_column": str,
    "industry_segment_column": str,
    "chat_inline_chart": int,
    "industry_focus_products": CaseList,
    "industry_segments": CaseList,
    "industry_competitors": list,
    "hero_products": list,
    "status_aman_below": float,
    "status_kritis_above": float,
    "price_table": str,
    "data_auth_mode": str,
    "data_auth_id": str,
    "company_name": str,
    "max_file_mb": float,
}
RUNTIME_TTL_SECONDS = 300
_runtime_cache: dict[str, Any] = {"loaded_at": 0.0, "data": {}}


def runtime_config_path() -> str:
    explicit = os.getenv("LIB_RUNTIME_CONFIG_PATH")
    if explicit:
        return explicit
    return _internal("config/settings.json")


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
        if kind is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "ya", "yes", "on")
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
