"""Tool analisis berbasis kode (Agent Engine Code Execution). Aktif hanya jika dinyalakan di settings.json."""
from __future__ import annotations

import functools
import logging
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


def _safe(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"Eksekusi gagal karena kendala teknis: {str(exc)[:300]}"}
    return wrapper


@_safe
def siapkan_sandbox(tool_context: ToolContext) -> dict[str, Any]:
    """Langkah pertama analisis berbasis kode: menyiapkan sandbox Python dan mengirim semua file data chat ini.

    Mengembalikan nama file CSV di sandbox (Excel sudah dikonversi, satu CSV per sheet), jumlah baris, dan kolom.
    Panggil sekali per chat, dan lagi bila user mengunggah file data baru.
    """
    from .. import code_exec

    return code_exec.prepare(tool_context)


@_safe
def jalankan_python(code: str, tujuan: str, tool_context: ToolContext) -> dict[str, Any]:
    """Menjalankan kode Python di sandbox terisolasi (tanpa internet) untuk analisis file data user.

    Variabel dan file tetap ada antar langkah dalam chat yang sama. Library tersedia antara lain pandas, numpy,
    matplotlib; jangan menginstal library. Simpan output yang diminta user (CSV, XLSX, PNG, HTML) sebagai file di
    direktori kerja — file baru otomatis dikirim ke user sebagai link. Cetak (print) semua angka yang akan dipakai
    di jawaban.

    Args:
        code: Kode Python lengkap untuk satu langkah analisis.
        tujuan: Satu kalimat tujuan langkah ini (mis. "Audit keunikan Customer Code × bulan").
    """
    from .. import code_exec

    return code_exec.run(code, tujuan, tool_context)


@_safe
def cek_biaya_analisis(tool_context: ToolContext) -> dict[str, Any]:
    """Biaya analisis yang tercatat hari ini (estimasi meteran) dan batas harian."""
    from .. import usage

    return {"status": "ok", **usage.budget_status()}


@_safe
def akhiri_sandbox(tool_context: ToolContext) -> dict[str, Any]:
    """Menghapus sandbox chat ini (hemat biaya) bila user menyatakan analisis selesai."""
    from .. import code_exec

    return {"status": "ok", "dihapus": code_exec.delete_sandbox(tool_context.state)}


SKILLS_DIR = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__file__)), "skills")
SKILL_INFO = {"excel": "Workbook Excel rapi: format, rumus, grafik native",
              "powerpoint": "Deck PowerPoint yang bisa diedit (bukan laporan template)",
              "word": "Dokumen Word: memo, kajian, notulen, ringkasan",
              "edit_file": "Mengedit file Excel/PowerPoint/Word milik user",
              "pdf": "PDF siap cetak selain laporan template",
              "analisis_data": "Cara kerja analis: intake, audit, metodologi, validasi"}


@_safe
def daftar_skill(tool_context: ToolContext) -> dict[str, Any]:
    """Daftar skill (panduan kerja) yang bisa dimuat sebelum membuat file atau menganalisis data di sandbox."""
    return {"status": "ok", "skill": SKILL_INFO}


@_safe
def muat_skill(nama: str, tool_context: ToolContext) -> dict[str, Any]:
    """Memuat panduan kerja (skill) sebelum mengerjakan tugas di sandbox. WAJIB dipanggil sebelum membuat file
    Excel/PowerPoint/Word/PDF, mengedit file user, atau analisis bertahap. Panduan gaya PTPL ikut dimuat otomatis.

    Args:
        nama: "excel", "powerpoint", "word", "edit_file", "pdf", atau "analisis_data".
    """
    import os

    key = nama.strip().lower().replace(" ", "_").replace("ppt", "powerpoint").replace("powerpointx", "powerpoint")
    key = {"xlsx": "excel", "docx": "word", "analisis": "analisis_data", "edit": "edit_file"}.get(key, key)
    if key not in SKILL_INFO:
        return {"status": "invalid", "message": f"Skill '{nama}' tidak ada.", "skill": list(SKILL_INFO)}
    with open(os.path.join(SKILLS_DIR, "_umum.md"), encoding="utf-8") as fh:
        umum = fh.read()
    with open(os.path.join(SKILLS_DIR, f"{key}.md"), encoding="utf-8") as fh:
        body = fh.read()
    return {"status": "ok", "skill": key, "panduan": body + "\n\n" + umum}


CODE_TOOLS = [siapkan_sandbox, jalankan_python, cek_biaya_analisis, akhiri_sandbox, daftar_skill, muat_skill]
