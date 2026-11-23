"""Tema visual laporan otomatis PTPL: kanvas 16:9, warna, format angka.

Satu sumber gaya untuk tiga format (PPTX, PDF, HTML) supaya tampilannya identik.
"""
from __future__ import annotations

import math
from typing import Any

# Kanvas (inci) = ukuran slide PowerPoint widescreen.
W, H = 13.333, 7.5
MX = 0.5                      # margin kiri/kanan
TITLE_Y, TITLE_H = 0.62, 0.95
BODY_Y = 1.72
BODY_B = 6.62                 # batas bawah area isi
NOTE_Y = 6.70
FOOT_Y = 7.12
BODY_W = W - 2 * MX
BODY_H = BODY_B - BODY_Y

FONT = "Arial"                # dirender: Arial (PPTX/HTML), Helvetica (PDF) — lebar huruf identik

NAVY, NAVY2, NAVY3 = "0C1E3C", "1A3260", "2A4A80"
GOLD, GOLD2, GOLD_BG = "92660A", "B58012", "FBF5E6"
GREEN, GREEN_BG = "15803D", "F0FDF4"
RED, RED_BG = "DC2626", "FEF2F2"
AMBER, AMBER_BG = "D97706", "FFFBEB"
BLUE, BLUE_BG = "1D4ED8", "EFF6FF"
TEXT, TEXT2, MUTED = "1F2937", "475569", "64748B"
GRID, BORDER, BG2, BG3, WHITE = "E2E8F0", "CBD5E1", "F8FAFC", "EEF3FA", "FFFFFF"
COMP = "A3ADBA"               # kompetitor (abu-abu)
PTPL_2 = "6E8BBF"             # merek Pertamina lain (navy muda)
SERIES = [NAVY, GOLD2, "0891B2", "7C3AED", GREEN, RED, "94A3B8", "BE185D"]
HEAT = ["FFFFFF", "FDF2D9", "F9DFA6", "F2C46B", "E6A23C", "C97F1A"]   # intensitas rendah -> tinggi

# Ukuran huruf (pt)
SZ_TITLE, SZ_TITLE_MIN = 24, 17
SZ_BODY, SZ_BODY_MIN = 13, 9.5
SZ_SMALL, SZ_NOTE = 10.5, 8.5
SZ_MIN_ABS = 7.5               # batas paling kecil untuk teks apa pun

FOOTER = "PT Pertamina Lubricants · Confidential"


def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def to_num(v: Any) -> float | None:
    """Angka dari int/float/teks ('21,0', '1.234', '−1.98', '35%'); None bila bukan angka."""
    if is_num(v):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace("−", "-").replace("–", "-").replace("%", "").replace("Rp", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:                       # 1.234,5 (ID) atau 1,234.5 (EN)
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and head.lstrip("-+").isdigit() else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


MAX_DEC = 6


def decimals_of(values: list[float]) -> int:
    """Jumlah desimal ASLI sekelompok angka (tanpa pembulatan; maks 6, sisa derau float diabaikan)."""
    best = 0
    for v in values:
        if not is_num(v):
            continue
        for d in range(0, MAX_DEC + 1):
            if abs(round(v, d) - v) < 1e-9 * max(1.0, abs(v)):
                best = max(best, d)
                break
        else:
            best = MAX_DEC
    return best


def fmt(v: Any, dec: int | None = None, unit: str = "", style: str = "id", sign: bool = False) -> str:
    """Format angka untuk label: style 'id' -> 1.234,5 ; 'en' -> 1,234.5. Teks dikembalikan apa adanya.

    `dec` = jumlah desimal MINIMUM (untuk menyeragamkan, mis. 21 -> 21,0); angka TIDAK PERNAH dibulatkan
    di bawah presisi aslinya (permintaan klien: tampilkan angka asli)."""
    if not is_num(v):
        return "" if v is None else str(v)
    d = decimals_of([v]) if dec is None else max(int(dec), decimals_of([v]))
    s = f"{abs(v):,.{d}f}"
    if style == "id":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    pre = "−" if v < 0 else ("+" if sign and v > 0 else "")
    u = unit or ""
    if u in ("%", "pp", "poin", "pts"):
        return f"{pre}{s}{'' if u == '%' else ' '}{u}"
    if u.lower().startswith("rp"):
        return f"{pre}Rp {s}"
    return f"{pre}{s}{(' ' + u) if u else ''}"


def hex_ok(c: Any, default: str) -> str:
    s = str(c or "").lstrip("#").upper()
    return s if len(s) == 6 and all(ch in "0123456789ABCDEF" for ch in s) else default


def mix(c1: str, c2: str, t: float) -> str:
    """Campuran dua warna hex (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(x + (y - x) * max(0.0, min(1.0, t))):02X}" for x, y in zip(a, b))


def heat_color(v: float | None, lo: float, hi: float) -> str:
    if v is None or hi <= lo:
        return HEAT[0] if v is None else HEAT[2]
    t = (v - lo) / (hi - lo)
    return HEAT[min(len(HEAT) - 1, max(1, 1 + int(t * (len(HEAT) - 1.0001))))]


def text_on(fill: str) -> str:
    """Warna teks yang kontras di atas warna isi."""
    r, g, b = (int(fill[i:i + 2], 16) for i in (0, 2, 4))
    return WHITE if (0.299 * r + 0.587 * g + 0.114 * b) < 150 else TEXT


TONE = {"pos": (GREEN, GREEN_BG), "neg": (RED, RED_BG), "warn": (AMBER, AMBER_BG), "info": (BLUE, BLUE_BG),
        "gold": (GOLD, GOLD_BG), "navy": (NAVY, BG3), "": (NAVY2, BG3)}


def tone(name: Any) -> tuple[str, str]:
    key = str(name or "").lower()
    key = {"positif": "pos", "baik": "pos", "hijau": "pos", "negatif": "neg", "buruk": "neg", "merah": "neg",
           "risiko": "neg", "waspada": "warn", "kuning": "warn", "netral": "", "biru": "info"}.get(key, key)
    return TONE.get(key, TONE[""])
