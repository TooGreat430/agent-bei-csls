"""Tool ADK untuk Report sub-agent."""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import insights, report_engine, search
from ..clients import get_user_id
from .library_tools import ACTIVE_KEY, DEFAULT_WORKSPACE, WORKSPACE_KEY

logger = logging.getLogger(__name__)


def _with_dashboard(items: list) -> list:
    return list(items) + [DASHBOARD_INFO]


def list_report_templates() -> dict[str, Any]:
    """Menampilkan template laporan resmi yang tersedia beserta bagian-bagiannya."""
    try:
        return {"status": "ok", "templates": _with_dashboard(report_engine.list_templates())}
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
    include_charts: bool = True,
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
        include_charts: False jika user meminta laporan TANPA grafik. Jika True, grafik yang sudah
            dibuat di chat (tersimpan bersama insight) dipakai apa adanya di laporan.

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
        content = report_engine.apply_insight_charts(template, content, items, include_charts)
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
    logger.info("Laporan dibuat: %s (%s)", meta["report_title"], fmt)
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


DASHBOARD_ID = "dashboard_daya_saing_harga"
DASHBOARD_INFO = {
    "template_id": DASHBOARD_ID,
    "title": "Dashboard Daya Saing Harga Retail (langsung dari BigQuery)",
    "description": ("Dashboard eksekutif lengkap: Executive Summary multizona, lalu per zona (Nasional, Zona 1-3) "
                    "halaman konsumen (HET vs harga jual) dan outlet (HTO & margin bengkel), dengan KPI, tabel SKU, "
                    "grafik per segmen, anomali, dan kompetitor yang perlu diwaspadai. Data diambil langsung dari "
                    "BigQuery untuk periode yang diminta (bisa dibandingkan dengan periode lain); tidak butuh insight."),
    "formats": ["html", "pdf", "pptx"],
}
CONTENT_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf",
                 "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


def _render_dashboard(pages: list, meta: dict, fmt: str) -> bytes:
    from .. import dashboard_render as dr

    return {"html": dr.render_html, "pdf": dr.render_pdf, "pptx": dr.render_pptx}[fmt](pages, meta)


def generate_price_dashboard(period: str, tool_context: ToolContext, compare_period: str = "",
                             output_format: str = "", title: str = "") -> dict[str, Any]:
    """Membuat DASHBOARD daya saing harga retail lengkap langsung dari data BigQuery.

    Gunakan saat user meminta laporan/dashboard daya saing harga (price competitiveness) untuk suatu
    periode, mis. "laporan daya saing harga Q3 2026 vs Q2 2026". Tidak memerlukan insight.

    Args:
        period: Periode utama. Format: "2026-Q3", "2026-07", atau rentang "2026-04:2026-06".
        compare_period: Periode pembanding (opsional, HANYA jika user meminta perbandingan), format sama.
        output_format: "pdf", "pptx" (PowerPoint), atau "html". Kosongkan jika user belum menyebut.
        title: Judul laporan (opsional).
    """
    from .. import price_dashboard, price_data
    from ..config import live, settings

    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": DASHBOARD_INFO["formats"],
                "message": "Tanyakan ke user format yang diinginkan: PDF, PowerPoint, atau HTML (dengan tab)."}
    try:
        pa = price_data.parse_period(period)
        pb = price_data.parse_period(compare_period) if compare_period.strip() else None
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    heroes = list(live("hero_products") or settings.hero_products)
    try:
        agg, monthly = price_data.fetch(pa, pb, heroes, live("price_table") or settings.price_table)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query dashboard gagal")
        hint = " Service account agent belum punya akses ke tabel BigQuery." if "403" in str(exc) or "Access Denied" in str(exc) else ""
        return {"status": "error", "message": f"Data BigQuery tidak bisa diambil.{hint}", "detail": str(exc)[:300]}
    dataset = price_data.build_dataset(agg, monthly, heroes, pa, pb, live("status_aman_below"), live("status_kritis_above"))
    if not dataset["has_data"]:
        return {"status": "error", "message": f"Tidak ada data survei untuk periode {pa['label']}. Coba periode lain."}
    has_b = any(r["PERIOD"] == "B" for r in agg)
    company = live("company_name")
    narrative = price_dashboard.generate_narrative(dataset, company)
    pages = price_dashboard.build_pages(dataset, narrative, company)
    periode = f"{pb['label']} vs {pa['label']}" if pb else pa["label"]
    title = title.strip() or f"Dashboard Daya Saing Harga Retail {periode}"
    meta = {"report_title": title, "period_text": f"{periode} · Standardized per liter (IDR/L)", "company": company}
    try:
        data = _render_dashboard(pages, meta, fmt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Render dashboard gagal")
        return {"status": "error", "message": f"Dashboard gagal dibuat: {exc}"}
    links = report_engine.save_output(get_user_id(tool_context), DASHBOARD_ID, title, data, fmt, CONTENT_TYPES[fmt],
                                      record={"source": "bigquery", "periode": pa["label"],
                                              "pembanding": pb["label"] if pb else None})
    note = "" if not pb or has_b else f" Data periode pembanding {pb['label']} tidak ditemukan, jadi kolom tren kosong."
    logger.info("Dashboard dibuat: %s (%s)", title, fmt)
    return {"status": "ok", "report_title": title, **links, "message": f"Dashboard siap.{note}"}


def preview_price_dashboard(tool_context: ToolContext, output_format: str = "") -> dict[str, Any]:
    """Contoh tampilan dashboard daya saing harga dengan DATA ILUSTRASI (bukan data asli).

    Args:
        output_format: "pdf", "pptx", atau "html". Kosongkan jika user belum menyebut.
    """
    from .. import price_dashboard, price_data, sample_price

    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": DASHBOARD_INFO["formats"],
                "message": "Tanyakan ke user format contoh yang diinginkan (PDF, PowerPoint, atau HTML)."}
    agg, monthly = sample_price.make()
    pa, pb = price_data.parse_period("2026-Q3"), price_data.parse_period("2026-Q2")
    dataset = price_data.build_dataset(agg, monthly, sample_price.HEROES, pa, pb)
    pages = price_dashboard.build_pages(dataset, {"ringkasan": [], "insight_eksekutif": [], "zona": {}}, "PT Pertamina Lubricants")
    for p in pages:
        p["footer"] = "CONTOH TAMPILAN — angka ilustrasi, bukan data asli · " + p["footer"]
    title = "CONTOH TAMPILAN - Dashboard Daya Saing Harga Retail"
    meta = {"report_title": title, "period_text": "Q2 2026 vs Q3 2026 · ILUSTRASI", "company": "PT Pertamina Lubricants"}
    data = _render_dashboard(pages, meta, fmt)
    links = report_engine.save_output(get_user_id(tool_context), DASHBOARD_ID, title, data, fmt, CONTENT_TYPES[fmt],
                                      record={"preview": True})
    return {"status": "ok", "report_title": title, **links,
            "message": "Ini contoh tampilan dengan angka ilustrasi, bukan data asli."}


REPORT_TOOLS = [list_report_templates, generate_report, preview_report_template,
                generate_price_dashboard, preview_price_dashboard]
