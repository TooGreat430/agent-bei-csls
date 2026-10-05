"""Grafik dari tabel hasil query BigQuery: spesifikasi grafik + gambar PNG untuk chat.

Angka grafik SELALU diambil dari tabel hasil query (bukan ditulis model), sehingga tidak bisa
dikarang. Spesifikasi grafik memakai struktur yang sama dengan blok "charts" di laporan
(judul, jenis, satuan, kategori, seri), jadi grafik yang dilihat user di chat bisa ikut ke laporan.
"""
from __future__ import annotations

import io
import os
import re
from typing import Any

from .report_render import SERIES_KEYS, clean_charts, fmt_id, parse_number

MAX_CATEGORIES = 12
MAX_SERIES = 4

DEFAULT_THEME = {
    "primary": "0F2347", "accent": "1E6FD9", "highlight": "E0A526", "text": "1E2329", "muted": "5B6470",
    "light": "EEF2F7", "line": "D5DBE3", "high": "C0392B", "mid": "B7791F", "low": "1E7B4F",
}


_NUMERIC_TEXT = re.compile(r"^[-−–+]?\s*(rp\.?\s*)?[-−–+]?\d[\d.,]*\s*(%|/l|/liter)?$", re.IGNORECASE)


def numeric_cell(value: Any) -> float | None:
    """Angka dari sel tabel; teks campuran seperti 'Zona 1' TIDAK dianggap angka."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return parse_number(value)
    text = str(value).strip()
    return parse_number(text) if _NUMERIC_TEXT.match(text) else None


_KEEP_UPPER = {"HET", "HTO", "TOV", "PTPL", "QNR", "KIMAP", "HJ", "HT", "NHT", "MCO", "PCO", "SKU", "SR", "NPS", "BEI"}


def pretty_label(column: str) -> str:
    """'GAP_HET_PER_LITER' -> 'Gap HET per liter'."""
    words = str(column).replace("_", " ").split()
    out = []
    for i, w in enumerate(words):
        up = w.upper()
        if up in _KEEP_UPPER:
            out.append(up)
        else:
            out.append(w.lower().capitalize() if i == 0 else w.lower())
    return " ".join(out) or str(column)


def _match(columns: list[str], name: str) -> int | None:
    wanted = (name or "").strip().lower()
    for i, col in enumerate(columns):
        if str(col).strip().lower() == wanted:
            return i
    return None


def build_chart(table: dict[str, Any], x_column: str, y_columns: list[str], chart_type: str = "bar",
                title: str = "", unit: str = "") -> tuple[dict[str, Any] | None, str]:
    """Bangun spesifikasi grafik dari tabel. Hasil: (chart, pesan_error)."""
    columns = [str(c) for c in table.get("columns") or []]
    rows = table.get("rows") or []
    xi = _match(columns, x_column)
    if xi is None:
        return None, f"Kolom '{x_column}' tidak ada. Kolom tersedia: {', '.join(columns)}"
    yis = []
    for name in y_columns[:MAX_SERIES]:
        idx = _match(columns, name)
        if idx is None:
            return None, f"Kolom '{name}' tidak ada. Kolom tersedia: {', '.join(columns)}"
        yis.append(idx)
    if not yis:
        return None, "Pilih minimal satu kolom angka untuk sumbu Y."
    rows = rows[:MAX_CATEGORIES]
    categories = ["" if r[xi] is None else str(r[xi]) for r in rows]
    series = [{"nama": pretty_label(columns[i]), "nilai": [numeric_cell(r[i]) for r in rows]} for i in yis]
    chart = {"judul": title or f"{', '.join(pretty_label(columns[i]) for i in yis)} per {pretty_label(columns[xi])}",
             "jenis": "line" if chart_type == "line" else "bar", "satuan": unit,
             "kategori": categories, "seri": series, "catatan": ""}
    cleaned = clean_charts([chart])
    if not cleaned:
        return None, "Kolom yang dipilih tidak berisi angka."
    note = f"Menampilkan {MAX_CATEGORIES} baris pertama dari {len(table.get('rows') or [])}." \
        if len(table.get("rows") or []) > MAX_CATEGORIES else ""
    cleaned[0]["catatan"] = note
    return cleaned[0], ""


def _font() -> str:
    from matplotlib import font_manager

    folder = os.path.join(os.path.dirname(__file__), "fonts")
    for name in ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            font_manager.fontManager.addfont(path)
    return "Liberation Sans"


def render_png(chart: dict[str, Any], theme: dict[str, str] | None = None) -> bytes:
    """Gambar grafik (batang berkelompok / garis) sebagai PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    import textwrap

    theme = theme or DEFAULT_THEME
    plt.rcParams["font.family"] = _font()
    colors = ["#" + theme[k] for k in SERIES_KEYS]
    cats, series = chart["kategori"], chart["seri"]
    fig, ax = plt.subplots(figsize=(10, 5.4), dpi=130)
    n = len(series)
    width = 0.8 / n
    xs = list(range(len(cats)))
    for si, s in enumerate(series):
        vals = [v if v is not None else float("nan") for v in s["nilai"]]
        color = colors[si % len(colors)]
        if chart["jenis"] == "line":
            ax.plot(xs, vals, marker="o", linewidth=2.4, color=color, label=s["nama"])
        else:
            pos = [x - 0.4 + width * (si + 0.5) for x in xs]
            bars = ax.bar(pos, vals, width=width * 0.92, color=color, label=s["nama"])
            if len(cats) * n <= 24:
                for b, v in zip(bars, s["nilai"]):
                    if v is not None:
                        ax.annotate(fmt_id(v), (b.get_x() + b.get_width() / 2, v),
                                    xytext=(0, 4 if v >= 0 else -12), textcoords="offset points",
                                    ha="center", fontsize=8, color="#" + theme["text"])
    ax.axhline(0, color="#" + theme["muted"], linewidth=0.8)
    ax.set_xticks(xs)
    wrap = 14 if len(cats) > 5 else 20
    labels = ["\n".join(textwrap.wrap(c, wrap)[:3]) for c in cats]
    ax.set_xticklabels(labels, fontsize=8.5 if len(cats) > 5 else 9)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt_id(v)))
    ax.grid(axis="y", color="#" + theme["line"], linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    title = chart["judul"] + (f" ({chart['satuan']})" if chart.get("satuan") else "")
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#" + theme["primary"])
    if n > 1 or chart["jenis"] == "line":
        ax.legend(frameon=False, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=min(n, 4))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
