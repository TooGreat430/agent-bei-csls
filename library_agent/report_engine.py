"""Fungsi bersama laporan: format file, pemanggilan Gemini berskema JSON, dan penyimpanan hasil.

(Mesin laporan berbasis template dokumen BEI/CSLS sudah dihapus. Laporan yang tersedia:
dashboard retail, one-pager industri, laporan planogram, dan laporan custom.)
"""
from __future__ import annotations

import copy
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

FORMATS = {
    "html": ("html", "text/html; charset=utf-8"),
    "pdf": ("pdf", "application/pdf"),
    "pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}
FORMAT_ALIASES = {"ppt": "pptx", "powerpoint": "pptx", "slide": "pptx", "slides": "pptx", "web": "html"}
_DROP_KEYS = {"$schema", "$id", "title", "additionalProperties", "minItems", "maxItems", "default", "examples"}


def normalize_format(value: str) -> str:
    v = (value or "").strip().lower().lstrip(".")
    v = FORMAT_ALIASES.get(v, v)
    return v if v in FORMATS else ""


def schema_for_model(schema: dict[str, Any]) -> dict[str, Any]:
    """Versi skema yang aman untuk Gemini (response_json_schema): $ref di-inline, anyOf [X, null] -> X."""
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def simplify(node: Any) -> Any:
        if isinstance(node, list):
            return [simplify(n) for n in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(("#/$defs/", "#/definitions/")):
            target = defs.get(ref.split("/")[-1], {})
            return simplify({**target, **{k: v for k, v in node.items() if k != "$ref"}})
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if not (isinstance(o, dict) and o.get("type") == "null")]
            if len(options) == 1:
                rest = {k: v for k, v in node.items() if k != "anyOf"}
                return simplify({**options[0], **rest})
        if isinstance(node.get("type"), list):
            types = [t for t in node["type"] if t != "null"]
            node = {**node, "type": types[0] if types else "string"}
        return {k: simplify(v) for k, v in node.items() if k not in _DROP_KEYS and k not in ("$defs", "definitions")}

    return simplify(copy.deepcopy(schema))


def generate_text(prompt: str, model: str = "", temperature: float = 0.2) -> str:
    """Teks bebas dari Gemini (dipakai laporan custom). Default: model utama (Argon)."""
    from google.genai import types

    from .clients import genai_client, location_for

    model = model or settings.model_pro
    config = types.GenerateContentConfig(temperature=temperature, max_output_tokens=32768)
    response = genai_client(location_for(model)).models.generate_content(model=model, contents=prompt, config=config)
    return response.text or ""


def _generate_json(prompt: str, schema: dict[str, Any], model: str = "") -> dict[str, Any]:
    """JSON sesuai skema dari Gemini (narasi laporan). Default: model utama (Argon)."""
    from google.genai import types

    from .clients import genai_client, location_for

    model = model or settings.model_pro
    client = genai_client(location_for(model))
    model_schema = schema_for_model(schema)
    try:
        config = types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json",
                                             response_json_schema=model_schema)
    except Exception:  # noqa: BLE001  (SDK lama tanpa response_json_schema)
        config = types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json")
        prompt += "\n\nSKEMA JSON YANG WAJIB DIIKUTI:\n" + json.dumps(model_schema, ensure_ascii=False)
    try:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
    except Exception as exc:  # noqa: BLE001
        if "400" not in str(exc) and "INVALID_ARGUMENT" not in str(exc):
            raise
        logger.warning("Skema JSON ditolak model (%s); ulang tanpa response_json_schema", str(exc)[:120])
        config = types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json")
        response = client.models.generate_content(
            model=model, config=config,
            contents=prompt + "\n\nSKEMA JSON YANG WAJIB DIIKUTI:\n" + json.dumps(model_schema, ensure_ascii=False))
    text = (response.text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    return json.loads(text)


def save_output(user_id: str, template_id: str, report_title: str, data: bytes, ext: str, content_type: str,
                record: dict[str, Any] | None = None) -> dict[str, str]:
    """Simpan file laporan dan catatannya (report.json) ke folder laporan."""
    from .clients import gcs_console_url, storage_client

    slug = re.sub(r"[^a-z0-9]+", "-", report_title.lower()).strip("-")[:60] or template_id
    user_slug = re.sub(r"[^A-Za-z0-9._@-]+", "_", user_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{settings.report_prefix}/{user_slug}/{stamp}-{slug}"
    bucket_name = settings.report_bucket
    bucket = storage_client().bucket(bucket_name)

    blob = bucket.blob(f"{base}.{ext}")
    blob.content_disposition = f'attachment; filename="{slug}.{ext}"' if ext != "html" else None
    blob.upload_from_string(data, content_type=content_type)
    out = {"format": ext, "url": gcs_console_url(bucket_name, f"{base}.{ext}"),
           "gcs_uri": f"gs://{bucket_name}/{base}.{ext}"}
    manifest = {**(record or {}), "owner": user_id, "template_id": template_id,
                "report_title": report_title, "created_at": stamp, **out}
    bucket.blob(f"{base}.report.json").upload_from_string(
        json.dumps(manifest, ensure_ascii=False, indent=2), content_type="application/json")
    return out
