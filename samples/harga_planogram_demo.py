"""Contoh laporan "Harga × Planogram" dengan DESAIN yang sama seperti dashboard daya saing harga.

Menunjukkan konsep laporan dinamis: tata letak, font, dan warna mengikuti template laporan PTPL,
sedangkan isi (tab, KPI, kolom tabel, grafik, insight) disusun sesuai permintaan user.
SEMUA ANGKA DI SINI ADALAH ILUSTRASI.

Jalankan:  python samples/harga_planogram_demo.py  (hasil di samples/out/)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library_agent import dashboard_render as dr  # noqa: E402
from library_agent.price_dashboard import gap_tone, num, rp  # noqa: E402

PERIOD = "Juli 2026"
STATUS = ["Sesuai planogram", "Sebagian sesuai", "Tidak sesuai"]
ZONES = ["Nasional", "Zona 1", "Zona 2", "Zona 3"]
# (status, zona) -> (gap HJ, gap margin, jumlah outlet, facing PTPL %)
DATA = {
    ("Sesuai planogram", "Nasional"): (-9120, 640, 412, 38), ("Sebagian sesuai", "Nasional"): (-6480, 210, 268, 27),
    ("Tidak sesuai", "Nasional"): (-4310, -380, 196, 16),
    ("Sesuai planogram", "Zona 1"): (-9650, 710, 188, 40), ("Sebagian sesuai", "Zona 1"): (-7020, 260, 112, 29),
    ("Tidak sesuai", "Zona 1"): (-4870, -290, 74, 17),
    ("Sesuai planogram", "Zona 2"): (-8810, 590, 121, 37), ("Sebagian sesuai", "Zona 2"): (-6150, 180, 86, 26),
    ("Tidak sesuai", "Zona 2"): (-3920, -460, 69, 15),
    ("Sesuai planogram", "Zona 3"): (-8640, 560, 103, 35), ("Sebagian sesuai", "Zona 3"): (-5890, 150, 70, 24),
    ("Tidak sesuai", "Zona 3"): (-3780, -410, 53, 14),
}
HEROES = [  # (segmen, hero, gap HJ sesuai, gap HJ tidak sesuai, margin sesuai, margin tidak)
    ("MCO", "ENDURO MATIC-S 0.8L", -9840, -5120, 10910, 9870),
    ("MCO", "ENDURO 4T 1L", -6230, -2980, 8120, 7340),
    ("PCO", "FASTRON ECOGREEN 5W-30 3.5L", -18450, -11020, 15230, 13980),
    ("PCO", "FASTRON TECHNO 10W-40 4L", -12780, -7410, 13110, 12090),
    ("COMMERCIAL", "MEDITRAN SC DIESEL 15W-40 5L", 410, 2950, 9820, 8710),
    ("COMMERCIAL", "MEDITRAN S 40 5L", -4120, -1260, 8930, 8240),
]
OUTLETS = [  # outlet, zona, status, facing %, gap HJ, gap margin, tren facing 4 bulan
    ("BENGKEL SINAR MOTOR · BEKASI", "Zona 1", "Tidak sesuai", 9, 1840, -720, [15, 13, 11, 9]),
    ("TOKO OLI MAJU JAYA · PALEMBANG", "Zona 2", "Tidak sesuai", 11, 950, -610, [18, 16, 13, 11]),
    ("BENGKEL BERKAH · MAKASSAR", "Zona 3", "Sebagian sesuai", 18, 420, -330, [24, 22, 20, 18]),
]
TONE_BY_STATUS = {"Sesuai planogram": "AMAN", "Sebagian sesuai": "WATCH", "Tidak sesuai": "KRITIS"}
STATUS_TONE = {"AMAN": "low", "WATCH": "mid", "KRITIS": "high"}


def exec_page() -> dict:
    cards = []
    for z, nick in zip(ZONES, ["RERATA RI", "JAWA-NUSRA", "SUMATRA-KALTIM", "SUMUT & TIMUR"]):
        s, t = DATA[("Sesuai planogram", z)], DATA[("Tidak sesuai", z)]
        total = sum(DATA[(st, z)][2] for st in STATUS)
        cards.append({"title": z.upper() if z != "Nasional" else "NASIONAL (AVERAGE)", "subtitle": nick,
                      "metrics": [{"label": "Outlet sesuai planogram:", "value": f"{round(100 * s[2] / total)}%", "tone": None},
                                  {"label": "Gap HJ outlet sesuai:", "value": rp(s[0]), "tone": gap_tone(s[0])},
                                  {"label": "Gap HJ outlet tidak sesuai:", "value": rp(t[0]), "tone": gap_tone(t[0])},
                                  {"label": "Facing PTPL (sesuai):", "value": f"{s[3]}%", "tone": "low"}],
                      "note_label": "Kondisi Juli:", "note": "Outlet sesuai planogram punya keunggulan harga lebih lebar."})
    groups = [("STATUS PLANOGRAM", 1)] + [(z.upper() if z == "Nasional" else f"{z.upper()}", 2) for z in ZONES] + [("OUTLET", 1)]
    cols = [""] + ["GAP HJ", "GAP MARG"] * 4 + ["JUMLAH"]
    rows = [{"kind": "group", "cells": ["SEMUA HERO SKU (RETAIL OUTLET)"] + [""] * (len(cols) - 1), "tones": [None] * len(cols)}]
    for st in STATUS:
        cells, tones = [st], [None]
        for z in ZONES:
            g, m, _, _ = DATA[(st, z)]
            cells += [rp(g, False), rp(m, False)]
            tones += [gap_tone(g), gap_tone(m, "positif")]
        cells.append(num(DATA[(st, "Nasional")][2]))
        tones.append(None)
        rows.append({"kind": "hero" if st == "Tidak sesuai" else "viscosity", "cells": cells, "tones": tones})
    charts = [
        {"judul": "GAP HJ PER STATUS PLANOGRAM", "jenis": "bar", "satuan": "IDR/L", "kategori": STATUS,
         "seri": [{"nama": z, "nilai": [DATA[(st, z)][0] for st in STATUS]} for z in ZONES], "catatan": ""},
        {"judul": "GAP MARGIN PER STATUS PLANOGRAM", "jenis": "bar", "satuan": "IDR/L", "kategori": STATUS,
         "seri": [{"nama": z, "nilai": [DATA[(st, z)][1] for st in STATUS]} for z in ZONES], "catatan": ""},
    ]
    insights = [
        {"kategori": "I. CONSUMER VIEW · DAMPAK PLANOGRAM PADA HARGA", "judul": "Outlet sesuai planogram lebih kompetitif",
         "uraian": "Gap HJ nasional outlet sesuai planogram −Rp 9.120/L, lebih lebar dibanding outlet tidak sesuai −Rp 4.310/L.",
         "tingkat": "positif"},
        {"kategori": "II. OUTLET VIEW · MARGIN BENGKEL", "judul": "Margin tertekan di outlet tidak sesuai",
         "uraian": "Gap margin outlet tidak sesuai planogram −Rp 380/L, sementara outlet sesuai +Rp 640/L.", "tingkat": "kritis"},
        {"kategori": "III. PRIORITAS · PERBAIKAN DISPLAY", "judul": "196 outlet tidak sesuai planogram",
         "uraian": "Perbaikan display di 196 outlet tidak sesuai berpotensi memperlebar keunggulan harga PTPL.", "tingkat": "perhatian"},
    ]
    return {"tab": "★ EXECUTIVE SUMMARY", "kind": "exec", "tag": "BOARD OF DIRECTORS & COMMISSIONERS REPORT",
            "title": f"Executive Summary: Pengaruh Kepatuhan Planogram terhadap Daya Saing Harga Retail ({PERIOD})",
            "subtitle": f"Data planogram (unggahan user) × Survey Harga Jual & Tebus · {PERIOD}",
            "zone_cards": cards,
            "bullets": ["Outlet sesuai planogram mencatat gap HJ −Rp 9.120/L vs −Rp 4.310/L di outlet tidak sesuai (nasional).",
                        "Meditran SC Diesel 15W-40 tetap berisiko di outlet tidak sesuai planogram (gap HJ +Rp 2.950/L)."],
            "sec": {"table": ("CROSS-TAB STATUS PLANOGRAM × GAP HARGA", f"{PERIOD.upper()} (IDR/L)"),
                    "insights": ("STRATEGIC ACTIONABLE INSIGHTS", "REKOMENDASI C-LEVEL")},
            "table": {"columns": cols, "groups": groups, "rows": rows,
                      "note": "▸ Gap HJ = PTPL − kompetitor (negatif = PTPL lebih murah) · Gap Marg positif = margin PTPL lebih besar."},
            "charts": charts, "insights": insights}


def crosstab_page() -> dict:
    kpis = []
    for label, val, tone, detail, extra, status in [
        ("▲ OUTLET SESUAI PLANOGRAM", "47%", None, "412 dari 876 outlet survei", "Kepatuhan tertinggi di Zona 1.", "AMAN"),
        ("▲ GAP HJ · OUTLET SESUAI", rp(-9120), "low", "Tidak sesuai: −4.310/L", "Keunggulan harga 2x lebih lebar.", "AMAN"),
        ("▲ GAP HJ · TIDAK SESUAI", rp(-4310), "low", "Selisih vs sesuai: 4.810/L", "Mendekati switching zone.", "WATCH"),
        ("▲ GAP MARGIN · TIDAK SESUAI", rp(-380), "high", "Outlet sesuai: +640/L", "Margin bengkel di bawah kompetitor.", "KRITIS"),
    ]:
        chip = {"AMAN": "✓ KOMPETITIF", "WATCH": "⚠ MONITOR", "KRITIS": "⚡ RISK"}[status]
        kpis.append({"label": label, "value": val, "tone": tone, "detail": detail, "extra": extra, "chip": chip,
                     "chip_tone": STATUS_TONE[status]})
    cols = ["HERO SKU / STATUS PLANOGRAM", "OUTLET", "GAP HJ", "MARG PTPL", "GAP MARG", "STATUS"]
    rows, seg_now = [], None
    for seg, hero, g_ok, g_bad, m_ok, m_bad in HEROES:
        if seg != seg_now:
            rows.append({"kind": "group", "cells": [f"{seg} (RETAIL OUTLET)"] + [""] * (len(cols) - 1), "tones": [None] * len(cols)})
            seg_now = seg
        for st, g, m, n in (("Sesuai planogram", g_ok, m_ok, 140), ("Tidak sesuai", g_bad, m_bad, 62)):
            status = "AMAN" if g < -5000 else ("KRITIS" if g > 0 else "WATCH")
            rows.append({"kind": "viscosity" if st.startswith("Sesuai") else "hero",
                         "cells": [f"{hero} · {st}" if st.startswith("Sesuai") else f"▸ {hero} · {st}", num(n), rp(g, False),
                                   num(m), rp(m - 10000, False), status],
                         "tones": [None, None, gap_tone(g), None, gap_tone(m - 10000, "positif"), "status:" + STATUS_TONE[status]]})
    charts = []
    for seg in ("MCO", "PCO", "COMMERCIAL"):
        hs = [h for h in HEROES if h[0] == seg]
        charts.append({"judul": f"SEGMEN {seg} · GAP HJ SESUAI VS TIDAK SESUAI", "jenis": "bar", "satuan": "IDR/L",
                       "kategori": [h[1] for h in hs],
                       "seri": [{"nama": "Sesuai planogram", "nilai": [h[2] for h in hs]},
                                {"nama": "Tidak sesuai", "nilai": [h[3] for h in hs]}], "catatan": ""})
    watch = []
    for outlet, zone, st, facing, g, m, trend in OUTLETS:
        watch.append({"product": outlet, "brand": zone.upper(), "segment": st, "metric": "Facing PTPL",
                      "subtitle": f"Status planogram: {st} · Facing PTPL per bulan",
                      "stats": [("FACING PTPL", f"{facing}%", "high"), ("GAP HJ", rp(g, False), gap_tone(g)),
                                ("GAP MARG", rp(m, False), gap_tone(m, "positif"))],
                      "months": ["APR-26", "MEI-26", "JUN-26", "JUL-26"], "values": [f"{v}%" for v in trend],
                      "tones": ["high"] * len(trend), "caption": f"Facing PTPL turun dari {trend[0]}% menjadi {trend[-1]}%."})
    return {"tab": "ANALISIS SILANG", "kind": "zone", "view": "konsumen", "zone": "Nasional",
            "tag": "PAGE 1 / 1 — PLANOGRAM × PRICING",
            "title": "Analisa Silang Kepatuhan Planogram dan Daya Saing Harga Hero SKU",
            "subtitle": f"Data planogram unggahan user digabung dengan survey harga per outlet · {PERIOD}",
            "zone_label": "NASIONAL · RERATA RI", "kpis": kpis,
            "sec": {"table": ("HERO SKU × STATUS PLANOGRAM", f"GAP HARGA & MARGIN {PERIOD.upper()} (IDR/L)"),
                    "charts": ("PENGARUH PLANOGRAM", "GAP HJ SESUAI VS TIDAK SESUAI"),
                    "insights": ("INSIGHTS PLANOGRAM", "& HARGA"),
                    "watch": ("⚠ OUTLET YANG PERLU DIWASPADAI", "FACING PTPL MENURUN")},
            "table": {"columns": cols, "rows": rows,
                      "note": "▸ Gabungan per outlet (ID outlet) dan Hero SKU · Gap = PTPL − kompetitor (negatif = PTPL lebih murah)."},
            "charts": charts, "anomaly_title": f"ANOMALI PLANOGRAM & HARGA ({PERIOD.upper()})",
            "anomaly": ["Meditran SC Diesel 15W-40 lebih mahal dari kompetitor di outlet tidak sesuai planogram (+Rp 2.950/L).",
                        "Facing PTPL turun 4 bulan berturut-turut di 3 outlet prioritas."],
            "insights": [
                {"kategori": "CONSUMER VIEW", "judul": "Planogram memperkuat keunggulan harga",
                 "uraian": "Gap HJ Enduro Matic-S di outlet sesuai −Rp 9.840/L vs −Rp 5.120/L di outlet tidak sesuai.", "tingkat": "positif"},
                {"kategori": "COMMERCIAL RISK", "judul": "Meditran SC rawan di outlet tidak sesuai",
                 "uraian": "Gap HJ +Rp 2.950/L di outlet tidak sesuai planogram.", "tingkat": "kritis"}],
            "watch": watch,
            "footnote": "Kolom penghubung: ID outlet (data planogram) ↔ OUTLET_ID (survei harga). Status planogram dari kolom kepatuhan di file unggahan."}


def main() -> None:
    pages = [exec_page(), crosstab_page()]
    for p in pages:
        p["footer"] = f"Source Data: Data planogram (unggahan user) × Survey Response Report Retail · {PERIOD} · ILUSTRASI"
        p["topbar"] = f"C-SUITE EXEC DASHBOARD: HARGA × PLANOGRAM OUTLET ({PERIOD.upper()}) · CONTOH ILUSTRASI"
    meta = {"report_title": "Harga × Planogram Outlet", "period_text": f"{PERIOD} · ILUSTRASI", "company": "PT Pertamina Lubricants"}
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    for fmt, fn in (("html", dr.render_html), ("pdf", dr.render_pdf), ("pptx", dr.render_pptx)):
        with open(os.path.join(out, f"contoh_harga_x_planogram.{fmt}"), "wb") as fh:
            fh.write(fn(pages, meta))
    print("OK:", out)


if __name__ == "__main__":
    main()
