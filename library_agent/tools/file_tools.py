"""Tool agent analisis file: CSV/Excel yang diunggah user di chat ini."""
from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import data_engine as de
from ..config import live, settings
from .data_tools import CHART_KEY, LAST_KEY

logger = logging.getLogger(__name__)
FILES_KEY = "data_files"
KIND_LABEL = {"retail": "format Survei Retail (SURVEY_PRODUCTS)", "industri": "format Survei Industri (survey_industry)",
              "lainnya": "format umum"}


def _files(tool_context: ToolContext) -> list[dict]:
    return list(tool_context.state.get(FILES_KEY, []))


def _get(tool_context: ToolContext, file_id: str) -> dict | None:
    return next((f for f in _files(tool_context) if f["file_id"] == file_id), None)


def _frame(entry: dict, sheet: str = ""):
    df, sheets = de.load_frame(entry["uri"], entry["filename"], sheet or entry.get("sheet") or None)
    return df, sheets


def _prepared(entry: dict):
    df, _ = _frame(entry)
    kind = entry.get("kind") or de.detect_kind(df)
    heroes = list(live("hero_products") or settings.hero_products)
    return de.prepare(df, kind, heroes) + (kind,)


def _safe(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except de.PlanError as exc:
            return {"status": "invalid", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"File tidak bisa diproses: {str(exc)[:200]}"}
    return wrapper


@_safe
def list_data_files(tool_context: ToolContext) -> dict[str, Any]:
    """Daftar file data (CSV/Excel) yang sudah diunggah user di chat ini."""
    files = [{k: f.get(k) for k in ("file_id", "filename", "size_bytes", "kind", "rows")} for f in _files(tool_context)]
    return {"status": "ok", "files": files,
            "message": "" if files else "Belum ada file CSV/Excel di chat ini. Minta user mengunggahnya."}


@_safe
def profile_data_file(file_id: str, tool_context: ToolContext, sheet: str = "") -> dict[str, Any]:
    """Membaca dan memprofil file: jenis data, kolom, tipe, nilai unik, contoh baris, dan aturan yang diterapkan.

    Panggil SEBELUM analisis pertama atas suatu file.

    Args:
        file_id: ID file dari list_data_files (mis. "f1").
        sheet: Nama sheet Excel (opsional; default sheet pertama yang berisi data).
    """
    entry = _get(tool_context, file_id)
    if not entry:
        return {"status": "error", "message": f"File {file_id} tidak ada di chat ini."}
    df, sheets = _frame(entry, sheet)
    kind = de.detect_kind(df)
    heroes = list(live("hero_products") or settings.hero_products)
    prepared, notes = de.prepare(df, kind, heroes)
    files = _files(tool_context)
    for f in files:
        if f["file_id"] == file_id:
            f.update(kind=kind, rows=int(len(df)), sheet=sheet or f.get("sheet"))
    tool_context.state[FILES_KEY] = files
    prof = de.profile(df)
    return {"status": "ok", "file_id": file_id, "filename": entry["filename"], "sheets": sheets,
            "jenis_data": kind, "keterangan_jenis": KIND_LABEL[kind], "profil": prof,
            "aturan_diterapkan": notes, "kolom_tambahan_tersedia": notes["added_columns"],
            "catatan": ("Aturan bisnis survei diterapkan otomatis (filter wajib, harga per liter, zona). "
                        "Sebutkan jumlah baris yang dikecualikan ke user.") if kind != "lainnya" else
                       "Format umum: tidak ada aturan otomatis; tanyakan definisi bisnis yang tidak jelas ke user."}


@_safe
def find_join_keys(file_a: str, file_b: str, tool_context: ToolContext) -> dict[str, Any]:
    """Mencari kolom penghubung antara dua file berdasarkan kecocokan nilai. Tunjukkan buktinya ke user
    dan minta konfirmasi sebelum menggabungkan.

    Args:
        file_a: ID file pertama.
        file_b: ID file kedua.
    """
    ea, eb = _get(tool_context, file_a), _get(tool_context, file_b)
    if not ea or not eb:
        return {"status": "error", "message": "Salah satu file tidak ada di chat ini."}
    a, _, _ = _prepared(ea)
    b, _, _ = _prepared(eb)
    cand = de.find_join_keys(a, b)
    return {"status": "ok", "kandidat": cand,
            "message": "Tidak ada kolom dengan nilai yang cocok." if not cand else
                       "Sampaikan kandidat teratas beserta persentase kecocokan, lalu minta konfirmasi user."}


@_safe
def analyze_data(plan_json: str, question: str, tool_context: ToolContext) -> dict[str, Any]:
    """Menjalankan rencana analisis atas file unggahan. Angka DIHITUNG oleh kode (pandas), bukan oleh model.

    Args:
        plan_json: Rencana analisis (JSON). Kunci yang didukung:
            file (wajib, ID file), join {file, left_on[], right_on[], how}, filters [{column, op, value}]
            (op: == != > >= < <= in "not in" contains between isnull notnull), derive [{name, expr}]
            (expr aritmetika kolom), preset "gap_kimap" + preset_args {metrics[], group_by[],
            competitor_brands[], hero_only}, group_by [], metrics [{column, agg, name}]
            (agg: mean sum count min max median nunique), pivot {index[], columns, values, agg},
            columns [] (tanpa agregasi), sort [{column, desc}], limit (maks 200).
        question: Pertanyaan user yang sedang dijawab (untuk sitasi dan insight).
    """
    try:
        plan = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "message": f"plan_json bukan JSON yang valid: {exc}"}
    files = _files(tool_context)
    frames, notes, kinds = {}, {}, {}
    needed = {plan.get("file"), (plan.get("join") or {}).get("file")} - {None}
    for fid in needed:
        entry = next((f for f in files if f["file_id"] == fid), None)
        if not entry:
            return {"status": "error", "message": f"File {fid} tidak ada di chat ini."}
        frames[fid], notes[fid], kinds[fid] = _prepared(entry)
    result = de.run_plan(frames, plan)
    main = next(f for f in files if f["file_id"] == plan["file"])
    kind = kinds[plan["file"]]
    citation = f"File unggahan: {main['filename']}"
    tool_context.state[CHART_KEY] = None
    tool_context.state[LAST_KEY] = {"answer": "", "question": question, "domain": "file",
                                    "tables": [{"columns": result["columns"], "rows": result["rows"][:60]}],
                                    "citation": citation, "insight_source": f"file_{kind}",
                                    "file_id": plan["file"]}
    shown = result["rows"][:15]
    return {"status": "ok", "columns": result["columns"], "rows": shown, "rows_total": result["rows_total"],
            "baris_input": result["rows_input"], "baris_setelah_filter": result["rows_after_filter"],
            "aturan_diterapkan": {fid: n["excluded"] for fid, n in notes.items()},
            "jenis_data": kind, "source": citation, "table_columns": [result["columns"]],
            "message": ("Jawab HANYA dengan angka dari rows. Jika rows_total > baris yang ditampilkan, sebutkan "
                        "bahwa hanya sebagian yang ditampilkan.")}


def periksa_angka(angka_tidak_terverifikasi: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Pemeriksaan otomatis: dipanggil sistem jika jawaban memuat angka yang tidak ada di hasil tool.

    Args:
        angka_tidak_terverifikasi: Angka di jawaban yang tidak ditemukan pada hasil tool.
    """
    return {"status": "perlu_revisi",
            "message": ("Angka berikut tidak ada di hasil tool: " + ", ".join(angka_tidak_terverifikasi[:10])
                        + ". Tulis ulang jawaban HANYA dengan angka persis dari hasil tool di percakapan ini. "
                          "Jangan menghitung angka baru. Jika perlu angka lain, panggil tool lagi.")}


FILE_TOOLS = [list_data_files, profile_data_file, find_join_keys, analyze_data, periksa_angka]
