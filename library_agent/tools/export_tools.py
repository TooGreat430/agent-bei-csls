"""Ekspor hasil analisis file ke Excel (.xlsx) — tanpa Code Execution, tanpa kode buatan model.

Setiap analyze_data di chat dicatat (state `file_analyses`). ekspor_excel menjalankan ULANG rencana analisis itu
dengan kode baku yang sama, tetapi TANPA batas baris tampilan (mis. seluruh 5.129 outlet, bukan Top 50), lalu menulis
satu workbook multi-sheet yang rapi dan memberi link unduhan. Angkanya identik dengan yang dijelaskan di chat.
"""
from __future__ import annotations

import functools
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)
EXCEL_MAX_ROWS = 1_000_000
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WIB = timezone(timedelta(hours=7))


def _safe(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"Ekspor Excel gagal karena kendala teknis: {str(exc)[:300]}"}
    return wrapper


def sheet_name(title: str, used: set[str]) -> str:
    base = re.sub(r"\s+", " ", re.sub(r"[\[\]:*?/\\]+", " ", title or "Analisis")).strip()[:28] or "Analisis"
    name, n = base, 2
    while name.lower() in used:
        name = f"{base[:25]} {n}"
        n += 1
    used.add(name.lower())
    return name


def build_workbook(sheets: list[dict[str, Any]], info_rows: list[list[Any]], title: str) -> bytes:
    """sheets: [{'name', 'df'}]. Header tebal, freeze baris 1, filter, lebar kolom menyesuaikan isi."""
    import pandas as pd
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        info = pd.DataFrame(info_rows, columns=["Sheet", "Isi analisis", "Sumber", "Jumlah baris", "Catatan"])
        info.to_excel(writer, sheet_name="Keterangan", index=False, startrow=3)
        ws = writer.sheets["Keterangan"]
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=13, color="0C1E3C")
        ws["A2"] = (f"Dibuat {datetime.now(WIB).strftime('%d-%m-%Y %H:%M')} WIB oleh Marketing Insight Assistant. "
                    "Angka dihitung kode dari file unggahan; setiap sheet berisi seluruh baris hasil analisis.")
        for s in sheets:
            s["df"].to_excel(writer, sheet_name=s["name"], index=False)
        for name, ws in writer.sheets.items():
            header_row = 4 if name == "Keterangan" else 1
            for cell in ws[header_row]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="0C1E3C")
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
            if ws.max_row > header_row:
                ws.auto_filter.ref = f"A{header_row}:{get_column_letter(ws.max_column)}{ws.max_row}"
            for col in ws.iter_cols(min_row=header_row, max_row=min(ws.max_row, header_row + 200)):
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 2, 10), 60)
    return buf.getvalue()


@_safe
def ekspor_excel(tool_context: ToolContext, nama_file: str = "", analisis: list[str] | None = None,
                 nama_sheet: list[str] | None = None) -> dict[str, Any]:
    """Mengekspor hasil analisis file di chat ini menjadi file Excel (.xlsx) multi-sheet yang bisa diunduh user.

    Setiap analisis dijalankan ulang dengan SEMUA baris (bukan hanya yang ditampilkan di chat). Pakai ini setiap kali
    user meminta Excel, spreadsheet, CSV, atau "file hasil analisis". Jangan pernah menyuruh user menjalankan
    script/Python sendiri.

    Args:
        nama_file: Judul/nama file, mis. "Analisa RFM Retail Outlet PTPL SR1 v1.3" (opsional).
        analisis: Daftar analisis_id (mis. ["a1", "a3"]) dari hasil analyze_data. Kosongkan untuk semua analisis
            di chat ini.
        nama_sheet: Nama sheet untuk tiap analisis (urutan sama dengan `analisis`), mis. ["Audit Data", "RFM 2025"].
    """
    import pandas as pd

    from .. import data_engine as de
    from .. import report_engine
    from ..clients import get_user_id
    from .file_tools import ANALYSES_KEY, _files, _prepared

    log = list(tool_context.state.get(ANALYSES_KEY, []) or [])
    if not log:
        return {"status": "needs_input", "message": "Belum ada hasil analisis file di chat ini. Jalankan analyze_data "
                                                    "untuk tabel yang diminta user, lalu panggil ekspor_excel lagi."}
    chosen = [a for a in log if a["id"] in set(analisis)] if analisis else log
    if not chosen:
        return {"status": "invalid", "message": "analisis_id tidak ditemukan.", "tersedia": [a["id"] for a in log]}
    files = {f["file_id"]: f for f in _files(tool_context)}
    cache: dict[str, tuple] = {}
    used: set[str] = {"keterangan"}
    sheets, info = [], []
    for i, a in enumerate(chosen):
        plan = dict(a["plan"])
        needed = {plan.get("file"), (plan.get("join") or {}).get("file")} - {None}
        frames, notes = {}, {}
        for fid in needed:
            if fid not in files:
                return {"status": "error", "message": f"File {fid} untuk analisis {a['id']} sudah tidak ada di chat."}
            if fid not in cache:
                cache[fid] = _prepared(files[fid])
            frames[fid], notes[fid] = cache[fid][0], cache[fid][1]
        result = de.run_plan(frames, plan, max_rows=EXCEL_MAX_ROWS)
        df = pd.DataFrame(result["rows"], columns=result["columns"])
        title = (nama_sheet[i] if nama_sheet and i < len(nama_sheet) and nama_sheet[i] else a["question"])
        name = sheet_name(title, used)
        sheets.append({"name": name, "df": df})
        excluded = "; ".join(f"{k}: {v}" for n in notes.values() for k, v in (n.get("excluded") or {}).items())
        cut = " Dipotong pada 1.000.000 baris." if result["rows_total"] > len(df) else ""
        info.append([name, a["question"], a.get("file", ""), len(df), (f"Baris dikecualikan aturan data: {excluded}."
                                                                        if excluded else "") + cut])
    title = nama_file.strip() or "Hasil Analisis Data"
    data = build_workbook(sheets, info, title)
    links = report_engine.save_output(get_user_id(tool_context), "ekspor_excel", title, data, "xlsx", XLSX_TYPE,
                                      record={"analisis": [a["id"] for a in chosen]})
    return {"status": "ok", "file": f"{title}.xlsx", "url": links["url"],
            "sheet": [{"nama": s["name"], "baris": len(s["df"])} for s in sheets],
            "message": "Berikan link unduhan ke user dan sebutkan isi tiap sheet beserta jumlah barisnya."}


EXPORT_TOOLS = [ekspor_excel]
