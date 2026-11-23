"""Gerbang mutu laporan: visual di setiap halaman, judul berupa kesimpulan, teks tidak meluap, angka lengkap.

Hasilnya dipakai untuk SATU putaran revisi otomatis oleh model (bukan ditampilkan mentah ke user).
"""
from __future__ import annotations

import re
from typing import Any

from . import theme as T

_NUM = re.compile(r"[-−+]?\d[\d.,]*")
VERB_HINT = re.compile(r"\b(naik|turun|unggul|tertinggal|kalah|menang|memimpin|melampaui|melonjak|anjlok|tumbuh|"
                       r"menurun|meningkat|stabil|bocor|menjadi|perlu|harus|didorong|dipicu|karena|namun|tetapi|"
                       r"lebih|kurang|terbesar|terendah|tertinggi|dominan|menggerus|menutup|memangkas|menyusut)\b", re.I)


def numbers_in(text: str) -> list[float]:
    out = []
    for raw in _NUM.findall(text or ""):
        raw = raw.rstrip(".,")
        v = T.to_num(raw)
        if v is not None:
            out.append(v)
            # "21.0" bisa dibaca 21,0 (EN) — sudah; "1.234" bisa ribuan (ID) atau 1,234 (EN): simpan keduanya
            if re.fullmatch(r"[-−+]?\d{1,3}(\.\d{3})+", raw):          # 1.000 / 1.234.567 = ribuan (ID)
                out.append(float(raw.replace("−", "-").replace(".", "")))
            elif re.fullmatch(r"[-−+]?\d{1,3}(,\d{3})+", raw):         # 1,000 = ribuan (EN)
                out.append(float(raw.replace("−", "-").replace(",", "")))
    return out


def coverage(deck, required: list) -> list[str]:
    """Angka wajib (hasil analitik) yang TIDAK muncul di laporan. Cocok bila sama setelah pembulatan wajar
    (desimal angka wajib), atau bila angka wajib ≥ 1.000 dibulatkan ke ratusan."""
    if not required:
        return []
    have = numbers_in(deck.all_text())
    missing = []
    for r in required:
        v = T.to_num(r)
        if v is None:
            continue
        dec = T.decimals_of([v])
        tol = 0.5 * 10 ** (-dec) + 1e-9
        ok = any(abs(abs(h) - abs(v)) <= tol for h in have)
        if not ok and abs(v) >= 1000:
            ok = any(abs(abs(h) - abs(v)) <= 50 for h in have)
        if not ok:
            missing.append(r if isinstance(r, str) else T.fmt(v, dec, "", deck.style))
    return missing


def review(deck) -> dict[str, Any]:
    issues: list[str] = []
    content = [s for s in deck.slides if not s.dark and s.kind != "lampiran"]
    for s in content:
        if not s.has_visual():
            issues.append(f"slide {s.index}: tidak ada visual (chart/tabel/diagram)")
        t = s.title.strip()
        if t and not (re.search(r"\d", t) or VERB_HINT.search(t)) and len(t.split()) < 7:
            issues.append(f"slide {s.index}: judul '{t[:60]}' berupa topik, bukan kesimpulan")
        for p in s.prims:
            if getattr(p, "overflow", False):
                kind = type(p).__name__.lower()
                issues.append(f"slide {s.index}: {('teks' if kind == 'text' else 'tabel')} terlalu panjang untuk kotaknya"
                              " — persingkat")
                break
    charts = sum(s.charts() for s in content)
    if len(content) >= 4 and charts < max(2, len(content) // 3):
        issues.append(f"hanya {charts} chart untuk {len(content)} halaman isi — tambahkan visual data")
    return {"masalah": issues, "chart": charts, "halaman_isi": len(content)}
