"""Tool ADK untuk Report sub-agent: laporan TEMPLATE (retail, industri, planogram) dan laporan CUSTOM."""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import insights, report_engine
from ..clients import get_user_id

logger = logging.getLogger(__name__)


def _logged(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001  (jangan biarkan error menjatuhkan agent)
            logger.exception("%s gagal", func.__name__)
            result = {"status": "error", "message": f"Laporan gagal dibuat karena kendala teknis: {str(exc)[:200]}"}
        if isinstance(result, dict) and result.get("status") != "ok":
            logger.warning("%s -> %s: %s", func.__name__, result.get("status"), str(result.get("message"))[:300])
        return result
    return wrapper


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


def generate_price_dashboard(tool_context: ToolContext, period: str = "", compare_period: str = "",
                             output_format: str = "", title: str = "", file_id: str = "") -> dict[str, Any]:
    """Membuat LAPORAN (dashboard daya saing harga retail) langsung dari data BigQuery.

    Ini SATU-SATUNYA cara membuat laporan. Gunakan untuk semua permintaan laporan, termasuk
    "buatkan laporan dari insight tadi" (periode diambil otomatis dari insight di chat).

    Args:
        period: Periode utama. Format: "2026-Q3", "2026-07", atau rentang "2026-04:2026-06".
            Kosongkan jika user tidak menyebut periode; periode diambil dari insight di chat (atau bulan
            terakhir di file jika file_id diisi).
        file_id: Isi (mis. "f1") jika laporan dibuat dari FILE unggahan format survei retail, bukan BigQuery.
        compare_period: Periode pembanding (opsional, HANYA jika user meminta perbandingan), format sama.
        output_format: "pdf", "pptx" (PowerPoint), atau "html". Kosongkan jika user belum menyebut.
        title: Judul laporan (opsional).
    """
    from .. import price_dashboard, price_data
    from ..config import live, settings

    frame, entry = (None, None)
    if file_id.strip():
        frame, entry = _file_frame(tool_context, file_id.strip(), "retail")
        if frame is None:
            return {"status": "error", "message": entry}
        if not period.strip():
            period = _latest_month(frame)
    if not period.strip():
        texts = []
        for it in insights.list_full(tool_context.state):
            if it.get("source") != "bigquery":
                continue
            texts += [it.get("title", ""), it.get("content", ""), " ".join(it.get("citations") or []),
                      ((it.get("data") or {}).get("question") or "")]
        period = price_data.infer_period(texts) or ""
        if not period:
            return {"status": "needs_input",
                    "message": "Tanyakan ke user periode laporannya (mis. Juli 2026, atau Q3 2026 vs Q2 2026)."}
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
        if frame is not None:
            from .. import data_engine as de

            agg, monthly = de.retail_report_rows(frame, pa, pb, heroes)
        else:
            agg, monthly = price_data.fetch(pa, pb, heroes, live("price_table") or settings.price_table)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query dashboard gagal")
        hint = " Service account agent belum punya akses ke tabel BigQuery." if "403" in str(exc) or "Access Denied" in str(exc) else ""
        return {"status": "error", "message": f"Data BigQuery tidak bisa diambil.{hint}", "detail": str(exc)[:300]}
    dataset = price_data.build_dataset(agg, monthly, heroes, pa, pb, live("status_aman_below"), live("status_kritis_above"))
    if entry:
        dataset["source_label"] = f"File unggahan {entry['filename']}"
    if not dataset["has_data"]:
        return {"status": "error", "message": f"Tidak ada data survei untuk periode {pa['label']}. Coba periode lain."}
    has_b = any(r["PERIOD"] == "B" for r in agg)
    company = live("company_name")
    narrative = price_dashboard.generate_narrative(dataset, company)
    chat_cards = [{"kategori": "INSIGHT DARI DISKUSI", "judul": i.get("title", ""),
                   "uraian": (i.get("content") or "")[:320], "tingkat": "perhatian"}
                  for i in insights.list_full(tool_context.state) if i.get("source") == "bigquery"]
    narrative["insight_eksekutif"] = (chat_cards[:2] + narrative.get("insight_eksekutif", []))[:4]
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


generate_price_dashboard = _logged(generate_price_dashboard)
preview_price_dashboard = _logged(preview_price_dashboard)
INDUSTRY_ID = "daya_saing_harga_industri"


def _file_frame(tool_context: ToolContext, file_id: str, expected_kind: str):
    """Frame file unggahan yang sudah diberi aturan bisnis. Mengembalikan (frame, entry) atau (None, pesan)."""
    from .. import data_engine as de
    from ..config import live

    entry = next((f for f in tool_context.state.get("data_files", []) if f["file_id"] == file_id), None)
    if not entry:
        return None, f"File {file_id} tidak ada di chat ini."
    df, _ = de.load_frame(entry["uri"], entry["filename"], entry.get("sheet"))
    kind = de.detect_kind(df)
    if kind != expected_kind:
        return None, (f"File {entry['filename']} bukan format survei {expected_kind} (terdeteksi: {kind}); "
                      "laporan template ini tidak bisa dibuat dari file tersebut.")
    prepared, _ = de.prepare(df, kind, list(live("hero_products") or [])
                             )
    return prepared, entry


def _latest_month(df) -> str:
    months = sorted(m for m in df.get("PERIODE", []).dropna().unique() if isinstance(m, str) and len(m) == 7) \
        if "PERIODE" in df.columns else []
    return months[-1] if months else ""


def _industry_period(tool_context: ToolContext, period: str) -> str:
    from .. import price_data

    if period.strip():
        return period
    texts = []
    for it in insights.list_full(tool_context.state):
        if it.get("source") == "bigquery_industri":
            texts += [it.get("title", ""), it.get("content", ""), ((it.get("data") or {}).get("question") or "")]
    found = price_data.infer_period(texts) or ""
    return found.split(":")[-1] if ":" in found else ("" if "Q" in found else found)


def generate_industry_report(tool_context: ToolContext, period: str = "", output_format: str = "",
                             competitor: str = "", title: str = "", file_id: str = "") -> dict[str, Any]:
    """Membuat laporan "Price Competitiveness Analysis — B2B Segment" (INDUSTRI) dari survei industri BigQuery.

    One-pager: tombol Early/Next Stage, KPI per kategori produk & segmen customer, matriks gap per zona
    dan per segmen customer (Agro, Construction, Fleet, Manufacturing, Marine, Mining), executive summary.
    Gap (%) = (harga kompetitor − HTD PTPL+3%) / HTD PTPL+3%; POSITIF = PTPL kompetitif.

    Args:
        period: Bulan laporan "YYYY-MM" (mis. "2026-08"). Dibandingkan otomatis dengan bulan sebelumnya.
            Kosongkan jika user tidak menyebut; diambil dari insight industri di chat.
        output_format: "pdf", "pptx", atau "html". Kosongkan jika user belum menyebut.
        competitor: Merek pembanding (default dari pengaturan, mis. SHELL).
        title: Judul laporan (opsional).
        file_id: Isi (mis. "f1") jika laporan dibuat dari FILE unggahan format survei industri, bukan BigQuery.
    """
    from .. import industry_data as idm
    from .. import industry_report as ir
    from ..config import live

    frame, entry = (None, None)
    if file_id.strip():
        frame, entry = _file_frame(tool_context, file_id.strip(), "industri")
        if frame is None:
            return {"status": "error", "message": entry}
        if not period.strip():
            period = _latest_month(frame)
    period = _industry_period(tool_context, period)
    if not period:
        return {"status": "needs_input", "message": "Tanyakan ke user bulan laporannya (mis. Agustus 2026)."}
    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": ["pdf", "pptx", "html"],
                "message": "Tanyakan ke user format yang diinginkan: PDF, PowerPoint, atau HTML (dengan tombol stage)."}
    try:
        pa = idm.month_period(period)
        pb = idm.month_period(idm.previous_month(pa["months"][0]))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    comps = [competitor.strip().upper()] if competitor.strip() else list(live("industry_competitors") or ["SHELL"])
    try:
        if frame is not None:
            from .. import data_engine as de

            rows = de.industry_report_rows(frame, pa, pb, live("industry_htd_column"),
                                           live("industry_segment_column") or "channel")
        else:
            rows = idm.fetch(pa, pb, live("industry_table"), live("industry_htd_column"),
                             live("industry_segment_column") or "channel")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Query industri gagal")
        hint = " Service account agent belum punya akses ke tabel survei industri." if "403" in str(exc) or "Access Denied" in str(exc) else ""
        return {"status": "error", "message": f"Data survei industri tidak bisa diambil.{hint}", "detail": str(exc)[:300]}
    ds = idm.build_dataset(rows, list(live("industry_focus_products")), comps, pa, pb,
                           segments_focus=list(live("industry_segments") or []))
    if entry:
        ds["source_label"] = f"File unggahan {entry['filename']}"
    if not ds["has_data"]:
        msg = f"Tidak ada data survei industri untuk {pa['label']} dengan pembanding {', '.join(comps)}."
        if ds["unmatched"]:
            msg += " Nama produk di data tidak cocok dengan daftar produk fokus; contoh: " + ", ".join(ds["unmatched"][:5])
        return {"status": "error", "message": msg}
    company = live("company_name")
    narr = ir.generate_narrative(ds, comps[0])
    title = title.strip() or f"Price Competitiveness B2B {pa['label']}"
    meta = {"report_title": title, "company": company, "competitor": comps[0]}
    data = ir.RENDERERS[fmt](ds, narr, meta)
    links = report_engine.save_output(get_user_id(tool_context), INDUSTRY_ID, title, data, fmt, CONTENT_TYPES[fmt],
                                      record={"source": "bigquery_industri", "periode": pa["label"]})
    note = ""
    if ds["unmatched"]:
        note = f" Catatan: {len(ds['unmatched'])} nama produk di data tidak termasuk produk fokus dan tidak dihitung."
    return {"status": "ok", "report_title": title, **links, "message": "Laporan industri siap." + note}


def preview_industry_report(tool_context: ToolContext, output_format: str = "") -> dict[str, Any]:
    """Contoh tampilan laporan industri (B2B) dengan DATA ILUSTRASI (bukan data asli).

    Args:
        output_format: "pdf", "pptx", atau "html". Kosongkan jika user belum menyebut.
    """
    from .. import industry_data as idm
    from .. import industry_report as ir

    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": ["pdf", "pptx", "html"],
                "message": "Tanyakan ke user format contoh yang diinginkan (PDF, PowerPoint, atau HTML)."}
    pa, pb = idm.month_period("2026-08"), idm.month_period("2026-07")
    ds = idm.build_dataset(ir.sample_rows(), idm.DEFAULT_FOCUS, ["SHELL"], pa, pb)
    title = "CONTOH TAMPILAN - Price Competitiveness B2B (ILUSTRASI)"
    meta = {"report_title": title, "company": "PT Pertamina Lubricants", "competitor": "SHELL"}
    data = ir.RENDERERS[fmt](ds, {}, meta)
    links = report_engine.save_output(get_user_id(tool_context), INDUSTRY_ID, title, data, fmt, CONTENT_TYPES[fmt],
                                      record={"preview": True})
    return {"status": "ok", "report_title": title, **links, "message": "Ini contoh tampilan dengan angka ilustrasi, bukan data asli."}


generate_industry_report = _logged(generate_industry_report)
preview_industry_report = _logged(preview_industry_report)


# ==========================================================================
# Pilihan laporan
# ==========================================================================
def list_report_options() -> dict[str, Any]:
    """Pilihan laporan yang tersedia: TEMPLATE (isi & tata letak tetap) atau CUSTOM (disusun bebas oleh model
    utama dengan design system PTPL, mengikuti prompt laporan MIR). Tampilkan ke user saat jenis belum jelas."""
    return {"status": "ok",
            "template": [
                {"nama": "Daya Saing Harga Retail", "sumber": "BigQuery retail / file survei retail",
                 "format": ["pdf", "pptx", "html"], "tool": "generate_price_dashboard"},
                {"nama": "Daya Saing Harga Industri (B2B)", "sumber": "BigQuery industri / file survei industri",
                 "format": ["pdf", "pptx", "html"], "tool": "generate_industry_report"},
                {"nama": "Kinerja Planogram PTPL vs Kompetitor", "sumber": "BigQuery planogram / file VM_PLANOGRAM",
                 "isi": "sebaran outlet (carry & ND), availability & visibility, whitespace, rekomendasi per audiens",
                 "format": ["pdf", "pptx", "html"], "tool": "generate_planogram_report"}],
            "custom": {"sumber": ["retail", "industri", "planogram", "file unggahan"], "format": ["html"],
                       "status": "DRAFT sampai user menyetujui (approve)", "tool": "generate_custom_report"}}


# ==========================================================================
# Template planogram
# ==========================================================================
PLANOGRAM_ID = "kinerja_planogram"
PLANOGRAM_RENDER = {"html": "render_html", "pdf": "render_pdf", "pptx": "render_pptx"}


def _planogram_file_rows(tool_context: ToolContext, file_id: str, pa: dict, pb: dict | None):
    from .. import data_engine as de
    from .. import planogram_data as pdm

    entry = next((f for f in tool_context.state.get("data_files", []) if f["file_id"] == file_id), None)
    if not entry:
        return None, f"File {file_id} tidak ada di chat ini.", {}
    df, _ = de.load_frame(entry["uri"], entry["filename"], entry.get("sheet"))
    kind = entry.get("kind") if entry.get("kind_manual") else de.detect_kind(df)
    if kind != "planogram":
        return None, (f"File {entry['filename']} bukan format survei planogram VM_PLANOGRAM (terdeteksi: {kind}); "
                      "template planogram tidak bisa dibuat dari file tersebut."), {}
    prepared, notes = de.prepare(df, "planogram")
    return pdm.to_rows(prepared, pa, pb), entry, notes


def generate_planogram_report(tool_context: ToolContext, period: str = "", compare_period: str = "",
                              output_format: str = "", title: str = "", file_id: str = "",
                              focus: str = "") -> dict[str, Any]:
    """Membuat laporan TEMPLATE "Kinerja Planogram PTPL vs Kompetitor" (6 halaman, gaya design system PTPL).

    Isi: ringkasan eksekutif (KPI), sebaran outlet per SR (carry & ND), posisi per viskositas, availability &
    visibility (matriks KIMAP), analisa whitespace, dan rekomendasi untuk Management, Brand Owner, Sales Region.

    Args:
        period: Kuartal utama, mis. "2026-Q3". Kosongkan untuk default (dari pengaturan, mis. Q3 2026).
        compare_period: Kuartal pembanding. Kosongkan untuk kuartal sebelumnya secara otomatis.
        output_format: "pdf", "pptx" (PowerPoint), atau "html". Kosongkan jika user belum menyebut.
        title: Judul laporan (opsional).
        file_id: Isi (mis. "f1") jika laporan dibuat dari FILE unggahan berformat VM_PLANOGRAM, bukan BigQuery.
        focus: Penekanan tambahan dari user untuk narasi (opsional, mis. "fokus MCO Automatic di SR5").
    """
    from .. import data_engine as de
    from .. import planogram_data as pdm
    from .. import planogram_report as pr
    from .. import ptpl_design
    from ..config import live

    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": ["pdf", "pptx", "html"],
                "message": "Tanyakan ke user format yang diinginkan: PDF, PowerPoint, atau HTML."}
    try:
        pa = pdm.parse_period(period.strip() or live("planogram_default_period") or "2026-Q3")
        pb = pdm.parse_period(compare_period) if compare_period.strip() else pdm.previous_period(pa)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    entry, notes = None, {}
    if file_id.strip():
        rows, entry, notes = _planogram_file_rows(tool_context, file_id.strip(), pa, pb)
        if rows is None:
            return {"status": "error", "message": entry}
    else:
        try:
            raw = pdm.fetch(pa, pb, live("planogram_table"))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Query planogram gagal")
            hint = (" Service account agent belum punya akses ke tabel VM_PLANOGRAM."
                    if "403" in str(exc) or "Access Denied" in str(exc) else "")
            return {"status": "error", "message": f"Data planogram tidak bisa diambil.{hint}", "detail": str(exc)[:300]}
        if raw.empty:
            return {"status": "error", "message": f"Tidak ada data planogram untuk {pa['label']}. Coba periode lain."}
        prepared, notes = de.prepare(raw, "planogram")
        rows = pdm.to_rows(prepared, pa, pb)
    keep = {k: v for k, v in notes.items() if k in ("excluded", "viskositas_2T_dinormalisasi")}
    ds = pdm.build_dataset(rows, pa, pb, float(live("planogram_carry_ratio_line") or 70),
                           int(live("planogram_min_carry") or 30), keep)
    if entry:
        ds["source_label"] = f"File unggahan {entry['filename']} (format VM_PLANOGRAM)"
    if not ds["has_data"]:
        return {"status": "error", "message": f"Tidak ada data oli mesin untuk {pa['label']}. Coba periode lain."}
    narr = pr.generate_narrative(ds, live("company_name"), focus)
    pages = pr.build_pages(ds, narr)
    for p in pages:
        p["draft"] = False
    periode = f"{pb['label']} vs {pa['label']}" if ds["has_b"] else pa["label"]
    title = title.strip() or f"Kinerja Planogram PTPL vs Kompetitor {periode}"
    data = getattr(ptpl_design, PLANOGRAM_RENDER[fmt])(pages, title)
    links = report_engine.save_output(get_user_id(tool_context), PLANOGRAM_ID, title, data, fmt,
                                      report_engine.FORMATS[fmt][1],
                                      record={"source": "file" if entry else "bigquery_planogram", "periode": pa["label"],
                                              "pembanding": pb["label"] if pb else None})
    note = "" if ds["has_b"] or not pb else f" Data pembanding {pb['label']} tidak ditemukan, jadi kolom perubahan berisi n/a."
    return {"status": "ok", "report_title": title, **links, "message": f"Laporan planogram siap.{note}"}


def preview_planogram_report(tool_context: ToolContext, output_format: str = "") -> dict[str, Any]:
    """Contoh tampilan laporan planogram dengan DATA ILUSTRASI (bukan data asli).

    Args:
        output_format: "pdf", "pptx", atau "html". Kosongkan jika user belum menyebut.
    """
    from .. import data_engine as de
    from .. import planogram_data as pdm
    from .. import planogram_report as pr
    from .. import ptpl_design, sample_planogram

    fmt = report_engine.normalize_format(output_format)
    if not fmt:
        return {"status": "needs_input", "available_formats": ["pdf", "pptx", "html"],
                "message": "Tanyakan ke user format contoh yang diinginkan (PDF, PowerPoint, atau HTML)."}
    pa, pb = pdm.parse_period("2026-Q3"), pdm.parse_period("2026-Q2")
    prepared, notes = de.prepare(sample_planogram.rows(), "planogram")
    ds = pdm.build_dataset(pdm.to_rows(prepared, pa, pb), pa, pb, 70, 30,
                           {"viskositas_2T_dinormalisasi": notes.get("viskositas_2T_dinormalisasi")})
    ds["source_label"] = "CONTOH TAMPILAN — angka ilustrasi, bukan data asli"
    pages = pr.build_pages(ds, pr.fallback_narrative(ds))
    for p in pages:
        p["draft"] = False
    title = "CONTOH TAMPILAN - Kinerja Planogram PTPL vs Kompetitor (ILUSTRASI)"
    data = getattr(ptpl_design, PLANOGRAM_RENDER[fmt])(pages, title)
    links = report_engine.save_output(get_user_id(tool_context), PLANOGRAM_ID, title, data, fmt,
                                      report_engine.FORMATS[fmt][1], record={"preview": True})
    return {"status": "ok", "report_title": title, **links, "message": "Ini contoh tampilan dengan angka ilustrasi, bukan data asli."}


# ==========================================================================
# Laporan custom (prompt MIR + model utama)
# ==========================================================================
CUSTOM_ID = "laporan_custom"
CUSTOM_KEY = "custom_reports"
INSIGHT_DOMAIN = {"bigquery": "retail", "bigquery_industri": "industri", "bigquery_planogram": "planogram"}


def _gcs_text(uri: str) -> str:
    from ..clients import parse_gcs_uri, storage_client

    bucket, path = parse_gcs_uri(uri)
    return storage_client().bucket(bucket).blob(path).download_as_text()


def _gcs_put(uri: str, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
    from ..clients import parse_gcs_uri, storage_client

    bucket, path = parse_gcs_uri(uri)
    storage_client().bucket(bucket).blob(path).upload_from_string(text, content_type=content_type)


def _insight_blocks(tool_context: ToolContext, domain: str = "", file_based: bool = False) -> list[str]:
    from .. import custom_report as cr

    out = []
    for it in insights.list_full(tool_context.state):
        src = it.get("source", "")
        if file_based and not str(src).startswith("file"):
            continue
        if not file_based and INSIGHT_DOMAIN.get(src) != domain:
            continue
        data = it.get("data") or {}
        tables = [data] if data.get("columns") else []
        out.append(cr.data_block(f"Insight tersimpan: {it.get('title', '')}", it.get("content", ""), tables))
    return out


def _file_auto_analyses(kind: str) -> list[tuple[str, dict]]:
    """Analisis standar per jenis file untuk bahan laporan custom (dihitung pandas)."""
    if kind == "planogram":
        return [("ND PTPL per kuartal & SR", {"preset": "planogram_nd", "preset_args": {"group_by": ["SR"]}}),
                ("ND PTPL per segmen & viskositas", {"preset": "planogram_nd",
                                                      "preset_args": {"group_by": ["SEGMEN_USAGE", "VISCOSITY"]}}),
                ("Skor AV PTPL vs kompetitor per SR (dalam KIMAP)", {"preset": "planogram_av", "preset_args": {"group_by": ["SR"]}}),
                ("Skor AV per KIMAP", {"preset": "planogram_av", "preset_args": {"group_by": ["PAIR_KIMAP"]}}),
                ("Whitespace per SR", {"preset": "planogram_whitespace", "preset_args": {"group_by": ["SR"]}})]
    if kind == "retail":
        return [("Gap harga PTPL vs kompetitor (KIMAP) per zona", {"preset": "gap_kimap",
                                                                   "preset_args": {"metrics": ["HJ_L", "HTO_L", "MARG_L"],
                                                                                   "group_by": ["ZONA"]}}),
                ("Gap harga Product Hero per zona", {"preset": "gap_kimap", "preset_args": {
                    "metrics": ["HJ_L", "HTO_L"], "group_by": ["ZONA"], "hero_only": True}})]
    if kind == "industri":
        return [("Gap % per channel", {"group_by": ["channel"], "metrics": [{"column": "GAP_PCT", "agg": "mean",
                                                                              "name": "GAP_PCT_RATA2"}]}),
                ("Gap % per zona", {"group_by": ["ZONA"], "metrics": [{"column": "GAP_PCT", "agg": "mean",
                                                                         "name": "GAP_PCT_RATA2"}]})]
    return []


def _file_data_text(tool_context: ToolContext, file_id: str) -> tuple[str, str, str]:
    """(teks data, jenis file, sumber) dari file unggahan: analisis standar + hasil analisis & insight di chat."""
    from .. import custom_report as cr
    from .. import data_engine as de
    from .data_tools import LAST_KEY
    from .file_tools import _prepared

    files = tool_context.state.get("data_files", [])
    entry = next((f for f in files if f["file_id"] == file_id), None) if file_id else (files[-1] if files else None)
    if not entry:
        return "", "", ""
    frame, notes, kind = _prepared(entry)
    blocks = [f"### File: {entry['filename']} (jenis data: {kind}; baris dipakai {notes.get('rows_used')}; "
              f"dikecualikan: {notes.get('excluded') or 'tidak ada'})"]
    for label, plan in _file_auto_analyses(kind):
        try:
            res = de.run_plan({"f": frame}, {"file": "f", "limit": 200, **plan})
            blocks.append(cr.data_block(label, "", [{"columns": res["columns"], "rows": res["rows"],
                                                     "total_rows": res["rows_total"]}]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analisis standar '%s' gagal: %s", label, str(exc)[:200])
    last = tool_context.state.get(LAST_KEY) or {}
    if last.get("domain") == "file" and last.get("file_id") == entry["file_id"]:
        blocks.append(cr.data_block(f"Analisis terakhir di chat: {last.get('question', '')}", "", last.get("tables")))
    blocks += _insight_blocks(tool_context, file_based=True)
    return "\n\n".join(blocks) if len(blocks) > 1 else "", kind, f"File unggahan {entry['filename']}"


def _save_custom(tool_context: ToolContext, result: dict, domain: str, request: str, data_text: str, source: str,
                 parent: str = "") -> dict[str, Any]:
    from .. import custom_report as cr

    title = result["title"]
    links = report_engine.save_output(get_user_id(tool_context), CUSTOM_ID, title, cr.to_html(title, result["body"]),
                                      "html", report_engine.FORMATS["html"][1],
                                      record={"source": source, "domain": domain, "status": "DRAFT", "parent": parent,
                                              "angka_tidak_terverifikasi": result["unverified"]})
    data_uri = links["gcs_uri"].rsplit(".", 1)[0] + ".data.txt"
    _gcs_put(data_uri, data_text)
    reports = list(tool_context.state.get(CUSTOM_KEY, []))
    rid = f"r{len(reports) + 1}"
    reports.append({"report_id": rid, "title": title, "domain": domain, "request": request, "source": source,
                    "html_uri": links["gcs_uri"], "data_uri": data_uri, "status": "DRAFT", "parent": parent})
    tool_context.state[CUSTOM_KEY] = reports[-10:]
    msg = ("Laporan custom berstatus DRAFT. Minta user meninjau, lalu ketik 'approve' untuk menerbitkan versi FINAL "
           "atau berikan masukan untuk revisi.")
    if result["unverified"]:
        msg += (" Pemeriksa angka menemukan angka yang tidak cocok dengan data sumber dan sudah diberi catatan di "
                "halaman terakhir: " + ", ".join(result["unverified"][:8]) + ". Sampaikan ini ke user.")
    return {"status": "ok", "report_id": rid, "report_title": title, **links, "status_laporan": "DRAFT",
            "angka_tidak_terverifikasi": result["unverified"], "penjelasan_model": result.get("explanation", ""),
            "message": msg}


def generate_custom_report(request: str, source: str, tool_context: ToolContext,
                           data_questions: list[str] | None = None, file_id: str = "") -> dict[str, Any]:
    """Membuat laporan CUSTOM (HTML, gaya design system PTPL) yang disusun model utama sesuai permintaan user,
    memakai prompt laporan MIR (Retail Only / Industry Only / Planogram). Status awal DRAFT.

    Data diambil lebih dulu: dari Data Agent BigQuery (source retail/industri/planogram) atau dari file unggahan
    (source "file"). Angka di laporan diperiksa otomatis terhadap data tersebut.

    Args:
        request: Permintaan laporan user selengkap mungkin (fokus produk/segmen/wilayah/periode, audiens).
        source: "retail", "industri", "planogram", atau "file".
        data_questions: 1-3 pertanyaan data untuk Data Agent yang bersama-sama mencakup permintaan (opsional;
            default: request). Abaikan jika source "file".
        file_id: ID file (mis. "f1") jika source "file"; kosongkan untuk file terakhir.
    """
    from .. import custom_report as cr
    from .. import data_agent
    from .data_tools import pull

    if not request.strip():
        return {"status": "needs_input", "message": "Tanyakan ke user isi laporan yang diinginkan (fokus, periode, audiens)."}
    src = source.strip().lower()
    if src in ("file", "upload", "unggahan", "csv", "excel"):
        data_text, kind, label = _file_data_text(tool_context, file_id.strip())
        if not data_text:
            return {"status": "needs_input",
                    "message": ("Belum ada file CSV/Excel atau hasil analisis yang bisa dipakai. Minta user mengunggah file "
                                "atau menganalisisnya dulu.") if not label else
                               ("Format file tidak dikenali sehingga belum ada angka untuk laporan. Minta user menganalisis "
                                "file dulu (mis. cross-tab) atau menyimpan hasilnya sebagai insight.")}
        domain = kind if kind in ("retail", "industri", "planogram") else "umum"
    else:
        domain = data_agent.normalize_domain(src)
        blocks, errors = [], []
        for q in (data_questions or [request])[:3]:
            res = pull(q, tool_context, domain)
            if res.get("status") == "needs_authorization":
                return res
            if res.get("status") != "ok":
                errors.append(res.get("message", "gagal"))
                continue
            blocks.append(cr.data_block(f"Hasil {data_agent.SOURCE_LABELS[domain]} — {q}", res["answer"], res["tables"]))
        blocks += _insight_blocks(tool_context, domain)
        if not blocks:
            return {"status": "error", "message": "Data tidak bisa diambil dari Data Agent: " + "; ".join(errors)[:300]}
        data_text = "\n\n".join(blocks)
        label = data_agent.SOURCE_LABELS[domain]
    result = cr.generate(domain, request, data_text)
    if result["status"] == "no_data":
        return {"status": "error", "message": "Data dari sumber tidak berisi angka yang bisa dipakai untuk laporan. "
                                              + result["message"][:200]}
    return _save_custom(tool_context, result, domain, request, data_text, label)


def _find_report(tool_context: ToolContext, report_id: str) -> dict | None:
    reports = tool_context.state.get(CUSTOM_KEY, [])
    if report_id:
        return next((r for r in reports if r["report_id"] == report_id), None)
    return reports[-1] if reports else None


def revise_custom_report(feedback: str, tool_context: ToolContext, report_id: str = "") -> dict[str, Any]:
    """Menulis ulang laporan CUSTOM dengan masukan user (data sama, status kembali DRAFT).

    Args:
        feedback: Masukan revisi dari user, persis seperti yang diminta.
        report_id: ID laporan (mis. "r1"); kosongkan untuk laporan custom terakhir.
    """
    from .. import custom_report as cr

    rec = _find_report(tool_context, report_id.strip())
    if not rec:
        return {"status": "error", "message": "Belum ada laporan custom di chat ini untuk direvisi."}
    html_doc = _gcs_text(rec["html_uri"])
    body = cr.parse_output("```html\n" + html_doc + "\n```")["body"]
    data_text = _gcs_text(rec["data_uri"])
    result = cr.generate(rec["domain"], rec["request"], data_text, previous_body=body, feedback=feedback)
    if result["status"] != "ok":
        return {"status": "error", "message": result.get("message", "Revisi gagal dibuat.")}
    return _save_custom(tool_context, result, rec["domain"], rec["request"], data_text, rec["source"], parent=rec["report_id"])


def approve_report(tool_context: ToolContext, report_id: str = "") -> dict[str, Any]:
    """Menyetujui laporan CUSTOM: label DRAFT diganti "FINAL · Disetujui <user> · <tanggal>" dan file FINAL diterbitkan.

    Panggil HANYA jika user secara eksplisit menyetujui (mis. "approve", "setuju", "ok final").

    Args:
        report_id: ID laporan (mis. "r2"); kosongkan untuk laporan custom terakhir.
    """
    from .. import custom_report as cr

    rec = _find_report(tool_context, report_id.strip())
    if not rec:
        return {"status": "error", "message": "Belum ada laporan custom di chat ini untuk disetujui."}
    if rec["status"] == "FINAL":
        return {"status": "ok", "report_title": rec["title"], "url": rec.get("final_url"), "message": "Laporan ini sudah FINAL."}
    user = get_user_id(tool_context)
    label = cr.approved_label(user)
    doc = _gcs_text(rec["html_uri"]).replace("<body>", f'<body class="final" data-approved="{label}">', 1)
    title = f"{rec['title']} (FINAL)"
    links = report_engine.save_output(user, CUSTOM_ID, title, doc.encode("utf-8"), "html", report_engine.FORMATS["html"][1],
                                      record={"source": rec["source"], "domain": rec["domain"], "status": "FINAL",
                                              "approved_by": user, "draft": rec["html_uri"]})
    reports = list(tool_context.state.get(CUSTOM_KEY, []))
    for r in reports:
        if r["report_id"] == rec["report_id"]:
            r.update(status="FINAL", final_url=links["url"])
    tool_context.state[CUSTOM_KEY] = reports
    return {"status": "ok", "report_id": rec["report_id"], "report_title": title, **links, "status_laporan": "FINAL",
            "message": f"Laporan disetujui ({label})."}


generate_planogram_report = _logged(generate_planogram_report)
preview_planogram_report = _logged(preview_planogram_report)
generate_custom_report = _logged(generate_custom_report)
revise_custom_report = _logged(revise_custom_report)
approve_report = _logged(approve_report)
REPORT_TOOLS = [list_report_options, generate_price_dashboard, preview_price_dashboard, generate_industry_report,
                preview_industry_report, generate_planogram_report, preview_planogram_report, generate_custom_report,
                revise_custom_report, approve_report]
