"""Komponen slide laporan otomatis. Setiap komponen menggambar isi (area badan slide) dari dict storyboard.

Prinsip: angka hanya dari dict (hasil analitik / dihitung kode), tata letak & warna diatur di sini.
Komponen yang gagal TIDAK menjatuhkan laporan: build.py menggantinya dengan `poin` berisi semua teksnya.
Tabel/daftar yang tidak muat berlanjut ke slide lanjutan (bukan dipotong).
"""
from __future__ import annotations

from typing import Any, Callable

from . import charts as CH
from . import theme as T
from .prims import Chart, Image, Line, Rect, Slide, Table, Text, para, run

X0, Y0, BW, BH = T.MX, T.BODY_Y, T.BODY_W, T.BODY_H
GAP = 0.3


class Ctx:
    def __init__(self, style: str = "id"):
        self.style = style
        self.appendix: list[dict] = []        # data lengkap chart yang dipotong
        self.cont: list[dict] = []            # slide lanjutan (sisa baris tabel / poin)


# ---------------------------------------------------------------- utilitas
def s_(v: Any) -> str:
    return "" if v is None else str(v)


def lst(v: Any) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return default


def cols(n: int, x: float = X0, w: float = BW, gap: float = GAP) -> list[tuple[float, float]]:
    n = max(n, 1)
    cw = (w - gap * (n - 1)) / n
    return [(x + i * (cw + gap), cw) for i in range(n)]


def txt(x, y, w, h, content, size=T.SZ_BODY, min_size=T.SZ_BODY_MIN, color=T.TEXT, bold=False, align="l",
        valign="t", fill=None) -> Text:
    if isinstance(content, list) and content and isinstance(content[0], dict) and "runs" in content[0]:
        paras = content
    else:
        paras = [para([run(content, bold, color)], align)]
    return Text(x, y, w, h, paras, size=size, min_size=min_size, valign=valign, fill=fill)


def item_runs(it: Any, color=T.TEXT) -> list[dict]:
    """'teks' atau {'judul','teks'} -> run (judul tebal)."""
    if isinstance(it, dict):
        head = s_(first(it, "judul", "label", "nama", "title", default=""))
        body = s_(first(it, "teks", "isi", "text", "desc", default=""))
        num = s_(first(it, "angka", "nilai", default=""))
        rs = []
        if head:
            rs.append(run(head + (": " if body or num else ""), True, color))
        if num:
            rs.append(run(num + (" — " if body else ""), True, T.NAVY))
        if body:
            rs.append(run(body, False, color))
        return rs or [run("")]
    return [run(s_(it), False, color)]


def bullets(items: list, color=T.TEXT, after=0.35) -> list[dict]:
    return [para(item_runs(it, color), bullet=True, after=after) for it in items] or [para("")]


def card(slide: Slide, x, y, w, h, fill=T.WHITE, line=T.GRID):
    slide.add(Rect(x, y, w, h, fill=fill, line=line, radius=True))


def chart_box(slide: Slide, ctx: Ctx, x, y, w, h, raw: dict, kind: str, title: str = "") -> None:
    spec, issues, full = CH.normalize(raw, kind, ctx.style)
    slide.issues += issues
    if full:
        ctx.appendix.append({"judul": title or slide.title, "data": full, "unit": spec.get("unit", "")})
    slide.add(Chart(x, y, w, h, spec))


def panels_of(d: dict, keys=("panel", "panels", "grafik", "charts")) -> list[dict]:
    p = first(d, *keys)
    if isinstance(p, dict):
        return [p]
    if p:
        return [x for x in p if isinstance(x, dict)][:3]
    return [d]                                   # satu panel langsung di level slide


def panel_title(slide: Slide, x, y, w, text, size=12.5) -> float:
    if not text:
        return 0.0
    slide.add(txt(x, y, w, 0.42, text, size=size, min_size=10, color=T.NAVY, bold=True))
    return 0.45


def insight_box(slide: Slide, x, y, w, h, content, tone_name="") -> None:
    fg, bg = T.tone(tone_name)
    slide.add(Rect(x, y, w, h, fill=bg, line=None, radius=True))
    rs = item_runs(content, T.TEXT) if isinstance(content, dict) else [run(s_(content), False, T.TEXT)]
    slide.add(Text(x + 0.08, y + 0.04, w - 0.16, h - 0.08, [para(rs)], size=11, min_size=8.5, valign="m"))


# ---------------------------------------------------------------- komponen sampul & pemisah
def c_judul(slide: Slide, d: dict, ctx: Ctx) -> None:
    slide.dark = True
    slide.add(Rect(0, 0, T.W, T.H, fill=T.NAVY, line=None))
    slide.add(Rect(0, T.H - 1.55, T.W, 1.55, fill=T.NAVY2, line=None))
    kicker = s_(first(d, "kicker", "bagian", default="PT PERTAMINA LUBRICANTS")).upper()
    slide.add(txt(0.8, 0.75, 9, 0.4, kicker, size=12, min_size=10, color=T.GOLD2, bold=True))
    slide.add(txt(0.8, 1.2, 10.4, 2.3, s_(first(d, "judul", default="")), size=38, min_size=24, color=T.WHITE,
                  bold=True, valign="b"))
    sub = s_(first(d, "subjudul", "sub", default=""))
    if sub:
        slide.add(txt(0.8, 3.6, 10.4, 1.0, sub, size=16, min_size=11, color="D6DEEB"))
    chips = lst(first(d, "kartu", "segmen", "merek", default=[]))[:4]
    for (x, w), ch in zip(cols(len(chips), 0.8, min(11.7, 2.9 * len(chips)), 0.25), chips):
        slide.add(Rect(x, T.H - 1.3, w, 0.95, fill=T.NAVY3, line=None, radius=True))
        if isinstance(ch, dict):
            head, sub2 = s_(first(ch, "nama", "label", "judul", default="")), s_(first(ch, "sub", "teks", default=""))
        else:
            head, sub2 = s_(ch), ""
        slide.add(Text(x + 0.15, T.H - 1.25, w - 0.3, 0.85,
                       [para([run(head, True, T.WHITE)]), para([run(sub2, False, "C9D3E3", 0.8)])],
                       size=15, min_size=10, valign="m"))
    meta = s_(first(d, "meta", "tanggal", "sumber", default=""))
    if meta:
        slide.add(txt(0.8, T.H - 0.3, 11, 0.26, meta, size=9, min_size=8, color="AFC0D8"))


def c_pemisah(slide: Slide, d: dict, ctx: Ctx) -> None:
    slide.dark = True
    slide.add(Rect(0, 0, T.W, T.H, fill=T.NAVY, line=None))
    num = s_(first(d, "nomor", "no", default=""))
    if num:
        slide.add(txt(0.9, 2.0, 2.2, 1.4, num, size=66, min_size=40, color=T.GOLD2, bold=True, valign="b"))
    slide.add(txt(0.9 + (2.2 if num else 0), 2.1, 9.5, 1.4, s_(first(d, "judul", default="")), size=34,
                  min_size=22, color=T.WHITE, bold=True, valign="b"))
    teks = first(d, "teks", "subjudul", default="")
    if teks:
        slide.add(txt(0.9 + (2.2 if num else 0), 3.65, 9.5, 1.6, s_(teks), size=15, min_size=11, color="C9D3E3"))


# ---------------------------------------------------------------- komponen teks berstruktur
def c_ringkasan(slide: Slide, d: dict, ctx: Ctx) -> None:
    kol = [k for k in lst(first(d, "kolom", "merek", "segmen", default=[])) if isinstance(k, dict)][:4]
    thread = s_(first(d, "benang_merah", "kesimpulan", "takeaway", default=""))
    if not kol:
        return c_poin(slide, d, ctx)
    bottom = Y0 + BH - (0.85 if thread else 0)
    for (x, w), k in zip(cols(len(kol)), kol):
        card(slide, x, Y0, w, bottom - Y0 - 0.12)
        slide.add(Rect(x, Y0, w, 0.72, fill=T.NAVY, line=None, radius=True))
        slide.add(Text(x + 0.12, Y0 + 0.04, w - 0.24, 0.64,
                       [para([run(s_(first(k, "nama", "judul", default="")), True, T.WHITE)]),
                        para([run(s_(first(k, "sub", default="")), False, "C9D3E3", 0.78)])],
                       size=14, min_size=10, valign="m"))
        rows = [r for r in lst(first(k, "baris", "poin", default=[]))]
        n = max(len(rows), 1)
        rh = (bottom - Y0 - 0.12 - 0.85) / n
        for i, r in enumerate(rows):
            ry = Y0 + 0.82 + i * rh
            if isinstance(r, dict):
                lab = s_(first(r, "label", "judul", default="")).upper()
                body = s_(first(r, "teks", "isi", default=""))
                fg, _ = T.tone(r.get("tone") or r.get("nada"))
            else:
                lab, body, fg = "", s_(r), T.NAVY2
            paras = ([para([run(lab, True, T.GOLD2, 0.78)], after=0.1)] if lab else []) + [para([run(body)])]
            slide.add(Text(x + 0.12, ry, w - 0.24, rh - 0.06, paras, size=12, min_size=8.5))
            if i < n - 1:
                slide.add(Line(x + 0.12, ry + rh - 0.02, x + w - 0.12, ry + rh - 0.02, T.GRID, 0.75))
    if thread:
        slide.add(Rect(X0, Y0 + BH - 0.75, BW, 0.75, fill=T.GOLD_BG, line=None, radius=True))
        slide.add(Text(X0 + 0.15, Y0 + BH - 0.72, BW - 0.3, 0.69,
                       [para([run("Benang merah: ", True, T.GOLD), run(thread)])], size=12.5, min_size=9,
                       valign="m"))


def c_kartu(slide: Slide, d: dict, ctx: Ctx) -> None:
    items = [k for k in lst(first(d, "kartu", "angka", "kpi", default=[])) if k is not None][:8]
    extra = lst(first(d, "poin", default=[]))
    from .prims import layout_text

    per_row = 4 if len(items) in (4, 7, 8) else min(3, max(len(items), 1))
    nrows = (len(items) + per_row - 1) // per_row or 1
    area_h = BH - (1.45 if extra else 0)
    max_ch = (area_h - GAP * (nrows - 1)) / nrows
    cw = cols(per_row)[0][1]
    built = []
    for k in items:
        k = k if isinstance(k, dict) else {"angka": k}
        lab = s_(first(k, "label", "judul", default=""))
        delta = s_(first(k, "delta", "perubahan", default=""))
        fg, _ = T.tone(k.get("tone") or k.get("nada"))
        paras = [para([run(lab, True, T.NAVY)] + ([run("  " + delta, True, fg, 0.85)] if delta else []), after=0.3)]
        teks = s_(first(k, "teks", "keterangan", default=""))
        if teks:
            paras.append(para([run(teks, False, T.TEXT2)]))
        built.append((k, paras, layout_text(paras, cw - 0.5, 99, 13)[1]))
    need = max([b[2] for b in built] or [1.0]) + 1.25
    ch = max(min(max_ch, need + 0.35), min(max_ch, 2.3))
    total = nrows * ch + GAP * (nrows - 1)
    top = Y0 + (0 if extra else max(0.0, (area_h - total) / 2))
    for r in range(nrows):
        row = built[r * per_row:(r + 1) * per_row]
        for (x, w), (k, paras, _) in zip(cols(len(row)), row):
            y = top + r * (ch + GAP)
            fg, bg = T.tone(k.get("tone") or k.get("nada"))
            card(slide, x, y, w, ch, fill=bg, line=None)
            big = s_(first(k, "angka", "nilai", default=""))
            if T.is_num(k.get("angka", k.get("nilai"))):
                big = T.fmt(k.get("angka", k.get("nilai")), None, s_(k.get("satuan", "")), ctx.style)
            slide.add(txt(x + 0.25, y + 0.2, w - 0.5, 0.95, big, size=40, min_size=20, color=fg, bold=True,
                          valign="b"))
            ty = y + 1.25
            slide.add(Text(x + 0.25, ty, w - 0.5, y + ch - ty - 0.15, paras, size=13, min_size=8.5))
    if extra:
        slide.add(Text(X0, Y0 + BH - 1.3, BW, 1.3, bullets(extra), size=13, min_size=9))


def c_poin(slide: Slide, d: dict, ctx: Ctx) -> None:
    items = lst(first(d, "poin", "insight", "isi", "teks", default=[]))
    chart = first(d, "chart", "grafik_utama")
    img = d.get("_png")
    has_side = bool(chart) or bool(img)
    tw = BW * 0.42 if has_side else BW
    if items:
        t = Text(X0, Y0, tw, BH, bullets(items), size=14, min_size=10.5)
        t.fit()
        if t.overflow and len(items) > 2:                      # lanjut ke slide berikut, bukan dipotong
            half = max(1, len(items) // 2)
            t = Text(X0, Y0, tw, BH, bullets(items[:half]), size=14, min_size=10.5)
            ctx.cont.append({**{k: v for k, v in d.items() if k not in ("chart", "_png")}, "poin": items[half:],
                             "komponen": "poin", "_lanjutan": True})
        slide.add(t)
    if chart and isinstance(chart, dict):
        x = X0 + tw + GAP
        chart_box(slide, ctx, x, Y0, BW - tw - GAP, BH, chart, "column")
    elif img:
        x = X0 + tw + GAP
        slide.add(Image(x, Y0, BW - tw - GAP, BH, img, s_(d.get("judul"))))


def c_benang_merah(slide: Slide, d: dict, ctx: Ctx) -> None:
    teks = s_(first(d, "teks", "pernyataan", "benang_merah", default=""))
    items = [p for p in lst(first(d, "poin", "bukti", default=[]))][:4]
    slide.add(Rect(X0, Y0, BW, 1.45, fill=T.NAVY, line=None, radius=True))
    slide.add(txt(X0 + 0.3, Y0 + 0.1, BW - 0.6, 1.25, teks, size=20, min_size=13, color=T.WHITE, bold=True,
                  valign="m"))
    if items:
        y = Y0 + 1.75
        for (x, w), it in zip(cols(len(items)), items):
            card(slide, x, y, w, BH - 1.75)
            it = it if isinstance(it, dict) else {"teks": it}
            big = s_(first(it, "angka", "nilai", default=""))
            off = 0.15
            if big:
                slide.add(txt(x + 0.2, y + 0.15, w - 0.4, 0.8, big, size=30, min_size=16, color=T.GOLD2, bold=True,
                              valign="b"))
                off = 1.0
            paras = []
            if first(it, "judul", "label"):
                paras.append(para([run(s_(first(it, "judul", "label")), True, T.NAVY)], after=0.2))
            paras.append(para([run(s_(first(it, "teks", "isi", default="")), False, T.TEXT2)]))
            slide.add(Text(x + 0.2, y + off, w - 0.4, BH - 1.75 - off - 0.12, paras, size=12.5, min_size=8.5))


# ---------------------------------------------------------------- komponen chart
def _chart_panels(slide: Slide, d: dict, ctx: Ctx, kind: str, value_keys: tuple) -> None:
    ps = panels_of(d)
    n = len(ps)
    for (x, w), p in zip(cols(n), ps):
        y = Y0
        y += panel_title(slide, x, y, w, s_(first(p, "judul_panel", "nama_panel", "subjudul", default="")
                                            if p is not d else first(p, "judul_panel", default="")))
        ins = first(p, "insight", "catatan_panel", "badge", "keterangan")
        ins_h = 0.85 if ins else 0
        raw = {"kind": first(p, "kind", "jenis_chart", default=kind)}
        for k in ("kategori", "categories", "labels", "seri", "series", "nilai", "values", "langkah", "steps", "sorot",
                  "sorot2", "satuan", "unit", "dec", "urut", "legend", "total_pertama", "total_terakhir"):
            if k in p:
                raw[k] = p[k]
        if not any(k in raw for k in value_keys):
            raise ValueError("panel tanpa data")
        chart_box(slide, ctx, x, y, w, Y0 + BH - y - ins_h - (0.1 if ins else 0), raw, kind,
                  s_(first(p, "judul_panel", "subjudul", default="")))
        if ins:
            insight_box(slide, x, Y0 + BH - ins_h, w, ins_h, ins, p.get("tone") or p.get("nada") or "")


def c_papan_skor(slide, d, ctx):
    _chart_panels(slide, d, ctx, "barh", ("nilai", "values", "seri", "series"))


def c_perbandingan(slide, d, ctx):
    _chart_panels(slide, d, ctx, "column", ("nilai", "values", "seri", "series"))


def c_tren(slide, d, ctx):
    _chart_panels(slide, d, ctx, "line", ("nilai", "values", "seri", "series"))


def c_waterfall(slide, d, ctx):
    _chart_panels(slide, d, ctx, "waterfall", ("langkah", "steps", "nilai", "values"))


def c_funnel(slide: Slide, d: dict, ctx: Ctx) -> None:
    ps = panels_of(d)
    for (x, w), p in zip(cols(len(ps)), ps):
        stages = [s_(t) for t in lst(first(p, "tahap", "stages", "kategori", default=[]))]
        series = [s for s in lst(first(p, "seri", "series", default=[])) if isinstance(s, dict)][:2]
        if not stages or not series:
            raise ValueError("funnel tanpa tahap/seri")
        y = Y0
        y += panel_title(slide, x, y, w, s_(first(p, "judul_panel", "subjudul", default="")))
        ins = first(p, "insight", "keterangan")
        bottom = Y0 + BH - (0.95 if ins else 0)
        lab_w = min(1.05, w * 0.27)
        val_w = 0.95
        k = len(series)
        vals = [[T.to_num(v) for v in lst(first(s, "nilai", "values", default=[]))] for s in series]
        deltas = [[T.to_num(v) for v in lst(first(s, "delta", default=[]))] for s in series]
        convs = [lst(first(s, "konversi", default=[])) for s in series]
        vmax = max([v for vs in vals for v in vs if v is not None] or [1])
        unit = s_(first(p, "satuan", "unit", default=""))
        colors = [T.NAVY, T.COMP]
        lx = x + lab_w                                                   # legenda seri
        for j, s in enumerate(series):
            slide.add(Rect(lx, y + 0.1, 0.16, 0.16, fill=colors[j], line=None))
            nm = s_(first(s, "nama", "name", default=""))
            slide.add(txt(lx + 0.2, y, (w - lab_w) / 2 - 0.25, 0.36, nm, size=11, min_size=8.5, color=T.TEXT,
                          bold=True, valign="m"))
            lx += (w - lab_w) / 2
        y += 0.42
        n = len(stages)
        conv_h = 0.24
        row_h = (bottom - y - conv_h * (n - 1)) / n
        bar_max = w - lab_w - val_w
        for i, st in enumerate(stages):
            ry = y + i * (row_h + conv_h)
            slide.add(txt(x, ry, lab_w - 0.08, row_h, st, size=11, min_size=8.5, color=T.TEXT2, bold=True,
                          valign="m"))
            sub_h = row_h / k
            for j in range(k):
                v = vals[j][i] if i < len(vals[j]) else None
                by = ry + j * sub_h
                bw = max(0.05, bar_max * (v or 0) / vmax) if v is not None else 0
                if bw:
                    slide.add(Rect(lx := x + lab_w, by + sub_h * 0.1, bw, sub_h * 0.8, fill=colors[j], line=None))
                label = T.fmt(v, None, unit, ctx.style) if v is not None else "—"
                dv = deltas[j][i] if i < len(deltas[j]) else None
                rs = [run(label, True, T.TEXT)]
                if dv is not None:
                    rs.append(run("  " + T.fmt(dv, None, "", ctx.style, sign=True), True,
                                  T.GREEN if dv > 0 else T.RED if dv < 0 else T.MUTED, 0.82))
                slide.add(Text(x + lab_w + bw + 0.03, by, val_w + bar_max - bw, sub_h, [para(rs)], size=11,
                               min_size=8, valign="m"))
            if i < n - 1:                                                # konversi antar tahap (dihitung kode)
                rs = [run("↓ ", True, T.GOLD)]
                for j in range(k):
                    v = vals[j][i] if i < len(vals[j]) else None
                    nv = vals[j][i + 1] if i + 1 < len(vals[j]) else None
                    given = convs[j][i] if i < len(convs[j]) else None
                    if given not in (None, ""):
                        cv = given if isinstance(given, str) else T.fmt(T.to_num(given), None, "%", ctx.style)
                    elif v and nv is not None:                             # hasil bagi: 1 desimal
                        cv = T.fmt(round(nv / v * 100, 1), None, "%", ctx.style)
                    else:
                        cv = "—"
                    rs.append(run(cv, True, T.NAVY if j == 0 else T.MUTED))
                    if j < k - 1:
                        rs.append(run("  ·  ", False, T.MUTED))
                slide.add(Text(x + lab_w, ry + row_h, w - lab_w, conv_h, [para(rs)], size=9, min_size=7.5,
                               valign="m"))
        if ins:
            insight_box(slide, x, Y0 + BH - 0.85, w, 0.85, ins, p.get("tone") or "")


# ---------------------------------------------------------------- komponen tabel
def _cell(v: Any, ctx: Ctx, unit: str = "", **kw) -> dict:
    if T.is_num(v):
        return {"t": T.fmt(v, None, unit, ctx.style), "align": "r", **kw}
    return {"t": "—" if v in (None, "") else s_(v), "align": kw.pop("align", "l"), **kw}


def _rows_of(d: dict) -> list[list]:
    rows = []
    cols_ = [s_(c) for c in lst(first(d, "kolom", "columns", "header", default=[]))]
    for r in lst(first(d, "baris", "rows", "data", default=[])):
        if isinstance(r, dict):
            if cols_ and any(c in r for c in cols_):
                rows.append([r.get(c) for c in cols_])
            else:
                lab = first(r, "label", "nama", "merek", default="")
                rows.append([lab] + lst(first(r, "nilai", "values", default=[])))
        else:
            rows.append(lst(r))
    return rows


def _first_col_w(rows: list[list], header: list[str], w: float, ncol: int) -> float:
    """Lebar kolom label sesuai isinya (tidak terlalu lebar, tidak terlalu sempit)."""
    from .prims import text_width

    longest = max([text_width(s_(r[0]) if r else "", 12, True) for r in rows] + [text_width(s_(header[0]), 12, True)])
    need = longest / 72 + 0.25
    return max(min(need, w * 0.42), min(1.3, w * 0.3)) if ncol > 2 else w * 0.5


def _place_table(slide: Slide, d: dict, ctx: Ctx, x, y, w, max_h, header: list[str], rows: list[list],
                 cell_fn: Callable, widths: list[float] | None = None, size=12.0, stretch=True) -> None:
    ncol = max([len(header)] + [len(r) for r in rows] or [1])
    header = (header + [""] * ncol)[:ncol]
    if widths is None:
        first_w = _first_col_w(rows, header, w, ncol)
        rest = (w - first_w) / max(ncol - 1, 1)
        widths = [first_w] + [rest] * (ncol - 1)
    head = [{"t": h, "b": True, "c": T.WHITE, "fill": T.NAVY, "align": "l" if i == 0 else "c"} for i, h in enumerate(header)]
    body = [[cell_fn(i, j, (r + [None] * ncol)[j]) for j in range(ncol)] for i, r in enumerate(rows)]
    tbl = Table(x, y, w, widths, [head] + body, size=size)
    tbl.fit(max_h, max_size=14.5, stretch=stretch)
    if tbl.overflow and len(rows) > 1:                       # pecah ke slide lanjutan
        keep = len(rows)
        while keep > 1:
            keep -= 1
            t2 = Table(x, y, w, widths, [head] + body[:keep], size=size).fit(max_h)
            if not t2.overflow:
                break
        tbl = Table(x, y, w, widths, [head] + body[:keep], size=size).fit(max_h, stretch=stretch)
        rest_d = {k: v for k, v in d.items()}
        rest_d["baris"] = [list(r) for r in rows[keep:]]
        rest_d["kolom"] = header
        rest_d["_lanjutan"] = True
        ctx.cont.append(rest_d)
    slide.add(tbl)


def c_tabel(slide: Slide, d: dict, ctx: Ctx) -> None:
    header = [s_(c) for c in lst(first(d, "kolom", "columns", "header", default=[]))]
    rows = _rows_of(d)
    if not rows:
        raise ValueError("tabel tanpa baris")
    hl = {s_(x).lower() for x in lst(first(d, "sorot_baris", "sorot", default=[]))}
    signed = bool(d.get("warna_tanda"))
    unit = s_(first(d, "satuan", default=""))
    side = lst(first(d, "poin", "insight", default=[]))
    tw = BW * 0.64 if side else BW

    def cell(i, j, v):
        row = rows[i]
        is_hl = s_(row[0]).lower() in hl if row else False
        c = _cell(v, ctx, unit if j else "")
        if is_hl:
            c.update(b=True, fill=T.BLUE_BG)
        elif i % 2:
            c["fill"] = T.BG2
        n = T.to_num(v) if j else None
        if signed and n is not None:
            c["c"] = T.GREEN if n > 0 else T.RED if n < 0 else T.TEXT
        return c
    _place_table(slide, d, ctx, X0, Y0, tw, BH, header, rows, cell)
    if side:
        slide.add(Text(X0 + tw + GAP, Y0, BW - tw - GAP, BH, bullets(side), size=12.5, min_size=9))


def c_heatmap(slide: Slide, d: dict, ctx: Ctx) -> None:
    header = [s_(c) for c in lst(first(d, "kolom", "columns", default=[]))]
    rows = _rows_of(d)
    if not rows:
        raise ValueError("heatmap tanpa baris")
    if header and len(header) == max(len(r) for r in rows) - 1:
        header = [s_(first(d, "label_baris", default=""))] + header
    unit = s_(first(d, "satuan", default=""))
    nums = [T.to_num(v) for r in rows for v in r[1:]]
    nums = [v for v in nums if v is not None]
    lo, hi = (min(nums), max(nums)) if nums else (0, 1)
    deltas = {}
    for i, r in enumerate(lst(first(d, "baris", "rows", default=[]))):
        if isinstance(r, dict) and r.get("delta"):
            deltas[i] = lst(r["delta"])
    side = lst(first(d, "poin", "insight", default=[]))
    tw = BW * 0.66 if side else BW

    def cell(i, j, v):
        if j == 0:
            return {"t": s_(v), "b": True, "align": "l"}
        n = T.to_num(v)
        fill = T.heat_color(n, lo, hi)
        t = T.fmt(n, None, unit, ctx.style) if n is not None else ("—" if v in (None, "") else s_(v))
        dl = deltas.get(i, [])
        if n is not None and j - 1 < len(dl) and T.to_num(dl[j - 1]) is not None:
            t += f"  ({T.fmt(T.to_num(dl[j - 1]), None, '', ctx.style, sign=True)})"
        return {"t": t, "align": "c", "fill": fill, "c": T.text_on(fill), "b": n is not None and n >= hi - (hi - lo) * 0.2}
    _place_table(slide, d, ctx, X0, Y0, tw, BH - 0.35, header, rows, cell)
    slide.add(txt(X0, Y0 + BH - 0.3, tw, 0.3, "Warna lebih pekat = nilai lebih tinggi", size=9, min_size=8,
                  color=T.MUTED))
    if side:
        x = X0 + tw + GAP
        sw = BW - tw - GAP
        n = len(side)
        ch = (BH - GAP * (n - 1)) / max(n, 1)
        for i, it in enumerate(side[:4]):
            y = Y0 + i * (ch + GAP)
            card(slide, x, y, sw, ch, fill=T.BG3, line=None)
            slide.add(Text(x + 0.15, y + 0.08, sw - 0.3, ch - 0.16, [para(item_runs(it))], size=12, min_size=8.5,
                           valign="m"))


def c_target_kpi(slide: Slide, d: dict, ctx: Ctx) -> None:
    header = [s_(c) for c in lst(first(d, "kolom", "columns", default=["KPI", "Baseline", "Target"]))]
    rows = _rows_of(d)
    if not rows:
        raise ValueError("target tanpa baris")
    ncol = max(len(header), max(len(r) for r in rows))
    side = lst(first(d, "poin", "misi", default=[]))
    tw = BW * 0.58 if side else BW

    def cell(i, j, v):
        c = _cell(v, ctx)
        if j == 0:
            c.update(b=True, align="l")
        elif j == ncol - 1:
            c.update(b=True, fill=T.GOLD_BG, c=T.GOLD, align="c")
        else:
            c["align"] = "c"
            if i % 2:
                c["fill"] = T.BG2
        return c
    _place_table(slide, d, ctx, X0, Y0, tw, BH, header, rows, cell)
    if side:
        x = X0 + tw + GAP
        sw = BW - tw - GAP
        n = min(len(side), 5)
        ch = (BH - 0.15 * (n - 1)) / n
        for i, it in enumerate(side[:5]):
            y = Y0 + i * (ch + 0.15)
            card(slide, x, y, sw, ch)
            slide.add(Rect(x + 0.12, y + ch / 2 - 0.2, 0.4, 0.4, fill=T.GOLD2, line=None, shape="ellipse"))
            slide.add(txt(x + 0.12, y + ch / 2 - 0.2, 0.4, 0.4, str(i + 1), size=12, min_size=10, color=T.WHITE,
                          bold=True, align="c", valign="m"))
            slide.add(Text(x + 0.65, y + 0.05, sw - 0.8, ch - 0.1, [para(item_runs(it))], size=11.5, min_size=8.5,
                           valign="m"))


def c_aksi(slide: Slide, d: dict, ctx: Ctx) -> None:
    raw = lst(first(d, "baris", "aksi", "rows", default=[]))
    if not raw:
        raise ValueError("aksi kosong")
    header = ["#", "Aksi", "Pemilik", "Waktu", "Ukuran keberhasilan"]
    rows = []
    for i, r in enumerate(raw):
        if isinstance(r, dict):
            rows.append([str(i + 1), first(r, "aksi", "teks", "judul", default=""), first(r, "pemilik", "owner", default="—"),
                         first(r, "waktu", "kapan", default="—"), first(r, "kpi", "ukuran", "target", default="—")])
        else:
            rows.append([str(i + 1)] + lst(r))
    widths = [0.45, BW * 0.42, BW * 0.16, BW * 0.13, BW - 0.45 - BW * 0.71]

    def cell(i, j, v):
        c = {"t": s_(v) if v not in (None, "") else "—", "align": "c" if j in (0, 3) else "l"}
        if j == 0:
            c.update(b=True, c=T.WHITE, fill=T.GOLD2)
        elif i % 2:
            c["fill"] = T.BG2
        if j == 1:
            c["b"] = True
        return c
    _place_table(slide, d, ctx, X0, Y0, BW, BH, header, rows, cell, widths)


# ---------------------------------------------------------------- komponen kerangka strategi
SWOT_META = [("S", "STRENGTHS · Kekuatan", T.GREEN, T.GREEN_BG), ("W", "WEAKNESSES · Kelemahan", T.RED, T.RED_BG),
             ("O", "OPPORTUNITIES · Peluang", T.BLUE, T.BLUE_BG), ("T", "THREATS · Ancaman", T.AMBER, T.AMBER_BG)]
SWOT_KEYS = {"S": ("S", "strengths", "kekuatan"), "W": ("W", "weaknesses", "kelemahan"),
             "O": ("O", "opportunities", "peluang"), "T": ("T", "threats", "ancaman")}


def c_swot(slide: Slide, d: dict, ctx: Ctx) -> None:
    q = first(d, "kuadran", "swot", default=d)
    chips = lst(first(d, "sorotan", "kpi", default=[]))[:5]
    y0 = Y0
    if chips:
        for (x, w), ch in zip(cols(len(chips), gap=0.2), chips):
            slide.add(Rect(x, y0, w, 0.55, fill=T.BG3, line=None, radius=True))
            rs = item_runs(ch, T.NAVY) if isinstance(ch, dict) else [run(s_(ch), True, T.NAVY)]
            slide.add(Text(x + 0.1, y0 + 0.03, w - 0.2, 0.49, [para(rs, "c")], size=12, min_size=8.5, valign="m"))
        y0 += 0.7
    hh = (Y0 + BH - y0 - 0.2) / 2
    cw = (BW - 0.2) / 2
    found = 0
    for idx, (key, title, fg, bg) in enumerate(SWOT_META):
        items = []
        for k in SWOT_KEYS[key]:
            for kk in (k, k.lower(), k.upper(), k.capitalize()):
                if isinstance(q, dict) and q.get(kk):
                    items = lst(q[kk])
                    break
            if items:
                break
        found += bool(items)
        x = X0 + (idx % 2) * (cw + 0.2)
        y = y0 + (idx // 2) * (hh + 0.2)
        slide.add(Rect(x, y, cw, hh, fill=bg, line=None, radius=True))
        slide.add(Rect(x, y, cw, 0.42, fill=fg, line=None, radius=True))
        slide.add(txt(x + 0.15, y + 0.04, cw - 0.3, 0.34, title, size=12, min_size=10, color=T.WHITE, bold=True,
                      valign="m"))
        slide.add(Text(x + 0.12, y + 0.52, cw - 0.24, hh - 0.6, bullets(items, after=0.35), size=13.5, min_size=8.5))
    if not found:
        raise ValueError("SWOT kosong")


SMART_META = [("S", "Specific"), ("M", "Measurable"), ("A", "Achievable"), ("R", "Relevant"), ("T", "Time-bound")]


def c_smart(slide: Slide, d: dict, ctx: Ctx) -> None:
    kol = [s_(k.get("nama") if isinstance(k, dict) else k) for k in lst(first(d, "kolom", "merek", default=[""]))][:4]
    rows = first(d, "baris", "smart", default={})
    if not isinstance(rows, dict) or not rows:
        raise ValueError("SMART kosong")
    visi = lst(first(d, "visi", default=[]))
    lw = 1.75
    sub = cols(len(kol), X0 + lw, BW - lw, 0.15)
    y = Y0
    for (x, w), k in zip(sub, kol):
        slide.add(Rect(x, y, w, 0.45, fill=T.NAVY, line=None, radius=True))
        slide.add(txt(x + 0.1, y + 0.03, w - 0.2, 0.39, k, size=12.5, min_size=9, color=T.WHITE, bold=True,
                      align="c", valign="m"))
    y += 0.55
    letters = [m for m in SMART_META if rows.get(m[0]) or rows.get(m[1]) or rows.get(m[1].lower())]
    nrows = len(letters) + (1 if visi else 0)
    rh = (Y0 + BH - y - 0.08 * (nrows - 1)) / max(nrows, 1)
    if visi:
        slide.add(txt(X0, y, lw - 0.1, rh, "VISI", size=11, min_size=9, color=T.GOLD, bold=True, valign="m"))
        for (x, w), v in zip(sub, visi):
            slide.add(Rect(x, y, w, rh, fill=T.GOLD_BG, line=None, radius=True))
            slide.add(Text(x + 0.08, y + 0.04, w - 0.16, rh - 0.08, [para([run(s_(v), False, T.TEXT)])], size=11,
                           min_size=8, valign="m"))
        y += rh + 0.08
    for letter, name in letters:
        vals = lst(rows.get(letter) or rows.get(name) or rows.get(name.lower()))
        slide.add(Rect(X0, y + rh / 2 - 0.24, 0.48, 0.48, fill=T.GOLD2, line=None, shape="ellipse"))
        slide.add(txt(X0, y + rh / 2 - 0.24, 0.48, 0.48, letter, size=15, min_size=11, color=T.WHITE, bold=True,
                      align="c", valign="m"))
        slide.add(txt(X0 + 0.55, y, lw - 0.6, rh, name, size=10.5, min_size=8, color=T.TEXT2, bold=True,
                      valign="m"))
        for (x, w), v in zip(sub, vals):
            slide.add(Rect(x, y, w, rh, fill=T.BG2, line=T.GRID, radius=True))
            slide.add(Text(x + 0.1, y + 0.03, w - 0.2, rh - 0.06, [para(item_runs(v))], size=12.5, min_size=8,
                           valign="m"))
        y += rh + 0.08


def c_roadmap(slide: Slide, d: dict, ctx: Ctx) -> None:
    stages = [s for s in lst(first(d, "tahap", "milestone", "fase", default=[])) if s is not None][:6]
    if not stages:
        raise ValueError("roadmap kosong")
    from .prims import layout_text

    slots = cols(len(stages), gap=0.25)
    contents = []
    for st in stages:
        st = st if isinstance(st, dict) else {"judul": st}
        paras = []
        if first(st, "judul", "nama"):
            paras.append(para([run(s_(first(st, "judul", "nama")), True, T.NAVY)], after=0.35))
        paras += bullets(lst(first(st, "item", "poin", "isi", default=[])), after=0.3)
        contents.append((st, paras))
    need = max(layout_text(p, slots[0][1] - 0.3, 99, 13)[1] for _, p in contents) + 0.3
    avail = BH - 1.15
    card_h = max(min(avail, need), min(avail, 2.0))
    ly = Y0 + max(0.75, (BH - 1.15 - card_h) / 2 + 0.75)
    slide.add(Line(X0, ly, X0 + BW, ly, T.NAVY, 2.5, arrow=True))
    for (x, w), (st, paras) in zip(slots, contents):
        cx = x + w / 2
        slide.add(Rect(cx - 0.17, ly - 0.17, 0.34, 0.34, fill=T.GOLD2, line=T.WHITE, lw=2, shape="ellipse"))
        slide.add(txt(x, ly - 0.75, w, 0.45, s_(first(st, "waktu", "kapan", default="")), size=14, min_size=9,
                      color=T.GOLD, bold=True, align="c", valign="b"))
        card(slide, x, ly + 0.4, w, card_h, fill=T.BG3, line=None)
        slide.add(Text(x + 0.15, ly + 0.5, w - 0.3, card_h - 0.2, paras, size=13, min_size=8.5))


def c_kerangka(slide: Slide, d: dict, ctx: Ctx) -> None:
    """Diagram kerangka strategi (PNG dari strategy_diagrams, dihitung kode) + poin penjelas."""
    png = d.get("_png")
    if not png:
        raise ValueError("diagram belum tersedia")
    items = lst(first(d, "poin", "insight", default=[]))
    iw = BW * (0.62 if items else 1.0)
    slide.add(Image(X0, Y0, iw, BH, png, s_(d.get("judul"))))
    if items:
        slide.add(Text(X0 + iw + GAP, Y0, BW - iw - GAP, BH, bullets(items), size=12.5, min_size=9))


def c_lampiran(slide: Slide, d: dict, ctx: Ctx) -> None:
    data = d.get("data") or {}
    cats = data.get("categories") or []
    series = data.get("series") or []
    header = [""] + [s.get("name") or "Nilai" for s in series]
    if d.get("_lanjutan") and d.get("baris") is not None:          # slide lanjutan: hanya sisa baris
        rows = [list(r) for r in d["baris"]]
        header = [s_(h) for h in d.get("kolom") or header]
    else:
        rows = [[c] + [s["values"][i] if i < len(s["values"]) else None for s in series] for i, c in enumerate(cats)]
    unit = s_(d.get("unit", ""))

    def cell(i, j, v):
        c = _cell(v, ctx, unit if j else "")
        if i % 2:
            c["fill"] = T.BG2
        return c
    _place_table(slide, {**d, "komponen": "lampiran"}, ctx, X0, Y0, BW * (0.7 if len(header) > 3 else 0.55), BH,
                 header, rows, cell, size=11)


COMPONENTS: dict[str, Callable] = {
    "judul": c_judul, "pemisah": c_pemisah, "ringkasan": c_ringkasan, "kartu": c_kartu, "poin": c_poin,
    "benang_merah": c_benang_merah, "papan_skor": c_papan_skor, "perbandingan": c_perbandingan, "tren": c_tren,
    "waterfall": c_waterfall, "funnel": c_funnel, "tabel": c_tabel, "heatmap": c_heatmap,
    "target_kpi": c_target_kpi, "aksi": c_aksi, "swot": c_swot, "smart": c_smart, "roadmap": c_roadmap,
    "kerangka": c_kerangka, "lampiran": c_lampiran,
}
ALIASES = {"cover": "judul", "sampul": "judul", "section": "pemisah", "divider": "pemisah", "summary": "ringkasan",
           "ringkasan_eksekutif": "ringkasan", "kpi": "kartu", "angka_besar": "kartu", "stat": "kartu",
           "insight": "poin", "bullet": "poin", "teks": "poin", "scoreboard": "papan_skor", "peringkat": "papan_skor",
           "ranking": "papan_skor", "bar": "perbandingan", "kolom": "perbandingan", "column": "perbandingan",
           "line": "tren", "trend": "tren", "garis": "tren", "air_terjun": "waterfall", "dekomposisi": "waterfall",
           "corong": "funnel", "table": "tabel", "heat": "heatmap", "target": "target_kpi", "kpi_target": "target_kpi",
           "action": "aksi", "rencana_aksi": "aksi", "rekomendasi": "aksi", "timeline": "roadmap", "linimasa": "roadmap",
           "diagram": "kerangka", "framework": "kerangka", "thread": "benang_merah", "temuan_utama": "benang_merah"}


def kind_of(d: dict) -> str:
    k = str(d.get("komponen") or d.get("jenis") or d.get("type") or "poin").strip().lower().replace(" ", "_")
    return ALIASES.get(k, k)
