"""Spesifikasi chart bersama + gambar matplotlib (PDF/HTML). PPTX memakai chart native (render_pptx).

Spesifikasi ternormalisasi:
    {"kind": "barh|column|line|waterfall|stacked", "categories": [...],
     "series": [{"name", "values": [...], "color", "colors": [warna per titik | None]}],
     "unit", "dec", "style", "legend", "labels", "totals": [bool per titik, khusus waterfall]}
Kategori yang terlalu banyak dipotong untuk chart, tetapi data lengkapnya dikembalikan ke pemanggil untuk lampiran
(angka hasil analitik tidak boleh hilang dari laporan).
"""
from __future__ import annotations

import io
from typing import Any

from . import theme as T

KINDS = {"barh", "column", "line", "waterfall", "stacked"}
ALIAS = {"bar": "column", "kolom": "column", "batang": "column", "col": "column", "hbar": "barh",
         "bar_horizontal": "barh", "horizontal": "barh", "garis": "line", "tren": "line", "trend": "line",
         "air_terjun": "waterfall", "bertumpuk": "stacked", "stack": "stacked", "stacked_column": "stacked"}
MAX_CATS = {"barh": 15, "column": 12, "line": 24, "waterfall": 10, "stacked": 12}


def _names(x: Any) -> set[str]:
    if isinstance(x, str):
        return {x.strip().lower()} if x.strip() else set()
    return {str(v).strip().lower() for v in (x or []) if str(v).strip()}


def normalize(raw: dict, default_kind: str = "column", style: str = "id") -> tuple[dict, list[str], dict | None]:
    """(spesifikasi, catatan masalah, data lengkap untuk lampiran bila dipotong)."""
    issues: list[str] = []
    kind = str(raw.get("kind") or raw.get("jenis") or default_kind).strip().lower()
    kind = ALIAS.get(kind, kind)
    if kind not in KINDS:
        issues.append(f"jenis chart '{kind}' tidak dikenal; dipakai '{default_kind}'")
        kind = default_kind
    cats = [str(c) for c in (raw.get("categories") or raw.get("kategori") or raw.get("labels") or [])]
    series_in = raw.get("series") or raw.get("seri")
    if series_in is None and (raw.get("values") is not None or raw.get("nilai") is not None):
        series_in = [{"name": raw.get("nama_seri") or "", "values": raw.get("values", raw.get("nilai"))}]
    totals: list[bool] = []
    if kind == "waterfall" and (raw.get("steps") or raw.get("langkah")):
        steps = raw.get("steps") or raw.get("langkah") or []
        cats = [str(s.get("label", "")) for s in steps]
        series_in = [{"name": "", "values": [s.get("value", s.get("nilai")) for s in steps]}]
        totals = [bool(s.get("total") or str(s.get("tipe", "")).lower() == "total") for s in steps]
    series = []
    for j, s in enumerate(series_in or []):
        if not isinstance(s, dict):
            s = {"values": s}
        vals = [T.to_num(v) for v in (s.get("values") or s.get("nilai") or [])]
        vals = (vals + [None] * len(cats))[:len(cats)] if cats else vals
        series.append({"name": str(s.get("name") or s.get("nama") or ""), "values": vals,
                       "color": T.hex_ok(s.get("color") or s.get("warna"), T.SERIES[j % len(T.SERIES)]),
                       "colors": None})
    if not cats and series:
        cats = [str(i + 1) for i in range(len(series[0]["values"]))]
    if not series or not cats or not any(v is not None for s in series for v in s["values"]):
        raise ValueError("chart tanpa data")
    if kind == "waterfall":
        series = series[:1]
        if not totals:
            totals = [False] * len(cats)
            if raw.get("total_terakhir", True) and len(cats) > 1:
                totals[-1] = True
            if raw.get("total_pertama", True):
                totals[0] = True
    full = None
    limit = MAX_CATS[kind]
    if len(cats) > limit:
        full = {"categories": cats, "series": [{"name": s["name"], "values": list(s["values"])} for s in series]}
        if kind in ("barh", "column") and len(series) == 1 and raw.get("urut", True):
            order = sorted(range(len(cats)), key=lambda i: -(series[0]["values"][i] or 0))[:limit]
            order.sort(key=lambda i: -(series[0]["values"][i] or 0))
        else:
            order = list(range(limit))
        cats = [cats[i] for i in order]
        for s in series:
            s["values"] = [s["values"][i] for i in order]
        totals = [totals[i] for i in order] if totals else totals
        issues.append(f"chart dipotong ke {limit} dari {len(full['categories'])} kategori; data lengkap di lampiran")
    hi1, hi2 = _names(raw.get("sorot") or raw.get("highlight")), _names(raw.get("sorot2"))
    if len(series) == 1 and kind in ("barh", "column") and (hi1 or hi2):
        series[0]["colors"] = [T.NAVY if c.lower() in hi1 else (T.PTPL_2 if c.lower() in hi2 else T.COMP)
                               for c in cats]
    if kind == "waterfall":
        series[0]["colors"] = [T.NAVY if totals[i] else (T.GREEN if (v or 0) >= 0 else T.RED)
                               for i, v in enumerate(series[0]["values"])]
    allv = [v for s in series for v in s["values"] if v is not None]
    spec = {"kind": kind, "categories": cats, "series": series, "unit": str(raw.get("unit") or raw.get("satuan") or ""),
            "dec": raw.get("dec") if isinstance(raw.get("dec"), int) else T.decimals_of(allv), "style": style,
            "legend": bool(raw.get("legend", len(series) > 1)), "labels": bool(raw.get("labels", True)),
            "totals": totals, "title": str(raw.get("title") or raw.get("judul_chart") or "")}
    if kind == "waterfall" and not isinstance(raw.get("dec"), int):
        vals = series[0]["values"]
        spec["dec_total"] = T.decimals_of([v for v, t in zip(vals, totals) if t and v is not None])
        spec["dec_step"] = T.decimals_of([v for v, t in zip(vals, totals) if not t and v is not None])
    return spec, issues, full


def label(spec: dict, v: float | None, i: int = 0, total: bool = True) -> str:
    if v is None:
        return ""
    is_total = (spec.get("totals") or [False] * (i + 1))[i] if spec["kind"] == "waterfall" else True
    dec = spec.get("dec")
    if spec["kind"] == "waterfall" and "dec_total" in spec:
        dec = spec["dec_total"] if is_total else spec["dec_step"]
    return T.fmt(v, dec, spec.get("unit", ""), spec.get("style", "id"), sign=not is_total)


def chart_text(spec: dict) -> str:
    """Teks yang tampil di chart (kategori, nama seri, label angka) — dasar pemeriksaan cakupan angka."""
    parts = list(spec.get("categories") or []) + [spec.get("title", "")]
    for s in spec.get("series") or []:
        parts.append(s.get("name", ""))
        parts += [label(spec, v, i) for i, v in enumerate(s.get("values") or [])]
    return " ".join(p for p in parts if p)


def waterfall_geometry(values: list[float | None], totals: list[bool]) -> list[tuple[float, float]]:
    """(bawah, atas) tiap batang waterfall."""
    out, run = [], 0.0
    for v, tot in zip(values, totals):
        v = v or 0.0
        if tot:
            out.append((min(0.0, v), max(0.0, v)))
            run = v
        else:
            a, b = run, run + v
            out.append((min(a, b), max(a, b)))
            run = b
    return out


def render_image(spec: dict, w_in: float, h_in: float, fmt: str = "png") -> bytes:
    """Gambar chart dengan gaya yang sama dengan chart native PowerPoint."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({"font.family": "sans-serif",
                         "font.sans-serif": ["Arial", "Liberation Sans", "Helvetica", "DejaVu Sans"],
                         "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(max(w_in, 1.5), max(h_in, 1.0)), dpi=200)
    fs = 9 if min(w_in, h_in) > 2.2 else 8
    kind, cats, series = spec["kind"], spec["categories"], spec["series"]
    n = len(cats)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#" + T.BORDER)
    ax.tick_params(colors="#" + T.TEXT2, labelsize=fs, length=0)
    c = lambda h: "#" + h  # noqa: E731
    if kind == "barh":
        y = np.arange(n)[::-1]
        k = len(series)
        bh = 0.75 / k
        vmax = max([abs(v) for s in series for v in s["values"] if v is not None] or [1])
        for j, s in enumerate(series):
            vals = [v or 0 for v in s["values"]]
            cols = [c(x) for x in (s["colors"] or [s["color"]] * n)]
            pos = y + (k - 1) * bh / 2 - j * bh
            ax.barh(pos, vals, bh * 0.88, color=cols, label=s["name"] or None)
            if spec["labels"]:
                for p, v, raw in zip(pos, vals, s["values"]):
                    if raw is not None:
                        ax.text(v + (vmax * 0.015 if v >= 0 else -vmax * 0.015), p, label(spec, raw), va="center",
                                ha="left" if v >= 0 else "right", fontsize=fs, color=c(T.TEXT))
        ax.set_yticks(y, [str(x)[:28] for x in cats])
        ax.xaxis.set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.set_xlim(min(0, min([v or 0 for s in series for v in s["values"]]) * 1.25), vmax * 1.22)
    elif kind in ("column", "stacked"):
        x = np.arange(n)
        k = len(series)
        base = np.zeros(n)
        bw = 0.75 / (1 if kind == "stacked" else k)
        for j, s in enumerate(series):
            vals = np.array([v or 0 for v in s["values"]], dtype=float)
            cols = [c(xx) for xx in (s["colors"] or [s["color"]] * n)]
            pos = x if kind == "stacked" else x - 0.375 + bw * (j + 0.5)
            bars = ax.bar(pos, vals, bw * 0.88, bottom=base if kind == "stacked" else 0, color=cols,
                          label=s["name"] or None)
            if spec["labels"]:
                for b, raw, bb in zip(bars, s["values"], base):
                    if raw is None:
                        continue
                    if kind == "stacked":
                        ax.text(b.get_x() + b.get_width() / 2, bb + raw / 2, label(spec, raw), ha="center",
                                va="center", fontsize=fs - 1, color=c(T.text_on(s["color"])))
                    else:
                        ax.text(b.get_x() + b.get_width() / 2, raw, label(spec, raw), ha="center",
                                va="bottom" if raw >= 0 else "top", fontsize=fs - (1 if k > 2 else 0), color=c(T.TEXT))
            if kind == "stacked":
                base = base + vals
        ax.set_xticks(x, [str(cc)[:18] for cc in cats], rotation=0 if n <= 6 else 30, ha="center" if n <= 6 else "right")
        ax.yaxis.set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.axhline(0, color=c(T.BORDER), lw=0.8)
        ax.margins(y=0.15)
    elif kind == "line":
        x = np.arange(n)
        for j, s in enumerate(series):
            pts = [(i, v) for i, v in enumerate(s["values"]) if v is not None]
            if not pts:
                continue
            xs, ys = zip(*pts)
            ax.plot(xs, ys, marker="o", ms=4, lw=2, color=c(s["color"]), label=s["name"] or None)
            if spec["labels"] and (len(pts) <= 12 or len(series) == 1):
                for xi, yi in pts if len(pts) <= 12 else [pts[0], pts[-1]]:
                    ax.annotate(label(spec, yi), (xi, yi), textcoords="offset points", xytext=(0, 6), ha="center",
                                fontsize=fs - 1, color=c(s["color"]))
        ax.set_xticks(x, [str(cc)[:12] for cc in cats], rotation=0 if n <= 8 else 45, ha="center" if n <= 8 else "right")
        ax.grid(axis="y", color=c(T.GRID), lw=0.6)
        ax.set_axisbelow(True)
        ax.margins(y=0.2)
    elif kind == "waterfall":
        s = series[0]
        geo = waterfall_geometry(s["values"], spec["totals"])
        x = np.arange(n)
        for i, ((lo, hi), col) in enumerate(zip(geo, s["colors"])):
            ax.bar(i, hi - lo, 0.62, bottom=lo, color=c(col))
            v = s["values"][i]
            if v is not None and spec["labels"]:
                ax.text(i, hi, label(spec, v, i), ha="center", va="bottom", fontsize=fs, color=c(T.TEXT),
                        fontweight="bold" if spec["totals"][i] else "normal")
        for i in range(n - 1):
            lvl = geo[i][1] if (s["values"][i] or 0) >= 0 or spec["totals"][i] else geo[i][0]
            ax.plot([i + 0.31, i + 0.69], [lvl, lvl], color=c(T.MUTED), lw=0.6, ls=":")
        ax.set_xticks(x, [str(cc)[:16] for cc in cats])
        ax.yaxis.set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.axhline(0, color=c(T.BORDER), lw=0.8)
        ax.margins(y=0.15)
    if spec.get("legend") and len(series) > 1:
        ax.legend(fontsize=fs - 1, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.12), ncol=min(4, len(series)))
    fig.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, facecolor="white")
    plt.close(fig)
    return buf.getvalue()
