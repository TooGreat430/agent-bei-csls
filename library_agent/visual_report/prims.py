"""Elemen dasar slide (kotak, teks, chart, tabel, garis, gambar) + pengukuran & pemenggalan teks.

Teks diukur dengan metrik Helvetica (lebar identik Arial) sehingga hasil pemenggalan di PDF/HTML sama dengan
PowerPoint. Teks yang tidak muat dikecilkan sampai batas minimum; bila masih tidak muat ditandai `overflow`
(dilaporkan gerbang mutu), tidak pernah dipotong diam-diam.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import theme as T

PAD_X, PAD_Y = 0.06, 0.04          # padding dalam kotak teks (inci) — sama di semua renderer
LINE = 1.18                         # tinggi baris = LINE × ukuran huruf
SAFE = 0.95                         # cadangan lebar (perbedaan kecil antar-renderer)


_FONTS: dict[str, str] = {}


def pdf_fonts() -> dict[str, str]:
    """Font untuk ukur & PDF: DejaVu Sans (ikut matplotlib; mendukung ↓ − · —). Sedikit lebih lebar dari Arial,
    jadi teks yang muat di PDF pasti muat di PowerPoint/HTML. Cadangan: Helvetica."""
    if _FONTS:
        return _FONTS
    try:
        import os

        import matplotlib
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        base = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        pdfmetrics.registerFont(TTFont("VR-Sans", os.path.join(base, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("VR-Bold", os.path.join(base, "DejaVuSans-Bold.ttf")))
        _FONTS.update(r="VR-Sans", b="VR-Bold")
    except Exception:  # noqa: BLE001
        _FONTS.update(r="Helvetica", b="Helvetica-Bold")
    return _FONTS


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Lebar teks dalam poin (font PDF)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    f = pdf_fonts()
    return stringWidth(text, f["b"] if bold else f["r"], size)


def run(t: Any, b: bool = False, c: str = T.TEXT, s: float = 1.0, i: bool = False) -> dict:
    return {"t": "" if t is None else str(t), "b": b, "c": c, "s": s, "i": i}


def para(runs: Any, align: str = "l", bullet: bool = False, after: float = 0.25) -> dict:
    if isinstance(runs, (str, int, float)) or runs is None:
        runs = [run(runs)]
    elif isinstance(runs, dict):
        runs = [runs]
    return {"runs": list(runs), "align": align, "bullet": bullet, "after": after}


def _wrap_para(p: dict, width_pt: float, size: float) -> list[list[tuple[str, dict]]]:
    """Pecah satu paragraf menjadi baris (list segmen (teks, run))."""
    indent = size * 1.1 if p.get("bullet") else 0.0
    avail = max(width_pt - indent, size)
    tokens: list[tuple[str, dict]] = []
    for r in p["runs"]:
        text = str(r.get("t", ""))
        parts = text.replace("\n", " \n ").split(" ")
        for k, w in enumerate(parts):
            if w == "\n":
                tokens.append(("\n", r))
                continue
            if w:
                tokens.append((w, r))
            if k < len(parts) - 1:
                tokens.append((" ", r))
    lines: list[list[tuple[str, dict]]] = [[]]
    cur = 0.0
    space_pending: tuple[str, dict] | None = None
    for tok, r in tokens:
        rs = size * r.get("s", 1.0)
        if tok == "\n":
            lines.append([])
            cur, space_pending = 0.0, None
            continue
        if tok == " ":
            if lines[-1]:
                space_pending = (" ", r)
            continue
        w = text_width(tok, rs, r.get("b", False))
        sp = text_width(" ", rs, r.get("b", False)) if space_pending else 0.0
        if lines[-1] and cur + sp + w > avail:
            lines.append([])
            cur, space_pending, sp = 0.0, None, 0.0
        while w > avail and len(tok) > 1:          # kata lebih panjang dari baris: penggal paksa
            n = len(tok)
            while n > 1 and text_width(tok[:n], rs, r.get("b", False)) > avail - cur:
                n -= 1
            if lines[-1] and n <= 1:
                lines.append([])
                cur = 0.0
                continue
            lines[-1].append((tok[:n], r))
            lines.append([])
            tok, cur = tok[n:], 0.0
            w = text_width(tok, rs, r.get("b", False))
        if space_pending and lines[-1]:
            lines[-1].append(space_pending)
            cur += sp
        space_pending = None
        lines[-1].append((tok, r))
        cur += w
    return [ln for ln in lines] or [[]]


def layout_text(paras: list[dict], w_in: float, h_in: float, size: float) -> tuple[list[list], float]:
    """(baris per paragraf, tinggi total dalam inci) pada ukuran huruf tertentu."""
    width_pt = max((w_in - 2 * PAD_X) * 72 * SAFE, 6)
    out, total = [], 0.0
    for k, p in enumerate(paras):
        lines = _wrap_para(p, width_pt, size)
        out.append(lines)
        for ln in lines:
            mx = max([size * r.get("s", 1.0) for _, r in ln] or [size])
            total += mx * LINE
        if k < len(paras) - 1:
            total += size * p.get("after", 0.25)
    return out, total / 72 + 2 * PAD_Y


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str | None = None
    line: str | None = None
    lw: float = 0.75
    radius: bool = False
    shape: str = "rect"               # rect | ellipse | chevron | trapezoid
    name: str = ""


@dataclass
class Text:
    x: float
    y: float
    w: float
    h: float
    paras: list[dict]
    size: float = T.SZ_BODY
    min_size: float = T.SZ_BODY_MIN
    valign: str = "t"
    lines: list = field(default_factory=list)
    overflow: bool = False
    fill: str | None = None
    name: str = ""

    def fit(self) -> "Text":
        """Kecilkan huruf sampai muat; tandai overflow bila tetap tidak muat di ukuran minimum."""
        size = self.size
        floor = max(min(self.min_size, size), T.SZ_MIN_ABS)
        while True:
            lines, need = layout_text(self.paras, self.w, self.h, size)
            if need <= self.h + 1e-6 or size <= floor:
                self.size, self.lines = size, lines
                self.overflow = need > self.h + 1e-6
                return self
            size = max(floor, round(size - 0.5, 2))

    def plain(self) -> str:
        return " ".join("".join(r.get("t", "") for r in p["runs"]) for p in self.paras)


@dataclass
class Chart:
    x: float
    y: float
    w: float
    h: float
    spec: dict
    name: str = ""


@dataclass
class Table:
    x: float
    y: float
    w: float
    cols: list[float]                 # lebar kolom (inci), jumlah = w
    rows: list[list[dict]]            # sel: {t, b, c, fill, align}
    size: float = 11.0
    header_rows: int = 1
    row_h: list[float] = field(default_factory=list)
    overflow: bool = False
    name: str = ""

    @property
    def h(self) -> float:
        return sum(self.row_h)

    def measure(self, size: float) -> list[float]:
        hs = []
        for row in self.rows:
            mh, s = 0.0, size
            for c, cell in enumerate(row):
                cw = self.cols[c] if c < len(self.cols) else self.cols[-1]
                s = size * cell.get("s", 1.0)
                _, need = layout_text([para([run(cell.get("t", ""), cell.get("b", False), s=1.0)])], cw, 99, s)
                mh = max(mh, need + 0.04)
            hs.append(max(mh, s / 72 * LINE + 0.12))
        return hs

    def word_cap(self) -> float:
        """Ukuran huruf terbesar agar kata terpanjang di tiap sel muat di kolomnya (tidak dipenggal di tengah)."""
        cap = 99.0
        for row in self.rows:
            for c, cell in enumerate(row):
                cw = self.cols[c] if c < len(self.cols) else self.cols[-1]
                avail = max((cw - 2 * PAD_X) * 72 * SAFE, 4)
                for wd in str(cell.get("t", "")).split():
                    w1 = text_width(wd, 1.0, cell.get("b", False)) * cell.get("s", 1.0)
                    if w1 > 0:
                        cap = min(cap, avail / w1)
        return cap

    def fit(self, max_h: float, min_size: float = T.SZ_BODY_MIN, max_size: float | None = None,
            stretch: bool = False, row_cap: float = 0.62) -> "Table":
        """Kecilkan sampai muat; bila `max_size`, perbesar huruf selama muat; bila `stretch`, tinggikan baris
        (maks `row_cap` per baris) agar tabel pendek mengisi ruang."""
        size = max(min(self.size, self.word_cap()), min_size)
        while True:
            hs = self.measure(size)
            if sum(hs) <= max_h + 1e-6 or size <= min_size:
                break
            size = max(min_size, round(size - 0.5, 2))
        if max_size and sum(hs) <= max_h:
            top = min(max_size, self.word_cap())
            while size + 0.5 <= top:
                hs2 = self.measure(size + 0.5)
                if sum(hs2) > max_h * 0.82:
                    break
                size, hs = size + 0.5, hs2
        self.size, self.row_h = size, hs
        self.overflow = sum(hs) > max_h + 1e-6
        if stretch and not self.overflow and len(hs) > 1:
            extra = max_h - sum(hs)
            body = list(range(self.header_rows, len(hs)))
            for _ in range(3):
                room = [i for i in body if self.row_h[i] < row_cap]
                if extra <= 0.01 or not room:
                    break
                add = extra / len(room)
                for i in room:
                    inc = min(add, row_cap - self.row_h[i])
                    self.row_h[i] += inc
                    extra -= inc
        return self

    def plain(self) -> str:
        return " ".join(str(c.get("t", "")) for r in self.rows for c in r)


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = T.BORDER
    lw: float = 1.0
    arrow: bool = False
    dash: bool = False


@dataclass
class Image:
    x: float
    y: float
    w: float
    h: float
    png: bytes
    alt: str = ""


Prim = Rect | Text | Chart | Table | Line | Image


@dataclass
class Slide:
    prims: list = field(default_factory=list)
    title: str = ""
    kind: str = ""
    dark: bool = False
    note: str = ""
    issues: list[str] = field(default_factory=list)
    index: int = 0

    def add(self, *items):
        for it in items:
            if isinstance(it, Text):
                it.fit()
            self.prims.append(it)
        return items[0] if len(items) == 1 else items

    def has_visual(self) -> bool:
        return any(isinstance(p, (Chart, Table, Image)) for p in self.prims) or self.kind in VISUAL_KINDS

    def charts(self) -> int:
        return sum(isinstance(p, Chart) for p in self.prims)

    def all_text(self) -> str:
        out = []
        for p in self.prims:
            if isinstance(p, (Text, Table)):
                out.append(p.plain())
            elif isinstance(p, Chart):
                from .charts import chart_text

                out.append(chart_text(p.spec))
        return " ".join(out)


# Komponen yang visualnya digambar dengan bentuk (bukan chart/tabel) tetap dihitung sebagai slide bervisual.
VISUAL_KINDS = {"funnel", "swot", "roadmap", "ringkasan", "kartu", "judul", "pemisah", "smart", "benang_merah",
                "kerangka"}
