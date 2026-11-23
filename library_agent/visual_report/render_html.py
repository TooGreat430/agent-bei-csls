"""Deck -> HTML mandiri (satu file). Tiap slide = kanvas 16:9 yang menyesuaikan lebar layar; chart = SVG."""
from __future__ import annotations

import base64
import html
import logging

from . import charts as CH
from . import theme as T
from .prims import PAD_X, PAD_Y, Chart, Image, Line, Rect, Table, Text

logger = logging.getLogger(__name__)


def _pos(x, y, w, h) -> str:
    return (f"left:{x / T.W * 100:.3f}%;top:{y / T.H * 100:.3f}%;width:{w / T.W * 100:.3f}%;"
            f"height:{h / T.H * 100:.3f}%")


def _cq(inches: float) -> str:
    return f"{inches / T.W * 100:.4f}cqw"


def _fs(pt: float) -> str:
    return _cq(pt / 72)


def _e(s) -> str:
    return html.escape(str(s or ""))


def _rect(r: Rect) -> str:
    rad = "50%" if r.shape == "ellipse" else (_cq(0.07) if r.radius else "0")
    bg = f"background:#{r.fill};" if r.fill else ""
    bd = f"border:{max(r.lw, 0.5) / 72 / T.W * 100:.4f}cqw solid #{r.line};" if r.line else ""
    return f'<div class="e" style="{_pos(r.x, r.y, r.w, r.h)};{bg}{bd}border-radius:{rad};box-sizing:border-box"></div>'


def _runs(rs: list, size: float) -> str:
    out = []
    for r in rs:
        st = f"color:#{r.get('c', T.TEXT)};font-size:{_fs(size * r.get('s', 1.0))}"
        if r.get("b"):
            st += ";font-weight:700"
        if r.get("i"):
            st += ";font-style:italic"
        out.append(f'<span style="{st}">{_e(r.get("t", ""))}</span>')
    return "".join(out)


def _text(t: Text) -> str:
    jc = {"m": "center", "b": "flex-end"}.get(t.valign, "flex-start")
    ps = []
    for k, p in enumerate(t.paras):
        mb = _fs(t.size * p.get("after", 0.25)) if k < len(t.paras) - 1 else "0"
        cls = ' class="b"' if p.get("bullet") else ""
        ps.append(f'<p{cls} style="text-align:{ {"c": "center", "r": "right"}.get(p.get("align"), "left") };'
                  f'margin:0 0 {mb};padding-left:{_fs(t.size * 1.1) if p.get("bullet") else 0}">'
                  f'{_runs(p["runs"], t.size)}</p>')
    bg = f"background:#{t.fill};" if t.fill else ""
    return (f'<div class="e t" style="{_pos(t.x, t.y, t.w, t.h)};{bg}justify-content:{jc};'
            f'padding:{_cq(PAD_Y)} {_cq(PAD_X)};font-size:{_fs(t.size)}">{"".join(ps)}</div>')


def _table(tb: Table) -> str:
    cols = "".join(f'<col style="width:{w / tb.w * 100:.2f}%">' for w in tb.cols)
    rows = []
    for i, row in enumerate(tb.rows):
        rh = tb.row_h[i] if i < len(tb.row_h) else 0.3
        cells = []
        for j in range(len(tb.cols)):
            c = row[j] if j < len(row) else {"t": ""}
            st = (f"background:#{c.get('fill') or T.WHITE};color:#{c.get('c', T.TEXT)};"
                  f"text-align:{ {'c': 'center', 'r': 'right'}.get(c.get('align'), 'left') };"
                  f"font-size:{_fs(tb.size * c.get('s', 1.0))};height:{_cq(rh)}")
            if c.get("b"):
                st += ";font-weight:700"
            cells.append(f'<td style="{st}">{_e(c.get("t", ""))}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<table class="e" style="{_pos(tb.x, tb.y, tb.w, tb.h)}"><colgroup>{cols}</colgroup>'
            f'{"".join(rows)}</table>')


def _chart(ch: Chart) -> str:
    svg = CH.render_image(ch.spec, ch.w, ch.h, "svg")
    b64 = base64.b64encode(svg).decode()
    alt = _e(CH.chart_text(ch.spec)[:300])
    return f'<img class="e" alt="{alt}" style="{_pos(ch.x, ch.y, ch.w, ch.h)}" src="data:image/svg+xml;base64,{b64}">'


def _image(im: Image) -> str:
    b64 = base64.b64encode(im.png).decode()
    return (f'<img class="e" alt="{_e(im.alt)}" style="{_pos(im.x, im.y, im.w, im.h)};object-fit:contain" '
            f'src="data:image/png;base64,{b64}">')


def _lines(lines: list[Line]) -> str:
    if not lines:
        return ""
    out = []
    for ln in lines:
        mk = ' marker-end="url(#ah)"' if ln.arrow else ""
        dash = ' stroke-dasharray="0.05 0.04"' if ln.dash else ""
        out.append(f'<line x1="{ln.x1}" y1="{ln.y1}" x2="{ln.x2}" y2="{ln.y2}" stroke="#{ln.color}" '
                   f'stroke-width="{ln.lw / 72:.4f}"{dash}{mk}/>')
    return (f'<svg class="e" style="{_pos(0, 0, T.W, T.H)}" viewBox="0 0 {T.W} {T.H}">'
            '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" '
            'orient="auto"><path d="M0 0L10 5L0 10z" fill="#0C1E3C"/></marker></defs>' + "".join(out) + "</svg>")


CSS = """
:root{--bg:#E9EEF5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);font-family:Arial,Helvetica,sans-serif;color:#1F2937}
header{max-width:1280px;margin:0 auto;padding:18px 16px 8px;display:flex;justify-content:space-between;gap:12px;
 align-items:baseline;flex-wrap:wrap}
header h1{font-size:18px;margin:0;color:#0C1E3C}header span{font-size:12px;color:#64748B}
.deck{max-width:1280px;margin:0 auto;padding:0 16px 32px}
.slide{position:relative;width:100%;aspect-ratio:13.333/7.5;container-type:inline-size;background:#fff;
 margin:0 0 18px;box-shadow:0 2px 10px rgba(12,30,60,.12);overflow:hidden;border-radius:6px}
.e{position:absolute;margin:0}
.t{display:flex;flex-direction:column;overflow:hidden;line-height:1.18}
.t p.b{position:relative}.t p.b:before{content:"\\2022";position:absolute;left:0;color:inherit}
table.e{border-collapse:collapse;table-layout:fixed;line-height:1.18}
table.e td{border:1px solid #E2E8F0;padding:0 0.45cqw;vertical-align:middle;overflow:hidden}
@media print{@page{size:13.333in 7.5in;margin:0}body{background:#fff}header{display:none}
 .deck{padding:0;max-width:none}.slide{margin:0;box-shadow:none;border-radius:0;break-after:page;width:13.333in}}
"""


def render(deck) -> bytes:
    parts = []
    for sl in deck.slides:
        items, lines = [], []
        for p in sl.prims:
            try:
                if isinstance(p, Line):
                    lines.append(p)
                elif isinstance(p, Rect):
                    items.append(_rect(p))
                elif isinstance(p, Text):
                    items.append(_text(p))
                elif isinstance(p, Table):
                    items.append(_table(p))
                elif isinstance(p, Chart):
                    items.append(_chart(p))
                elif isinstance(p, Image):
                    items.append(_image(p))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Elemen %s gagal digambar di slide %d (HTML): %s", type(p).__name__, sl.index, exc)
                if isinstance(p, Chart):
                    try:
                        from .render_pptx import _chart_as_table

                        items.append(_table(_chart_as_table(p)))
                    except Exception:  # noqa: BLE001
                        logger.exception("Tabel pengganti chart gagal (HTML)")
                deck.issues.append(f"slide {sl.index}: {type(p).__name__} diganti versi sederhana (HTML)")
        items.append(_lines(lines))
        parts.append(f'<section class="slide" aria-label="Slide {sl.index}: {_e(sl.title)}">{"".join(items)}</section>')
    doc = (f'<!doctype html><html lang="id"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(deck.title)}</title>'
           f'<style>{CSS}</style></head><body><header><h1>{_e(deck.title)}</h1>'
           f'<span>{len(deck.slides)} halaman · PT Pertamina Lubricants · Confidential</span></header>'
           f'<main class="deck">{"".join(parts)}</main></body></html>')
    return doc.encode("utf-8")
