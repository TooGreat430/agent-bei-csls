"""Mesin laporan berbasis template.

Prinsip: Gemini hanya mengisi KONTEN (JSON sesuai schema.json template).
Bentuk laporan (layout, urutan bagian, gaya) dikunci oleh template.html dan
dirender oleh kode (Jinja2), sehingga hasilnya selalu konsisten.

Struktur satu template (lokal: ./templates/<id>/, produksi: gs://<bucket>/<internal>/templates/<id>/):
    manifest.json      id, judul, deskripsi, format output (html/pdf/pptx), tema warna, layout
    schema.json        JSON Schema isi laporan (field yang diisi Gemini)
    template.html      (opsional) template Jinja2 khusus untuk output HTML
    template.pptx      (opsional) file PowerPoint klien: master/tema-nya dipakai untuk output PPTX
    style_examples.md  (opsional) potongan laporan lama sebagai acuan gaya bahasa
    sample.json        (opsional) isi contoh untuk pratinjau template ("buatkan contoh laporannya")

Satu isi laporan (JSON) bisa dirender ke HTML, PDF, atau PPTX. User cukup menyebut
format yang diinginkan, dan hanya format itu yang dibuat.
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
    html: str | None
    style_examples: str = ""
    pptx_base: bytes | None = None

    @property
    def outputs(self) -> list[str]:
        declared = [o.lower() for o in self.manifest.get("outputs") or []]
        return [o for o in (declared or list(FORMATS)) if o in FORMATS]


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


def _read_bytes(template_id: str, filename: str) -> bytes | None:
    if settings.template_source == "local":
        path = os.path.join(settings.local_template_dir, template_id, filename)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()
    from .clients import storage_client

    blob = storage_client().bucket(settings.bucket).blob(f"{settings.template_prefix}/{template_id}/{filename}")
    return blob.download_as_bytes() if blob.exists() else None


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
    manifest_raw, schema_raw = read(template_id, "manifest.json"), read(template_id, "schema.json")
    if not (manifest_raw and schema_raw):
        raise FileNotFoundError(f"Template '{template_id}' tidak lengkap atau tidak ditemukan.")
    manifest = json.loads(manifest_raw)
    wants_pptx = "pptx" in [o.lower() for o in manifest.get("outputs") or list(FORMATS)]
    return Template(
        template_id=template_id,
        manifest=manifest,
        schema=json.loads(schema_raw),
        html=read(template_id, "template.html"),
        style_examples=read(template_id, "style_examples.md") or "",
        pptx_base=_read_bytes(template_id, "template.pptx") if wants_pptx else None,
    )


SOURCE_LABELS = {"bigquery": "data BigQuery", "dokumen": "dokumen"}


def source_requirement_problem(template: Template, items: list[dict[str, Any]]) -> str | None:
    """Pesan jika template butuh insight dari sumber tertentu (mis. BigQuery) tetapi tidak ada."""
    required = template.manifest.get("requires_source")
    if not required:
        return None
    if any(i.get("source", "dokumen") == required for i in items):
        return None
    found = sorted({SOURCE_LABELS.get(i.get("source", "dokumen"), i.get("source")) for i in items}) or ["tidak ada"]
    return (f"Template '{template.manifest.get('title', template.template_id)}' membutuhkan insight dari "
            f"{SOURCE_LABELS.get(required, required)}, sedangkan insight yang tersedia bersumber dari: "
            f"{', '.join(found)}.")


def load_sample(template_id: str) -> dict[str, Any] | None:
    raw = _reader()(template_id, "sample.json")
    return json.loads(raw) if raw else None


def preview_meta(template: Template, user_id: str) -> dict[str, Any]:
    meta = build_meta(template, user_id, f"CONTOH TAMPILAN - {template.manifest.get('title', template.template_id)}")
    meta["is_preview"] = True
    return meta


def list_templates() -> list[dict[str, Any]]:
    out = []
    for template_id in list_template_ids():
        try:
            t = load_template(template_id)
            out.append({
                "template_id": template_id,
                "title": t.manifest.get("title", template_id),
                "description": t.manifest.get("description", ""),
                "formats": t.outputs,
                "requires_insight_source": SOURCE_LABELS.get(t.manifest.get("requires_source"), "dokumen atau data"),
                "has_preview_sample": load_sample(template_id) is not None,
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
    def table_csv(table: dict[str, Any] | None) -> str:
        if not table or not table.get("rows"):
            return ""
        lines = [", ".join(str(c) for c in table.get("columns") or [])]
        lines += [", ".join("" if v is None else str(v) for v in row) for row in table["rows"][:60]]
        question = f"Pertanyaan data: {table.get('question')}\n" if table.get("question") else ""
        return f"\nTabel data BigQuery pendukung:\n{question}" + "\n".join(lines)

    insight_text = "\n\n".join(
        f"### Insight {i + 1} (sumber: {it.get('source', 'dokumen')}): {it['title']}\n{it['content']}\n"
        f"Sitasi: {', '.join(it.get('citations', [])) or '-'}{table_csv(it.get('data'))}"
        for i, it in enumerate(insight_items)
    ) or "(tidak ada insight)"
    excerpt_text = "\n\n".join(
        f"{ex['citation']}\n{ex['content']}" for ex in excerpts
    ) or "(tidak ada kutipan tambahan)"

    return f"""Anda menyusun ISI laporan resmi perusahaan berjenis "{template.manifest.get('title', template.template_id)}".

ATURAN WAJIB
1. Landasan utama adalah INSIGHT di bawah. Kutipan dokumen hanya untuk memperkuat dan memberi sitasi.
2. Jangan menambahkan fakta, angka, atau klaim yang tidak ada di insight, tabel data, atau kutipan.
   Untuk field "nilai" (KPI, matriks, grafik): salin angka PERSIS dari tabel data/insight. Jangan menghitung
   angka baru, jangan merata-rata sendiri. Jika data untuk suatu bagian tidak ada, kosongkan bagian itu.
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
    from . import grounding

    prompt = build_prompt(template, insight_items, excerpts, extra_instructions)
    nums = grounding.source_numbers(insight_items, excerpts) if template.manifest.get("grounding") else None
    last_errors: list[str] = []
    last_valid: dict[str, Any] | None = None
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
        if not last_errors and nums is not None:
            last_valid = content
            issues = grounding.check(content, nums)
            if issues:
                last_errors = ["Angka berikut tidak ditemukan di tabel data/insight. Salin angka persis dari data "
                               "atau kosongkan: " + "; ".join(issues[:25])]
        if not last_errors:
            return content
        logger.warning("Konten tidak valid (percobaan %d): %s", attempt + 1, last_errors)
    if last_valid is not None:
        fixed, removed = grounding.strip_ungrounded(last_valid, nums or [])
        logger.warning("Menghapus %d nilai yang tidak terverifikasi dari laporan", removed)
        return fixed
    raise ValueError("Konten laporan tidak sesuai skema template: " + "; ".join(last_errors))


# ==========================================================================
# Render & simpan
# ==========================================================================
FORMATS = {
    "html": ("html", "text/html; charset=utf-8"),
    "pdf": ("pdf", "application/pdf"),
    "pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}
FORMAT_ALIASES = {"ppt": "pptx", "powerpoint": "pptx", "slide": "pptx", "slides": "pptx", "web": "html"}


def normalize_format(value: str) -> str:
    v = (value or "").strip().lower().lstrip(".")
    return FORMAT_ALIASES.get(v, v)


def render_html(template: Template, content: dict[str, Any], meta: dict[str, Any]) -> str:
    """HTML dari template.html (jika ada), atau dari layout bawaan."""
    if not template.html:
        from . import report_render

        return report_render.render_html(template.manifest, template.schema, content, meta)
    from jinja2 import Environment, StrictUndefined, select_autoescape

    env = Environment(autoescape=select_autoescape(["html"], default=True), undefined=StrictUndefined)
    return env.from_string(template.html).render(c=content, meta=meta)


def render(template: Template, content: dict[str, Any], meta: dict[str, Any], fmt: str) -> tuple[bytes, str, str]:
    """Render ke SATU format. Mengembalikan (data, ekstensi, content_type)."""
    from . import report_render

    fmt = normalize_format(fmt)
    if fmt not in template.outputs:
        raise ValueError(f"Format '{fmt}' tidak didukung template ini. Pilihan: {', '.join(template.outputs)}")
    ext, ctype = FORMATS[fmt]
    if fmt == "html":
        return render_html(template, content, meta).encode("utf-8"), ext, ctype
    if fmt == "pdf":
        return report_render.render_pdf(template.manifest, template.schema, content, meta), ext, ctype
    return report_render.render_pptx(template.manifest, template.schema, content, meta, template.pptx_base), ext, ctype


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
        json.dumps(manifest, ensure_ascii=False, indent=2), content_type="application/json"
    )
    return out
