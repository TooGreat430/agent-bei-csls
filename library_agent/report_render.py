"""Render isi laporan (JSON sesuai schema.json) ke HTML, PDF, atau PPTX.

Ketiga format memakai satu `layout` yang sama (dari manifest.json, atau dibuat otomatis
dari schema), sehingga isi dan urutan bagian identik di semua format:

    cover     : sampul (otomatis)
    section   : halaman pemisah bab            {"title"}
    bullets   : daftar poin                     {"field", "title", "lead"?}
    text      : paragraf                        {"field", "title"}
    cards     : kartu (maks 4 per baris)        {"field", "title", "card_title", "card_body"}
    findings  : satu halaman per temuan         {"field"}  item: judul, pesan_utama?, poin|uraian, tabel?, sitasi
    table     : tabel dari daftar objek         {"field", "title", "columns":[{key,label,style?}], "widths"?}
    closing   : halaman penutup (otomatis)

PDF memakai reportlab dan PPTX memakai python-pptx. Keduanya murni Python, tanpa
komponen sistem tambahan, sehingga berjalan di Agent Runtime.
"""
from __future__ import annotations

import html as _html
import io
import math
import os
import re
from typing import Any

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

DEFAULT_THEME = {
    "primary": "1C2757", "accent": "1BA5B8", "highlight": "D6DD3C", "text": "1E2329",
    "muted": "5B6470", "light": "EEF2F7", "line": "D5DBE3",
    "high": "C0392B", "mid": "B7791F", "low": "2F7D4F",
}
PRIORITY_KEYS = {"tinggi": "high", "sedang": "mid", "rendah": "low", "high": "high", "medium": "mid", "low": "low"}

# Karakter yang sering muncul dari model tetapi tidak perlu/aneh di dokumen.
_CHAR_MAP = {"\u2264": "<=", "\u2265": ">=", "\u2192": "->", "\u00a0": " ", "\u200b": ""}


# ==========================================================================
# Layout & utilitas (logika murni)
# ==========================================================================
def clean(text: Any) -> str:
    s = "" if text is None else str(text)
    for k, v in _CHAR_MAP.items():
        s = s.replace(k, v)
    return s.strip()


def paragraphs(text: Any) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", clean(text)) if p.strip()]


def titleize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def theme_of(manifest: dict[str, Any]) -> dict[str, str]:
    theme = dict(DEFAULT_THEME)
    for k, v in (manifest.get("theme") or {}).items():
        if isinstance(v, str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", v):
            theme[k] = v.lstrip("#").upper()
    return theme


def default_layout(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Layout otomatis dari schema, untuk template yang tidak mendefinisikan `layout`."""
    blocks: list[dict[str, Any]] = []
    for key, prop in (schema.get("properties") or {}).items():
        kind = prop.get("type")
        title = prop.get("title") or titleize(key)
        if key in ("periode", "segmen", "judul_utama"):
            continue  # dipakai di sampul
        if kind == "string":
            blocks.append({"type": "text", "field": key, "title": title})
        elif kind == "array":
            items = prop.get("items") or {}
            if items.get("type") == "string":
                blocks.append({"type": "bullets", "field": key, "title": title})
            elif items.get("type") == "object":
                props = items.get("properties") or {}
                if "judul" in props and ("poin" in props or "uraian" in props) and "sitasi" in props:
                    blocks.append({"type": "findings", "field": key})
                else:
                    blocks.append({"type": "table", "field": key, "title": title,
                                   "columns": [{"key": k, "label": titleize(k),
                                                "style": "priority" if k in ("prioritas", "priority") else ""}
                                               for k in props]})
    return blocks


def resolve_layout(manifest: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    return manifest.get("layout") or default_layout(schema)


def cover_info(manifest: dict[str, Any], content: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    cover = manifest.get("cover") or {}
    title = clean(content.get(cover.get("title_field", "judul_utama"))) or clean(meta.get("report_title"))
    subtitle_fields = cover.get("subtitle_fields") or [f for f in ("segmen", "periode") if f in content]
    subtitle = " – ".join(clean(content.get(f)) for f in subtitle_fields if clean(content.get(f)))
    tag = clean(content.get(cover.get("tag_field", "segmen"))) if cover.get("tag_field", "segmen") in content else ""
    return {
        "title": title,
        "report_title": clean(meta.get("report_title")),
        "subtitle": subtitle,
        "tag": tag,
        "company": clean(meta.get("company_name")),
        "date": clean(meta.get("generated_date")),
    }


def footer_text(manifest: dict[str, Any], meta: dict[str, Any]) -> str:
    pattern = manifest.get("footer") or "{company} | {report_title} | {date} | Confidential"
    return pattern.format(company=clean(meta.get("company_name")), report_title=clean(meta.get("report_title")),
                          date=clean(meta.get("generated_date")))


def estimate_lines(text: str, chars_per_line: int) -> int:
    return max(1, math.ceil(len(text) / max(chars_per_line, 10)))


def chunk_by_lines(items: list[str], chars_per_line: int, max_lines: int, gap: float = 0.5) -> list[list[str]]:
    """Bagi daftar teks ke beberapa halaman supaya tidak meluber dari kotak."""
    chunks: list[list[str]] = [[]]
    used = 0.0
    for item in items:
        need = estimate_lines(item, chars_per_line) + gap
        if chunks[-1] and used + need > max_lines:
            chunks.append([])
            used = 0.0
        chunks[-1].append(item)
        used += need
    return [c for c in chunks if c]


def chunk_rows(rows: list[list[str]], col_chars: list[int], max_lines: int) -> list[list[list[str]]]:
    """Bagi baris tabel ke beberapa halaman berdasarkan perkiraan tinggi baris."""
    chunks: list[list[list[str]]] = [[]]
    used = 0
    for row in rows:
        need = max(estimate_lines(str(cell), col_chars[min(i, len(col_chars) - 1)]) for i, cell in enumerate(row)) if row else 1
        if chunks[-1] and used + need > max_lines:
            chunks.append([])
            used = 0
        chunks[-1].append(row)
        used += need
    return [c for c in chunks if c]


def table_rows(items: list[dict[str, Any]], columns: list[dict[str, Any]]) -> list[list[str]]:
    return [[clean(item.get(c["key"], "")) for c in columns] for item in items or []]


def finding_body(item: dict[str, Any]) -> list[str]:
    points = item.get("poin")
    if isinstance(points, list) and points:
        return [clean(p) for p in points if clean(p)]
    return paragraphs(item.get("uraian", ""))


def finding_table(item: dict[str, Any]) -> tuple[list[str], list[list[str]]] | None:
    table = item.get("tabel")
    if not isinstance(table, dict):
        return None
    cols = [clean(c) for c in table.get("kolom") or []]
    rows = [[clean(c) for c in r] for r in table.get("baris") or [] if isinstance(r, list)]
    if not cols or not rows:
        return None
    width = len(cols)
    rows = [(r + [""] * width)[:width] for r in rows]
    return cols, rows


def first_col_weights(n: int) -> list[float]:
    """Kolom pertama tabel temuan (nama merek/kategori) dibuat lebih lebar."""
    raw = [1.7] + [1.0] * (n - 1)
    total = sum(raw)
    return [r / total for r in raw]


def weights(columns: list[dict[str, Any]], block: dict[str, Any], n: int) -> list[float]:
    given = block.get("widths")
    if given and len(given) == n:
        total = sum(given)
        return [w / total for w in given]
    return [1 / n] * n


# ==========================================================================
# HTML
# ==========================================================================
_HTML_CSS = """
:root{--primary:#%(primary)s;--accent:#%(accent)s;--highlight:#%(highlight)s;--text:#%(text)s;
--muted:#%(muted)s;--light:#%(light)s;--line:#%(line)s;--high:#%(high)s;--mid:#%(mid)s;--low:#%(low)s}
*{box-sizing:border-box}
body{margin:0;background:#E9ECF1;color:var(--text);font:15px/1.5 "Barlow","Segoe UI",Arial,sans-serif}
.deck{max-width:1100px;margin:0 auto;padding:24px 16px}
.slide{background:#fff;aspect-ratio:16/9;margin:0 0 24px;padding:4.5%% 5%% 5.5%%;position:relative;
box-shadow:0 1px 3px rgba(0,0,0,.12);overflow:hidden;display:flex;flex-direction:column}
.dark{background:var(--primary);color:#fff;justify-content:center}
.tag{position:absolute;top:3.5%%;right:4%%;background:var(--accent);color:#fff;font-weight:700;padding:.25em .9em;border-radius:4px;font-size:.85em}
h1{font-size:2.6em;line-height:1.08;margin:0 0 .5em;text-transform:uppercase;font-weight:800;max-width:70%%}
h2{font-size:1.6em;margin:0 0 .35em;color:var(--primary);text-transform:uppercase;font-weight:800;max-width:85%%}
.dark h2{color:#fff;font-size:2.4em}
.lead{margin:0 0 1em;font-size:1.05em;max-width:95%%}
.sub{opacity:.85;margin:.2em 0}
ul{margin:0;padding-left:1.2em}li{margin:0 0 .5em}
.cols{display:grid;grid-template-columns:2fr 3fr;gap:1.5em;align-items:start;flex:1;min-height:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1em}
.card{background:var(--light);padding:1em;border-radius:6px}.card b{display:block;color:var(--primary);margin-bottom:.4em}
table{width:100%%;border-collapse:collapse;font-size:.88em}
th{background:var(--primary);color:#fff;text-align:left;padding:.45em .6em;font-weight:700}
td{padding:.4em .6em;border-bottom:1px solid var(--line);vertical-align:top}
tr:nth-child(even) td{background:var(--light)}
.p-high{color:var(--high);font-weight:700}.p-mid{color:var(--mid);font-weight:700}.p-low{color:var(--low);font-weight:700}
.cite{margin-top:auto;padding-top:.8em;font-size:.78em;color:var(--muted)}
.foot{position:absolute;left:5%%;right:5%%;bottom:3%%;display:flex;justify-content:space-between;font-size:.7em;color:var(--muted)}
.dark .foot{color:rgba(255,255,255,.7)}
@media print{body{background:#fff}.deck{padding:0;max-width:none}.slide{box-shadow:none;margin:0;page-break-after:always}}
"""


def _e(s: Any) -> str:
    return _html.escape(clean(s))


def render_html(manifest: dict[str, Any], schema: dict[str, Any], content: dict[str, Any], meta: dict[str, Any]) -> str:
    theme = theme_of(manifest)
    info = cover_info(manifest, content, meta)
    foot = _e(footer_text(manifest, meta))
    tag = f'<div class="tag">{_e(info["tag"])}</div>' if info["tag"] else ""
    slides: list[str] = []
    n = 0

    def slide(inner: str, dark: bool = False, with_tag: bool = True) -> None:
        nonlocal n
        n += 1
        cls = "slide dark" if dark else "slide"
        slides.append(f'<section class="{cls}">{tag if with_tag else ""}{inner}'
                      f'<div class="foot"><span>{foot}</span><span>{n}</span></div></section>')

    slide(f'<h1>{_e(info["title"])}</h1><p class="sub">{_e(info["subtitle"])}</p>'
          f'<p class="sub">{_e(info["company"])}</p><p class="sub">{_e(info["date"])}</p>', dark=True, with_tag=False)

    for block in resolve_layout(manifest, schema):
        kind, value = block.get("type"), content.get(block.get("field", ""), None)
        title = _e(block.get("title", ""))
        if kind == "section":
            slide(f"<h2>{title}</h2>", dark=True, with_tag=False)
        elif kind == "bullets" and value:
            lead = f'<p class="lead">{_e(block["lead"])}</p>' if block.get("lead") else ""
            slide(f"<h2>{title}</h2>{lead}<ul>" + "".join(f"<li>{_e(v)}</li>" for v in value) + "</ul>")
        elif kind == "text" and value:
            slide(f"<h2>{title}</h2>" + "".join(f"<p>{_e(p)}</p>" for p in paragraphs(value)))
        elif kind == "cards" and value:
            ct, cb = block.get("card_title", "judul"), block.get("card_body", "uraian")
            cards = "".join(f'<div class="card"><b>{_e(v.get(ct))}</b>{_e(v.get(cb))}</div>' for v in value)
            slide(f'<h2>{title}</h2><div class="cards">{cards}</div>')
        elif kind == "findings" and value:
            for item in value:
                body = "<ul>" + "".join(f"<li>{_e(p)}</li>" for p in finding_body(item)) + "</ul>"
                tbl = finding_table(item)
                if tbl:
                    cols, rows = tbl
                    t = ("<table><tr>" + "".join(f"<th>{_e(c)}</th>" for c in cols) + "</tr>"
                         + "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
                         + "</table>")
                    body = f'<div class="cols"><div>{body}</div><div>{t}</div></div>'
                lead = f'<p class="lead">{_e(item.get("pesan_utama"))}</p>' if item.get("pesan_utama") else ""
                cite = f'<div class="cite">Sumber: {_e("; ".join(item.get("sitasi") or []))}</div>' if item.get("sitasi") else ""
                slide(f"<h2>{_e(item.get('judul'))}</h2>{lead}{body}{cite}")
        elif kind == "table" and value:
            cols = block.get("columns") or []
            head = "".join(f"<th>{_e(c['label'])}</th>" for c in cols)
            body = ""
            for item in value:
                cells = ""
                for c in cols:
                    v = item.get(c["key"], "")
                    cls = f' class="p-{PRIORITY_KEYS.get(clean(v).lower(), "")}"' if c.get("style") == "priority" else ""
                    cells += f"<td{cls}>{_e(v)}</td>"
                body += f"<tr>{cells}</tr>"
            slide(f"<h2>{title}</h2><table><tr>{head}</tr>{body}</table>")

    slide(f'<h2>Terima kasih</h2><p class="sub">{_e(info["company"])}</p>', dark=True, with_tag=False)
    css = _HTML_CSS % theme
    return (f'<!DOCTYPE html><html lang="id"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_e(meta.get('report_title'))}</title><style>{css}</style></head>"
            f'<body><main class="deck">{"".join(slides)}</main></body></html>')


# ==========================================================================
# PDF (reportlab)
# ==========================================================================
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


def render_pdf(manifest: dict[str, Any], schema: dict[str, Any], content: dict[str, Any], meta: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, NextPageTemplate, PageBreak,
                                    PageTemplate, Paragraph, Spacer, Table, TableStyle)

    regular, bold, italic = _register_fonts()
    theme = {k: colors.HexColor("#" + v) for k, v in theme_of(manifest).items()}
    info = cover_info(manifest, content, meta)
    foot = footer_text(manifest, meta)
    W, H = 960, 540
    M = 44

    def esc(s: Any) -> str:
        return _html.escape(clean(s))

    st = {
        "h": ParagraphStyle("h", fontName=bold, fontSize=24, leading=28, textColor=theme["primary"], spaceAfter=6),
        "lead": ParagraphStyle("lead", fontName=regular, fontSize=14, leading=19, textColor=theme["text"], spaceAfter=12),
        "body": ParagraphStyle("body", fontName=regular, fontSize=13, leading=18, textColor=theme["text"], spaceAfter=6, alignment=TA_LEFT),
        "bullet": ParagraphStyle("bullet", fontName=regular, fontSize=13, leading=18, textColor=theme["text"],
                                 leftIndent=14, bulletIndent=2, spaceAfter=7),
        "card_t": ParagraphStyle("ct", fontName=bold, fontSize=12.5, leading=16, textColor=theme["primary"], spaceAfter=4),
        "card_b": ParagraphStyle("cb", fontName=regular, fontSize=10.5, leading=14.5, textColor=theme["text"]),
        "th": ParagraphStyle("th", fontName=bold, fontSize=10, leading=13, textColor=colors.white),
        "td": ParagraphStyle("td", fontName=regular, fontSize=10, leading=13, textColor=theme["text"]),
        "cite": ParagraphStyle("cite", fontName=italic, fontSize=8.5, leading=11, textColor=theme["muted"], spaceBefore=8),
    }

    class SetAttr(Flowable):
        """Mengirim judul halaman pemisah ke template halaman berikutnya."""
        def __init__(self, value: str):
            super().__init__()
            self.value = value

        def wrap(self, *_):
            return 0, 0

        def draw(self):
            self.canv._doctemplate.dark_title = self.value

    def draw_footer(canv, doc, dark=False):
        canv.setFont(regular, 7.5)
        canv.setFillColor(colors.Color(1, 1, 1, 0.7) if dark else theme["muted"])
        canv.drawString(M, 20, foot[:180])
        canv.drawRightString(W - M, 20, str(doc.page))

    def on_content(canv, doc):
        canv.saveState()
        if info["tag"]:
            tw = canv.stringWidth(info["tag"], bold, 11) + 22
            canv.setFillColor(theme["accent"])
            canv.roundRect(W - M - tw, H - 38, tw, 22, 3, stroke=0, fill=1)
            canv.setFillColor(colors.white)
            canv.setFont(bold, 11)
            canv.drawCentredString(W - M - tw / 2, H - 31, info["tag"])
        draw_footer(canv, doc)
        canv.restoreState()

    def on_cover(canv, doc):
        canv.saveState()
        canv.setFillColor(theme["primary"])
        canv.rect(0, 0, W, H, stroke=0, fill=1)
        canv.setFillColor(theme["highlight"])
        canv.circle(W - 40, 40, 150, stroke=0, fill=1)
        canv.setFillColor(theme["accent"])
        canv.circle(W - 150, H + 30, 190, stroke=0, fill=1)
        title_style = ParagraphStyle("ct", fontName=bold, fontSize=34, leading=38, textColor=colors.white)
        p = Paragraph(esc(info["title"]).upper(), title_style)
        _, ph = p.wrap(560, 260)
        p.drawOn(canv, 56, H - 70 - ph)
        canv.setFillColor(colors.white)
        y = 150
        for line, size in ((info["subtitle"], 15), (info["company"], 13), (info["date"], 12)):
            if line:
                canv.setFont(regular, size)
                canv.drawString(56, y, line)
                y -= size + 10
        draw_footer(canv, doc, dark=True)
        canv.restoreState()

    def on_dark(canv, doc):
        canv.saveState()
        canv.setFillColor(theme["primary"])
        canv.rect(0, 0, W, H, stroke=0, fill=1)
        canv.setFillColor(theme["accent"])
        canv.circle(W - 60, 60, 120, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont(bold, 36)
        canv.drawString(56, H / 2 - 12, (getattr(doc, "dark_title", "") or "").upper())
        if getattr(doc, "dark_title", "") == "Terima kasih" and info["company"]:
            canv.setFont(regular, 14)
            canv.drawString(56, H / 2 - 44, info["company"])
        draw_footer(canv, doc, dark=True)
        canv.restoreState()

    frame = Frame(M, 40, W - 2 * M, H - 40 - 44, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=(W, H), title=clean(meta.get("report_title")), author=info["company"])
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=on_cover),
        PageTemplate(id="content", frames=[frame], onPage=on_content),
        PageTemplate(id="dark", frames=[frame], onPage=on_dark),
    ])

    def data_table(header: list[str], rows: list[list[str]], width: float, fractions: list[float],
                   priority_col: int | None = None) -> Table:
        data = [[Paragraph(esc(h), st["th"]) for h in header]]
        for r in rows:
            cells = []
            for i, c in enumerate(r):
                style = st["td"]
                if i == priority_col:
                    key = PRIORITY_KEYS.get(clean(c).lower())
                    if key:
                        style = ParagraphStyle(f"p{key}", parent=st["td"], fontName=bold, textColor=theme[key])
                cells.append(Paragraph(esc(c), style))
            data.append(cells)
        t = Table(data, colWidths=[width * f for f in fractions], repeatRows=1)
        cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), theme["primary"]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, theme["line"]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]
        for i in range(2, len(data), 2):
            cmds.append(("BACKGROUND", (0, i), (-1, i), theme["light"]))
        t.setStyle(TableStyle(cmds))
        return t

    def bullets(items: list[str]) -> list[Paragraph]:
        return [Paragraph(esc(i), st["bullet"], bulletText="\u2022") for i in items]

    story: list[Any] = [Spacer(1, 1)]  # halaman 1 = sampul (digambar oleh on_cover)
    content_width = W - 2 * M

    def new_page() -> None:
        story.extend([NextPageTemplate("content"), PageBreak()])

    def dark_page(title: str) -> None:
        story.extend([SetAttr(title), NextPageTemplate("dark"), PageBreak(), Spacer(1, 1)])

    for block in resolve_layout(manifest, schema):
        kind, value = block.get("type"), content.get(block.get("field", ""), None)
        title = esc(block.get("title", "")).upper()
        if kind == "section":
            dark_page(clean(block.get("title", "")))
            continue
        if kind in ("bullets", "text", "cards", "table") and not value:
            continue
        if kind == "findings":
            for item in value or []:
                new_page()
                story.append(Paragraph(esc(item.get("judul")).upper(), st["h"]))
                if item.get("pesan_utama"):
                    story.append(Paragraph(esc(item["pesan_utama"]), st["lead"]))
                tbl = finding_table(item)
                body = bullets(finding_body(item))
                if tbl:
                    cols, rows = tbl
                    left_w, right_w = content_width * 0.38, content_width * 0.6
                    right = data_table(cols, rows, right_w, first_col_weights(len(cols)))
                    grid = Table([[body, right]], colWidths=[left_w, right_w + content_width * 0.02])
                    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 14)]))
                    story.append(grid)
                else:
                    story.extend(body)
                if item.get("sitasi"):
                    story.append(Paragraph("Sumber: " + esc("; ".join(item["sitasi"])), st["cite"]))
            continue

        new_page()
        story.append(Paragraph(title, st["h"]))
        if kind == "bullets":
            if block.get("lead"):
                story.append(Paragraph(esc(block["lead"]), st["lead"]))
            else:
                story.append(Spacer(1, 8))
            story.extend(bullets([clean(v) for v in value]))
        elif kind == "text":
            story.append(Spacer(1, 8))
            story.extend(Paragraph(esc(p), st["body"]) for p in paragraphs(value))
        elif kind == "cards":
            story.append(Spacer(1, 12))
            ct, cb = block.get("card_title", "judul"), block.get("card_body", "uraian")
            per_row = min(4, len(value))
            cw = content_width / per_row
            rows = []
            for i in range(0, len(value), per_row):
                row = [[Paragraph(esc(v.get(ct)), st["card_t"]), Paragraph(esc(v.get(cb)), st["card_b"])]
                       for v in value[i:i + per_row]]
                rows.append(row + [""] * (per_row - len(row)))
            t = Table(rows, colWidths=[cw] * per_row)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), theme["light"]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEAFTER", (0, 0), (-2, -1), 6, colors.white), ("LINEBELOW", (0, 0), (-1, -2), 6, colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]))
            story.append(t)
        elif kind == "table":
            story.append(Spacer(1, 8))
            cols = block.get("columns") or []
            prio = next((i for i, c in enumerate(cols) if c.get("style") == "priority"), None)
            story.append(data_table([c["label"] for c in cols], table_rows(value, cols), content_width,
                                    weights(cols, block, len(cols)), prio))

    dark_page("Terima kasih")
    doc.build(story)
    return buf.getvalue()


# ==========================================================================
# PPTX (python-pptx)
# ==========================================================================
def render_pptx(manifest: dict[str, Any], schema: dict[str, Any], content: dict[str, Any], meta: dict[str, Any],
                base_pptx: bytes | None = None) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Inches, Pt

    theme = theme_of(manifest)
    rgb = {k: RGBColor.from_string(v) for k, v in theme.items()}
    white = RGBColor(0xFF, 0xFF, 0xFF)
    info = cover_info(manifest, content, meta)
    foot = footer_text(manifest, meta)
    FONT = "Arial"

    prs = Presentation(io.BytesIO(base_pptx)) if base_pptx else Presentation()
    if base_pptx:
        # Buang slide contoh bawaan template; pakai master/layout-nya saja.
        id_list = prs.slides._sldIdLst
        for sld_id in list(id_list):
            prs.part.drop_rel(sld_id.rId)
            id_list.remove(sld_id)
    else:
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    SW, SH = prs.slide_width / 914400, prs.slide_height / 914400
    layout = next((l for l in prs.slide_layouts if l.name.lower() in ("blank", "kosong")), prs.slide_layouts[-1])
    M = 0.6
    page = {"n": 0}

    def new_slide(dark: bool = False, tag: bool = True):
        s = prs.slides.add_slide(layout)
        for ph in list(s.placeholders):
            ph._element.getparent().remove(ph._element)
        page["n"] += 1
        if dark:
            s.background.fill.solid()
            s.background.fill.fore_color.rgb = rgb["primary"]
        if tag and info["tag"] and not dark:
            w = 0.35 + 0.11 * len(info["tag"])
            shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(SW - M - w), Inches(0.32), Inches(w), Inches(0.38))
            shp.fill.solid()
            shp.fill.fore_color.rgb = rgb["accent"]
            shp.line.fill.background()
            shp.shadow.inherit = False
            tf = shp.text_frame
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            _runs(tf.paragraphs[0], info["tag"], 12, white, bold=True)
            tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        col = white if dark else rgb["muted"]
        text(s, M, SH - 0.45, SW - 2 * M - 0.8, 0.3, [foot], 9, col)
        num = text(s, SW - M - 0.7, SH - 0.45, 0.7, 0.3, [str(page["n"])], 9, col)
        num.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
        return s

    def _runs(p, value: str, size: float, color, bold: bool = False, italic: bool = False):
        r = p.add_run()
        r.text = value
        f = r.font
        f.size, f.bold, f.italic, f.name = Pt(size), bold, italic, FONT
        f.color.rgb = color
        return r

    def set_bullet(p):
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(Emu(Inches(0.28))))
        pPr.set("indent", str(-Emu(Inches(0.22))))
        for tag_name in ("a:buNone", "a:buChar", "a:buAutoNum"):
            for el in pPr.findall(qn(tag_name)):
                pPr.remove(el)
        bu = pPr.makeelement(qn("a:buChar"), {"char": "\u2022"})
        pPr.append(bu)

    def text(s, x, y, w, h, lines: list[str], size: float, color, bold=False, italic=False,
             bullet=False, space_after=6):
        box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = 0
        tf.margin_top = tf.margin_bottom = 0
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            _runs(p, line, size, color, bold, italic)
            p.space_after = Pt(space_after)
            if bullet:
                set_bullet(p)
        return box

    def heading(s, title: str, lead: str = "") -> float:
        text(s, M, 0.4, SW - 2 * M - 1.6, 0.8, [title.upper()], 26, rgb["primary"], bold=True)
        if lead:
            lead_lines = estimate_lines(lead, int((SW - 2 * M) * 72 / (14 * 0.5)))
            text(s, M, 1.2, SW - 2 * M, 0.3 + 0.3 * lead_lines, [lead], 14, rgb["text"])
            return 1.35 + 0.3 * lead_lines + 0.15
        return 1.45

    def cpl(width_in: float, size: float) -> int:
        return int(width_in * 72 / (size * 0.5))

    def add_table(s, x, y, w, header: list[str], rows: list[list[str]], fractions: list[float],
                  size=11, priority_col: int | None = None):
        tbl = s.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y), Inches(w),
                                 Inches(0.35 * (len(rows) + 1))).table
        for i, f in enumerate(fractions):
            tbl.columns[i].width = Inches(w * f)
        for r, values in enumerate([header] + rows):
            for c, value in enumerate(values):
                cell = tbl.cell(r, c)
                cell.margin_left = cell.margin_right = Inches(0.08)
                cell.margin_top = cell.margin_bottom = Inches(0.04)
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb["primary"] if r == 0 else (rgb["light"] if r % 2 == 0 else white)
                tf = cell.text_frame
                tf.word_wrap = True
                color, bold = (white, True) if r == 0 else (rgb["text"], False)
                if r > 0 and c == priority_col:
                    key = PRIORITY_KEYS.get(clean(value).lower())
                    if key:
                        color, bold = rgb[key], True
                p = tf.paragraphs[0]
                _runs(p, clean(value), size, color, bold=bold)

    body_top_default = 1.45
    body_bottom = SH - 0.75

    # Sampul
    s = new_slide(dark=True, tag=False)
    circle = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(SW - 3.3), Inches(SH - 3.0), Inches(4.2), Inches(4.2))
    circle.fill.solid()
    circle.fill.fore_color.rgb = rgb["highlight"]
    circle.line.fill.background()
    circle2 = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(SW - 4.6), Inches(-2.4), Inches(5.0), Inches(5.0))
    circle2.fill.solid()
    circle2.fill.fore_color.rgb = rgb["accent"]
    circle2.line.fill.background()
    text(s, 0.8, 0.9, 7.6, 3.2, [info["title"].upper()], 36, white, bold=True, space_after=0)
    sub = [x for x in (info["subtitle"], info["company"], info["date"]) if x]
    text(s, 0.8, 4.6, 7.0, 1.6, sub, 16, white, space_after=6)

    for block in resolve_layout(manifest, schema):
        kind, value = block.get("type"), content.get(block.get("field", ""), None)
        title = clean(block.get("title", ""))
        if kind == "section":
            s = new_slide(dark=True, tag=False)
            text(s, 0.8, SH / 2 - 0.5, SW - 1.6, 1.0, [title.upper()], 40, white, bold=True)
            continue
        if not value:
            continue
        if kind == "bullets":
            items = [clean(v) for v in value]
            top = body_top_default + (0.55 if block.get("lead") else 0)
            chunks = chunk_by_lines(items, cpl(SW - 2 * M - 0.3, 16), int((body_bottom - top) * 72 / (16 * 1.35)))
            for i, chunk in enumerate(chunks):
                s = new_slide()
                t = heading(s, title + (" (lanjutan)" if i else ""), block.get("lead", "") if i == 0 else "")
                text(s, M, t, SW - 2 * M, body_bottom - t, chunk, 16, rgb["text"], bullet=True, space_after=10)
        elif kind == "text":
            paras = paragraphs(value)
            chunks = chunk_by_lines(paras, cpl(SW - 2 * M, 15), int((body_bottom - 1.5) * 72 / (15 * 1.35)), gap=1)
            for i, chunk in enumerate(chunks):
                s = new_slide()
                t = heading(s, title + (" (lanjutan)" if i else ""))
                text(s, M, t, SW - 2 * M, body_bottom - t, chunk, 15, rgb["text"], space_after=12)
        elif kind == "cards":
            ct, cb = block.get("card_title", "judul"), block.get("card_body", "uraian")
            for start in range(0, len(value), 4):
                cards = value[start:start + 4]
                s = new_slide()
                t = heading(s, title + (" (lanjutan)" if start else ""))
                gap = 0.3
                w = (SW - 2 * M - gap * (len(cards) - 1)) / len(cards)
                longest = max(len(clean(c.get(cb))) for c in cards)
                size = 13 if longest < cpl(w - 0.4, 13) * 9 else 11
                body_lines = max(estimate_lines(clean(c.get(cb)), cpl(w - 0.4, size)) for c in cards)
                card_h = min(body_bottom - t - 0.3, max(2.4, 1.45 + body_lines * size * 1.3 / 72 + 0.35))
                for i, card in enumerate(cards):
                    x = M + i * (w + gap)
                    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(t + 0.2), Inches(w), Inches(card_h))
                    box.adjustments[0] = 0.04
                    box.fill.solid()
                    box.fill.fore_color.rgb = rgb["light"]
                    box.line.fill.background()
                    box.shadow.inherit = False
                    text(s, x + 0.2, t + 0.4, w - 0.4, 0.8, [clean(card.get(ct))], 15, rgb["primary"], bold=True)
                    text(s, x + 0.2, t + 1.25, w - 0.4, card_h - 1.2, [clean(card.get(cb))], size, rgb["text"])
        elif kind == "findings":
            for item in value:
                body = finding_body(item)
                tbl = finding_table(item)
                cite = "Sumber: " + "; ".join(clean(c) for c in item.get("sitasi") or []) if item.get("sitasi") else ""
                cite_h = 0.35 if cite else 0
                s = new_slide()
                t = heading(s, clean(item.get("judul")), clean(item.get("pesan_utama")))
                avail = body_bottom - cite_h - t
                if tbl:
                    cols, rows = tbl
                    left_w, right_x = 4.4, M + 4.4 + 0.35
                    right_w = SW - M - right_x
                    fr_t = first_col_weights(len(cols))
                    col_chars = [cpl(right_w * f - 0.16, 11) for f in fr_t]
                    row_chunks = chunk_rows(rows, col_chars, max(3, int(avail * 72 / (11 * 1.55)) - 1))
                    b_chunks = chunk_by_lines(body, cpl(left_w - 0.3, 14), int(avail * 72 / (14 * 1.35)))
                    pages = max(len(row_chunks), len(b_chunks))
                    for pi in range(pages):
                        if pi:
                            s = new_slide()
                            t = heading(s, clean(item.get("judul")) + " (lanjutan)")
                            avail = body_bottom - cite_h - t
                        if pi < len(b_chunks):
                            text(s, M, t, left_w, avail, b_chunks[pi], 14, rgb["text"], bullet=True, space_after=8)
                        if pi < len(row_chunks):
                            add_table(s, right_x, t, right_w, cols, row_chunks[pi], fr_t)
                        if cite:
                            text(s, M, body_bottom - cite_h + 0.05, SW - 2 * M, cite_h, [cite], 10, rgb["muted"], italic=True)
                else:
                    chunks = chunk_by_lines(body, cpl(SW - 2 * M - 0.3, 16), int(avail * 72 / (16 * 1.35)))
                    for pi, chunk in enumerate(chunks):
                        if pi:
                            s = new_slide()
                            t = heading(s, clean(item.get("judul")) + " (lanjutan)")
                        text(s, M, t, SW - 2 * M, body_bottom - cite_h - t, chunk, 16, rgb["text"], bullet=True, space_after=10)
                        if cite:
                            text(s, M, body_bottom - cite_h + 0.05, SW - 2 * M, cite_h, [cite], 10, rgb["muted"], italic=True)
        elif kind == "table":
            cols = block.get("columns") or []
            fr = weights(cols, block, len(cols))
            prio = next((i for i, c in enumerate(cols) if c.get("style") == "priority"), None)
            rows = table_rows(value, cols)
            col_chars = [cpl((SW - 2 * M) * f - 0.16, 12) for f in fr]
            for i, chunk in enumerate(chunk_rows(rows, col_chars, int((body_bottom - 1.6) * 72 / (12 * 1.6)) - 1)):
                s = new_slide()
                t = heading(s, title + (" (lanjutan)" if i else ""))
                add_table(s, M, t, SW - 2 * M, [c["label"] for c in cols], chunk, fr, size=12, priority_col=prio)

    s = new_slide(dark=True, tag=False)
    text(s, 0.8, SH / 2 - 0.7, SW - 1.6, 1.0, ["TERIMA KASIH"], 44, white, bold=True)
    if info["company"]:
        text(s, 0.8, SH / 2 + 0.35, SW - 1.6, 0.5, [info["company"]], 18, white)

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
