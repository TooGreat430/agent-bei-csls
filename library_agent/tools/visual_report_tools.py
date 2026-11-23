"""Laporan VISUAL otomatis (Tahap B): user cukup meminta "buatkan laporan" — isi, alur, dan visual disusun Claude dari
seluruh hasil analisis di chat, angka diperiksa kode, file PPTX (chart native) / PDF / HTML dibuat mesin visual_report.

Prinsip: user TIDAK PERNAH melihat error teknis. Setiap kegagalan punya jalur cadangan (storyboard kode, deck
sederhana); bila benar-benar tidak bisa, pesan sopan tanpa detail teknis.
"""
from __future__ import annotations

import functools
import json
import logging
from typing import Any

from google.adk.tools import ToolContext

from .rfm_tools import _num, heavy_turn, is_rfm_request

logger = logging.getLogger(__name__)
VISUAL_KEY = "visual_reports"
TEMPLATE_ID = "laporan_visual"
CONTENT_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf",
                 "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
FORMAT_LABEL = {"pptx": "PowerPoint", "pdf": "PDF", "html": "HTML"}
CHAT_TEXTS = 8                  # jawaban analisis terakhir di chat yang angkanya wajib masuk laporan
SOFT_FAIL = ("Laporan belum berhasil disusun pada percobaan ini. Sampaikan ke user dengan sopan bahwa laporan "
             "sedang disiapkan ulang dan minta user mengirim ulang permintaan yang sama (cukup ketik 'buat ulang "
             "laporannya'). JANGAN menyebut error, kode, atau istilah teknis apa pun.")


def _quiet(func):
    """Pengaman terakhir: pengecualian apa pun -> pesan sopan (detail hanya di log)."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:  # noqa: BLE001
            logger.exception("%s gagal total", func.__name__)
            return {"status": "retry", "message": SOFT_FAIL}
    return wrapper


def _budget_ok() -> dict | None:
    from ..usage import heavy_allowed

    ok, msg = heavy_allowed()
    if ok:
        return None
    return {"status": "budget_limit", "message": msg + " Sampaikan pesan ini apa adanya ke user; jangan membuat "
                                                       "laporan dalam bentuk teks sebagai pengganti."}


# ------------------------------------------------------------------------------------------ bahan dari chat
def chat_texts(tool_context: Any, limit: int = CHAT_TEXTS) -> list[str]:
    """Jawaban analisis agent yang sudah dilihat user di chat ini (terbaru lebih dulu)."""
    ic = getattr(tool_context, "_invocation_context", None)
    events = list(getattr(getattr(ic, "session", None), "events", []) or [])
    out: list[str] = []
    for e in reversed(events[-200:]):
        if getattr(e, "author", "user") == "user":
            continue
        content = getattr(e, "content", None)
        parts = getattr(content, "parts", None) or []
        text = "".join(getattr(p, "text", "") or "" for p in parts if not getattr(p, "thought", False))
        if len(text.strip()) > 40:
            out.append(text.strip())
        if len(out) >= limit:
            break
    return out


def analysis_texts(tool_context: ToolContext) -> list[str]:
    """Sumber angka kunci: jawaban analisis di chat + fakta chart insight (dihitung kode) + insight tersimpan."""
    from .. import insights
    from .chart_insight_tools import CHARTS_KEY

    texts = chat_texts(tool_context)
    for c in (tool_context.state.get(CHARTS_KEY) or [])[-12:]:
        texts.append(f"{c.get('judul', '')}. " + ". ".join(c.get("fakta") or []))
    try:
        for it in insights.list_full(tool_context.state)[-6:]:
            texts.append(f"{it.get('title', '')}. {it.get('content', '')}")
    except Exception:  # noqa: BLE001
        logger.warning("Insight tersimpan tidak terbaca untuk laporan visual")
    return texts


def auto_source(state: Any) -> str:
    """Sumber bila model tidak menyebutnya: hasil analisis paling relevan yang ada di chat."""
    from .data_tools import LAST_KEY, PULLS_KEY
    from .doc_tools import DOCS_KEY

    last = state.get(LAST_KEY) or {}
    files = state.get("data_files") or []
    pulls = state.get(PULLS_KEY) or []
    docs = [d for d in state.get(DOCS_KEY) or [] if d.get("text_uri")]
    if last.get("domain") == "file" and files:
        return "file"
    if pulls:
        return str(pulls[-1].get("domain") or "")
    if files:
        return "file"
    if docs:
        return "dokumen"
    return ""


def _save(tool_context: ToolContext, title: str, out: dict, record: dict, keys: list[dict], data_text: str,
          formats: list[str]) -> tuple[dict[str, str], str, str]:
    from .. import report_engine
    from ..clients import get_user_id
    from .report_tools import _gcs_put

    user = get_user_id(tool_context)
    links: dict[str, str] = {}
    first_uri = ""
    for fmt in formats:
        data = out["files"].get(fmt)
        if not data:
            continue
        saved = report_engine.save_output(user, TEMPLATE_ID, title, data, fmt, CONTENT_TYPES[fmt], record=record)
        links[fmt] = saved["url"]
        first_uri = first_uri or saved["gcs_uri"]
    base = first_uri.rsplit(".", 1)[0]
    sb_uri, data_uri = base + ".storyboard.json", base + ".data.txt"
    try:
        _gcs_put(sb_uri, json.dumps({"storyboard": out["storyboard"], "keys": keys}, ensure_ascii=False),
                 "application/json")
        _gcs_put(data_uri, data_text)
    except Exception:  # noqa: BLE001  (file laporan sudah tersimpan; revisi saja yang tidak bisa)
        logger.exception("Storyboard laporan visual tidak tersimpan")
        sb_uri = data_uri = ""
    return links, sb_uri, data_uri


def _result(tool_context: ToolContext, out: dict, links: dict, record: dict) -> dict[str, Any]:
    reports = list(tool_context.state.get(VISUAL_KEY) or [])
    rid = f"v{len(reports) + 1}"
    reports.append({"report_id": rid, **record})
    tool_context.state[VISUAL_KEY] = reports[-10:]
    deck = out["deck"]
    titles = [s.title for s in deck.slides if s.title and s.kind not in ("judul", "lampiran")][:16]
    msg = (f"Laporan visual selesai: {out['stats']['slide']} halaman, {out['stats']['chart']} chart (bisa diedit di "
           "PowerPoint). Sampaikan ke user secara ringkas: judul laporan, 3–5 temuan utama (ambil dari 'alur_halaman'), "
           "lalu link setiap format. Tawarkan penyesuaian (tambah/kurangi halaman, ubah fokus atau gaya) — cukup "
           "tulis masukannya, nanti dipanggil revisi_laporan_visual. Jangan menempelkan isi laporan sebagai teks.")
    if out.get("angka_tidak_terverifikasi"):
        msg += (" Halaman terakhir memuat catatan beberapa angka yang tidak ditemukan di data sumber: "
                + ", ".join(out["angka_tidak_terverifikasi"][:8]) + ". Sampaikan dengan tenang agar user mengeceknya.")
    return {"status": "ok", "report_id": rid, "judul": deck.title, "file": links,
            "halaman": out["stats"]["slide"], "chart": out["stats"]["chart"], "alur_halaman": titles,
            "angka_perlu_dicek": out.get("angka_tidak_terverifikasi", []), "message": msg}


def _formats(output_format: str) -> list[str]:
    from .. import custom_report as cr

    return cr.parse_formats(output_format)


def _run(tool_context: ToolContext, request: str, data_text: str, label: str, formats: list[str], budget: float,
         images=None, previous: dict | None = None, feedback: str = "", keys: list[dict] | None = None,
         judul: str = "") -> dict[str, Any]:
    from ..visual_report.planner import key_numbers, make_report

    if keys is None:
        keys = key_numbers(analysis_texts(tool_context))
    try:
        out = make_report(request, data_text, keys, formats, title=judul, label=label, budget=budget,
                          previous=previous, feedback=feedback, images=images)
    except Exception:  # noqa: BLE001  (jalur cadangan: tanpa model)
        logger.exception("Laporan visual jalur utama gagal; memakai jalur cadangan tanpa model")
        if previous:
            from ..visual_report import render_report

            out = {**render_report(previous, formats, angka_wajib=[k["nilai"] for k in keys]), "storyboard": previous,
                   "angka_tidak_terverifikasi": []}
        else:
            out = make_report(request, data_text, keys, formats, title=judul, label=label, budget=60,
                              use_model=False)
    if not out["files"]:
        raise RuntimeError("tidak ada format yang berhasil dirender")
    title = out["deck"].title
    record = {"title": title, "request": request, "label": label, "formats": formats}
    links, sb_uri, data_uri = _save(tool_context, title, out, {**record, "jenis": "laporan_visual"}, keys, data_text,
                                    formats)
    record.update({"storyboard_uri": sb_uri, "data_uri": data_uri})
    return _result(tool_context, out, links, record)


# ------------------------------------------------------------------------------------------ alat
@_quiet
@heavy_turn("laporan visual")
def buat_laporan_visual(tool_context: ToolContext, permintaan: str = "", sumber: str = "", output_format: str = "",
                        file_id: str = "", data_questions: list[str] | None = None, period: str = "",
                        gambar_referensi: list[str] | None = None, judul: str = "") -> dict[str, Any]:
    """Membuat LAPORAN/DECK VISUAL OTOMATIS (PowerPoint dengan chart native, PDF, HTML) dari hasil analisis di chat —
    user TIDAK perlu menyebut isi laporan. Claude menyusun alur cerita (ringkasan eksekutif, angka kunci, chart
    papan skor/perbandingan/tren/waterfall/funnel/heatmap, SWOT/SMART/target/aksi/roadmap bila relevan); angka
    diperiksa kode dan angka kunci hasil analisis dijamin masuk. Ini PILIHAN UTAMA untuk setiap permintaan
    "buat laporan / deck / presentasi / PPT / PDF" dari analisis, KECUALI user membawa template/prompt laporan sendiri
    (pakai generate_custom_report) atau meminta laporan template standar (dashboard harga, industri, planogram,
    battlefield) atau RFM (analisis_rfm).

    Args:
        permintaan: Permintaan user apa adanya + konteks penting (fokus, audiens, periode). Boleh singkat.
        sumber: Asal bahan: "dokumen" (PDF/Word/PPT/TXT yang diunggah & dianalisis), "file" (CSV/Excel), "retail",
            "industri", "planogram", "sellout", atau "retail_planogram". Kosongkan bila ragu — dipilih otomatis dari
            analisis terakhir di chat.
        output_format: "pptx", "pdf", "html", atau gabungan ("pptx,pdf"). Kosongkan bila user belum memilih — alat
            akan meminta Anda menanyakannya.
        file_id: ID file/dokumen (mis. "f1" / "d1") bila ada beberapa; kosongkan untuk yang terakhir.
        data_questions: (BigQuery) 1-3 pertanyaan data tambahan bila data di chat belum cukup; biasanya kosong.
        period: Kuartal utama untuk Retail × Planogram (opsional).
        gambar_referensi: ID gambar contoh bentuk laporan (opsional); angka tidak pernah diambil dari gambar.
        judul: Judul laporan bila user menyebutkannya (opsional).
    """
    import time

    from ..config import live
    from .report_tools import _gather_source, _reference_images

    t0 = time.monotonic()
    blocked = _budget_ok()
    if blocked:
        return blocked
    formats = _formats(output_format)
    if not formats:
        return {"status": "needs_input", "available_formats": ["pptx", "pdf", "html"],
                "message": ("Tanyakan SEKALI ke user format laporan (boleh lebih dari satu): PowerPoint (siap presentasi, "
                            "chart bisa diedit), PDF (siap kirim/cetak), atau HTML (dibuka di browser). Isi laporan "
                            "tidak perlu ditanyakan — disusun otomatis dari analisis.")}
    src = (sumber or "").strip().lower().replace(" ", "") or auto_source(tool_context.state)
    if not src:
        return {"status": "needs_input",
                "message": ("Belum ada hasil analisis di chat ini untuk dijadikan laporan. Minta user mengunggah "
                            "dokumen/file atau menanyakan data terlebih dahulu.")}
    if "sellout" in src.replace("-", "").replace("sellingout", "sellout") and is_rfm_request(permintaan):
        return {"status": "redirect", "tool": "analisis_rfm",
                "message": "Laporan RFM outlet dibuat dengan analisis_rfm (dihitung kode), bukan laporan visual."}
    got = _gather_source(tool_context, permintaan or "laporan lengkap dari hasil analisis", src, data_questions,
                         file_id.strip(), period)
    if got.get("status") != "ok":
        return got
    images, _ = _reference_images(tool_context, gambar_referensi)
    budget = _num(live("visual_report_budget"), 240) - (time.monotonic() - t0)   # waktu tarik data ikut dihitung
    return _run(tool_context, permintaan, got["data_text"], got["label"], formats, max(60.0, budget), images=images,
                judul=judul)


@_quiet
@heavy_turn("revisi laporan visual")
def revisi_laporan_visual(masukan: str, tool_context: ToolContext, report_id: str = "",
                          output_format: str = "") -> dict[str, Any]:
    """Merevisi laporan visual sesuai masukan user (tambah/kurangi halaman, ubah fokus, gaya, urutan, judul) dan
    membuat versi baru di semua format sebelumnya (atau output_format bila user meminta format lain).

    Args:
        masukan: Masukan user apa adanya.
        report_id: ID laporan visual (mis. "v1"); kosongkan untuk yang terakhir.
        output_format: Format baru bila user meminta (opsional).
    """
    from ..config import live
    from .report_tools import _gcs_text

    if not (masukan or "").strip():
        return {"status": "needs_input", "message": "Tanyakan ke user bagian laporan yang ingin diubah."}
    blocked = _budget_ok()
    if blocked:
        return blocked
    reports = tool_context.state.get(VISUAL_KEY) or []
    rec = next((r for r in reports if r.get("report_id") == report_id), None) if report_id else \
        (reports[-1] if reports else None)
    if not rec or not rec.get("storyboard_uri"):
        return {"status": "needs_input", "message": ("Belum ada laporan visual yang bisa direvisi di chat ini. Tawarkan "
                                                     "membuat laporan baru dengan buat_laporan_visual.")}
    saved = json.loads(_gcs_text(rec["storyboard_uri"]))
    data_text = _gcs_text(rec["data_uri"]) if rec.get("data_uri") else ""
    formats = _formats(output_format) or rec.get("formats") or ["pptx"]
    budget = _num(live("visual_report_budget"), 240)
    return _run(tool_context, rec.get("request", ""), data_text, rec.get("label", ""), formats, budget,
                previous=saved.get("storyboard"), feedback=masukan, keys=saved.get("keys") or [])


VISUAL_TOOLS = [buat_laporan_visual, revisi_laporan_visual]
