"""Laporan HTML "PTPL RFM Retail Outlet Intelligence" — struktur 8 section mengikuti standar SR7 v5.

Semua angka, tabel, dan grafik diisi KODE dari hasil rfm_engine.compute(). Model (Claude, cadangan Argon) hanya
menulis narasi singkat (headline, interpretasi, aksi), lalu kalimat yang memuat angka di luar data dibuang.
Grafik = SVG inline (tanpa JavaScript/CDN) agar tampil sama di browser dan saat dicetak.
Palet & elemen mengikuti panduan v5: navy #18324B, teal #149688, cyan #43B8C4, orange #F29B50, pink #E77B92,
violet #8272C7, ink #263747, muted #687B8C, paper #F4F7FA, line #E3EAF0.
"""
from __future__ import annotations

import html
import logging
import math
from datetime import datetime, timezone
from typing import Any

from .rfm_engine import PRIORITY_SEGMENTS, R_BANDS, SEGMENT_RULES, SEGMENTS

logger = logging.getLogger(__name__)
NAVY, TEAL, CYAN, ORANGE, PINK, VIOLET = "#18324B", "#149688", "#43B8C4", "#F29B50", "#E77B92", "#8272C7"
INK, MUTED, PAPER, LINE = "#263747", "#687B8C", "#F4F7FA", "#E3EAF0"
SEG_COLORS = [TEAL, PINK, "#9AA8B5", ORANGE, VIOLET, "#B9A6E0", CYAN, "#7FD1D9", "#F6C08F", NAVY, "#2BB3A3", "#F3A6B6"]
OWNERS = ("Management", "Brand Owner", "Sales Region", "MIR")
PHASES = ("Hari 1–30", "Hari 31–60", "Hari 61–90")


# ==========================================================================
# Format angka (Indonesia)
# ==========================================================================
def n2(v, dec: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    s = f"{float(v):,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def n0(v) -> str:
    return n2(v, 0)


def pc(v, dec: int = 1, sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    return ("+" if sign and v > 0 else "") + n2(v, dec) + "%"


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ==========================================================================
# Narasi
# ==========================================================================
NARRATIVE_SCHEMA = {"type": "object", "properties": {
    "headline": {"type": "string"},
    "ringkasan": {"type": "array", "items": {"type": "string"}},
    "interpretasi_overview": {"type": "string"},
    "interpretasi_rfm": {"type": "string"},
    "interpretasi_segmen": {"type": "string"},
    "interpretasi_produk": {"type": "string"},
    "interpretasi_momentum": {"type": "string"},
    "aksi_segmen": {"type": "array", "items": {"type": "object", "properties": {
        "segmen": {"type": "string", "enum": SEGMENTS}, "aksi": {"type": "string"}}, "required": ["segmen", "aksi"]}},
    "rencana_90_hari": {"type": "array", "items": {"type": "object", "properties": {
        "fase": {"type": "string", "enum": list(PHASES)}, "fokus": {"type": "string"}, "aksi": {"type": "string"},
        "owner": {"type": "string", "enum": list(OWNERS)}, "kpi": {"type": "string"}, "ritme": {"type": "string"}},
        "required": ["fase", "fokus", "aksi", "owner", "kpi", "ritme"]}},
}, "required": ["headline", "ringkasan", "interpretasi_overview", "interpretasi_rfm", "interpretasi_segmen",
                "interpretasi_produk", "interpretasi_momentum", "aksi_segmen", "rencana_90_hari"]}


def narrative_prompt(res: dict[str, Any], request: str = "") -> str:
    import json

    from .rfm_engine import compact, to_json_safe

    data = json.dumps(to_json_safe(compact(res)), ensure_ascii=False, default=str)
    return f"""Anda Senior Marketing Intelligence & Commercial Analytics PT Pertamina Lubricants. Tulis narasi laporan
"RFM Retail Outlet Intelligence" ({res['scope_label']}, {res['window']['label_ytd']} vs {res['window']['label_ytd_prev']},
baseline {res['window']['label_base']}) untuk Marketing Head Office dan Sales Region, berdasarkan DATA berikut yang SUDAH
DIHITUNG kode dari datamart sell-out distributor (outlet Bengkel & Toko Oli).

ATURAN WAJIB
- Bahasa Indonesia eksekutif, ringkas. Setiap interpretasi maksimal 3 kalimat; ringkasan 3–4 poin, masing-masing 1 kalimat.
- Semua angka HARUS persis dari DATA, format Indonesia (12.345,67 KL; 74,3%; 1.624 outlet). Jangan menghitung angka
  baru (jangan menjumlah, mengurangi, merata-rata), jangan kisaran/perkiraan/target/proyeksi.
- Pisahkan pertumbuhan total dataset dari kinerja baseline cohort, dan sebut kontribusi Dataset Entrants.
- Guardrail: F = kontinuitas bulan pembelian (BUKAN frekuensi transaksi); momentum = perubahan skor R+F+M; "Lost" bukan
  bukti outlet tutup; "New Customers"/Dataset Entrant bukan bukti akuisisi; penetrasi bukan market share; data penjualan
  deskriptif tidak membuktikan sebab-akibat; jangan menyarankan diskon menyeluruh.
- aksi_segmen: 4–6 aksi berbeda per segmen prioritas. rencana_90_hari: 3–6 baris, owner salah satu dari
  Management / Brand Owner / Sales Region / MIR; KPI berupa metrik yang bisa diukur dari data ini (tanpa angka target).
{('- Penekanan dari user: ' + request.strip()) if request.strip() else ''}

DATA
{data}"""


def fallback_narrative(res: dict[str, Any]) -> dict[str, Any]:
    k, w = res["kpi"], res["window"]
    seg = {s["segment"]: s for s in res["segments"]}
    ch = seg.get("Champions", {})
    mom = {m["status"]: m for m in res["momentum"]}
    top = (res["products"].get("top") or [{}])[0]
    return {
        "headline": f"{n0(ch.get('outlets', 0))} outlet Champions menyumbang {pc(ch.get('vol_share'))} volume "
                    f"{w['label_ytd']}",
        "ringkasan": [f"Volume {w['label_ytd']} {n2(k['vol_ytd'])} KL ({pc(k['yoy_total_pct'], sign=True)} vs "
                      f"{w['label_ytd_prev']}); baseline cohort {pc(k['yoy_cohort_pct'], sign=True)}.",
                      f"{n0(k['outlets_baseline'])} outlet baseline dan {n0(k['outlets_entrants'])} Dataset Entrants "
                      f"(kontribusi {pc(k['entrant_share_pct'])} volume YTD).",
                      f"{n0(mom.get('Deteriorated', {}).get('outlets', 0))} outlet baseline "
                      f"({pc(mom.get('Deteriorated', {}).get('share'))}) mengalami penurunan skor R+F+M."],
        "interpretasi_overview": "Pertumbuhan total dataset dipengaruhi Dataset Entrants; kinerja outlet yang sama dibaca "
                                 "dari baseline cohort.",
        "interpretasi_rfm": f"Champions menguasai {pc(ch.get('vol_share'))} volume dengan {pc(ch.get('outlet_share'))} outlet.",
        "interpretasi_segmen": "Momentum adalah perubahan skor R+F+M pada cohort baseline yang sama, bukan bukti "
                               "perubahan frekuensi transaksi.",
        "interpretasi_produk": (f"Seri dengan volume terbesar adalah {top.get('series', 'n/a')} "
                                f"({n2(top.get('vol_cur'))} KL)." if top else "Data seri produk tidak tersedia."),
        "interpretasi_momentum": "Bandingkan kuartal setara dan pisahkan kontribusi Dataset Entrants.",
        "aksi_segmen": [{"segmen": "Champions", "aksi": "Jaga kontinuitas pasokan dan kunjungan rutin."},
                        {"segmen": "At Risk", "aksi": "Kunjungan pemulihan prioritas oleh Sales Region."},
                        {"segmen": "Potential Loyalists", "aksi": "Dorong kontinuitas pembelian bulanan."}],
        "rencana_90_hari": [
            {"fase": PHASES[0], "fokus": "Validasi daftar prioritas", "aksi": "Verifikasi status outlet daftar "
             "pemulihan bersama distributor.", "owner": "Sales Region", "kpi": "Jumlah outlet terverifikasi", "ritme": "Mingguan"},
            {"fase": PHASES[1], "fokus": "Pemulihan", "aksi": "Kunjungan outlet At Risk & Can't Lose Them.",
             "owner": "Sales Region", "kpi": "Outlet kembali aktif", "ritme": "Mingguan"},
            {"fase": PHASES[2], "fokus": "Evaluasi", "aksi": "Ukur ulang segmen dengan data terbaru.", "owner": "MIR",
             "kpi": "Perpindahan segmen", "ritme": "Bulanan"}],
    }


def generate_narrative(res: dict[str, Any], request: str = "") -> dict[str, Any]:
    from .price_dashboard import ungrounded_numbers
    from .report_engine import _generate_json
    from .rfm_engine import numbers_pool

    base = fallback_narrative(res)
    try:
        raw = _generate_json(narrative_prompt(res, request), NARRATIVE_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("Narasi RFM gagal dibuat; memakai narasi berbasis aturan")
        return base
    pool = numbers_pool(res)
    dropped = 0

    def ok(t) -> bool:
        nonlocal dropped
        if ungrounded_numbers(str(t or ""), pool):
            dropped += 1
            return False
        return bool(str(t or "").strip())
    out = {"headline": raw.get("headline") if ok(raw.get("headline")) else base["headline"],
           "ringkasan": [t for t in raw.get("ringkasan") or [] if ok(t)][:4] or base["ringkasan"]}
    for key in ("interpretasi_overview", "interpretasi_rfm", "interpretasi_segmen", "interpretasi_produk",
                "interpretasi_momentum"):
        out[key] = raw.get(key) if ok(raw.get(key)) else base[key]
    out["aksi_segmen"] = [a for a in raw.get("aksi_segmen") or [] if ok(a.get("aksi"))][:6] or base["aksi_segmen"]
    out["rencana_90_hari"] = [r for r in raw.get("rencana_90_hari") or []
                              if ok(f"{r.get('fokus')} {r.get('aksi')} {r.get('kpi')}")][:6] or base["rencana_90_hari"]
    if dropped:
        logger.warning("Narasi RFM: %d bagian dibuang karena angka di luar data", dropped)
    out["_dropped"] = dropped
    return out


# ==========================================================================
# Grafik SVG
# ==========================================================================
def _axis_max(v: float) -> float:
    if v <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(v))
    for f in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= f * p:
            return f * p
    return 10 * p


def svg_line(labels: list[str], series: list[tuple[str, str, list]], unit: str = "KL", w: int = 760, h: int = 300) -> str:
    ml, mr, mt, mb = 64, 18, 36, 34
    vals = [v for _, _, s in series for v in s if v is not None]
    top = _axis_max(max(vals) if vals else 1)
    x = lambda i: ml + i * (w - ml - mr) / max(len(labels) - 1, 1)  # noqa: E731
    y = lambda v: mt + (1 - v / top) * (h - mt - mb)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Tren volume bulanan">']
    for i in range(5):
        v = top * i / 4
        out.append(f'<line x1="{ml}" y1="{y(v):.1f}" x2="{w - mr}" y2="{y(v):.1f}" stroke="{LINE}"/>'
                   f'<text x="{ml - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="ax">{n0(v) if top >= 50 else n2(v, 1)}</text>')
    for i, lab in enumerate(labels):
        out.append(f'<text x="{x(i):.1f}" y="{h - 12}" text-anchor="middle" class="ax">{e(lab)}</text>')
    lx = ml
    for name, col, s in series:
        pts = [(x(i), y(v)) for i, v in enumerate(s) if v is not None]
        if pts:
            out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.6" points="'
                       + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '"/>')
            out += [f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3.2" fill="{col}"/>' for a, b in pts]
        out.append(f'<rect x="{lx}" y="10" width="12" height="12" rx="3" fill="{col}"/>'
                   f'<text x="{lx + 18}" y="20" class="lg">{e(name)}</text>')
        lx += 18 + 8 * len(name) + 24
    out.append(f'<text x="{w - mr}" y="20" text-anchor="end" class="ax">{e(unit)}</text></svg>')
    return "".join(out)


def svg_hbar(labels: list[str], values: list, colors: list[str] | str = TEAL, unit: str = "", w: int = 560,
             fmt=None, h_row: int = 26) -> str:
    fmt = fmt or (lambda v: n2(v))
    h = 16 + h_row * len(labels)
    vals = [v for v in values if v is not None]
    lo, hi = min(0.0, min(vals) if vals else 0.0), max(0.0, max(vals) if vals else 1.0)
    raw_span = (hi - lo) or 1.0
    lo -= 0.16 * raw_span if lo < 0 else 0.0                       # ruang label angka di sisi negatif
    hi += 0.16 * raw_span if hi > 0 else 0.0
    span = (hi - lo) or 1.0
    ml = min(230, 30 + 7 * max((len(str(l)) for l in labels), default=8))
    mr = 16
    x = lambda v: ml + (v - lo) / span * (w - ml - mr)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    if lo < 0:
        out.append(f'<line x1="{x(0):.1f}" y1="6" x2="{x(0):.1f}" y2="{h - 6}" stroke="{MUTED}"/>')
    for i, (lab, v) in enumerate(zip(labels, values)):
        cy = 10 + i * h_row
        col = colors[i % len(colors)] if isinstance(colors, list) else colors
        out.append(f'<text x="{ml - 8}" y="{cy + h_row / 2 + 1:.1f}" text-anchor="end" class="lb">{e(str(lab)[:34])}</text>')
        if v is None:
            continue
        a, b = sorted((x(0), x(v)))
        out.append(f'<rect x="{a:.1f}" y="{cy + 4}" width="{max(b - a, 1):.1f}" height="{h_row - 9}" rx="4" fill="{col}"/>')
        tx = (b + 6) if v >= 0 else (a - 6)
        out.append(f'<text x="{tx:.1f}" y="{cy + h_row / 2 + 1:.1f}" text-anchor="{"start" if v >= 0 else "end"}" '
                   f'class="vl">{e(fmt(v))}{e(unit)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_share_bars(segments: list[dict], w: int = 560) -> str:
    rows = [s for s in segments if s["outlets"] > 0]
    h_row = 30
    h = 40 + h_row * len(rows)
    ml, mr = 160, 56
    x = lambda v: ml + v / 100 * (w - ml - mr)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Komposisi segmen">',
           f'<rect x="{ml}" y="8" width="12" height="12" rx="3" fill="{NAVY}"/><text x="{ml + 18}" y="18" class="lg">% outlet</text>',
           f'<rect x="{ml + 100}" y="8" width="12" height="12" rx="3" fill="{TEAL}"/><text x="{ml + 118}" y="18" class="lg">% volume</text>']
    for i, s in enumerate(rows):
        cy = 30 + i * h_row
        out.append(f'<text x="{ml - 8}" y="{cy + 15}" text-anchor="end" class="lb">{e(s["segment"])}</text>')
        for j, (v, col) in enumerate(((s["outlet_share"], NAVY), (s["vol_share"], TEAL))):
            out.append(f'<rect x="{ml}" y="{cy + 3 + j * 12}" width="{max(x(v) - ml, 1):.1f}" height="10" rx="3" fill="{col}"/>'
                       f'<text x="{x(v) + 5:.1f}" y="{cy + 12 + j * 12}" class="vl">{pc(v)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_bubble(segments: list[dict], w: int = 760, h: int = 360) -> str:
    pts = [s for s in segments if s["outlets"] > 0]
    if not pts:
        return '<p class="muted">Tidak ada data segmen.</p>'
    ml, mr, mt, mb = 70, 30, 24, 46
    xmax = _axis_max(max(p["outlets"] for p in pts) * 1.1)
    ymax = _axis_max(max(p["avg_m"] for p in pts) * 1.15 or 1)
    vmax = max(p["vol_ytd"] for p in pts) or 1
    x = lambda v: ml + v / xmax * (w - ml - mr)  # noqa: E731
    y = lambda v: mt + (1 - v / ymax) * (h - mt - mb)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Peta gelembung segmen">']
    for i in range(5):
        yv, xv = ymax * i / 4, xmax * i / 4
        out.append(f'<line x1="{ml}" y1="{y(yv):.1f}" x2="{w - mr}" y2="{y(yv):.1f}" stroke="{LINE}"/>'
                   f'<text x="{ml - 8}" y="{y(yv) + 4:.1f}" text-anchor="end" class="ax">{n2(yv, 3)}</text>'
                   f'<text x="{x(xv):.1f}" y="{h - mb + 18}" text-anchor="middle" class="ax">{n0(xv)}</text>')
    placed: list[tuple[float, float, float, float]] = []
    labels = []
    for p in sorted(pts, key=lambda p: -p["vol_ytd"]):
        col = SEG_COLORS[SEGMENTS.index(p["segment"]) % len(SEG_COLORS)]
        r = 6 + 34 * math.sqrt(max(p["vol_ytd"], 0) / vmax)
        cx, cy = x(p["outlets"]), y(p["avg_m"])
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{col}" '
                   f'fill-opacity="0.72" stroke="#fff" stroke-width="1.5"><title>{e(p["segment"])}: {n0(p["outlets"])} outlet, '
                   f'M rata-rata {n2(p["avg_m"], 3)} KL/bln, {n2(p["vol_ytd"])} KL</title></circle>')
        tw = 6.2 * len(p["segment"]) + 6
        # label: di atas gelembung; bila bertabrakan dengan label lain, coba di bawah lalu naik bertahap
        for ly in [cy - r - 4, cy + r + 13] + [cy - r - 4 - 13 * k for k in range(1, 8)]:
            lx = min(max(cx, ml + tw / 2), w - mr - tw / 2)
            box = (lx - tw / 2, ly - 11, lx + tw / 2, ly + 2)
            if mt - 4 <= box[1] and box[3] <= h - mb and not any(
                    box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                break
        placed.append(box)
        lead = (f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx:.1f}" y2="{ly - 3:.1f}" stroke="{MUTED}" stroke-width="0.6"/>'
                if abs(ly - (cy - r - 4)) > 1 and abs(ly - (cy + r + 13)) > 1 else "")
        labels.append(f'{lead}<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" class="lb">{e(p["segment"])}</text>')
    out += labels
    out.append(f'<text x="{(ml + w - mr) / 2:.0f}" y="{h - 8}" text-anchor="middle" class="ax">Jumlah outlet</text>'
               f'<text x="16" y="{(mt + h - mb) / 2:.0f}" text-anchor="middle" class="ax" '
               f'transform="rotate(-90 16 {(mt + h - mb) / 2:.0f})">Rata-rata M (KL/bulan)</text></svg>')
    return "".join(out)


# ==========================================================================
# Komponen HTML
# ==========================================================================
def kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return (f'<div class="card kpi span3 {tone}"><div class="kpi-l">{e(label)}</div><div class="kpi-v">{e(value)}</div>'
            f'<div class="kpi-s">{e(sub)}</div></div>')


def table(headers: list[str], rows: list[list], cls: str = "", num_from: int = 1, wide: bool = False) -> str:
    th = "".join(f'<th class="{"num" if i >= num_from else ""}">{e(h)}</th>' for i, h in enumerate(headers))
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            if isinstance(c, tuple):                                   # (teks, kelas)
                tds.append(f'<td class="{c[1]}">{e(c[0])}</td>')
            else:
                tds.append(f'<td class="{"num" if i >= num_from else "txt"}">{e(c)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    t = f'<table class="tbl {cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    return f'<div class="tbl-wrap{" wide" if wide else ""}">{t}</div>'


def card(title: str, body: str, span: int = 12, sub: str = "") -> str:
    return (f'<div class="card span{span}"><div class="card-h"><h3>{e(title)}</h3>'
            + (f'<span class="card-sub">{e(sub)}</span>' if sub else "") + f'</div>{body}</div>')


def note(text: str) -> str:
    return f'<p class="note">{e(text)}</p>'


def insight(text: str, label: str = "INTERPRETASI") -> str:
    return f'<div class="insight"><div class="ins-l">{e(label)}</div><p>{e(text)}</p></div>'


def section(num: str, title: str, headline: str, body: str) -> str:
    return (f'<section class="sec" id="s{num}"><div class="sec-k">{e(num)} / {e(title)}</div>'
            f'<h2>{e(headline)}</h2><div class="grid">{body}</div></section>')


def heat_class(v) -> str:
    if v is None:
        return "h0"
    return "h5" if v >= 60 else "h4" if v >= 40 else "h3" if v >= 20 else "h2" if v >= 5 else "h1"


def _yoy_cls(v) -> str:
    return "num pos" if v is not None and v > 0 else "num neg" if v is not None and v < 0 else "num"


# ==========================================================================
# Halaman
# ==========================================================================
def render_html(res: dict[str, Any], narr: dict[str, Any], credit: str = "Prepared with Marketing Insight Assistant",
                source: str = "Selling Out Intelligence — ptpl-curated-prd.DATAMART.SALES_OUT_DAILY",
                fetched_at: str = "") -> str:  # noqa: C901
    k, w, t, p = res["kpi"], res["window"], res["thresholds"], res["products"]
    seg = {s["segment"]: s for s in res["segments"]}
    mom = {m["status"]: m for m in res["momentum"]}
    scope = res["scope_label"]
    region_tag = res["scope"] if res["scope"] != "NASIONAL" else "Nasional"
    yt, yp, yb = w["label_ytd"], w["label_ytd_prev"], w["label_base"]
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    # ---------------- 01 EXECUTIVE OVERVIEW
    ch = seg.get("Champions", {})
    pl = seg.get("Potential Loyalists", {})
    s1 = "".join([
        kpi(f"Volume {yt}", f"{n2(k['vol_ytd'])} KL", f"{yp}: {n2(k['vol_ytd_prev'])} KL"),
        kpi("YoY total dataset", pc(k["yoy_total_pct"], sign=True), f"Baseline cohort {pc(k['yoy_cohort_pct'], sign=True)}",
            "kg" if (k["yoy_total_pct"] or 0) >= 0 else "kr"),
        kpi("Outlet valid", n0(k["outlets_valid"]), f"{n0(k['outlets_baseline'])} baseline · {n0(k['outlets_entrants'])} entrants"),
        kpi("Champions", f"{n0(ch.get('outlets', 0))} outlet", f"{pc(ch.get('vol_share'))} volume YTD", "kg"),
        kpi("Potential Loyalists", f"{n0(pl.get('outlets', 0))} outlet", f"{pc(pl.get('vol_share'))} volume YTD"),
        kpi("Deteriorated", f"{n0(mom.get('Deteriorated', {}).get('outlets', 0))} outlet",
            f"{pc(mom.get('Deteriorated', {}).get('share'))} baseline cohort", "kr"),
        kpi("Kontribusi entrants", pc(k["entrant_share_pct"]), f"{n2(k['vol_entrants_ytd'])} KL YTD"),
        kpi("Volume / outlet-bulan aktif", f"{n2(k['vol_per_active_outlet_month'], 3)} KL", "denominator: outlet-bulan "
            "dengan pembelian positif YTD"),
        card("Tren volume bulanan", svg_line(res["monthly"]["labels"], [(str(w["y0"]), "#9AA8B5", res["monthly"]["prev"]),
                                                                          (str(w["y1"]), TEAL, res["monthly"]["cur"])]),
             span=7, sub=f"{w['y0']} vs {w['y1']} · KL"),
        card("Komposisi segmen", svg_share_bars(res["segments"]), span=5, sub=f"Snapshot {yt}"),
        card("Ringkasan eksekutif", "<ul class='bul'>" + "".join(f"<li>{e(x)}</li>" for x in narr["ringkasan"]) + "</ul>"
             + insight(narr["interpretasi_overview"]), span=12),
    ])

    # ---------------- 02 RFM ANALYTICS
    seg_rows = [[s["segment"], n0(s["outlets"]), pc(s["outlet_share"]), pc(s["vol_share"]), n2(s["vol_ytd"]),
                 n2(s["avg_m"], 3)] for s in res["segments"]]
    seg_rows.append([("Total", "txt b"), (n0(sum(s["outlets"] for s in res["segments"])), "num b"), ("100,0%", "num b"),
                     ("100,0%", "num b"), (n2(sum(s["vol_ytd"] for s in res["segments"])), "num b"), ("", "num")])
    s2 = "".join([
        card("Peta gelembung segmen", svg_bubble(res["segments"], w=1100, h=380), span=12,
             sub="X = jumlah outlet · Y = rata-rata M · ukuran = volume YTD"),
        card("Ringkasan segmen", table(["Segmen", "Outlet", "% outlet", "% volume", "Volume YTD (KL)", "M rata-rata"],
                                       seg_rows), span=12, sub=f"Snapshot {yt} (baseline + entrants)"),
        card("Interpretasi", insight(narr["interpretasi_rfm"]), span=12),
    ])

    # ---------------- 03 SEGMENT INTELLIGENCE
    mig = res["migration"]
    mrows = []
    for i, a in enumerate(mig["rows"]):
        cells = []
        for j, v in enumerate(mig["cells"][i]):
            cells.append((n0(v) if v else "·", "num diag" if i == j and v else "num" if v else "num z"))
        mrows.append([(a, "txt b")] + cells + [(n0(sum(mig["cells"][i])), "num b")])
    col_tot = [sum(mig["cells"][i][j] for i in range(12)) for j in range(12)]
    mrows.append([("Total", "txt b")] + [(n0(v), "num b") for v in col_tot] + [(n0(mig["total"]), "num b")])
    acts = "".join(f'<div class="act"><span class="pill">{e(a["segmen"])}</span><p>{e(a["aksi"])}</p></div>'
                   for a in narr["aksi_segmen"])
    s3 = "".join([
        kpi("Improved", f"{n0(mom.get('Improved', {}).get('outlets', 0))}", pc(mom.get("Improved", {}).get("share")), "kg"),
        kpi("Stable", f"{n0(mom.get('Stable', {}).get('outlets', 0))}", pc(mom.get("Stable", {}).get("share"))),
        kpi("Deteriorated", f"{n0(mom.get('Deteriorated', {}).get('outlets', 0))}",
            pc(mom.get("Deteriorated", {}).get("share")), "kr"),
        kpi("Baseline cohort", n0(mig["cohort"]), f"Tetap di segmen sama: {n0(mig['stayed'])}"),
        card(f"Matriks perpindahan segmen {w['y0']} → {w['y1']} YTD",
             table(["Segmen 2025 ↓ / YTD →"] + [s.replace(" ", " ") for s in SEGMENTS] + ["Total"], mrows,
                   cls="matrix", wide=True)
             + note(f"Populasi = baseline cohort ({n0(mig['cohort'])} outlet, pembelian positif di {yb}). Jumlah sel = "
                    f"{n0(mig['total'])} ({'terekonsiliasi' if mig['reconciled'] else 'TIDAK terekonsiliasi'}). "
                    "Momentum = perubahan skor R+F+M, bukan bukti perubahan frekuensi transaksi."),
             span=12),
        card("Interpretasi & aksi per segmen", insight(narr["interpretasi_segmen"]) + f'<div class="acts">{acts}</div>', span=12),
    ])

    # ---------------- 04 PRODUCT INTELLIGENCE
    top = p.get("top") or []
    grow = p.get("growth") or []
    if top:
        pen = p["penetration"]
        prow = [[(sname, "txt b"), (n0(v["outlets"]), "num")] + [(pc(x) if x is not None else "n/a", f"num {heat_class(x)}")
                                                                  for x in v["values"]]
                for sname, v in pen["segments"].items()]
        prod_rows = [[r["series"], n2(r["vol_cur"]), n2(r["vol_prev"]), (pc(r["yoy_pct"], sign=True), _yoy_cls(r["yoy_pct"])),
                      pc(r["share"]), (pc(r["cohort_yoy_pct"], sign=True), _yoy_cls(r["cohort_yoy_pct"])), n0(r["buyers"]),
                      pc(r["penetration"])] for r in p["table"][:20]]
        adop_rows = [[r["series"], n0(r["adopted"]), n0(r["discontinued"]),
                      (("+" if r["net_adoption"] > 0 else "") + n0(r["net_adoption"]), _yoy_cls(r["net_adoption"]))]
                     for r in p["adoption"]]
        s4 = "".join([
            card("Top 10 seri produk", svg_hbar([r["series"] for r in top], [r["vol_cur"] for r in top], TEAL, " KL"),
                 span=6, sub=f"Volume {yt}"),
            card("Pertumbuhan comparable tertinggi",
                 svg_hbar([r["series"] for r in grow], [r["cohort_yoy_pct"] for r in grow],
                          [TEAL if (r["cohort_yoy_pct"] or 0) >= 0 else PINK for r in grow], "%", fmt=lambda v: n2(v, 1))
                 if grow else '<p class="muted">Tidak ada seri dengan basis memadai.</p>',
                 span=6, sub=f"Baseline cohort, {yt} vs {yp}"),
            card("Kinerja seri produk", table(["Seri", f"Vol {yt}", f"Vol {yp}", "YoY", "Porsi", "YoY cohort", "Outlet beli",
                                               "Penetrasi"], prod_rows, wide=True)
                 + note("Penetrasi = % outlet snapshot YTD yang membeli seri minimal sekali; bukan market share, "
                        "availability, atau technical fit. 20 seri teratas."), span=12),
            card("Heatmap penetrasi per segmen prioritas", table(["Segmen", "Outlet"] + pen["series"], prow, wide=True)
                 + note("Nilai = % outlet di segmen (snapshot YTD) yang membeli seri tersebut."), span=7),
            card("Adopsi & berhenti beli (baseline cohort)", table(["Seri", "Mulai beli", "Berhenti beli", "Neto"], adop_rows)
                 + note(f"Mulai beli = tidak membeli di {yp}, membeli di {yt}; berhenti = sebaliknya."), span=5),
            card("Interpretasi", insight(narr["interpretasi_produk"]), span=12),
        ])
    else:
        s4 = card("Product Intelligence", "<p class='muted'>Data seri produk tidak tersedia dari sumber.</p>", span=12)

    # ---------------- 05 COMMERCIAL PLAYBOOK
    ws_rows = [[x["series"], n0(x["high_value_outlets"]), n0(x["not_buying"]), pc(x["not_buying_share"])]
               for x in res["whitespace"]]
    plan_rows = [[r["fase"], r["fokus"], r["aksi"], r["owner"], r["kpi"], r["ritme"]] for r in narr["rencana_90_hari"]]
    s5 = "".join([
        card("Screening whitespace di segmen bernilai tinggi",
             table(["Seri (top 5)", "Outlet Champions + Loyal", "Belum membeli YTD", "% belum membeli"], ws_rows)
             + note("Hanya hitungan dari data penjualan. Sebelum menjadi rekomendasi produk, validasi aplikasi teknis, "
                    "stok, harga, margin, dan kebutuhan outlet. Bukan anjuran diskon menyeluruh."), span=6),
        card("Rencana 90 hari", table(["Fase", "Fokus", "Aksi", "Owner", "KPI", "Ritme"], plan_rows, num_from=99, cls="plan"),
             span=6),
    ])

    # ---------------- 06 OUTLET PRIORITY LISTS
    def idc(r):
        return [(r["code"], "txt code"), (r["name"], "txt"), (r["type"], "txt code")] + ([(r["region"], "txt code")]
                                                                                       if res["scope"] == "NASIONAL" else [])
    reg_h = ["Region"] if res["scope"] == "NASIONAL" else []
    champ_rows = [idc(r) + [n2(r["vol_ytd"]), n2(r["M"], 3), n2(r["F"]), (r["seg_base"], "txt")] for r in res["top_champions"]]
    dec_rows = [idc(r) + [n2(r["vol_prev"]), n2(r["vol_cur"]), (n2(r["change"]), "num neg"), pc(r["pct"], sign=True),
                          (f'{r["seg_base"]} → {r["seg_ytd"]}', "txt")] for r in res["top_declines"]]
    rec_rows = [idc(r) + [n2(r["vol_base"]), n2(r["vol_cur"]), (r["seg_ytd"], "txt"), (r["last"], "txt")] for r in res["recovery"]]
    s6 = "".join([
        card("Top 20 Champions berdasarkan volume YTD",
             table(["Customer Code", "Nama", "Tipe"] + reg_h + [f"Vol {yt}", "M (KL/bln)", "F YTD", f"Segmen {w['y0']}"],
                   champ_rows, num_from=3 + len(reg_h), wide=True), span=12),
        card("Top 20 penurunan volume comparable",
             table(["Customer Code", "Nama", "Tipe"] + reg_h + [f"Vol {yp}", f"Vol {yt}", "Perubahan", "%", "Segmen"],
                   dec_rows, num_from=3 + len(reg_h), wide=True), span=12),
        card("Kandidat pemulihan bernilai tinggi",
             table(["Customer Code", "Nama", "Tipe"] + reg_h + [f"Vol {yb}", f"Vol {yt}", "Segmen YTD", "Beli terakhir"],
                   rec_rows, num_from=3 + len(reg_h), wide=True)
             + note("Segmen YTD Can't Lose Them / At Risk / Hibernating / Lost, diurutkan volume tahun dasar. Nama dari "
                    "kolom CUSTOMER_NAME datamart; status outlet perlu diverifikasi Sales sebelum tindak lanjut."), span=12),
    ])

    # ---------------- 07 BUSINESS MOMENTUM
    q_rows = [[x["quarter"], n2(x["vol_prev"]), n2(x["vol_cur"]), (pc(x["yoy_pct"], sign=True), _yoy_cls(x["yoy_pct"])),
               n0(x["active_prev"]), n0(x["active_cur"])] for x in res["quarters"]]
    snap_rows = [["Total dataset", n0(k["outlets_valid"]), n2(k["vol_ytd_prev"]), n2(k["vol_ytd"]),
                  (pc(k["yoy_total_pct"], sign=True), _yoy_cls(k["yoy_total_pct"]))],
                 ["Baseline cohort", n0(k["outlets_baseline"]), n2(k["vol_cohort_ytd_prev"]), n2(k["vol_cohort_ytd"]),
                  (pc(k["yoy_cohort_pct"], sign=True), _yoy_cls(k["yoy_cohort_pct"]))],
                 ["Dataset Entrants", n0(k["outlets_entrants"]), "0,00", n2(k["vol_entrants_ytd"]), "n/a"],
                 [f"FY {w['y0']} (12 bulan)", n0(k["outlets_baseline"]), n2(k["vol_base_fy"]), "", ""]]
    st_rows = [[f'{x["key"]} · {x["label"]}', n0(x["outlets"]), n2(x["vol_ytd_prev"]), n2(x["vol_ytd"]),
                (pc(x["yoy_pct"], sign=True), _yoy_cls(x["yoy_pct"])), pc(x["vol_share"])] for x in res["store_types"]]
    s7 = [card("Kuartal comparable", table(["Kuartal", f"Vol {w['y0']}", f"Vol {w['y1']}", "YoY", f"Outlet aktif {w['y0']}",
                                            f"Outlet aktif {w['y1']}"], q_rows), span=6),
          card("Snapshot & cohort", table(["Populasi", "Outlet", f"Vol {yp}", f"Vol {yt}", "YoY"], snap_rows), span=6),
          card("Profil tipe outlet", table(["Tipe outlet", "Outlet", f"Vol {yp}", f"Vol {yt}", "YoY", "Porsi"], st_rows), span=12)]
    if res.get("regions"):
        r_rows = [[f'{x["key"]} · {x["label"]}', n0(x["outlets"]), n0(x["entrants"]), n2(x["vol_ytd_prev"]), n2(x["vol_ytd"]),
                   (pc(x["yoy_pct"], sign=True), _yoy_cls(x["yoy_pct"])), pc(x["vol_share"])] for x in res["regions"]]
        rs_rows = [[(x["region"], "txt b"), n0(x["outlets"])] + [n0(x[s]) for s in SEGMENTS] for x in res["region_segments"]]
        s7 += [card("Kinerja per Sales Region", table(["Region", "Outlet", "Entrants", f"Vol {yp}", f"Vol {yt}", "YoY", "Porsi"],
                                                     r_rows), span=12),
               card("Segmen RFM per Sales Region (threshold nasional)",
                    table(["Region", "Outlet"] + [s.replace(" ", " ") for s in SEGMENTS], rs_rows, wide=True)
                    + note("Laporan per region memakai threshold baseline region masing-masing, sehingga angka segmennya "
                           "dapat berbeda dari tabel ini."), span=12)]
    s7.append(card("Interpretasi", insight(narr["interpretasi_momentum"]), span=12))
    s7 = "".join(s7)

    # ---------------- 08 METHODOLOGY & DATA GOVERNANCE
    a, v125, chk = res["audit"], res["validation_125"], res["checks"]
    defs = [["R — Recency Months", "Jarak bulan kalender dari bulan pembelian positif terakhir ke bulan cut-off snapshot."],
            ["F — Active Month Ratio", f"Bulan dengan pembelian positif ÷ jumlah bulan snapshot (12 untuk {w['y0']}; "
                                       f"{w['n_ytd']} untuk YTD). Proxy kontinuitas, bukan frekuensi transaksi."],
            ["M — Monthly Volume Rate", "Volume bersih snapshot ÷ jumlah bulan snapshot (KL/bulan)."],
            ["Baseline cohort", f"Outlet valid dengan pembelian positif di {yb}; dipakai untuk migrasi & momentum."],
            ["Dataset Entrants", f"Outlet tanpa pembelian di {yb} yang membeli di {yt}. Data mulai Jan {w['y0']} "
                                 "(left-censoring) — bukan bukti akuisisi."],
            ["Special case", "Outlet baseline tanpa pembelian YTD: skor F = 1 dan M = 1."]]
    thr = [["F — Active Month Ratio"] + [n2(x, 4) for x in t["F"]], ["M — Monthly Volume Rate (KL/bln)"] + [n2(x, 4) for x in t["M"]]]
    rband = [[b, d] for b, d in R_BANDS]
    rules = [[f"{i + 1:02d}", s, SEGMENT_RULES[i]] for i, s in enumerate(SEGMENTS)]
    aud = [["Baris sumber dalam periode", n0(a.get("rows_total"))],
           ["Baris Customer Code kosong / placeholder (dikeluarkan)", n0(a.get("rows_bad_id"))],
           ["Baris MEDITRAN SX BIO SERIES (dikeluarkan)", n0(a.get("rows_excluded_series"))],
           ["Baris volume negatif (retur; dihitung sebagai volume bersih)", n0(a.get("rows_negative"))],
           ["Baris volume nol", n0(a.get("rows_zero"))],
           ["Outlet semua tipe / outlet Bengkel & Toko Oli (nasional)",
            f'{n0(a.get("outlets_all_types"))} / {n0(a.get("outlets_selected_types"))}'],
           ["Outlet dengan lebih dari satu region (region dominan dipakai)", n0(a.get("outlets_multi_region"))],
           ["Outlet cakupan ini tanpa pembelian positif (dikeluarkan)", n0(a.get("outlets_no_positive_purchase"))],
           ["Bulan data pertama / terakhir", f'{str(a.get("first_month", ""))[:7]} / {str(a.get("last_month", ""))[:7]}'],
           ["Validasi 125 kombinasi", f'{v125["status"]} · {v125["tested"]} diuji · {v125["unassigned"]} tanpa segmen · '
                                      f'{v125["overlaps_resolved"]} overlap diselesaikan urutan first-match'],
           ["Rekonsiliasi matriks migrasi", "PASS" if chk["migration_reconciled"] else "FAIL"],
           ["Rekonsiliasi segmen snapshot", "PASS" if chk["segments_reconciled"] else "FAIL"]]
    limits = ["Satuan volume: KL dari kolom TOTAL_VOL_KL_DELIVERED (volume terkirim, per deskripsi skema datamart).",
              "Tanggal: DT_PR. Deskripsi skema menyebut DT_PR sebagai tanggal proses/partisi — konfirmasi ke pemilik data "
              "bahwa DT_PR mewakili tanggal transaksi.",
              "Region dan tipe outlet: dari kolom REGION_NAME dan STORETYPE_CODE; outlet dengan beberapa nilai memakai "
              "nilai dengan volume terbesar.",
              "Grain sumber transaksi harian, dijumlah menjadi Customer Code × bulan; tidak ada perhitungan frekuensi "
              "invoice/transaksi.",
              "Visual QA: struktur & rekonsiliasi diperiksa otomatis oleh kode; pemeriksaan render di browser belum "
              "dilakukan oleh sistem — periksa tampilan sebelum distribusi resmi."]
    s8 = "".join([
        card("Definisi", table(["Istilah", "Definisi"], defs, num_from=99), span=7),
        card("Band Recency", table(["Skor", "Recency"], rband, num_from=99), span=5),
        card(f"Threshold F & M ({t['basis']})", table(["Dimensi", "P20", "P40", "P60", "P80"], thr)
             + note(f"Dikalibrasi dari {n0(t['n_baseline'])} outlet baseline; dipakai sama untuk snapshot {w['y0']} dan YTD. "
                    f"Metode: {t['method']}."), span=7),
        card("Aturan 12 segmen (first-match)", table(["#", "Segmen", "Aturan"], rules, num_from=99), span=5),
        card("Audit data & validasi", table(["Pemeriksaan", "Hasil"], aud, num_from=99), span=7),
        card("Keterbatasan & konfirmasi", "<ul class='bul'>" + "".join(f"<li>{e(x)}</li>" for x in limits) + "</ul>", span=5),
    ])

    body = "".join([
        section("01", "EXECUTIVE OVERVIEW", narr["headline"], s1),
        section("02", "RFM ANALYTICS", "Konsentrasi nilai per segmen", s2),
        section("03", "SEGMENT INTELLIGENCE", "Momentum & perpindahan segmen baseline cohort", s3),
        section("04", "PRODUCT INTELLIGENCE", "Kinerja, pertumbuhan & penetrasi seri produk", s4),
        section("05", "COMMERCIAL PLAYBOOK", "Prioritas komersial 90 hari", s5),
        section("06", "OUTLET PRIORITY LISTS", "Daftar outlet untuk tindak lanjut Sales", s6),
        section("07", "BUSINESS MOMENTUM", "Kuartal comparable, cohort & entrants", s7),
        section("08", "METHODOLOGY & DATA GOVERNANCE", "Definisi, threshold, audit & keterbatasan", s8),
    ])
    title = f"PTPL RFM Retail Outlet Intelligence — {scope} · {yt}"
    return f"""<!DOCTYPE html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body>
<header class="hero"><div class="hero-in"><div class="kicker">PT PERTAMINA LUBRICANTS · MARKETING INTELLIGENCE &amp; RESEARCH</div>
<h1>RFM Retail Outlet Intelligence — {e(scope)}</h1><p class="lead">{e(narr['headline'])}</p>
<div class="chips"><span>Bengkel &amp; Toko Oli</span><span>Snapshot {e(yt)} vs {e(yp)}</span><span>Baseline {e(yb)}</span>
<span>Sumber: Selling Out Intelligence</span><span>Dibuat {e(stamp)}</span></div></div></header>
<main class="wrap">{body}</main>
<footer class="foot"><span>Marketing Intelligence &amp; Research — PTPL {w['y1']}</span>
<span>RFM Retail Outlet Intelligence • {'Sales Region ' + e(region_tag[2:]) if region_tag.startswith('SR') else e(region_tag)}</span>
<span>{e(credit)}</span></footer>
<div class="src">Sumber data: {e(source)}{(' · data diambil ' + e(fetched_at)) if fetched_at else ''}</div>
</body></html>"""



def render_index(items: list[dict[str, Any]], credit: str = "Prepared with Marketing Insight Assistant",
                 source: str = "", fetched_at: str = "", pending: list[str] | None = None) -> str:
    """Halaman paket: perbandingan nasional & region (angka dari kode) + tautan ke tiap laporan dan register."""
    res0 = items[0]["res"]
    w = res0["window"]
    yt, yp, yb = w["label_ytd"], w["label_ytd_prev"], w["label_base"]
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    rows, links = [], []
    for it in items:
        r = it["res"]
        k = r["kpi"]
        seg = {x["segment"]: x for x in r["segments"]}
        mom = {m["status"]: m for m in r["momentum"]}
        ch = seg.get("Champions", {})
        rows.append([r["scope_label"], n0(k["outlets_valid"]), n0(k["outlets_baseline"]), n0(k["outlets_entrants"]),
                     n2(k["vol_ytd"]), (pc(k["yoy_total_pct"], sign=True), _yoy_cls(k["yoy_total_pct"])),
                     (pc(k["yoy_cohort_pct"], sign=True), _yoy_cls(k["yoy_cohort_pct"])),
                     n0(ch.get("outlets", 0)), pc(ch.get("vol_share")),
                     n0(mom.get("Improved", {}).get("outlets", 0)), n0(mom.get("Deteriorated", {}).get("outlets", 0)),
                     n2(r["thresholds"]["M"][-1], 3)])
        links.append(f'<div class="card span3 kpi"><div class="kpi-l">{e(r["scope_label"])}</div>'
                     f'<div class="kpi-v" style="font-size:18px">{n0(k["outlets_valid"])} outlet</div>'
                     f'<div class="kpi-s"><a href="{e(it["html"])}" target="_blank">Laporan HTML</a> · '
                     f'<a href="{e(it["xlsx"])}" target="_blank">Excel register</a></div></div>')
    head = ["Cakupan", "Outlet valid", "Baseline", "Entrants", f"Volume {yt} (KL)", "YoY total", "YoY cohort",
            "Champions", "Champions % vol", "Improved", "Deteriorated", "Threshold M P80 (KL/bln)"]
    body = card("Perbandingan cakupan", table(head, rows, wide=True), span=12,
                sub=f"{yt} vs {yp} · threshold F/M dihitung dari baseline {yb} masing-masing cakupan")
    body += "".join(links)
    notes = ["Setiap region memakai threshold F/M dari baseline region itu sendiri; laporan nasional memakai baseline "
             "nasional. Karena itu jumlah segmen region tidak dijumlahkan menjadi angka nasional.",
             "Outlet dihitung di region dominannya (volume terbesar) agar tidak tercatat ganda."]
    if pending:
        notes.append("Belum dibuat di paket ini (batas waktu satu pesan): " + ", ".join(pending)
                     + ". Ketik 'lanjut' untuk melengkapinya.")
    body += card("Catatan", "<ul class='bul'>" + "".join(f"<li>{e(x)}</li>" for x in notes) + "</ul>", span=12)
    title = f"PTPL RFM Retail Outlet Intelligence — Paket Laporan · {yt}"
    return f"""<!DOCTYPE html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body>
<header class="hero"><div class="hero-in"><div class="kicker">PT PERTAMINA LUBRICANTS · MARKETING INTELLIGENCE &amp; RESEARCH</div>
<h1>RFM Retail Outlet Intelligence — Paket Laporan</h1>
<p class="lead">{len(items)} laporan: {e(", ".join(it["res"]["scope_label"] for it in items))}</p>
<div class="chips"><span>Bengkel &amp; Toko Oli</span><span>Snapshot {e(yt)} vs {e(yp)}</span><span>Baseline {e(yb)}</span>
<span>Dibuat {e(stamp)}</span></div></div></header>
<main class="wrap">{section("00", "RINGKASAN PAKET", "Nasional & Sales Region dalam satu tampilan", body)}</main>
<footer class="foot"><span>Marketing Intelligence &amp; Research — PTPL {w['y1']}</span>
<span>RFM Retail Outlet Intelligence • Paket Laporan</span><span>{e(credit)}</span></footer>
<div class="src">Sumber data: {e(source)}{(' · data diambil ' + e(fetched_at)) if fetched_at else ''}</div>
</body></html>"""


CSS = f"""@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,'Segoe UI',Arial,sans-serif;background:{PAPER};color:{INK};font-size:14px;line-height:1.5;
font-variant-numeric:tabular-nums}}
.hero{{background:linear-gradient(120deg,{NAVY} 0%,#1d5a6e 55%,{TEAL} 100%);color:#fff;padding:36px 0 30px}}
.hero-in,.wrap{{max-width:1320px;margin:0 auto;padding:0 28px}}
.kicker{{font-size:12px;letter-spacing:1.4px;font-weight:700;color:#bfeee9;text-transform:uppercase}}
.hero h1{{font-size:30px;font-weight:800;margin:8px 0 6px;letter-spacing:-.3px}}
.lead{{font-size:17px;color:#e8f6f4;max-width:980px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}}
.chips span{{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);border-radius:999px;padding:4px 12px;font-size:12px}}
.sec{{padding:30px 0 6px}}
.sec-k{{color:{TEAL};font-weight:800;font-size:12.5px;letter-spacing:1.3px}}
.sec h2{{color:{NAVY};font-size:22px;font-weight:800;margin:4px 0 16px}}
.grid{{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px}}
.grid>*{{min-width:0}}
.span3{{grid-column:span 3}}.span4{{grid-column:span 4}}.span5{{grid-column:span 5}}.span6{{grid-column:span 6}}
.span7{{grid-column:span 7}}.span8{{grid-column:span 8}}.span12{{grid-column:span 12}}
.card{{background:#fff;border:1px solid {LINE};border-radius:14px;padding:18px 20px;box-shadow:0 1px 3px rgba(24,50,75,.06)}}
.card-h{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:12px}}
.card-h h3{{font-size:15px;color:{NAVY};font-weight:700}}
.card-sub{{font-size:12px;color:{MUTED}}}
.kpi{{border-top:4px solid {NAVY}}}.kpi.kg{{border-top-color:{TEAL}}}.kpi.kr{{border-top-color:{PINK}}}
.kpi-l{{font-size:11.5px;font-weight:700;letter-spacing:.6px;color:{MUTED};text-transform:uppercase}}
.kpi-v{{font-size:26px;font-weight:800;color:{NAVY};margin:4px 0 2px;white-space:nowrap}}
.kpi-s{{font-size:12.5px;color:{MUTED}}}
svg{{width:100%;height:auto;display:block}}
svg .ax{{font-size:11px;fill:{MUTED}}} svg .lb{{font-size:11.5px;fill:{INK}}} svg .vl{{font-size:11px;fill:{INK};font-weight:600}}
svg .lg{{font-size:12px;fill:{INK}}}
.tbl-wrap{{max-width:100%;min-width:0;overflow-x:auto}}
.tbl{{width:100%;border-collapse:collapse;font-size:12.5px}}
.tbl-wrap.wide .tbl{{width:max-content;min-width:100%}}
.tbl th{{background:#EAF2F7;color:{NAVY};font-weight:700;text-align:left;padding:8px 10px;border-bottom:2px solid #d3e1ea;
white-space:nowrap}}
.tbl td{{padding:7px 10px;border-bottom:1px solid {LINE};vertical-align:top}}
.tbl th.num,.tbl td.num{{text-align:right;white-space:nowrap}}
.tbl td.txt{{white-space:normal}} .tbl td.code{{white-space:nowrap;font-family:'Segoe UI',Arial,sans-serif;color:{NAVY}}}
.tbl td.b{{font-weight:700;color:{NAVY}}} .tbl tr:last-child td{{border-bottom:none}}
.tbl td.pos{{color:{TEAL};font-weight:700}} .tbl td.neg{{color:#c2415b;font-weight:700}}
.matrix td,.matrix th{{text-align:center;min-width:76px}} .matrix td:first-child,.matrix th:first-child{{text-align:left;min-width:170px}}
.matrix td.diag{{background:#dff3f0;font-weight:700;color:{NAVY}}} .matrix td.z{{color:#c5ced6}}
.plan td{{white-space:normal}}
.h0{{background:#f6f8fa}}.h1{{background:#eef8f7}}.h2{{background:#d7f0ed}}.h3{{background:#ade3dc}}.h4{{background:#7fd1c6;font-weight:700}}
.h5{{background:{TEAL};color:#fff;font-weight:700}}
.insight{{background:#f2faf9;border-left:4px solid {TEAL};border-radius:8px;padding:12px 14px;margin-top:12px}}
.ins-l{{font-size:11px;font-weight:800;letter-spacing:1px;color:{TEAL}}}
.insight p{{margin-top:4px}}
.bul{{padding-left:20px}} .bul li{{margin:5px 0}}
.acts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:12px}}
.act{{border:1px solid {LINE};border-radius:10px;padding:10px 12px}} .act p{{margin-top:6px;font-size:13px}}
.pill{{display:inline-block;background:{NAVY};color:#fff;border-radius:999px;padding:2px 10px;font-size:11.5px;font-weight:700}}
.note{{font-size:12px;color:{MUTED};margin-top:10px}} .muted{{color:{MUTED}}}
.foot{{max-width:1320px;margin:32px auto 0;padding:16px 28px;border-top:1px solid #d3dde6;display:flex;
justify-content:space-between;flex-wrap:wrap;gap:8px;color:{MUTED};font-size:12.5px}}
.src{{max-width:1320px;margin:0 auto 28px;padding:0 28px;color:{MUTED};font-size:11.5px}}
@media (max-width:1000px){{.span3{{grid-column:span 6}}.span4,.span5,.span6,.span7,.span8{{grid-column:span 12}}}}
@media print{{body{{background:#fff}}.sec{{break-inside:auto}}.card{{break-inside:avoid;box-shadow:none}}
*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}.tbl-wrap{{overflow:visible}}}}"""
