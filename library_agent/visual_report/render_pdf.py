"""Deck -> PDF (halaman 16:9, sama persis tata letaknya dengan PPTX). Chart digambar matplotlib (PNG tajam)."""
from __future__ import annotations

import io
import logging

from . import charts as CH
from . import theme as T
from .prims import LINE, PAD_X, PAD_Y, Chart, Image, Line, Rect, Table, Text, layout_text, pdf_fonts, text_width

logger = logging.getLogger(__name__)
PT = 72.0


def _c(h: str):
    from reportlab.lib.colors import HexColor

    return HexColor("#" + T.hex_ok(h, T.TEXT))


def _Y(y: float) -> float:
    return (T.H - y) * PT


def _rect(c, r: Rect):
    if not r.fill and not r.line:
        return
    c.setLineWidth(r.lw)
    if r.fill:
        c.setFillColor(_c(r.fill))
    if r.line:
        c.setStrokeColor(_c(r.line))
    x, y, w, h = r.x * PT, _Y(r.y + r.h), r.w * PT, r.h * PT
    if r.shape == "ellipse":
        c.ellipse(x, y, x + w, y + h, stroke=bool(r.line), fill=bool(r.fill))
    elif r.radius:
        c.roundRect(x, y, w, h, min(0.07 * PT, w / 2, h / 2), stroke=bool(r.line), fill=bool(r.fill))
    else:
        c.rect(x, y, w, h, stroke=bool(r.line), fill=bool(r.fill))


def _draw_lines(c, x: float, y: float, w: float, h: float, paras: list, lines_by_para: list, size: float,
                valign: str = "t") -> None:
    f = pdf_fonts()
    _, need = layout_text(paras, w, h, size)
    top = y + PAD_Y
    if valign == "m":
        top = y + max((h - need) / 2, 0) + PAD_Y
    elif valign == "b":
        top = y + max(h - need, 0) + PAD_Y
    cur = top * PT
    inner_w = (w - 2 * PAD_X) * PT
    for k, (p, lines) in enumerate(zip(paras, lines_by_para)):
        indent = size * 1.1 if p.get("bullet") else 0.0
        for li, ln in enumerate(lines):
            mx = max([size * r.get("s", 1.0) for _, r in ln] or [size])
            base = cur + mx * 0.93
            width = sum(text_width(t, size * r.get("s", 1.0), r.get("b", False)) for t, r in ln)
            x0 = (x + PAD_X) * PT + indent
            if p.get("align") == "c":
                x0 = (x + PAD_X) * PT + (inner_w - width) / 2
            elif p.get("align") == "r":
                x0 = (x + PAD_X) * PT + inner_w - width
            if p.get("bullet") and li == 0 and ln:
                c.setFont(f["r"], size)
                c.setFillColor(_c(ln[0][1].get("c", T.TEXT)))
                c.drawString((x + PAD_X) * PT, T.H * PT - base, "•")
            for t, r in ln:
                rs = size * r.get("s", 1.0)
                c.setFont(f["b"] if r.get("b") else f["r"], rs)
                c.setFillColor(_c(r.get("c", T.TEXT)))
                c.drawString(x0, T.H * PT - base, t)
                x0 += text_width(t, rs, r.get("b", False))
            cur += mx * LINE
        if k < len(paras) - 1:
            cur += size * p.get("after", 0.25)


def _text(c, t: Text):
    if t.fill:
        c.setFillColor(_c(t.fill))
        c.rect(t.x * PT, _Y(t.y + t.h), t.w * PT, t.h * PT, stroke=0, fill=1)
    c.saveState()
    p = c.beginPath()
    p.rect(t.x * PT, _Y(t.y + t.h), t.w * PT, t.h * PT)
    c.clipPath(p, stroke=0, fill=0)
    _draw_lines(c, t.x, t.y, t.w, t.h, t.paras, t.lines or layout_text(t.paras, t.w, t.h, t.size)[0], t.size,
                t.valign)
    c.restoreState()


def _table(c, tb: Table):
    from .prims import para, run

    y = tb.y
    for i, row in enumerate(tb.rows):
        rh = tb.row_h[i] if i < len(tb.row_h) else 0.3
        x = tb.x
        for j, w in enumerate(tb.cols):
            cell = row[j] if j < len(row) else {"t": ""}
            c.setFillColor(_c(cell.get("fill") or T.WHITE))
            c.setStrokeColor(_c(T.GRID))
            c.setLineWidth(0.5)
            c.rect(x * PT, _Y(y + rh), w * PT, rh * PT, stroke=1, fill=1)
            s = tb.size * cell.get("s", 1.0)
            paras = [para([run(cell.get("t", ""), cell.get("b", False), cell.get("c", T.TEXT))], cell.get("align", "l"))]
            lines, _ = layout_text(paras, w, rh, s)
            _draw_lines(c, x, y, w, rh, paras, lines, s, "m")
            x += w
        y += rh


def _chart(c, ch: Chart):
    from reportlab.lib.utils import ImageReader

    png = CH.render_image(ch.spec, ch.w, ch.h, "png")
    c.drawImage(ImageReader(io.BytesIO(png)), ch.x * PT, _Y(ch.y + ch.h), ch.w * PT, ch.h * PT, mask="auto")


def _line(c, ln: Line):
    c.setStrokeColor(_c(ln.color))
    c.setLineWidth(ln.lw)
    if ln.dash:
        c.setDash(3, 2)
    c.line(ln.x1 * PT, _Y(ln.y1), ln.x2 * PT, _Y(ln.y2))
    c.setDash()
    if ln.arrow:
        c.setFillColor(_c(ln.color))
        p = c.beginPath()
        ex, ey = ln.x2 * PT, _Y(ln.y2)
        p.moveTo(ex, ey)
        p.lineTo(ex - 8, ey + 4)
        p.lineTo(ex - 8, ey - 4)
        p.close()
        c.drawPath(p, stroke=0, fill=1)


def _image(c, im: Image):
    from reportlab.lib.utils import ImageReader

    ir = ImageReader(io.BytesIO(im.png))
    iw, ih = ir.getSize()
    scale = min(im.w / iw, im.h / ih)
    w, h = iw * scale, ih * scale
    c.drawImage(ir, (im.x + (im.w - w) / 2) * PT, _Y(im.y + (im.h - h) / 2 + h), w * PT, h * PT, mask="auto")


DRAW = {Rect: _rect, Text: _text, Table: _table, Chart: _chart, Line: _line, Image: _image}


def render(deck) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(T.W * PT, T.H * PT))
    c.setTitle(deck.title[:250])
    c.setAuthor("Marketing Insight Assistant · PT Pertamina Lubricants")
    for sl in deck.slides:
        c.setFillColor(_c(T.WHITE))
        c.rect(0, 0, T.W * PT, T.H * PT, stroke=0, fill=1)
        for p in sl.prims:
            try:
                DRAW[type(p)](c, p)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Elemen %s gagal digambar di slide %d (PDF): %s", type(p).__name__, sl.index, exc)
                if isinstance(p, Chart):
                    try:
                        from .render_pptx import _chart_as_table

                        _table(c, _chart_as_table(p))
                    except Exception:  # noqa: BLE001
                        logger.exception("Tabel pengganti chart gagal (PDF)")
                deck.issues.append(f"slide {sl.index}: {type(p).__name__} diganti versi sederhana (PDF)")
        c.showPage()
    c.save()
    return buf.getvalue()
