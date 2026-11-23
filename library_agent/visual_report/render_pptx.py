"""Deck -> PPTX. Chart = chart native PowerPoint (bisa diedit), tabel = tabel native, teks = kotak teks."""
from __future__ import annotations

import io
import logging

from . import charts as CH
from . import theme as T
from .prims import PAD_X, PAD_Y, Chart, Image, Line, Rect, Table, Text

logger = logging.getLogger(__name__)


def _rgb(h: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(T.hex_ok(h, T.TEXT))


def _font(f, size: float, bold=False, color=T.TEXT, italic=False):
    from pptx.util import Pt

    f.name = T.FONT
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = _rgb(color)


def _bullet(p, size: float) -> None:
    from pptx.oxml.ns import qn

    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(int(size * 1.1 * 12700)))
    pPr.set("indent", str(int(-size * 1.1 * 12700)))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    bu = pPr.makeelement(qn("a:buChar"), {"char": "•"})
    pPr.append(bu)


def _rect(s, r: Rect):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    kind = {"ellipse": MSO_SHAPE.OVAL, "chevron": MSO_SHAPE.CHEVRON, "trapezoid": MSO_SHAPE.TRAPEZOID}.get(
        r.shape, MSO_SHAPE.ROUNDED_RECTANGLE if r.radius else MSO_SHAPE.RECTANGLE)
    sh = s.shapes.add_shape(kind, Inches(r.x), Inches(r.y), Inches(max(r.w, 0.01)), Inches(max(r.h, 0.01)))
    if r.radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = min(0.5, 0.07 / max(min(r.w, r.h), 0.01))
    if r.fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = _rgb(r.fill)
    else:
        sh.fill.background()
    if r.line:
        sh.line.color.rgb = _rgb(r.line)
        sh.line.width = Pt(r.lw)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    if r.name:
        sh.name = r.name
    return sh


def _text(s, t: Text):
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.util import Inches, Pt

    tb = s.shapes.add_textbox(Inches(t.x), Inches(t.y), Inches(max(t.w, 0.05)), Inches(max(t.h, 0.05)))
    if t.fill:
        tb.fill.solid()
        tb.fill.fore_color.rgb = _rgb(t.fill)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = Inches(PAD_X)
    tf.margin_top = tf.margin_bottom = Inches(PAD_Y)
    tf.vertical_anchor = {"m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}.get(t.valign, MSO_ANCHOR.TOP)
    for k, p in enumerate(t.paras):
        para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        para.alignment = {"c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}.get(p.get("align"), PP_ALIGN.LEFT)
        para.space_after = Pt(t.size * p.get("after", 0.25)) if k < len(t.paras) - 1 else Pt(0)
        para.line_spacing = 1.0
        if p.get("bullet"):
            _bullet(para, t.size)
        for r in p["runs"]:
            rr = para.add_run()
            rr.text = r.get("t", "")
            _font(rr.font, t.size * r.get("s", 1.0), r.get("b", False), r.get("c", T.TEXT), r.get("i", False))
    if t.name:
        tb.name = t.name
    return tb


def _table(s, tb: Table):
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    nrow, ncol = len(tb.rows), len(tb.cols)
    gf = s.shapes.add_table(nrow, ncol, Inches(tb.x), Inches(tb.y), Inches(tb.w), Inches(max(tb.h, 0.2)))
    table = gf.table
    table.first_row = False
    table.horz_banding = False
    for j, w in enumerate(tb.cols):
        table.columns[j].width = Inches(w)
    for i, row in enumerate(tb.rows):
        table.rows[i].height = Inches(tb.row_h[i] if i < len(tb.row_h) else 0.3)
        for j in range(ncol):
            cell = table.cell(i, j)
            c = row[j] if j < len(row) else {"t": ""}
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(c.get("fill") or T.WHITE)
            cell.margin_left = cell.margin_right = Inches(PAD_X)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = {"c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}.get(c.get("align"), PP_ALIGN.LEFT)
            r = p.add_run()
            r.text = str(c.get("t", ""))
            _font(r.font, tb.size * c.get("s", 1.0), c.get("b", False), c.get("c", T.TEXT))
    return gf


def _chart(s, ch: Chart):
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    spec = ch.spec
    kind, cats, series = spec["kind"], spec["categories"], spec["series"]
    data = CategoryChartData()
    data.categories = cats
    stacked_wf = False
    if kind == "waterfall":
        geo = CH.waterfall_geometry(series[0]["values"], spec["totals"])
        if all(lo >= 0 for lo, _ in geo):                       # waterfall native: dasar transparan + batang
            stacked_wf = True
            data.add_series("dasar", [lo for lo, _ in geo])
            data.add_series(series[0]["name"] or "Nilai", [hi - lo for lo, hi in geo])
            ctype = XL_CHART_TYPE.COLUMN_STACKED
        else:                                                   # melewati nol: kolom berwarna per langkah
            data.add_series(series[0]["name"] or "Nilai", series[0]["values"])
            ctype = XL_CHART_TYPE.COLUMN_CLUSTERED
    else:
        for sr in series:
            data.add_series(sr["name"] or "Nilai", sr["values"])
        ctype = {"barh": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
                 "line": XL_CHART_TYPE.LINE_MARKERS, "stacked": XL_CHART_TYPE.COLUMN_STACKED}[kind]
    gf = s.shapes.add_chart(ctype, Inches(ch.x), Inches(ch.y), Inches(ch.w), Inches(ch.h), data)
    chart = gf.chart
    chart.font.name = T.FONT
    fs = 10 if min(ch.w, ch.h) > 2.2 else 9
    chart.font.size = Pt(fs)
    chart.has_title = False
    plot = chart.plots[0]
    if kind != "line":
        plot.gap_width = 55 if kind != "barh" else 45
        if kind in ("stacked",) or stacked_wf:
            plot.overlap = 100
        elif len(series) > 1:
            plot.overlap = -10
    vis = list(chart.series)
    if stacked_wf:
        base = vis[0]
        base.format.fill.background()
        base.format.line.fill.background()
        vis = vis[1:]
    for j, sr in enumerate(vis):
        src = series[0] if kind == "waterfall" else series[j]
        if kind == "line":
            sr.format.line.color.rgb = _rgb(src["color"])
            sr.format.line.width = Pt(2.25)
            sr.smooth = False
            sr.marker.format.fill.solid()
            sr.marker.format.fill.fore_color.rgb = _rgb(src["color"])
            sr.marker.size = 6
        else:
            sr.format.fill.solid()
            sr.format.fill.fore_color.rgb = _rgb(src["color"])
            if src.get("colors"):
                for i, col in enumerate(src["colors"]):
                    pt = sr.points[i]
                    pt.format.fill.solid()
                    pt.format.fill.fore_color.rgb = _rgb(col)
        if spec.get("labels", True):
            for i, v in enumerate(src["values"]):
                if v is None:
                    continue
                if kind == "line" and len(src["values"]) > 12 and i not in (0, len(src["values"]) - 1):
                    continue
                dl = sr.points[i].data_label
                dl.has_text_frame = True
                dl.text_frame.text = CH.label(spec, v, i)
                f = dl.text_frame.paragraphs[0].runs[0].font
                in_bar = kind == "stacked"
                _font(f, fs - (1 if in_bar else 0), bool(kind == "waterfall" and spec["totals"][i]),
                      T.text_on(src["color"]) if in_bar else T.TEXT)
                try:
                    dl.position = {"barh": XL_LABEL_POSITION.OUTSIDE_END, "column": XL_LABEL_POSITION.OUTSIDE_END,
                                   "line": XL_LABEL_POSITION.ABOVE, "stacked": XL_LABEL_POSITION.CENTER}.get(
                        kind, XL_LABEL_POSITION.INSIDE_END if stacked_wf else XL_LABEL_POSITION.OUTSIDE_END)
                except Exception:  # noqa: BLE001
                    pass
    va, ca = chart.value_axis, chart.category_axis
    va.has_major_gridlines = kind == "line"
    if kind == "line":
        va.major_gridlines.format.line.color.rgb = _rgb(T.GRID)
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(fs - 1)
        va.tick_labels.font.color.rgb = _rgb(T.MUTED)
    else:
        va.visible = False
    vals = [v for sr in series for v in sr["values"] if v is not None]
    if kind in ("barh", "column") and vals:
        hi_v, lo_v = max(vals + [0]), min(vals + [0])
        va.maximum_scale = hi_v * 1.18 if hi_v > 0 else 0
        va.minimum_scale = lo_v * 1.18 if lo_v < 0 else 0
    ca.format.line.color.rgb = _rgb(T.BORDER)
    ca.tick_labels.font.size = Pt(fs)
    ca.tick_labels.font.color.rgb = _rgb(T.TEXT2)
    ca.has_major_gridlines = False
    if kind == "barh":
        ca.reverse_order = True
    chart.has_legend = bool(spec.get("legend")) and len(series) > 1 and kind != "waterfall"
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(fs - 1)
    return gf


def _line(s, ln: Line):
    from pptx.enum.shapes import MSO_CONNECTOR
    from pptx.oxml.ns import qn
    from pptx.util import Inches, Pt

    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(ln.x1), Inches(ln.y1), Inches(ln.x2), Inches(ln.y2))
    c.line.color.rgb = _rgb(ln.color)
    c.line.width = Pt(ln.lw)
    if ln.arrow:
        lnel = c.line._get_or_add_ln()
        lnel.append(lnel.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))
    return c


def _image(s, im: Image):
    from PIL import Image as PILImage
    from pptx.util import Inches

    with PILImage.open(io.BytesIO(im.png)) as pi:
        iw, ih = pi.size
    scale = min(im.w / iw, im.h / ih)
    w, h = iw * scale, ih * scale
    pic = s.shapes.add_picture(io.BytesIO(im.png), Inches(im.x + (im.w - w) / 2), Inches(im.y + (im.h - h) / 2),
                               Inches(w), Inches(h))
    if im.alt:
        pic._element.nvPicPr.cNvPr.set("descr", im.alt[:250])
    return pic


DRAW = {Rect: _rect, Text: _text, Table: _table, Chart: _chart, Line: _line, Image: _image}


def render(deck) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(T.W), Inches(T.H)
    prs.core_properties.title = deck.title[:250]
    prs.core_properties.author = "Marketing Insight Assistant"
    prs.core_properties.comments = "PT Pertamina Lubricants"
    blank = prs.slide_layouts[6]
    for sl in deck.slides:
        s = prs.slides.add_slide(blank)
        for p in sl.prims:
            try:
                DRAW[type(p)](s, p)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Elemen %s gagal digambar di slide %d (PPTX): %s", type(p).__name__, sl.index, exc)
                if isinstance(p, Chart):                      # chart gagal -> tabel datanya (angka tetap ada)
                    try:
                        _table(s, _chart_as_table(p))
                    except Exception:  # noqa: BLE001
                        logger.exception("Tabel pengganti chart gagal")
                deck.issues.append(f"slide {sl.index}: {type(p).__name__} diganti versi sederhana (PPTX)")
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _chart_as_table(ch: Chart) -> Table:
    spec = ch.spec
    header = [{"t": "", "b": True, "c": T.WHITE, "fill": T.NAVY}] + [
        {"t": s["name"] or "Nilai", "b": True, "c": T.WHITE, "fill": T.NAVY, "align": "c"} for s in spec["series"]]
    rows = [header] + [[{"t": c}] + [{"t": CH.label(spec, s["values"][i], i), "align": "r"} for s in spec["series"]]
                       for i, c in enumerate(spec["categories"])]
    n = len(header)
    tb = Table(ch.x, ch.y, ch.w, [ch.w / n] * n, rows, size=10)
    return tb.fit(ch.h, 7.5)
