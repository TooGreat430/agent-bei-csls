"""Client Google Cloud yang dibuat sekali (lazy) dan helper konteks ADK / Cloud Storage."""
from __future__ import annotations

import functools
import re
from typing import Any

from .config import settings


# --------------------------------------------------------------------------
# Client GCP
# --------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def storage_client():
    from google.cloud import storage

    return storage.Client(project=settings.project_id)


@functools.lru_cache(maxsize=1)
def bigquery_client():
    from google.cloud import bigquery

    project = settings.data_agent_billing_project or settings.project_id
    return bigquery.Client(project=project)


@functools.lru_cache(maxsize=4)
def genai_client(location: str = ""):
    """Client Gemini (Vertex AI). Lokasi bisa berbeda per model (mis. Argon di asia-southeast1)."""
    from google import genai

    return genai.Client(vertexai=True, project=settings.project_id, location=location or settings.gemini_location)


def location_for(model: str) -> str:
    """Lokasi endpoint untuk sebuah model: model utama memakai LIB_GEMINI_LOCATION_PRO."""
    if model and model == settings.model_pro and model != settings.model_fast:
        return settings.gemini_location_pro
    return settings.gemini_location


# --------------------------------------------------------------------------
# Cloud Storage
# --------------------------------------------------------------------------
def gcs_console_url(bucket: str, blob_path: str) -> str:
    """URL unduhan terautentikasi (user perlu izin baca di bucket)."""
    return f"https://storage.cloud.google.com/{bucket}/{blob_path}"


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    """'gs://bucket/a/b.csv' -> ('bucket', 'a/b.csv')."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Bukan URI GCS: {uri}")
    bucket, _, path = uri[5:].partition("/")
    if not bucket or not path:
        raise ValueError(f"URI GCS tidak lengkap: {uri}")
    return bucket, path


def safe_filename(name: str) -> str:
    """Nama file aman untuk Cloud Storage (huruf, angka, titik, minus, garis bawah)."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._") or "file"
    return base[:120]


# --------------------------------------------------------------------------
# Helper konteks ADK (ToolContext / CallbackContext)
# --------------------------------------------------------------------------
def _invocation_context(ctx: Any):
    return getattr(ctx, "_invocation_context", None)


def get_user_id(ctx: Any) -> str:
    """Ambil ID user dari konteks ADK. Di Gemini Enterprise biasanya email user."""
    user_id = getattr(ctx, "user_id", None)
    if not user_id:
        inv = _invocation_context(ctx)
        user_id = getattr(inv, "user_id", None) if inv else None
    return user_id or "unknown-user"


def get_session_id(ctx: Any) -> str:
    inv = _invocation_context(ctx)
    session = getattr(inv, "session", None) if inv else None
    return getattr(session, "id", None) or "unknown-session"
