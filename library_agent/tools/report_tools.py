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
    report_title: str = "",
    extra_instructions: str = "",
    use_document_excerpts: bool = True,
) -> dict[str, Any]:
    """Membuat laporan dari insight tersimpan, mengikuti template resmi perusahaan.

    Layout laporan dikunci oleh template. Model hanya mengisi konten sesuai skema.

    Args:
        template_id: ID template dari list_report_templates.
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

    items = (insights.get_many(workspace, insight_ids) if insight_ids
             else insights.list_for(workspace))
    if not items:
        return {"status": "error",
                "message": "Belum ada insight yang bisa dijadikan landasan. Simpan insight terlebih dahulu."}

    excerpts: list[dict[str, Any]] = []
    active = list(tool_context.state.get(ACTIVE_KEY, []))
    if use_document_excerpts and active:
        seen = set()
        for item in items[:8]:
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
    html = report_engine.render_html(template, content, meta)
    pdf = report_engine.html_to_pdf(html) if "pdf" in template.manifest.get("outputs", ["html"]) else None
    links = report_engine.save_outputs(
        user_id, template_id, meta["report_title"], html, pdf,
        record={
            "workspace": workspace,
            "insight_ids": [i["insight_id"] for i in items],
            "doc_keys": active,
        },
    )
    return {"status": "ok", "report_title": meta["report_title"], **links}


REPORT_TOOLS = [list_report_templates, generate_report]
