"""Storyboard (dict) -> daftar Slide siap render. Tidak pernah melempar error untuk isi storyboard yang rusak.

Jaring pengaman:
- komponen gagal -> slide `poin` berisi SEMUA teks & angka dari dict itu (isi tidak hilang) + catatan masalah;
- tabel/poin terlalu panjang -> slide lanjutan;
- chart dipotong -> lampiran data lengkap di akhir laporan.
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from . import components as C
from . import theme as T
from .prims import Rect, Slide, Text, para, run

logger = logging.getLogger(__name__)
SKIP_KEYS = {"komponen", "jenis", "type", "judul", "bagian", "catatan", "sumber", "_png", "_lanjutan", "png_b64",
             "kind", "jenis_chart", "tone", "nada", "dec", "urut", "legend"}
MAX_SLIDES = 60
MAX_APPENDIX = 20
TIME_LIMIT = 90.0          # detik — penyusunan deck tidak boleh menggantung (batas waktu GE)


@dataclass
class Deck:
    slides: list[Slide] = field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    issues: list[str] = field(default_factory=list)
    style: str = "id"

    def stats(self) -> dict[str, Any]:
        content = [s for s in self.slides if not s.dark]
        return {"slide": len(self.slides), "chart": sum(s.charts() for s in self.slides),
                "slide_tanpa_visual": [s.index for s in content if not s.has_visual()],
                "teks_meluap": [s.index for s in self.slides if any(getattr(p, "overflow", False) for p in s.prims)],
                "masalah": len(self.issues)}

    def all_text(self) -> str:
        return "\n".join(s.title + " " + s.note + " " + s.all_text() for s in self.slides)


def flatten(v: Any, prefix: str = "") -> list[str]:
    """Semua teks & angka dari dict/list (untuk slide pengganti) — tidak ada isi yang hilang."""
    out: list[str] = []
    if isinstance(v, dict):
        for k, x in v.items():
            if k in SKIP_KEYS:
                continue
            sub = flatten(x, "" if k in ("poin", "baris", "panel", "seri", "kolom", "isi", "item") else str(k))
            out += sub
    elif isinstance(v, (list, tuple)):
        if v and all(not isinstance(x, (dict, list, tuple)) for x in v) and len(v) <= 12 and prefix:
            return [f"{prefix}: " + ", ".join(C.s_(x) for x in v)]
        for x in v:
            out += flatten(x, prefix)
    elif v not in (None, ""):
        out.append(f"{prefix}: {v}" if prefix and not isinstance(v, str) else (f"{prefix}: {v}" if prefix else str(v)))
    return out


def _chrome(slide: Slide, d: dict, deck: Deck, n: int) -> None:
    kicker = C.s_(C.first(d, "bagian", "kicker", default="")).upper()
    if kicker:
        slide.add(C.txt(T.MX, 0.3, 9.5, 0.3, kicker, size=10, min_size=8, color=T.GOLD2, bold=True))
    title = slide.title + (" (lanjutan)" if d.get("_lanjutan") else "")
    slide.add(Text(T.MX, T.TITLE_Y, T.BODY_W, T.TITLE_H, [para([run(title, True, T.NAVY)])], size=T.SZ_TITLE,
                   min_size=T.SZ_TITLE_MIN, valign="m", name="judul"))
    note = " · ".join(x for x in (C.s_(d.get("catatan")), ("Sumber: " + C.s_(d["sumber"])) if d.get("sumber") else "")
                      if x)
    slide.note = note
    if note:
        slide.add(C.txt(T.MX, T.NOTE_Y, T.BODY_W - 1.0, 0.4, note, size=T.SZ_NOTE, min_size=7.5, color=T.MUTED))
    slide.add(C.txt(T.MX, T.FOOT_Y, 6.5, 0.25, deck.title, size=8, min_size=7.5, color=T.MUTED))
    slide.add(C.txt(T.W - T.MX - 4.5, T.FOOT_Y, 4.5, 0.25, f"{T.FOOTER} · {n}", size=8, min_size=7.5,
                    color=T.MUTED, align="r"))


def _decode_png(d: dict) -> None:
    if d.get("png_b64") and not d.get("_png"):
        try:
            d["_png"] = base64.b64decode(d["png_b64"])
        except Exception:  # noqa: BLE001
            d["_png"] = None


def build_slide(d: dict, deck: Deck, ctx: C.Ctx, n: int) -> Slide:
    kind = C.kind_of(d)
    slide = Slide(title=C.s_(d.get("judul")), kind=kind, index=n)
    if kind not in ("judul", "pemisah") and not slide.title:
        slide.issues.append("slide tanpa judul kesimpulan")
    fn = C.COMPONENTS.get(kind)
    if fn is None:
        slide.issues.append(f"komponen '{kind}' tidak dikenal; ditampilkan sebagai poin")
        fn, kind = C.c_poin, "poin"
        d = {**d, "poin": flatten(d)}
        slide.kind = "poin"
    _decode_png(d)
    try:
        fn(slide, d, ctx)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Komponen %s gagal di slide %d: %s — memakai slide poin", kind, n, exc)
        slide.issues.append(f"komponen '{kind}' gagal ({str(exc)[:120]}); isi ditampilkan sebagai poin")
        slide.prims, slide.kind, slide.dark = [], "poin", False
        try:
            C.c_poin(slide, {"poin": flatten(d) or ["(isi tidak tersedia)"]}, ctx)
        except Exception:  # noqa: BLE001
            logger.exception("Slide pengganti juga gagal")
            slide.prims = []
    if not slide.dark:
        _chrome(slide, d, deck, n)
    return slide


def build_deck(spec: dict) -> Deck:
    """Storyboard -> Deck. Selalu mengembalikan Deck (minimal sampul) walau storyboard rusak."""
    spec = spec if isinstance(spec, dict) else {}
    style = "en" if str(spec.get("format_angka", "id")).lower() in ("en", "us", "titik") else "id"
    deck = Deck(title=C.s_(spec.get("judul") or "Laporan Analisis"), subtitle=C.s_(spec.get("subjudul")), style=style)
    ctx = C.Ctx(style)
    raw = [s for s in C.lst(spec.get("slides") or spec.get("halaman")) if isinstance(s, dict)]
    if not raw or C.kind_of(raw[0]) != "judul":
        raw.insert(0, {"komponen": "judul", "judul": deck.title, "subjudul": deck.subtitle,
                       "kicker": f"PT PERTAMINA LUBRICANTS · {C.s_(spec.get('periode'))}".rstrip(" ·"),
                       "kartu": spec.get("kartu") or [], "meta": spec.get("sumber") and f"Sumber: {spec['sumber']}"})
    t0 = time.monotonic()
    queue = list(raw)
    while queue and len(deck.slides) < MAX_SLIDES and time.monotonic() - t0 < TIME_LIMIT:
        d = queue.pop(0)
        ctx.cont = []
        s = build_slide(d, deck, ctx, len(deck.slides) + 1)
        deck.slides.append(s)
        deck.issues += [f"slide {s.index}: {m}" for m in s.issues]
        queue[0:0] = ctx.cont                                  # lanjutan langsung setelah slide asal
    if queue:
        deck.issues.append(f"laporan dibatasi {MAX_SLIDES} slide; {len(queue)} slide tidak dimuat")
    limit = MAX_SLIDES + MAX_APPENDIX
    for k, ap in enumerate(ctx.appendix):
        d = {"komponen": "lampiran", "judul": f"Lampiran {k + 1}: data lengkap — {ap['judul']}", "bagian": "Lampiran data",
             "data": ap["data"], "unit": ap.get("unit", ""), "catatan": "Data lengkap dari chart yang diringkas."}
        queue = [d]
        while queue and len(deck.slides) < limit and time.monotonic() - t0 < TIME_LIMIT:
            dd = queue.pop(0)
            ctx.cont = []
            s = build_slide(dd, deck, ctx, len(deck.slides) + 1)
            deck.slides.append(s)
            queue[0:0] = ctx.cont
        if queue:
            deck.issues.append("lampiran dibatasi; sebagian data lengkap tidak dimuat")
            break
    return deck


def emergency_deck(title: str, lines: list[str]) -> Deck:
    """Deck paling sederhana (judul + poin) — dipakai bila storyboard sama sekali tidak bisa dibangun."""
    deck = Deck(title=title or "Laporan Analisis")
    ctx = C.Ctx()
    cover = Slide(title=deck.title, kind="judul", index=1)
    C.c_judul(cover, {"judul": deck.title}, ctx)
    deck.slides.append(cover)
    chunk = 8
    for i in range(0, max(len(lines), 1), chunk):
        s = Slide(title="Ringkasan hasil analisis", kind="poin", index=len(deck.slides) + 1)
        s.add(Rect(T.MX, T.BODY_Y, T.BODY_W, T.BODY_H, fill=T.WHITE, line=None))
        C.c_poin(s, {"poin": lines[i:i + chunk] or ["-"]}, ctx)
        _chrome(s, {}, deck, s.index)
        deck.slides.append(s)
    return deck
