"""Model Gemini untuk agent ADK dengan lokasi endpoint yang dikunci per model.

Agent berjalan di Agent Engine region Jakarta (asia-southeast2), sedangkan model Gemini dipanggil
lewat endpoint yang ditentukan di .env:
- model cepat (LIB_MODEL_FAST)  -> LIB_GEMINI_LOCATION      (default: global)
- model utama (LIB_MODEL_PRO)   -> LIB_GEMINI_LOCATION_PRO  (default: asia-southeast1, Gemini 4 Argon)
Tanpa ini, ADK akan memakai region tempat agent berjalan dan bisa gagal dengan error 404.
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

    location: str = ""

    @cached_property
    def api_client(self) -> Client:
        return Client(vertexai=True, project=settings.project_id, location=self.location or settings.gemini_location)


def make_model(model_name: str, location: str = "") -> PinnedGemini:
    from .clients import location_for

    return PinnedGemini(model=model_name, location=location or location_for(model_name))
