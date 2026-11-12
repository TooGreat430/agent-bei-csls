"""Model Gemini untuk agent ADK dengan lokasi endpoint yang dikunci per model.

Agent berjalan di Agent Engine region Jakarta (asia-southeast2), sedangkan model Gemini dipanggil
lewat endpoint yang ditentukan di .env:
- model cepat (LIB_MODEL_FAST)  -> LIB_GEMINI_LOCATION      (default: global)
- model utama (LIB_MODEL_PRO)   -> LIB_GEMINI_LOCATION_PRO  (default: asia-southeast1, Gemini 4 Argon)
Tanpa ini, ADK akan memakai region tempat agent berjalan dan bisa gagal dengan error 404.

KETAHANAN KAPASITAS (429 RESOURCE_EXHAUSTED / 503): jika endpoint utama penuh, panggilan yang sama dicoba ke daftar
cadangan `model_fallbacks` (settings.json, format "model@lokasi", default: Argon global lalu model cepat global).
Jika semuanya penuh, agent membalas pesan "layanan sedang padat" alih-alih error — chat tidak rusak.
"""
from __future__ import annotations

import logging
import re
from functools import cached_property

from google.genai import Client

try:
    from google.adk.models.google_llm import Gemini
except ImportError:  # pragma: no cover
    from google.adk.models import Gemini

from .config import settings

logger = logging.getLogger(__name__)
_CAPACITY = re.compile(r"429|RESOURCE_EXHAUSTED|ResourceExhausted|503|UNAVAILABLE|overloaded", re.I)
BUSY_TEXT = ("Maaf, layanan model AI sedang sangat padat sehingga permintaan ini belum bisa diproses. "
             "Silakan kirim ulang pesan Anda dalam 1–2 menit. File dan hasil sebelumnya di chat ini tetap tersimpan.")


SKIP_SIGNATURE = b"skip_thought_signature_validator"
MODEL_ERROR_CODE = "MODEL_ERROR"


def ensure_signatures(contents) -> int:
    """Gemini 3.x menolak (400) function_call di riwayat yang tidak punya thought_signature — mis. panggilan
    sintetis `periksa_angka` dari pemeriksa angka atau riwayat dari Claude. Isi tanda lewati validasi resmi."""
    n = 0
    for content in contents or []:
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "function_call", None) and not getattr(part, "thought_signature", None):
                try:
                    part.thought_signature = SKIP_SIGNATURE
                    n += 1
                except Exception:  # noqa: BLE001
                    pass
    return n


def error_response(exc: BaseException):
    """Respons tanpa teks berkode error: agent selesai normal sehingga after_agent_callback (ensure_reply)
    tetap menyusun jawaban dari hasil tool — user tidak pernah menerima jawaban kosong karena error model."""
    from google.adk.models import LlmResponse

    return LlmResponse(error_code=MODEL_ERROR_CODE, error_message=str(exc)[:500])


def is_capacity_error(exc: BaseException) -> bool:
    return bool(_CAPACITY.search(f"{type(exc).__name__} {exc}"))


def fallback_targets(model: str, location: str) -> list[tuple[str, str]]:
    """Daftar (model, lokasi) cadangan dari settings, tanpa duplikat dan tanpa endpoint utama."""
    from .config import live

    out: list[tuple[str, str]] = []
    for item in live("model_fallbacks") or ():
        m, _, loc = str(item).partition("@")
        m = {"pro": settings.model_pro, "fast": settings.model_fast}.get(m.strip().lower(), m.strip())
        target = (m, (loc or "global").strip())
        if target[0] and target != (model, location) and target not in out:
            out.append(target)
    return out


def busy_response():
    from google.adk.models import LlmResponse
    from google.genai import types

    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=BUSY_TEXT)]))


class PinnedGemini(Gemini):
    """Gemini via Vertex AI dengan project dan lokasi yang ditentukan eksplisit, plus cadangan saat kapasitas penuh."""

    location: str = ""
    allow_fallback: bool = True

    @cached_property
    def api_client(self) -> Client:
        return Client(vertexai=True, project=settings.project_id, location=self.location or settings.gemini_location)

    async def generate_content_async(self, llm_request, stream: bool = False):
        yielded = False
        fixed = ensure_signatures(getattr(llm_request, "contents", None))
        if fixed:
            logger.info("thought_signature diisi untuk %d function_call tanpa signature", fixed)
        try:
            async for resp in super().generate_content_async(llm_request, stream):
                yielded = True
                yield resp
            return
        except Exception as exc:  # noqa: BLE001
            if yielded or not self.allow_fallback:
                raise
            if not is_capacity_error(exc):
                logger.exception("Error model %s @ %s (bukan kapasitas); jawaban disusun dari hasil tool",
                                 self.model, self.location)
                yield error_response(exc)
                return
            logger.warning("Kapasitas model penuh (%s @ %s): %s", self.model, self.location, str(exc)[:160])
        for model, location in fallback_targets(self.model, self.location):
            alt = PinnedGemini(model=model, location=location, allow_fallback=False)
            req = llm_request.model_copy(deep=True) if hasattr(llm_request, "model_copy") else llm_request
            try:
                req.model = model
            except Exception:  # noqa: BLE001
                pass
            try:
                async for resp in alt.generate_content_async(req, stream):
                    yield resp
                logger.warning("Memakai model cadangan %s @ %s", model, location)
                return
            except Exception as exc:  # noqa: BLE001
                if not is_capacity_error(exc):
                    logger.exception("Error model cadangan %s @ %s", model, location)
                    yield error_response(exc)
                    return
                logger.warning("Cadangan juga penuh (%s @ %s)", model, location)
        logger.error("Semua endpoint model penuh; mengirim pesan 'layanan padat' ke user")
        yield busy_response()


def make_model(model_name: str, location: str = "") -> PinnedGemini:
    from .clients import location_for

    return PinnedGemini(model=model_name, location=location or location_for(model_name))


def make_heavy_model():
    """Model untuk tugas berat: Claude (default, cadangan Argon) — saklar `heavy_model` di settings.json."""
    from .llm_claude import ClaudeVertex

    return ClaudeVertex(model=settings.model_claude)
