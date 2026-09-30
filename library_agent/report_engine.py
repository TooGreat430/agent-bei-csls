"""Mesin laporan berbasis template.

Prinsip: Gemini hanya mengisi KONTEN (JSON sesuai schema.json template).
Bentuk laporan (layout, urutan bagian, gaya) dikunci oleh template.html dan
dirender oleh kode (Jinja2), sehingga hasilnya selalu konsisten.

Struktur satu template (lokal: ./templates/<id>/, produksi: gs://<bucket>/templates/<id>/):
    manifest.json      id, judul, deskripsi, format output
    schema.json        JSON Schema isi laporan (field yang diisi Gemini)
    template.html      template Jinja2 (akses isi via `c`, metadata via `meta`)
    style_examples.md  potongan laporan lama sebagai acuan gaya bahasa (opsional)
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import settings, live

logger = logging.getLogger(__name__)


@dataclass
class Template:
    template_id: str
    manifest: dict[str, Any]
    schema: dict[str, Any]
    html: str
    style_examples: str = ""


# ==========================================================================
# Registry template
# ==========================================================================
def _read_local(template_id: str, filename: str) -> str | None:
    path = os.path.join(settings.local_template_dir, template_id, filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_gcs(template_id: str, filename: str) -> str | None:
    from .clients import storage_client

    blob = storage_client().bucket(settings.bucket).blob(
        f"{settings.template_prefix}/{template_id}/{filename}"
    )
    return blob.download_as_text() if blob.exists() else None


def _reader():
    return _read_local if settings.template_source == "local" else _read_gcs


def list_template_ids() -> list[str]:
    if settings.template_source == "local":
        root = settings.local_template_dir
        return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "manifest.json")))
    from .clients import storage_client

    prefix = f"{settings.template_prefix}/"
    ids = set()
    for blob in storage_client().list_blobs(settings.bucket, prefix=prefix):
        rest = blob.name[len(prefix):]
        if rest.endswith("/manifest.json") and rest.count("/") == 1:
            ids.add(rest.split("/", 1)[0])
    return sorted(ids)


def load_template(template_id: str) -> Template:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", template_id):
        raise ValueError("template_id tidak valid.")
    read = _reader()
    manifest_raw, schema_raw, html = (
        read(template_id, "manifest.json"), read(template_id, "schema.json"), read(template_id, "template.html"),
    )
    if not (manifest_raw and schema_raw and html):
        raise FileNotFoundError(f"Template '{template_id}' tidak lengkap atau tidak ditemukan.")
    return Template(
        template_id=template_id,
        manifest=json.loads(manifest_raw),
        schema=json.loads(schema_raw),
        html=html,
        style_examples=read(template_id, "style_examples.md") or "",
    )


def list_templates() -> list[dict[str, Any]]:
    out = []
    for template_id in list_template_ids():
        try:
            t = load_template(template_id)
            out.append({
                "template_id": template_id,
                "title": t.manifest.get("title", template_id),
                "description": t.manifest.get("description", ""),
                "sections": list(t.schema.get("properties", {}).keys()),
            })
        except Exception:  # noqa: BLE001
            logger.exception("Template %s gagal dimuat", template_id)
    return out


# ==========================================================================
# Validasi
# ==========================================================================
def schema_for_model(schema: dict[str, Any]) -> dict[str, Any]:
    """Salinan skema tanpa kata kunci yang tidak dibutuhkan model."""
    cleaned = copy.deepcopy(schema)
    for key in ("$schema", "$id", "title"):
        cleaned.pop(key, None)
    return cleaned


def validate_content(content: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Mengembalikan daftar pesan error (kosong = valid)."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(content), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors]


# ==========================================================================
# Penyusunan konten oleh Gemini
# ==========================================================================
def build_prompt(template: Template, insight_items: list[dict[str, Any]],
                 excerpts: list[dict[str, Any]], extra_instructions: str) -> str:
    insight_text = "\n\n".join(
        f"### Insight {i + 1}: {it['title']}\n{it['content']}\nSitasi: {', '.join(it.get('citations', [])) or '-'}"
        for i, it in enumerate(insight_items)
    ) or "(tidak ada insight)"
    excerpt_text = "\n\n".join(
        f"{ex['citation']}\n{ex['content']}" for ex in excerpts
    ) or "(tidak ada kutipan tambahan)"

    return f"""Anda menyusun ISI laporan resmi perusahaan berjenis "{template.manifest.get('title', template.template_id)}".

ATURAN WAJIB
1. Landasan utama adalah INSIGHT di bawah. Kutipan dokumen hanya untuk memperkuat dan memberi sitasi.
2. Jangan menambahkan fakta, angka, atau klaim yang tidak ada di insight atau kutipan.
   Jika informasi untuk suatu bagian tidak tersedia, tulis "Data tidak tersedia pada sumber yang dipilih."
3. Setiap temuan wajib menyertakan label sitasi persis seperti yang tertulis di sumber, misalnya "[Judul, v2, hal. 12]".
4. Output HANYA JSON yang sesuai skema. Jangan menulis HTML, markdown, atau teks lain.
5. Bahasa Indonesia formal. Ikuti gaya bahasa pada contoh.

CONTOH GAYA BAHASA LAPORAN SEBELUMNYA
{template.style_examples or '(tidak ada contoh)'}

INSTRUKSI TAMBAHAN DARI USER
{extra_instructions or '-'}

INSIGHT (LANDASAN)
{insight_text}

KUTIPAN DOKUMEN PENDUKUNG
{excerpt_text}
"""


def _generate_json(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    from google.genai import types

    from .clients import genai_client

    model_schema = schema_for_model(schema)
    try:
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=model_schema,
        )
    except Exception:  # noqa: BLE001  (SDK lama tanpa response_json_schema)
        config = types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json")
        prompt += "\n\nSKEMA JSON YANG WAJIB DIIKUTI:\n" + json.dumps(model_schema, ensure_ascii=False)

    response = genai_client().models.generate_content(
        model=settings.model_pro, contents=prompt, config=config
    )
    text = (response.text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    return json.loads(text)


def compose_content(template: Template, insight_items: list[dict[str, Any]],
                    excerpts: list[dict[str, Any]], extra_instructions: str = "",
                    max_attempts: int = 2) -> dict[str, Any]:
    prompt = build_prompt(template, insight_items, excerpts, extra_instructions)
    last_errors: list[str] = []
    for attempt in range(max_attempts):
        attempt_prompt = prompt
        if last_errors:
            attempt_prompt += (
                "\n\nPERCOBAAN SEBELUMNYA TIDAK VALID. Perbaiki error berikut:\n- " + "\n- ".join(last_errors)
            )
        try:
            content = _generate_json(attempt_prompt, template.schema)
        except json.JSONDecodeError as exc:
            last_errors = [f"Output bukan JSON valid: {exc}"]
            continue
        last_errors = validate_content(content, template.schema)
        if not last_errors:
            return content
        logger.warning("Konten tidak valid (percobaan %d): %s", attempt + 1, last_errors)
    raise ValueError("Konten laporan tidak sesuai skema template: " + "; ".join(last_errors))


# ==========================================================================
# Render & simpan
# ==========================================================================
def render_html(template: Template, content: dict[str, Any], meta: dict[str, Any]) -> str:
    from jinja2 import Environment, StrictUndefined, select_autoescape

    env = Environment(autoescape=select_autoescape(["html"], default=True), undefined=StrictUndefined)
    return env.from_string(template.html).render(c=content, meta=meta)


def html_to_pdf(html: str) -> bytes | None:
    try:
        from weasyprint import HTML
    except Exception:  # noqa: BLE001
        logger.warning("WeasyPrint tidak tersedia, PDF dilewati.")
        return None
    return HTML(string=html).write_pdf()


def build_meta(template: Template, user_id: str, report_title: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "company_name": live("company_name"),
        "report_title": report_title or template.manifest.get("title", template.template_id),
        "template_title": template.manifest.get("title", template.template_id),
        "generated_by": user_id,
        "generated_at": now.strftime("%d-%m-%Y %H:%M UTC"),
        "generated_date": now.strftime("%d-%m-%Y"),
    }


def save_outputs(user_id: str, template_id: str, report_title: str,
                 html: str, pdf: bytes | None, record: dict[str, Any] | None = None) -> dict[str, str]:
    """Simpan HTML/PDF dan file catatan (report.json) ke bucket laporan."""
    from .clients import gcs_console_url, storage_client

    slug = re.sub(r"[^a-z0-9]+", "-", report_title.lower()).strip("-")[:60] or template_id
    user_slug = re.sub(r"[^A-Za-z0-9._@-]+", "_", user_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{settings.report_prefix}/{user_slug}/{stamp}-{slug}"
    bucket_name = settings.report_bucket

    bucket = storage_client().bucket(bucket_name)
    bucket.blob(f"{base}.html").upload_from_string(html, content_type="text/html; charset=utf-8")
    out = {"html_url": gcs_console_url(bucket_name, f"{base}.html"),
           "html_gcs_uri": f"gs://{bucket_name}/{base}.html"}
    if pdf:
        bucket.blob(f"{base}.pdf").upload_from_string(pdf, content_type="application/pdf")
        out["pdf_url"] = gcs_console_url(bucket_name, f"{base}.pdf")
        out["pdf_gcs_uri"] = f"gs://{bucket_name}/{base}.pdf"

    manifest = {**(record or {}), "owner": user_id, "template_id": template_id,
                "report_title": report_title, "created_at": stamp, **out}
    bucket.blob(f"{base}.report.json").upload_from_string(
        json.dumps(manifest, ensure_ascii=False, indent=2), content_type="application/json"
    )
    return out
