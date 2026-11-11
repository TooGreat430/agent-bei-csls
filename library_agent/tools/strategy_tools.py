"""Kerangka analisis Strategist Toolkit: panduan per kerangka + diagram (dengan perhitungan keputusan oleh kode)."""
from __future__ import annotations

import functools
import logging
import os
import re
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)
SKILL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", "strategist.md")


def _safe(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"Gagal karena kendala teknis: {str(exc)[:300]}"}
    return wrapper


@functools.lru_cache(maxsize=1)
def _sections() -> dict[str, str]:
    text = open(SKILL_PATH, encoding="utf-8").read()
    out = {}
    for block in re.split(r"\n(?=## )", text):
        m = re.match(r"## ([a-z0-9_ /]+):", block)
        if m:
            for key in m.group(1).split("/"):
                out[key.strip()] = block.strip()
    out["_pengantar"] = text.split("\n## ")[0].strip()
    return out


@_safe
def panduan_kerangka(nama: str, tool_context: ToolContext) -> dict[str, Any]:
    """Memuat panduan kerangka analisis dari Strategist Toolkit sebelum memakainya.

    Args:
        nama: Kunci kerangka, mis. "scq", "outcome", "driver_tree", "hypothesis", "five_whys", "five_w_h", "yes_no",
            "tabular", "one_pager", "tri_column", "chevron", "gantt", "matrix", "from_to", "minto", "mece", "scqa",
            "eisenhower", "abcd", "decision_tree", "pros_cons", "evaluation", "bezos", "spade", "execution_plan",
            "decision_grid", "zero_to_one", dll. Kosongkan untuk daftar semua kerangka.
    """
    sec = _sections()
    key = nama.strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        keys = sorted(k for k in sec if not k.startswith("_"))
        return {"status": "ok", "pengantar": sec["_pengantar"], "kerangka": keys}
    if key not in sec:
        close = [k for k in sec if key[:4] in k]
        return {"status": "invalid", "message": f"Kerangka '{nama}' tidak ada.", "mungkin": close[:6]}
    return {"status": "ok", "kerangka": key, "panduan": sec[key], "prinsip": sec["_pengantar"]}


@_safe
def buat_diagram(jenis: str, judul: str, isi: dict, tool_context: ToolContext) -> dict[str, Any]:
    """Menggambar diagram kerangka strategi bergaya PTPL dan mengembalikan link-nya.

    Nilai harapan (decision_tree) dan skor berbobot (evaluation) DIHITUNG OTOMATIS — pakai angka di 'fakta'.

    Args:
        jenis: panel (scq/htdq/outcome/five_w_h), driver_tree, bucketing, hypothesis_tree, five_whys, decision_flow
            (yes_no), table/tabular, heat_table, one_pager, tri_column, chevron/horizon/timeline/journey,
            gantt/execution_plan, matrix_2x2/eisenhower/abcd, matrix_3x3, from_to, pyramid/minto, decision_tree,
            pros_cons, evaluation.
        judul: Headline berupa kesimpulan (bukan topik).
        isi: Isi diagram sesuai jenis, contoh driver_tree: {"akar": "...", "cabang": [{"label", "nilai", "anak": [...]}]};
            hypothesis_tree: {"akar", "cabang": [{"label", "status": "terbukti|tidak|belum", "catatan"}]};
            five_whys: {"masalah", "langkah": [{"mengapa", "alasan", "bukti"}], "akar_masalah"};
            decision_tree: {"keputusan", "satuan", "opsi": [{"nama", "hasil": [{"label", "peluang", "nilai"}]}]};
            evaluation: {"kriteria": [{"nama", "bobot"}], "opsi": [{"nama", "skor": [...]}]};
            gantt: {"periode": [...], "baris": [{"stream", "aktivitas", "mulai", "selesai", "pemimpin"}]};
            matrix_2x2: {"sumbu_x", "sumbu_y", "kuadran": [kanan atas, kiri atas, kiri bawah, kanan bawah],
            "item": [{"label", "kuadran": 1-4}]}; panel: {"bagian": [{"judul", "teks"}]};
            chevron: {"tahap": [{"nama", "poin": [...]}]}; pyramid: {"puncak", "argumen": [{"judul", "bukti": [...]}]}.
    """
    from .. import strategy_diagrams as sd
    from .chart_insight_tools import _remember, _upload

    try:
        png, facts = sd.render(jenis.strip().lower(), judul, isi or {})
    except sd.DiagramError as exc:
        return {"status": "error", "message": str(exc)}
    link = _upload(tool_context, png, judul)
    _remember(tool_context, {"judul": judul, "jenis": f"diagram:{jenis}", "data_id": "-", "sumber": "kerangka",
                             "fakta": facts, "link": link})
    return {"status": "ok", "judul": judul, "jenis": jenis, "fakta": facts, "link": link,
            "panduan": "Sertakan link diagram; jelaskan isinya singkat; hipotesis yang belum terbukti disebut hipotesis."}


STRATEGY_TOOLS = [panduan_kerangka, buat_diagram]
