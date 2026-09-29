"""Model Gemini untuk agent ADK dengan lokasi endpoint yang dikunci.

Agent berjalan di Agent Engine region Jakarta (asia-southeast2), sedangkan model
Gemini dipanggil lewat endpoint LIB_GEMINI_LOCATION (default: "global"), karena
tidak semua versi Gemini tersedia di setiap region. Tanpa ini, ADK akan memakai
region tempat agent berjalan dan bisa gagal dengan error 404 (model tidak ditemukan).
"""
from __future__ import annotations

from functools import cached_property

from google.genai import Client

try:
    from google.adk.models.google_llm import Gemini
except ImportError:  # pragma: no cover
    from google.adk.models import Gemini

from .config import settings


class PinnedGemini(Gemini):
    """Gemini via Vertex AI dengan project dan lokasi yang ditentukan eksplisit."""

    @cached_property
    def api_client(self) -> Client:
        return Client(vertexai=True, project=settings.project_id, location=settings.gemini_location)


def make_model(model_name: str) -> PinnedGemini:
    return PinnedGemini(model=model_name)
