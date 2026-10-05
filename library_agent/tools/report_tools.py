"""Tool ADK untuk Report sub-agent."""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import insights, report_engine, search
from ..clients import get_user_id
from .library_tools import ACTIVE_KEY, DEFAULT_WORKSPACE, WORKSPACE_KEY

logger = logging.getLogger(__name__)


def list_report_templates() -> dict[str, Any]:
    """Menampilkan template laporan resmi yang tersedia beserta bagian-bagiannya."""
    try:
        return {"status": "ok", "templates": report_engine.list_templates()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("list template gagal")
        return {"status": "error", "message": str(exc)}


def generate_report(
    template_id: str,
    insight_ids: list[str],
    tool_context: ToolContext,
    output_format: str = "",
    report_title: str = "",
    extra_instructions: str = "",
    use_document_excerpts: bool = True,
) -> dict[str, Any]:
    """Membuat laporan dari insight tersimpan, mengikuti template resmi perusahaan.

    Layout laporan dikunci oleh template. Model hanya mengisi konten sesuai skema.
    Hanya SATU format yang dibuat, sesuai permintaan user.

    Args:
        template_id: ID template dari list_report_templates.
        output_format: Format yang diminta user: "pdf", "pptx" (PowerPoint), atau "html".
            Kosongkan jika user belum menyebut format; tool akan mengembalikan pilihan format.
        insight_ids: ID insight yang dijadikan landasan (lihat list_insights). Kosongkan
            untuk memakai semua insight di workspace aktif.
        report_title: Judul laporan, misalnya "Laporan Studi CSLS Q3 2026".
        extra_instructions: Instruksi tambahan dari user, misalnya fokus atau periode.
        use_document_excerpts: True untuk menambah kutipan dari dokumen aktif sebagai sitasi pendukung.

    Returns:
        Link laporan HTML (dan PDF jika tersedia).
    """
    user_id = get_user_id(tool_context)
    workspace = tool_context.state.get(WORKSPACE_KEY, DEFAULT_WORKSPACE)

    try:
        template = report_engine.load_template(template_id)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": template.outputs,
                "message": "Tanyakan ke user format laporan yang diinginkan (PDF, PowerPoint, atau HTML)."}
    if fmt not in template.outputs:
        return {"status": "error", "available_formats": template.outputs,
                "message": f"Template ini tidak mendukung format {fmt}."}

    items = (insights.get_many(workspace, insight_ids, full=True) if insight_ids
             else insights.list_full(workspace))
    if not items:
        return {"status": "error",
                "message": "Belum ada insight yang bisa dijadikan landasan. Simpan insight terlebih dahulu."}
    problem = report_engine.source_requirement_problem(template, items)
    if problem:
        return {"status": "needs_input", "message": problem + (
            " JANGAN mengganti dengan insight lain. Sampaikan ke user: tanyakan data yang dibutuhkan "
            "(mis. gap harga per zona), simpan jawabannya sebagai insight, lalu buat laporan lagi. "
            "Atau tawarkan template lain yang sesuai dengan insight yang ada.")}

    excerpts: list[dict[str, Any]] = []
    active = list(tool_context.state.get(ACTIVE_KEY, []))
    if use_document_excerpts and active:
        seen = set()
        for item in [i for i in items if i.get("source", "dokumen") == "dokumen"][:8]:
            try:
                for ex in search.search_documents(item["title"], active, max_results=3):
                    key = (ex["doc_key"], ex["page"], ex["content"][:80])
                    if key not in seen:
                        seen.add(key)
                        excerpts.append(ex)
            except Exception:  # noqa: BLE001
                logger.exception("Gagal mengambil kutipan pendukung")

    try:
        content = report_engine.compose_content(template, items, excerpts, extra_instructions)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    meta = report_engine.build_meta(template, user_id, report_title)
    try:
        data, ext, ctype = report_engine.render(template, content, meta, fmt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Render laporan gagal")
        return {"status": "error", "message": f"Laporan gagal dibuat dalam format {fmt}: {exc}"}
    links = report_engine.save_output(
        user_id, template_id, meta["report_title"], data, ext, ctype,
        record={"workspace": workspace, "insight_ids": [i["insight_id"] for i in items], "doc_keys": active},
    )
    return {"status": "ok", "report_title": meta["report_title"], **links}


def preview_report_template(template_id: str, tool_context: ToolContext, output_format: str = "") -> dict[str, Any]:
    """Membuat CONTOH TAMPILAN laporan dari isi contoh bawaan template, TANPA data asli.

    Gunakan saat user meminta "contoh laporan", "preview template", "seperti apa laporannya",
    atau ingin melihat tampilan template sebelum ada data/insight. Tidak memakai insight,
    BigQuery, ataupun dokumen. Hasilnya ditandai sebagai CONTOH.

    Args:
        template_id: ID template dari list_report_templates.
        output_format: "pdf", "pptx" (PowerPoint), atau "html". Kosongkan jika user belum menyebut.
    """
    try:
        template = report_engine.load_template(template_id)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": template.outputs,
                "message": "Tanyakan ke user format contoh yang diinginkan (PDF, PowerPoint, atau HTML)."}
    if fmt not in template.outputs:
        return {"status": "error", "available_formats": template.outputs,
                "message": f"Template ini tidak mendukung format {fmt}."}
    sample = report_engine.load_sample(template_id)
    if not sample:
        return {"status": "error", "message": "Template ini belum punya isi contoh (sample.json)."}
    user_id = get_user_id(tool_context)
    meta = report_engine.preview_meta(template, user_id)
    try:
        data, ext, ctype = report_engine.render(template, sample, meta, fmt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Render contoh gagal")
        return {"status": "error", "message": f"Contoh gagal dibuat: {exc}"}
    links = report_engine.save_output(user_id, template_id, meta["report_title"], data, ext, ctype,
                                      record={"preview": True})
    return {"status": "ok", "report_title": meta["report_title"], **links,
            "message": "Ini contoh tampilan dengan angka ilustrasi bawaan template, bukan hasil data atau insight."}


REPORT_TOOLS = [list_report_templates, generate_report, preview_report_template]
