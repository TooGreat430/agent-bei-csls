"""Renderer halaman laporan bergaya DESIGN SYSTEM PTPL (sama dengan laporan workflow MIR).

Satu model halaman (list of page dict) dirender ke tiga format:
- HTML  : dibungkus `report_assets/ptpl_design_system.html` (CSS + JS grafik asli, tidak diubah).
- PDF   : reportlab, grafik digambar ulang dengan matplotlib.
- PPTX  : python-pptx, satu slide per halaman (ukuran A4 landscape), grafik sebagai gambar.

Model halaman:
    {"kicker": "PLANOGRAM · 01", "title": "...", "tag": "PLANOGRAM", "sub": "...", "right": "Q3 2026 · Nasional",
     "draft": True, "source": "Planogram Marketing Intelligence (VM_PLANOGRAM)", "blocks": [block, ...]}
Blok:
    {"type": "sec", "title": "...", "acc": "..."}
    {"type": "kpis", "items": [{"label","value","mono","desc","tone": kg|kw|kr|kb, "badge": {"text","tone": b-g|b-w|b-r|b-b|b-n}}]}
    {"type": "grid", "cols": "g2|g3|g4|g-6040|g-4060", "children": [[block, ...], [block, ...]]}
    {"type": "chart", "size": "lg|sm|xl|", "spec": {...JSON grafik design system...}}
    {"type": "table", "columns": [...], "rows": [{"cells": [cell, ...], "cls": "seg|ptpl|hl|"}]}
        cell = teks/angka, atau {"t": teks, "cls": "nm|up|dn|fl|pos|neg|h1c..h5c", "dot": "d-g|d-w|d-r|d-n"}
    {"type": "insights", "items": [{"tone": ig|ir|iw|ib, "label", "title", "body"}]}
    {"type": "cards", "items": [{"title", "body"}]}
    {"type": "note", "text": "..."}
"""
from __future__ import annotations

import functools
import html as _html
import io
import json
import os
from typing import Any

ASSET_DIR = os.path.join(os.path.dirname(__file__), "report_assets")
DESIGN_FILE = os.path.join(ASSET_DIR, "ptpl_design_system.html")
COMPANY_FOOTER = "PT Pertamina Lubricants · Confidential"
DRAFT_LABEL = "DRAFT - menunggu approval"

# Warna design system
NAVY, NAVY2, NAVY3 = "#0C1E3C", "#1A3260", "#2A4A80"
GOLD, GOLD2 = "#92660A", "#B58012"
RED2, GREEN2, WARN2, BLUE = "#DC2626", "#15803D", "#D97706", "#1D4ED8"
GRAY, GRAY2, BORDER, BG2, BG3, TEXT3 = "#475569", "#94A3B8", "#E2E8F0", "#F8FAFC", "#EEF3FA", "#475569"
SERIES = ["#0C1E3C", "#B58012", "#15803D", "#DC2626", "#1D4ED8", "#7C3AED", "#0891B2", "#94A3B8"]
KPI_TOP = {"kg": GREEN2, "kw": WARN2, "kr": RED2, "kb": BLUE, "": NAVY2}
INS_LEFT = {"ig": (GREEN2, "#F0FDF4"), "ir": (RED2, "#FEF2F2"), "iw": (WARN2, "#FFFBEB"), "ib": (BLUE, "#EFF6FF"),
            "": (NAVY2, BG2)}
BADGE = {"b-g": ("#DCFCE7", "#166534"), "b-w": ("#FEF3C7", "#B45309"), "b-r": ("#FEE2E2", "#B91C1C"),
         "b-b": ("#DBEAFE", "#1D4ED8"), "b-n": (BG3, NAVY2)}
CELL_FG = {"up": GREEN2, "pos": GREEN2, "dn": RED2, "neg": RED2, "fl": GRAY}
CELL_BG = {"h1c": "#F0FDF4", "h2c": "#DCFCE7", "h3c": "#FEF9C3", "h4c": "#FED7AA", "h5c": "#FECACA"}
ROW_BG = {"hl": "#FFFBEB", "ptpl": "#EFF6FF", "seg": NAVY}
DOT = {"d-g": GREEN2, "d-w": WARN2, "d-r": RED2, "d-n": GRAY2}
CHART_PT = {"lg": 157.5, "sm": 82.5, "xl": 210.0, "": 112.5}   # tinggi grafik (pt) = tinggi CSS px × 0,75
GRID_RATIO = {"g2": [1, 1], "g3": [1, 1, 1], "g4": [1, 1, 1, 1], "g5": [1] * 5, "g-6040": [0.6, 0.4],
              "g-4060": [0.4, 0.6]}


# ==========================================================================
# Design system & HTML
# ==========================================================================
@functools.lru_cache(maxsize=1)
def design_system() -> str:
    with open(DESIGN_FILE, encoding="utf-8") as fh:
        return fh.read()


def wrap(body_html: str, title: str, approved_label: str = "") -> str:
    """Bungkus isi halaman dengan DESIGN SYSTEM PTPL (CSS & JS tidak diubah).

    approved_label diisi saat laporan disetujui: <body class="final"> + label FINAL menggantikan DRAFT.
    """
    doc = design_system().replace("JUDUL_LAPORAN", _html.escape(title or "Laporan PTPL"), 1)
    if approved_label:
        doc = doc.replace("<body>", f'<body class="final" data-approved="{_html.escape(approved_label)}">', 1)
    return doc.replace("ISI_LAPORAN_HTML", body_html, 1)


def _e(v: Any) -> str:
    return _html.escape("" if v is None else str(v))


def _cell(c: Any) -> dict:
    return c if isinstance(c, dict) else {"t": c}


def _block_html(b: dict) -> str:
    t = b.get("type")
    if t == "sec":
        acc = f' <span class="acc">· {_e(b["acc"])}</span>' if b.get("acc") else ""
        return f'<h2 class="sec">{_e(b.get("title"))}{acc}</h2>'
    if t == "sub":
        return f'<h3 class="sub">{_e(b.get("title"))}</h3>'
    if t == "kpis":
        n = len(b.get("items") or [])
        out = [f'<div class="grid g{min(max(n, 2), 5)}">']
        for k in b.get("items") or []:
            badge = k.get("badge") or {}
            out.append(
                f'<div class="kpi {_e(k.get("tone", ""))}"><div class="kpi-lbl">{_e(k.get("label"))}</div>'
                f'<div class="kpi-val">{_e(k.get("value"))}</div>'
                + (f'<div class="kpi-mono">{_e(k.get("mono"))}</div>' if k.get("mono") else "")
                + (f'<div class="kpi-desc">{_e(k.get("desc"))}</div>' if k.get("desc") else "")
                + (f'<span class="badge {_e(badge.get("tone", "b-n"))}">{_e(badge.get("text"))}</span>'
                   if badge.get("text") else "") + "</div>")
        out.append("</div>")
        return "".join(out)
    if t == "grid":
        cols = "".join("<div>" + "".join(_block_html(x) for x in col) + "</div>" for col in b.get("children") or [])
        return f'<div class="grid {_e(b.get("cols", "g2"))}">{cols}</div>'
    if t == "chart":
        spec = json.dumps(b.get("spec") or {}, ensure_ascii=False, separators=(",", ":"))
        size = f' {b["size"]}' if b.get("size") else ""
        return f'<div class="chart{size}" data-chart=\'{_html.escape(spec, quote=True)}\'></div>'
    if t == "table":
        head = "".join(f"<th>{_e(c)}</th>" for c in b.get("columns") or [])
        rows = []
        for r in b.get("rows") or []:
            r = r if isinstance(r, dict) else {"cells": r}
            cls = f' class="{_e(r["cls"])}"' if r.get("cls") else ""
            if r.get("cls") == "seg":
                rows.append(f'<tr class="seg"><td colspan="{len(b.get("columns") or [1])}">{_e(_cell(r["cells"][0])["t"])}</td></tr>')
                continue
            tds = []
            for c in r.get("cells") or []:
                c = _cell(c)
                dot = f'<span class="dot {_e(c["dot"])}"></span>' if c.get("dot") else ""
                ccls = f' class="{_e(c["cls"])}"' if c.get("cls") else ""
                tds.append(f"<td{ccls}>{dot}{_e(c.get('t'))}</td>")
            rows.append(f"<tr{cls}>{''.join(tds)}</tr>")
        return f'<table class="gt"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    if t == "insights":
        return "".join(
            f'<div class="ins {_e(i.get("tone", ""))}"><div class="ins-lbl">{_e(i.get("label"))}</div>'
            f'<div class="ins-title">{_e(i.get("title"))}</div><div class="ins-body">{_e(i.get("body"))}</div></div>'
            for i in b.get("items") or [])
    if t == "cards":
        return "".join(f'<div class="card"><h4>{_e(c.get("title"))}</h4><p>{_e(c.get("body"))}</p></div>'
                       for c in b.get("items") or [])
    if t == "note":
        return f'<p class="note">{_e(b.get("text"))}</p>'
    if t == "text":
        return f'<p class="txt">{_e(b.get("text"))}</p>'
    return ""


def page_html(p: dict) -> str:
    tag = f' <span class="tag gold">{_e(p["tag"])}</span>' if p.get("tag") else ""
    draft = f'<br><span class="draft">{DRAFT_LABEL}</span>' if p.get("draft", True) else ""
    head = (f'<div class="hdr"><div class="hdr-l"><div class="logo">PERTAMINA<span>LUBRICANTS</span></div><div>'
            f'<div class="kicker">{_e(p.get("kicker"))}</div><div class="hdr-title">{_e(p.get("title"))}{tag}</div>'
            f'<div class="hdr-sub">{_e(p.get("sub"))}</div></div></div>'
            f'<div class="hdr-r">{_e(p.get("right"))}{draft}</div></div>')
    body = "".join(_block_html(b) for b in p.get("blocks") or [])
    foot = (f'<div class="footer"><span>Sumber: {_e(p.get("source"))}</span>'
            f'<span>{COMPANY_FOOTER}</span></div>')
    return f'<section class="page">{head}{body}{foot}</section>'


def render_html(pages: list[dict], title: str, approved_label: str = "") -> bytes:
    return wrap("\n".join(page_html(p) for p in pages), title, approved_label).encode("utf-8")


# ==========================================================================
# Grafik statis (matplotlib) untuk PDF/PPTX — meniru tampilan grafik design system
# ==========================================================================
def _fmt(v: Any, unit: str = "") -> str:
    from .report_render import fmt_id

    if v is None:
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    a = abs(v)
    if a >= 1e6:
        t = f"{v / 1e6:.1f}".replace(".", ",") + "jt"
    elif a >= 1e4:
        t = f"{round(v / 1e3):.0f}rb"
    elif a >= 100:
        t = fmt_id(round(v))
    else:
        t = f"{round(v * 10) / 10:g}".replace(".", ",")
    return t + (unit or "")


def chart_png(spec: dict, width_pt: float, height_pt: float) -> bytes | None:
    """Gambar grafik design system sebagai PNG. None jika data kosong."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kind = spec.get("type")
    w_in, h_in = max(width_pt, 120) / 72, max(height_pt, 60) / 72
    fig, ax = plt.subplots(figsize=(w_in, h_in), dpi=200)
    plt.rcParams.update({"font.size": 6})
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(BORDER)
    ax.spines["bottom"].set_color(BORDER)
    ax.tick_params(colors=GRAY, labelsize=5.5, length=0)
    unit = spec.get("unit", "")
    try:
        ok = _draw(ax, kind, spec, unit)
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        plt.close(fig)
        return None
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _vals(xs):
    return [x for x in xs if x is not None]


def _draw(ax, kind: str, o: dict, unit: str) -> bool:  # noqa: C901
    import numpy as np

    labels = [str(x) for x in o.get("labels") or []]
    series = o.get("series") or []
    if kind == "bar":
        if not labels or not any(_vals(s.get("data") or []) for s in series):
            return False
        n = len(series)
        x = np.arange(len(labels))
        bw = min(0.8 / max(n, 1), 0.35)
        for j, s in enumerate(series):
            data = [v if v is not None else 0 for v in s.get("data") or []]
            pos = x - bw * n / 2 + bw * j + bw / 2
            bars = ax.bar(pos, data, bw * 0.9, color=s.get("color") or SERIES[j % 8], label=s.get("name"))
            for rect, v in zip(bars, s.get("data") or []):
                if v is not None:
                    ax.annotate(_fmt(v, unit), (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                                ha="center", va="bottom" if v >= 0 else "top", fontsize=5, color="#1F2937")
        ax.set_xticks(x, [l[:16] for l in labels])
        ax.axhline(0, color=GRAY2, lw=0.5)
        ax.yaxis.grid(True, color=BORDER, lw=0.5)
        ax.set_axisbelow(True)
        if n > 1:
            ax.legend(fontsize=5.5, frameon=False, loc="upper left", ncol=n, bbox_to_anchor=(0, 1.12))
        return True
    if kind == "hbar":
        if not labels or not any(_vals(s.get("data") or []) for s in series):
            return False
        y = np.arange(len(labels))[::-1]
        n = len(series)
        bh = min(0.8 / max(n, 1), 0.6)
        for j, s in enumerate(series):
            data = [v if v is not None else 0 for v in s.get("data") or []]
            pos = y + bh * n / 2 - bh * j - bh / 2
            ax.barh(pos, data, bh * 0.9, color=s.get("color") or SERIES[j % 8], label=s.get("name"))
            for p_, v in zip(pos, s.get("data") or []):
                if v is not None:
                    ax.annotate(" " + _fmt(v, unit) + " ", (v, p_), ha="left" if v >= 0 else "right", va="center",
                                fontsize=5, color="#1F2937")
        ax.set_yticks(y, [l[:34] for l in labels])
        ax.axvline(0, color=GRAY2, lw=0.5)
        ax.margins(x=0.15)
        if n > 1:
            ax.legend(fontsize=5.5, frameon=False, loc="lower right")
        return True
    if kind == "line":
        if not labels:
            return False
        x = np.arange(len(labels))
        drew = False
        for j, s in enumerate(series):
            data = s.get("data") or []
            pts = [(i, v) for i, v in enumerate(data) if v is not None]
            if not pts:
                continue
            drew = True
            col = s.get("color") or SERIES[j % 8]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, lw=1.2, marker="o", ms=2.5, label=s.get("name"))
            for i, v in pts:
                ax.annotate(_fmt(v, unit), (i, v), textcoords="offset points", xytext=(0, 3), ha="center",
                            fontsize=5, color=col)
        ax.set_xticks(x, labels)
        ax.yaxis.grid(True, color=BORDER, lw=0.5)
        ax.legend(fontsize=5.5, frameon=False, loc="upper left", ncol=max(len(series), 1), bbox_to_anchor=(0, 1.15))
        return drew
    if kind == "stack":
        if not labels or not series:
            return False
        y = np.arange(len(labels))[::-1]
        totals = [sum((s.get("data") or [0] * len(labels))[i] or 0 for s in series) or 1 for i in range(len(labels))]
        left = np.zeros(len(labels))
        for j, s in enumerate(series):
            data = [(v or 0) for v in s.get("data") or []]
            share = np.array([d / t * 100 for d, t in zip(data, totals)])
            ax.barh(y, share, 0.6, left=left, color=s.get("color") or SERIES[j % 8], label=s.get("name"))
            for yy, l_, sh, d in zip(y, left, share, data):
                if sh > 7:
                    ax.text(l_ + sh / 2, yy, _fmt(d, o.get("unit", "")), ha="center", va="center", fontsize=4.8,
                            color="white")
            left += share
        ax.set_yticks(y, [l[:30] for l in labels])
        ax.set_xlim(0, 100)
        ax.set_xticks([])
        ax.legend(fontsize=5, frameon=False, loc="upper left", ncol=min(len(series), 5), bbox_to_anchor=(0, 1.16))
        return True
    if kind == "dumbbell":
        a, b = o.get("from") or [], o.get("to") or []
        if not labels or not (_vals(a) or _vals(b)):
            return False
        y = np.arange(len(labels))[::-1]
        du = o.get("deltaUnit", unit)
        for yy, p, q in zip(y, a, b):
            if p is not None and q is not None:
                up = q >= p
                col = GREEN2 if up else RED2
                ax.plot([p, q], [yy, yy], color=col, lw=1.6, zorder=1)
                ax.annotate(("+" if up else "") + _fmt(q - p, du), (max(p, q), yy), textcoords="offset points",
                            xytext=(5, -2), fontsize=5, color=col, fontweight="bold")
            if p is not None:
                ax.scatter([p], [yy], s=10, color=GRAY2, zorder=2)
            if q is not None:
                ax.scatter([q], [yy], s=12, color=NAVY, zorder=3)
        ax.set_yticks(y, [l[:34] for l in labels])
        ax.xaxis.grid(True, color="#EEF2F7", lw=0.5)
        ax.scatter([], [], s=10, color=GRAY2, label=o.get("fromName", "Awal"))
        ax.scatter([], [], s=12, color=NAVY, label=o.get("toName", "Akhir"))
        ax.legend(fontsize=5.5, frameon=False, loc="upper left", ncol=2, bbox_to_anchor=(0, 1.14))
        ax.margins(x=0.18)
        return True
    if kind in ("matrix", "scatter"):
        pts = [p for p in o.get("points") or [] if p.get("x") is not None and p.get("y") is not None]
        if not pts:
            return False
        xs, ys = [float(p["x"]) for p in pts], [float(p["y"]) for p in pts]
        if kind == "matrix":
            xl = o.get("xLine", sorted(xs)[len(xs) // 2])
            yl = o.get("yLine", sorted(ys)[len(ys) // 2])
            pad_x, pad_y = (max(xs) - min(xs)) * 0.12 or 1, (max(ys) - min(ys)) * 0.15 or 0.1
            x0, x1 = min(min(xs), xl) - pad_x, max(max(xs), xl) + pad_x
            y0, y1 = min(min(ys), yl) - pad_y, max(max(ys), yl) + pad_y
            ax.add_patch(__import__("matplotlib").patches.Rectangle((xl, yl), x1 - xl, y1 - yl, color="#F0FDF4", zorder=0))
            ax.add_patch(__import__("matplotlib").patches.Rectangle((x0, y0), xl - x0, yl - y0, color="#FEF2F2", zorder=0))
            ax.axvline(xl, color=GRAY2, lw=0.6, ls="--")
            ax.axhline(yl, color=GRAY2, lw=0.6, ls="--")
            q = o.get("quadrants") or []
            if len(q) == 4:
                kw = dict(fontsize=5.5, fontweight="bold", color="#64748B")
                ax.text(x1, y1, q[0] + " ", ha="right", va="top", **kw)
                ax.text(x0, y1, " " + q[1], ha="left", va="top", **kw)
                ax.text(x0, y0, " " + q[2], ha="left", va="bottom", **kw)
                ax.text(x1, y0, q[3] + " ", ha="right", va="bottom", **kw)
            smax = max(float(p.get("size") or 1) for p in pts)
            for i, p in enumerate(pts):
                r = 4 + 10 * (float(p.get("size") or 1) / smax) ** 0.5
                ax.scatter([p["x"]], [p["y"]], s=r * r * 0.6, color=p.get("color") or SERIES[i % 8], alpha=0.75,
                           edgecolors="white", zorder=3)
                ax.annotate(str(p.get("label", ""))[:22], (p["x"], p["y"]), textcoords="offset points",
                            xytext=(0, r * 0.6 + 1), ha="center", fontsize=4.8)
            ax.set_xlim(x0, x1)
            ax.set_ylim(y0, y1)
        else:
            ax.scatter(xs, ys, s=10, color=NAVY, alpha=0.8)
            for p in pts:
                ax.annotate(str(p.get("label", ""))[:22], (p["x"], p["y"]), textcoords="offset points", xytext=(3, 2),
                            fontsize=4.8)
        ax.set_xlabel(o.get("xTitle", ""), fontsize=5.5, color=GRAY)
        ax.set_ylabel(o.get("yTitle", ""), fontsize=5.5, color=GRAY)
        return True
    return False


# ==========================================================================
# PDF (reportlab)
# ==========================================================================
def render_pdf(pages: list[dict], title: str, approved_label: str = "") -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Frame, KeepInFrame

    from .report_render import _register_fonts

    fonts = _register_fonts()
    W, H = landscape(A4)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(title)
    mx, my = 9 * mm, 7 * mm
    for p in pages:
        top = _pdf_header(c, p, W, H, mx, my, fonts, approved_label)
        _pdf_footer(c, p, W, mx, my, fonts)
        body_h = top - (my + 12)
        story = []
        for b in p.get("blocks") or []:
            story += _flow(b, W - 2 * mx, fonts)
        frame = Frame(mx, my + 12, W - 2 * mx, body_h, leftPadding=0, rightPadding=0, topPadding=2, bottomPadding=0)
        frame.addFromList([KeepInFrame(W - 2 * mx, body_h - 4, story, mode="shrink")], c)
        c.showPage()
    c.save()
    return buf.getvalue()


def _hex(col: str):
    from reportlab.lib import colors

    return colors.HexColor(col)


def _pdf_header(c, p, W, H, mx, my, fonts, approved_label) -> float:
    reg, bold, _ = fonts
    y = H - my
    c.setFillColor(_hex(NAVY))
    c.rect(mx, y - 22, 58, 20, stroke=0, fill=1)
    c.setFillColor(_hex("#FFFFFF"))
    c.setFont(bold, 8.5)
    c.drawString(mx + 5, y - 11, "PERTAMINA")
    c.setFont(reg, 4.2)
    c.drawString(mx + 5, y - 18, "LUBRICANTS")
    tx = mx + 66
    c.setFillColor(_hex(GOLD2))
    c.setFont(bold, 5.2)
    c.drawString(tx, y - 6, str(p.get("kicker", "")).upper())
    c.setFillColor(_hex(NAVY))
    c.setFont(bold, 10)
    title = str(p.get("title", ""))
    c.drawString(tx, y - 16, title[:110])
    if p.get("tag"):
        tw = c.stringWidth(title[:110], bold, 10)
        c.setFillColor(_hex(GOLD2))
        c.rect(tx + tw + 5, y - 17, c.stringWidth(p["tag"], bold, 4.6) + 7, 8, stroke=0, fill=1)
        c.setFillColor(_hex("#FFFFFF"))
        c.setFont(bold, 4.6)
        c.drawString(tx + tw + 8.5, y - 14.5, p["tag"])
    c.setFillColor(_hex(GOLD2))
    c.setFont(reg, 5.8)
    c.drawString(tx, y - 24, str(p.get("sub", ""))[:150])
    c.setFillColor(_hex(GRAY))
    c.setFont(reg, 5.2)
    c.drawRightString(W - mx, y - 10, str(p.get("right", "")))
    if p.get("draft", True):
        c.setFillColor(_hex(GREEN2 if approved_label else RED2))
        c.setFont(bold, 5.2)
        c.drawRightString(W - mx, y - 18, approved_label or DRAFT_LABEL)
    c.setStrokeColor(_hex(NAVY))
    c.setLineWidth(1.5)
    c.line(mx, y - 28, W - mx, y - 28)
    return y - 31


def _pdf_footer(c, p, W, mx, my, fonts):
    reg = fonts[0]
    c.setStrokeColor(_hex("#CBD5E1"))
    c.setLineWidth(0.6)
    c.line(mx, my + 9, W - mx, my + 9)
    c.setFillColor(_hex(GRAY))
    c.setFont(reg, 4.8)
    c.drawString(mx, my + 3, f"Sumber: {p.get('source', '')}"[:160])
    c.drawRightString(W - mx, my + 3, COMPANY_FOOTER)


def _para(text, font, size, color=TEXT3, leading=None, align=0):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    st = ParagraphStyle("p", fontName=font, fontSize=size, leading=leading or size * 1.3, textColor=_hex(color),
                        alignment=align)
    return Paragraph(_html.escape("" if text is None else str(text)), st)


def _flow(b: dict, width: float, fonts) -> list:  # noqa: C901
    from reportlab.platypus import Image, Spacer, Table, TableStyle

    reg, bold, ital = fonts
    t = b.get("type")
    if t == "sec":
        text = str(b.get("title", "")).upper() + (f"  · {b['acc']}" if b.get("acc") else "")
        tb = Table([[_para(text, bold, 6.8, NAVY2)]], colWidths=[width])
        tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.1, _hex(NAVY2)), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
        return [tb, Spacer(1, 3)]
    if t == "sub":
        return [_para(b.get("title"), bold, 6.4, NAVY), Spacer(1, 1)]
    if t == "kpis":
        items = b.get("items") or []
        if not items:
            return []
        cw = (width - 4 * (len(items) - 1)) / len(items)
        cells = []
        for k in items:
            cell = [_para(str(k.get("label", "")).upper(), bold, 4.9, GRAY), _para(k.get("value"), bold, 11.5, NAVY, 13)]
            if k.get("mono"):
                cell.append(_para(k["mono"], bold, 5.3, GOLD2))
            if k.get("desc"):
                cell.append(_para(k["desc"], reg, 5.4, TEXT3))
            badge = k.get("badge") or {}
            if badge.get("text"):
                bg, fg = BADGE.get(badge.get("tone", "b-n"), BADGE["b-n"])
                bt = Table([[_para(badge["text"], bold, 4.8, fg)]])
                bt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _hex(bg)), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                                        ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
                bt.hAlign = "LEFT"
                cell.append(bt)
            cells.append(cell)
        row, widths = [], []
        for i, cell in enumerate(cells):
            row.append(cell)
            widths.append(cw)
            if i < len(cells) - 1:
                row.append("")
                widths.append(4)
        tb = Table([row], colWidths=widths)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        for i, k in enumerate(items):
            col = i * 2
            style += [("BOX", (col, 0), (col, 0), 0.6, _hex(BORDER)),
                      ("LINEABOVE", (col, 0), (col, 0), 2.2, _hex(KPI_TOP.get(k.get("tone", ""), NAVY2)))]
        tb.setStyle(TableStyle(style))
        return [tb, Spacer(1, 4)]
    if t == "grid":
        ratios = GRID_RATIO.get(b.get("cols", "g2"), [1, 1])
        children = b.get("children") or []
        gap = 5
        total = width - gap * (len(children) - 1)
        widths, row = [], []
        for i, col in enumerate(children):
            w = total * ratios[i % len(ratios)] / sum(ratios[:len(children)])
            flows = []
            for x in col:
                flows += _flow(x, w, fonts)
            row.append(flows)
            widths.append(w)
            if i < len(children) - 1:
                row.append("")
                widths.append(gap)
        tb = Table([row], colWidths=widths)
        tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return [tb, Spacer(1, 3)]
    if t == "chart":
        h = CHART_PT.get(b.get("size", ""), CHART_PT[""])
        png = chart_png(b.get("spec") or {}, width, h)
        if not png:
            return [_para("Data belum tersedia", ital, 5.5, GRAY), Spacer(1, 3)]
        img = Image(io.BytesIO(png), width=width, height=h)
        frame = Table([[img]], colWidths=[width])
        frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, _hex(BORDER)), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return [frame, Spacer(1, 3)]
    if t == "table":
        cols = b.get("columns") or []
        if not cols:
            return []
        data = [[_para(str(c).upper(), bold, 4.8, GRAY, align=0 if i == 0 else 2) for i, c in enumerate(cols)]]
        style = [("BACKGROUND", (0, 0), (-1, 0), _hex(BG3)), ("LINEBELOW", (0, 0), (-1, 0), 0.9, _hex("#CBD5E1")),
                 ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
                 ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        for ri, r in enumerate(b.get("rows") or [], start=1):
            r = r if isinstance(r, dict) else {"cells": r}
            if r.get("cls") == "seg":
                data.append([_para(str(_cell(r["cells"][0]).get("t", "")).upper(), bold, 5, "#FFFFFF")] + [""] * (len(cols) - 1))
                style += [("SPAN", (0, ri), (-1, ri)), ("BACKGROUND", (0, ri), (-1, ri), _hex(NAVY))]
                continue
            row = []
            for ci, c in enumerate(r.get("cells") or []):
                c = _cell(c)
                cls = c.get("cls", "")
                fg = CELL_FG.get(cls, "#0F172A" if cls == "nm" or ci == 0 else TEXT3)
                font = bold if cls in ("nm", "up", "dn", "pos", "neg") or ci == 0 else reg
                text = ("● " if c.get("dot") else "") + ("" if c.get("t") is None else str(c.get("t")))
                row.append(_para(text, font, 5.3, DOT.get(c.get("dot"), fg) if c.get("dot") else fg,
                                 align=0 if ci == 0 else 2))
                if cls in CELL_BG:
                    style.append(("BACKGROUND", (ci, ri), (ci, ri), _hex(CELL_BG[cls])))
            data.append(row + [""] * (len(cols) - len(row)))
            if r.get("cls") in ("hl", "ptpl"):
                style.append(("BACKGROUND", (0, ri), (-1, ri), _hex(ROW_BG[r["cls"]])))
            style.append(("LINEBELOW", (0, ri), (-1, ri), 0.5, _hex(BORDER)))
        weights = b.get("widths") or [2.2 if i == 0 else 1 for i in range(len(cols))]
        tw = sum(weights)
        tb = Table(data, colWidths=[width * w / tw for w in weights], repeatRows=1)
        tb.setStyle(TableStyle(style))
        return [tb, Spacer(1, 4)]
    if t in ("insights", "cards"):
        out = []
        for i in b.get("items") or []:
            if t == "cards":
                left, bg = GOLD2, "#FFFFFF"
                inner = [_para(i.get("title"), bold, 6.3, NAVY), _para(i.get("body"), reg, 5.6, TEXT3)]
            else:
                left, bg = INS_LEFT.get(i.get("tone", ""), INS_LEFT[""])
                inner = [_para(str(i.get("label", "")).upper(), bold, 4.8, GRAY), _para(i.get("title"), bold, 6.3, NAVY),
                         _para(i.get("body"), reg, 5.6, TEXT3)]
            tb = Table([[inner]], colWidths=[width])
            tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _hex(bg)), ("BOX", (0, 0), (-1, -1), 0.5, _hex(BORDER)),
                                    ("LINEBEFORE", (0, 0), (0, -1), 2.6, _hex(left)),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            out += [tb, Spacer(1, 3)]
        return out
    if t == "note":
        return [_para(b.get("text"), ital, 4.9, GRAY), Spacer(1, 2)]
    if t == "text":
        return [_para(b.get("text"), reg, 6.1, TEXT3), Spacer(1, 2)]
    return []


# ==========================================================================
# PPTX (python-pptx) — satu slide per halaman, ukuran A4 landscape
# ==========================================================================
def render_pptx(pages: list[dict], title: str, approved_label: str = "") -> bytes:
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Pt(841.89), Pt(595.28)
    blank = prs.slide_layouts[6]
    for p in pages:
        s = prs.slides.add_slide(blank)
        mx, my = 25.5, 20.0
        y = _pptx_header(s, p, 841.89, mx, my, approved_label)
        _pptx_footer(s, p, 841.89, 595.28, mx, my)
        for b in p.get("blocks") or []:
            y += _place(s, b, mx, y, 841.89 - 2 * mx)
    prs.core_properties.title = title
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _rgb(col: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(col.lstrip("#").upper())


def _box(s, x, y, w, h, fill=None, line=None, lw=0.6):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Pt

    shp = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(x), Pt(y), Pt(w), Pt(h))
    shp.shadow.inherit = False
    if fill:
        shp.fill.solid()
        shp.fill.fore_color.rgb = _rgb(fill)
    else:
        shp.fill.background()
    if line:
        shp.line.color.rgb = _rgb(line)
        shp.line.width = Pt(lw)
    else:
        shp.line.fill.background()
    return shp


def _text(s, x, y, w, h, runs, size=7, color=TEXT3, bold=False, align="l", italic=False):
    """runs: str atau list baris (str atau (teks, size, color, bold))."""
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt

    tb = s.shapes.add_textbox(Pt(x), Pt(y), Pt(w), Pt(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, side, 0)
    lines = runs if isinstance(runs, list) else [runs]
    for i, ln in enumerate(lines):
        par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        par.alignment = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT, "c": PP_ALIGN.CENTER}[align]
        txt, sz, col, bd = (ln, size, color, bold) if isinstance(ln, str) else ln
        r = par.add_run()
        r.text = "" if txt is None else str(txt)
        r.font.size = Pt(sz)
        r.font.bold = bd
        r.font.italic = italic
        r.font.name = "Arial"
        r.font.color.rgb = _rgb(col)
    return tb


def _pptx_header(s, p, W, mx, my, approved_label) -> float:
    _box(s, mx, my, 58, 20, fill=NAVY)
    _text(s, mx + 5, my + 3, 52, 16, [("PERTAMINA", 8.5, "#FFFFFF", True), ("LUBRICANTS", 4.2, "#FFFFFF", False)])
    tx = mx + 66
    _text(s, tx, my - 1, 560, 30, [(str(p.get("kicker", "")).upper(), 5.2, GOLD2, True),
                                   (str(p.get("title", "")) + (f"   [{p['tag']}]" if p.get("tag") else ""), 10, NAVY, True),
                                   (p.get("sub", ""), 5.8, GOLD2, False)])
    lines = [(p.get("right", ""), 5.2, GRAY, False)]
    if p.get("draft", True):
        lines.append((approved_label or DRAFT_LABEL, 5.2, GREEN2 if approved_label else RED2, True))
    _text(s, W - mx - 200, my + 2, 200, 22, lines, align="r")
    _box(s, mx, my + 28, W - 2 * mx, 1.4, fill=NAVY)
    return my + 34


def _pptx_footer(s, p, W, H, mx, my):
    _box(s, mx, H - my - 10, W - 2 * mx, 0.6, fill="#CBD5E1")
    _text(s, mx, H - my - 8, 500, 8, f"Sumber: {p.get('source', '')}", size=4.8, color=GRAY)
    _text(s, W - mx - 250, H - my - 8, 250, 8, COMPANY_FOOTER, size=4.8, color=GRAY, align="r")


def _place(s, b: dict, x: float, y: float, w: float) -> float:  # noqa: C901
    """Tempatkan blok di slide; kembalikan tinggi yang dipakai (pt)."""
    t = b.get("type")
    if t == "sec":
        text = str(b.get("title", "")).upper() + (f"  · {b['acc']}" if b.get("acc") else "")
        _text(s, x, y, w, 9, text, size=6.8, color=NAVY2, bold=True)
        _box(s, x, y + 10, w, 1, fill=NAVY2)
        return 15
    if t == "sub":
        _text(s, x, y, w, 9, b.get("title"), size=6.4, color=NAVY, bold=True)
        return 11
    if t == "kpis":
        items = b.get("items") or []
        if not items:
            return 0
        cw = (w - 4 * (len(items) - 1)) / len(items)
        h = 58
        for i, k in enumerate(items):
            cx = x + i * (cw + 4)
            _box(s, cx, y, cw, h, fill="#FFFFFF", line=BORDER)
            _box(s, cx, y, cw, 2.4, fill=KPI_TOP.get(k.get("tone", ""), NAVY2))
            lines = [(str(k.get("label", "")).upper(), 4.9, GRAY, True), (k.get("value"), 11.5, NAVY, True)]
            if k.get("mono"):
                lines.append((k["mono"], 5.3, GOLD2, True))
            if k.get("desc"):
                lines.append((k["desc"], 5.4, TEXT3, False))
            badge = k.get("badge") or {}
            if badge.get("text"):
                lines.append((badge["text"], 4.8, BADGE.get(badge.get("tone", "b-n"), BADGE["b-n"])[1], True))
            _text(s, cx + 5, y + 5, cw - 9, h - 7, lines)
        return h + 5
    if t == "grid":
        ratios = GRID_RATIO.get(b.get("cols", "g2"), [1, 1])
        children = b.get("children") or []
        gap = 5
        total = w - gap * (len(children) - 1)
        cx, hmax = x, 0
        for i, col in enumerate(children):
            cwid = total * ratios[i % len(ratios)] / sum(ratios[:len(children)])
            cy = y
            for child in col:
                cy += _place(s, child, cx, cy, cwid)
            hmax = max(hmax, cy - y)
            cx += cwid + gap
        return hmax + 2
    if t == "chart":
        from pptx.util import Pt

        h = CHART_PT.get(b.get("size", ""), CHART_PT[""])
        png = chart_png(b.get("spec") or {}, w, h)
        _box(s, x, y, w, h, fill="#FFFFFF", line=BORDER)
        if png:
            s.shapes.add_picture(io.BytesIO(png), Pt(x), Pt(y), Pt(w), Pt(h))
        else:
            _text(s, x + 4, y + 4, w - 8, 10, "Data belum tersedia", size=5.5, color=GRAY, italic=True)
        return h + 4
    if t == "table":
        return _pptx_table(s, b, x, y, w)
    if t in ("insights", "cards"):
        used = 0
        for i in b.get("items") or []:
            body = str(i.get("body", ""))
            lines_est = max(1, int(len(body) * 3.0 / max(w - 10, 40)) + 1)
            h = 22 + lines_est * 7.2
            if t == "cards":
                left, bg = GOLD2, "#FFFFFF"
                lines = [(i.get("title"), 6.3, NAVY, True), (body, 5.6, TEXT3, False)]
            else:
                left, bg = INS_LEFT.get(i.get("tone", ""), INS_LEFT[""])
                lines = [(str(i.get("label", "")).upper(), 4.8, GRAY, True), (i.get("title"), 6.3, NAVY, True),
                         (body, 5.6, TEXT3, False)]
            _box(s, x, y + used, w, h, fill=bg, line=BORDER, lw=0.5)
            _box(s, x, y + used, 2.6, h, fill=left)
            _text(s, x + 6, y + used + 3, w - 10, h - 4, lines)
            used += h + 3
        return used
    if t == "note":
        _text(s, x, y, w, 8, b.get("text"), size=4.9, color=GRAY, italic=True)
        return 10
    if t == "text":
        _text(s, x, y, w, 10, b.get("text"), size=6.1)
        return 12
    return 0


def _pptx_table(s, b: dict, x: float, y: float, w: float) -> float:
    from pptx.util import Pt

    cols = b.get("columns") or []
    rows = [r if isinstance(r, dict) else {"cells": r} for r in b.get("rows") or []]
    if not cols:
        return 0
    rh = 10.5
    shape = s.shapes.add_table(len(rows) + 1, len(cols), Pt(x), Pt(y), Pt(w), Pt(rh * (len(rows) + 1)))
    tbl = shape.table
    weights = b.get("widths") or [2.2 if i == 0 else 1 for i in range(len(cols))]
    tw = sum(weights)
    for i, wt in enumerate(weights):
        tbl.columns[i].width = Pt(w * wt / tw)

    def fill(cell, text, size, color, bold, bg, align="r"):
        from pptx.enum.text import PP_ALIGN

        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        for side in ("margin_left", "margin_right"):
            setattr(cell, side, Pt(2.5))
        cell.margin_top = cell.margin_bottom = Pt(1)
        tf = cell.text_frame
        tf.word_wrap = True
        par = tf.paragraphs[0]
        par.alignment = PP_ALIGN.LEFT if align == "l" else PP_ALIGN.RIGHT
        r = par.add_run()
        r.text = "" if text is None else str(text)
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = "Arial"
        r.font.color.rgb = _rgb(color)

    for ci, c in enumerate(cols):
        fill(tbl.cell(0, ci), str(c).upper(), 4.8, GRAY, True, BG3, "l" if ci == 0 else "r")
    for ri, r in enumerate(rows, start=1):
        tbl.rows[ri].height = Pt(rh)
        if r.get("cls") == "seg":
            first = tbl.cell(ri, 0)
            first.merge(tbl.cell(ri, len(cols) - 1))
            fill(first, str(_cell(r["cells"][0]).get("t", "")).upper(), 5, "#FFFFFF", True, NAVY, "l")
            continue
        row_bg = ROW_BG.get(r.get("cls", ""), "#FFFFFF")
        cells = list(r.get("cells") or []) + [""] * (len(cols) - len(r.get("cells") or []))
        for ci, c in enumerate(cells[:len(cols)]):
            c = _cell(c)
            cls = c.get("cls", "")
            fg = DOT.get(c.get("dot")) if c.get("dot") else CELL_FG.get(cls, "#0F172A" if cls == "nm" or ci == 0 else TEXT3)
            text = ("● " if c.get("dot") else "") + ("" if c.get("t") is None else str(c.get("t")))
            fill(tbl.cell(ri, ci), text, 5.3, fg, cls in ("nm", "up", "dn", "pos", "neg") or ci == 0,
                 CELL_BG.get(cls, row_bg), "l" if ci == 0 else "r")
    tbl.rows[0].height = Pt(rh + 1)
    return rh * (len(rows) + 1) + 6
