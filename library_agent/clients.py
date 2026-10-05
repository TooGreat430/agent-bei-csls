"""Client Google Cloud yang dibuat sekali (lazy) dan helper konteks ADK."""
from __future__ import annotations

import functools
from typing import Any

from .config import settings


# --------------------------------------------------------------------------
# Client GCP
# --------------------------------------------------------------------------
def _discovery_client_options():
    from google.api_core.client_options import ClientOptions

    if settings.search_location == "global":
        return None
    return ClientOptions(api_endpoint=f"{settings.search_location}-discoveryengine.googleapis.com")


@functools.lru_cache(maxsize=1)
def storage_client():
    from google.cloud import storage

    return storage.Client(project=settings.project_id)


@functools.lru_cache(maxsize=1)
def bigquery_client():
    from google.cloud import bigquery

    project = settings.data_agent_billing_project or settings.project_id
    return bigquery.Client(project=project)


@functools.lru_cache(maxsize=1)
def search_client():
    from google.cloud import discoveryengine_v1 as de

    return de.SearchServiceClient(client_options=_discovery_client_options())


@functools.lru_cache(maxsize=1)
def document_client():
    from google.cloud import discoveryengine_v1 as de

    return de.DocumentServiceClient(client_options=_discovery_client_options())


@functools.lru_cache(maxsize=1)
def genai_client():
    from google import genai

    return genai.Client(
        vertexai=True, project=settings.project_id, location=settings.gemini_location
    )


# --------------------------------------------------------------------------
# Nama resource Discovery Engine
# --------------------------------------------------------------------------
def datastore_path() -> str:
    return (
        f"projects/{settings.project_id}/locations/{settings.search_location}"
        f"/collections/default_collection/dataStores/{settings.datastore_id}"
    )


def branch_path() -> str:
    return f"{datastore_path()}/branches/default_branch"


def serving_config_path() -> str:
    return f"{datastore_path()}/servingConfigs/{settings.serving_config_id}"


def gcs_console_url(bucket: str, blob_path: str) -> str:
    """URL unduhan terautentikasi (user perlu izin baca di bucket)."""
    return f"https://storage.cloud.google.com/{bucket}/{blob_path}"


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
