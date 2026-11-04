"""Utilitas angka, format Indonesia, grafik, dan font untuk semua renderer laporan.

(Renderer laporan berbasis template dokumen BEI/CSLS sudah dihapus; modul ini hanya menyimpan
fungsi bersama yang dipakai dashboard retail, laporan industri, laporan planogram, dan grafik chat.)
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

# Karakter yang sering muncul dari model tetapi tidak perlu/aneh di dokumen.
_CHAR_MAP = {"\u2264": "<=", "\u2265": ">=", "\u2192": "->", "\u00a0": " ", "\u200b": "",
             "\u25b8": "\u203a", "\u25b6": "\u203a", "\u25ba": "\u203a", "\u2605": "*"}
SERIES_KEYS = ("primary", "accent", "mid", "low", "high", "highlight")
_NUM_RE = re.compile(r"[-−–+]?\s*(?:rp\.?\s*)?[-−–+]?\d[\d.,]*", re.IGNORECASE)


def clean(text: Any) -> str:
    s = "" if text is None else str(text)
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n")
    for k, v in _CHAR_MAP.items():
        s = s.replace(k, v)
    return s.strip()


def parse_number(value: Any) -> float | None:
    """'−9.390/L' -> -9390, 'Rp 10.596/L' -> 10596, '1,3' -> 1.3, '16.5' -> 16.5, 'NA' -> None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and (math.isnan(value) or math.isinf(value))) else float(value)
    match = _NUM_RE.search(str(value))
    if not match:
        return None
    raw = match.group(0)
    negative = bool(re.search(r"[-−–]", raw))
    digits = re.sub(r"[^\d.,]", "", raw)
    if "." in digits and "," in digits:
        digits = digits.replace(".", "").replace(",", ".")
    elif "." in digits:
        parts = digits.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            digits = digits.replace(".", "")
    elif "," in digits:
        parts = digits.split(",")
        digits = digits.replace(",", "") if len(parts) > 2 else digits.replace(",", ".")
    try:
        number = float(digits)
    except ValueError:
        return None
    return -number if negative else number


def fmt_id(number: float | None) -> str:
    """Format angka Indonesia: 9390 -> '9.390', -1.25 -> '−1,3'."""
    if number is None:
        return "–"
    sign = "−" if number < 0 else ""
    number = abs(number)
    if number >= 100 or float(number).is_integer():
        text = f"{number:,.0f}".replace(",", ".")
    else:
        text = f"{number:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return sign + text


def clean_charts(value: Any) -> list[dict[str, Any]]:
    """Validasi grafik: kategori & seri harus sejajar; nilai diubah ke angka (None jika kosong)."""
    out = []
    for chart in value or []:
        if not isinstance(chart, dict):
            continue
        cats = [clean(c) for c in chart.get("kategori") or []]
        series = []
        for s in chart.get("seri") or []:
            vals = [parse_number(v) for v in (s.get("nilai") or [])]
            if len(vals) == len(cats) and any(v is not None for v in vals):
                series.append({"nama": clean(s.get("nama")), "nilai": vals})
        if cats and series:
            out.append({"judul": clean(chart.get("judul")), "jenis": "line" if chart.get("jenis") == "line" else "bar",
                        "satuan": clean(chart.get("satuan")), "kategori": cats, "seri": series[:6],
                        "catatan": clean(chart.get("catatan"))})
    return out


def nice_ticks(vmin: float, vmax: float, count: int = 5) -> list[float]:
    if vmin == vmax:
        vmax = vmin + 1
    span = vmax - vmin
    raw = span / max(count - 1, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(vmin / step) * step
    ticks, t = [], start
    while True:
        ticks.append(round(t, 10))
        if t >= vmax - 1e-9 or len(ticks) > 50:
            break
        t += step
    return ticks


def _register_fonts() -> tuple[str, str, str]:
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.getFont("LibSans")
        return "LibSans", "LibSans-Bold", "LibSans-Italic"
    except KeyError:
        pass
    try:
        files = {"LibSans": "Regular", "LibSans-Bold": "Bold", "LibSans-Italic": "Italic", "LibSans-BoldItalic": "BoldItalic"}
        for name, style in files.items():
            pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, f"LiberationSans-{style}.ttf")))
        addMapping("LibSans", 0, 0, "LibSans")
        addMapping("LibSans", 1, 0, "LibSans-Bold")
        addMapping("LibSans", 0, 1, "LibSans-Italic")
        addMapping("LibSans", 1, 1, "LibSans-BoldItalic")
        return "LibSans", "LibSans-Bold", "LibSans-Italic"
    except Exception:  # noqa: BLE001  (font tidak ada: pakai Helvetica bawaan)
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
