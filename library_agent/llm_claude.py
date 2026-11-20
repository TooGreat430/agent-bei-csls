"""Claude (Anthropic) via Vertex AI sebagai model agent ADK — dengan cadangan otomatis ke Gemini 4 Argon.

Dipakai untuk TUGAS BERAT (agent analisis file + skill, agent laporan) dan penulisan laporan. Router dan tanya-jawab
data tetap memakai model cepat Gemini.

- Model & region: settings.model_claude @ settings.claude_region (default claude-opus-5-5 @ global).
- Saklar tanpa deploy: settings.json `heavy_model` = "claude" (default) | "gemini".
- Cadangan: bila Claude penuh/kuota habis (429, 529 overloaded, 503) atau gagal dipanggil, permintaan yang sama
  dijawab Gemini 4 Argon (PinnedGemini, dengan cadangannya sendiri) dan user diberi tahu sekali per chat.
- Konversi ADK (google.genai types) <-> Anthropic Messages API: teks, gambar/PDF, pemanggilan alat (tool_use) dan
  hasilnya (tool_result), instruksi sistem, dan pencatatan token untuk meteran biaya.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from google.adk.models import BaseLlm

from .config import live, settings

logger = logging.getLogger(__name__)
CAPACITY = re.compile(r"429|529|503|overloaded|rate.?limit|RESOURCE_EXHAUSTED|quota|capacity", re.I)
FALLBACK_NOTE = ("(Catatan: Claude sedang padat, jadi jawaban ini dibuat dengan Gemini 4 Argon. Hasil tetap memakai "
                 "data dan aturan yang sama.)")
MAX_TOKENS = 16000
SKIP_SIGNATURE = b"skip_thought_signature_validator"   # sama dengan llm.SKIP_SIGNATURE (dipakai uji)


def is_capacity_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return status in (429, 503, 529) or bool(CAPACITY.search(f"{type(exc).__name__} {exc}"))


def use_claude() -> bool:
    return str(live("heavy_model") or "claude").lower() == "claude"


# ==========================================================================
# Konversi skema & isi
# ==========================================================================
def _schema(obj: Any) -> dict:
    """Schema google.genai (type OBJECT/STRING, ...) -> JSON Schema (object/string, ...)."""
    if obj is None:
        return {"type": "object", "properties": {}}
    if hasattr(obj, "model_dump"):
        try:
            obj = obj.model_dump(mode="json", exclude_none=True)
        except TypeError:
            obj = obj.model_dump(exclude_none=True)

    def fix(x):
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k == "type" and isinstance(v, str):
                    out[k] = v.lower()
                elif k in ("property_ordering", "propertyOrdering", "title") and not isinstance(v, dict):
                    continue
                elif k == "any_of":
                    out["anyOf"] = fix(v)
                else:
                    out[k] = fix(v)
            return out
        if isinstance(x, list):
            return [fix(v) for v in x]
        if hasattr(x, "value"):                      # enum Type
            return str(x.value).lower()
        return x
    out = fix(obj)
    out.setdefault("type", "object")
    if out["type"] == "object":
        out.setdefault("properties", {})
    return out


def tools_param(llm_request) -> list[dict]:
    tools = []
    config = getattr(llm_request, "config", None)
    for tool in getattr(config, "tools", None) or []:
        for fd in getattr(tool, "function_declarations", None) or []:
            schema = getattr(fd, "parameters_json_schema", None) or _schema(getattr(fd, "parameters", None))
            tools.append({"name": fd.name, "description": (fd.description or "")[:4000], "input_schema": schema})
    return tools


def _system_text(llm_request) -> str:
    si = getattr(getattr(llm_request, "config", None), "system_instruction", None)
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    parts = getattr(si, "parts", None) or []
    return "\n".join(p.text for p in parts if getattr(p, "text", None))


def _part_blocks(part) -> list[dict]:
    if getattr(part, "thought", False):
        return []                                       # pemikiran internal model lain tidak dikirim
    if getattr(part, "text", None):
        return [{"type": "text", "text": part.text}]
    fc = getattr(part, "function_call", None)
    if fc:
        return [{"type": "tool_use", "id": _tool_id(fc.id, fc.name), "name": fc.name, "input": dict(fc.args or {})}]
    fr = getattr(part, "function_response", None)
    if fr:
        return [{"type": "tool_result", "tool_use_id": _tool_id(fr.id, fr.name),
                 "content": json.dumps(fr.response, ensure_ascii=False, default=str)[:200000]}]
    blob = getattr(part, "inline_data", None)
    if blob and blob.data:
        data = base64.b64encode(blob.data).decode()
        mime = (blob.mime_type or "").lower()
        if mime.startswith("image/"):
            return [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}]
        if mime == "application/pdf":
            return [{"type": "document", "source": {"type": "base64", "media_type": mime, "data": data}}]
    return []


def _tool_id(raw: str | None, name: str) -> str:
    tid = re.sub(r"[^A-Za-z0-9_-]", "_", raw or f"call_{name}")
    return tid[:64]


def messages_param(llm_request) -> list[dict]:
    """contents ADK -> messages Anthropic: peran user/assistant bergantian, dimulai dari user."""
    msgs: list[dict] = []
    for content in getattr(llm_request, "contents", None) or []:
        role = "assistant" if getattr(content, "role", "user") == "model" else "user"
        blocks = [b for p in (content.parts or []) for b in _part_blocks(p)]
        if not blocks:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"].extend(blocks)
        else:
            msgs.append({"role": role, "content": blocks})
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": [{"type": "text", "text": "(lanjutkan percakapan)"}]})
    for m in msgs:                                      # tool_result wajib di awal pesan user
        m["content"].sort(key=lambda b: 0 if b["type"] == "tool_result" else 1)
    return msgs


def to_llm_response(message, model_label: str):
    from google.adk.models import LlmResponse
    from google.genai import types

    parts = []
    for block in getattr(message, "content", None) or []:
        btype = getattr(block, "type", "")
        if btype == "text" and block.text:
            parts.append(types.Part(text=block.text))
        elif btype == "tool_use":
            parts.append(types.Part(function_call=types.FunctionCall(id=block.id, name=block.name,
                                                                   args=dict(block.input or {}))))
    usage = getattr(message, "usage", None)
    resp = LlmResponse(content=types.Content(role="model", parts=parts or [types.Part(text="")]))
    if usage is not None:
        cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        try:
            resp.usage_metadata = types.GenerateContentResponseUsageMetadata(
                prompt_token_count=int(getattr(usage, "input_tokens", 0) or 0) + cached,
                cached_content_token_count=cached,
                candidates_token_count=int(getattr(usage, "output_tokens", 0) or 0))
        except Exception:  # noqa: BLE001
            pass
    _tag(resp, model_label)
    return resp


def _tag(resp, model_label: str) -> None:
    try:
        resp.custom_metadata = {**(getattr(resp, "custom_metadata", None) or {}), "model_used": model_label}
    except Exception:  # noqa: BLE001
        pass


_BAD_KW = re.compile(r"unexpected keyword argument '([A-Za-z_]+)'")


REQUIRED = ("model", "max_tokens", "messages")


def _clean_kwargs(**kw) -> dict:
    """Parameter opsional hanya dikirim bila terisi (SDK menolak None untuk system/tools); parameter wajib selalu ada."""
    return {k: v for k, v in kw.items() if k in REQUIRED or v not in (None, [], "")}


async def create_async(messages_api, **kw):
    """messages.create yang tahan perbedaan versi SDK: parameter yang tidak dikenal dibuang lalu dicoba ulang."""
    kw = _clean_kwargs(**kw)
    for _ in range(4):
        try:
            return await messages_api.create(**kw)
        except TypeError as exc:
            m = _BAD_KW.search(str(exc))
            if not m or m.group(1) not in kw or m.group(1) in REQUIRED:
                raise
            logger.warning("SDK Anthropic tidak menerima parameter '%s'; dikirim tanpa parameter itu", m.group(1))
            kw.pop(m.group(1))
    return await messages_api.create(**kw)


def create_sync(messages_api, **kw):
    kw = _clean_kwargs(**kw)
    for _ in range(4):
        try:
            return messages_api.create(**kw)
        except TypeError as exc:
            m = _BAD_KW.search(str(exc))
            if not m or m.group(1) not in kw or m.group(1) in REQUIRED:
                raise
            logger.warning("SDK Anthropic tidak menerima parameter '%s'; dikirim tanpa parameter itu", m.group(1))
            kw.pop(m.group(1))
    return messages_api.create(**kw)


def anthropic_client():
    from anthropic import AsyncAnthropicVertex

    return AsyncAnthropicVertex(project_id=settings.project_id, region=settings.claude_region)


# ==========================================================================
# Model ADK
# ==========================================================================
class ClaudeVertex(BaseLlm):
    """Claude di Vertex AI untuk LlmAgent ADK, dengan cadangan Gemini 4 Argon."""

    model: str = "claude-opus-5-5"

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"claude-.*"]

    async def generate_content_async(self, llm_request, stream: bool = False):
        if use_claude():
            try:
                message = await create_async(
                    anthropic_client().messages, model=self.model, max_tokens=MAX_TOKENS,
                    system=_system_text(llm_request), messages=messages_param(llm_request),
                    tools=tools_param(llm_request))
                yield to_llm_response(message, self.model)
                return
            except Exception as exc:  # noqa: BLE001
                if not is_capacity_error(exc):
                    logger.exception("Claude gagal dipanggil; memakai Gemini 4 Argon")
                else:
                    logger.warning("Claude penuh (%s); memakai Gemini 4 Argon", str(exc)[:160])
            note = True
        else:
            note = False
        async for resp in self._gemini(llm_request, stream, note):
            yield resp

    async def _gemini(self, llm_request, stream: bool, note: bool):
        from .clients import location_for
        from .llm import PinnedGemini, ensure_signatures

        argon = PinnedGemini(model=settings.model_pro, location=location_for(settings.model_pro))
        req = llm_request.model_copy(deep=True) if hasattr(llm_request, "model_copy") else llm_request
        try:
            req.model = settings.model_pro
        except Exception:  # noqa: BLE001
            pass
        ensure_signatures(getattr(req, "contents", None))       # riwayat dari Claude: tanpa thought signature
        async for resp in argon.generate_content_async(req, stream):
            _tag(resp, settings.model_pro)
            parts = getattr(getattr(resp, "content", None), "parts", None)
            if note and parts and not any(getattr(p, "function_call", None) for p in parts) \
                    and any(getattr(p, "text", None) for p in parts):
                from google.genai import types

                parts.append(types.Part(text="\n\n" + FALLBACK_NOTE))
                note = False
            yield resp


# ==========================================================================
# Penulisan laporan (panggilan langsung, bukan percakapan)
# ==========================================================================
def complete(prompt: str, max_tokens: int = 32000, temperature: float | None = None,
             images: list[tuple[bytes, str]] | None = None) -> tuple[str, dict]:
    """Satu panggilan Claude (sinkron) -> (teks, usage). Melempar error bila gagal; pemanggil yang menangani cadangan."""
    from anthropic import AnthropicVertex

    client = AnthropicVertex(project_id=settings.project_id, region=settings.claude_region)
    content: list | str = prompt
    if images:
        content = [{"type": "image", "source": {"type": "base64", "media_type": mime,
                                                "data": base64.b64encode(data).decode()}} for data, mime in images]
        content.append({"type": "text", "text": prompt})
    msg = create_sync(client.messages, model=settings.model_claude, max_tokens=max_tokens, temperature=temperature,
                      messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    u = getattr(msg, "usage", None)
    usage = {"input": int(getattr(u, "input_tokens", 0) or 0), "output": int(getattr(u, "output_tokens", 0) or 0),
             "cached": int(getattr(u, "cache_read_input_tokens", 0) or 0)}
    return text, usage
