"""Isi halaman dashboard daya saing harga + narasi (Gemini) yang angkanya diverifikasi.

Halaman:
  1. Executive Summary (Multizona): kartu per zona, matriks terpadu, 2 grafik, insight strategis.
  2. Per zona (Nasional, Zona 1, 2, 3), masing-masing dua halaman:
     - Konsumen akhir: HET vs Harga Jual
     - Outlet: HTO vs Harga Tebus & margin bengkel
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import price_data as pdm
from .report_render import fmt_id, parse_number

logger = logging.getLogger(__name__)

TREND_SYMBOL = {"membaik": ("▼", "low"), "memburuk": ("▲", "high"), "stabil": ("▬", "muted"), "": ("", None)}
STATUS_TONE = {"AMAN": "low", "WATCH": "mid", "KRITIS": "high", "NA": "muted"}


def rp(value: float | None, per_liter: bool = True) -> str:
    if value is None:
        return "NA"
    text = fmt_id(round(value))
    if value > 0 and not text.startswith("+"):
        text = "+" + text
    return text + ("/L" if per_liter else "")


def num(value: float | None) -> str:
    return "NA" if value is None else fmt_id(round(value))


def gap_tone(value: float | None, good: str = "negatif") -> str | None:
    if value is None or value == 0:
        return None
    good_sign = value < 0 if good == "negatif" else value > 0
    return "low" if good_sign else "high"


# ==========================================================================
# Narasi
# ==========================================================================
NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "ringkasan": {"type": "array", "items": {"type": "string"}},
        "insight_eksekutif": {"type": "array", "items": {"$ref": "#/$defs/insight"}},
        "zona": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "zona": {"type": "string"},
                "kondisi": {"type": "string"},
                "konsumen_insight": {"type": "array", "items": {"$ref": "#/$defs/insight"}},
                "konsumen_anomali": {"type": "array", "items": {"type": "string"}},
                "outlet_insight": {"type": "array", "items": {"$ref": "#/$defs/insight"}},
                "outlet_anomali": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["zona", "kondisi", "konsumen_insight", "konsumen_anomali", "outlet_insight", "outlet_anomali"],
        }},
    },
    "required": ["ringkasan", "insight_eksekutif", "zona"],
    "$defs": {"insight": {
        "type": "object",
        "properties": {"kategori": {"type": "string"}, "judul": {"type": "string"}, "uraian": {"type": "string"},
                       "tingkat": {"type": "string", "enum": ["positif", "perhatian", "kritis"]}},
        "required": ["kategori", "judul", "uraian", "tingkat"],
    }},
}


def _compact(dataset: dict[str, Any]) -> dict[str, Any]:
    pa, pb = dataset["period_a"], dataset["period_b"]
    out = {"periode": pa["label"], "pembanding": pb["label"] if pb else None, "zona": {}}
    th = dataset["thresholds"]
    for z, data in dataset["zones"].items():
        heroes = []
        for h in data["heroes"]:
            a, b = h["a"], h["b"] or {}
            heroes.append({
                "produk": h["short"], "segmen": h["segment"],
                "gap_het": rp(a["GAP_HET"]), "gap_hj": rp(a["GAP_HJ"]), "gap_hto": rp(a["GAP_HTO"]),
                "gap_margin": rp(a["GAP_MARG"]), "hj_ptpl": num(a["HJ_P"]), "hj_komp": num(a["HJ_K"]),
                "margin_ptpl": num(a["MARG_P"]), "margin_komp": num(a["MARG_K"]),
                "status_hto": pdm.status_of(a["GAP_HTO"], th["aman_below"], th["kritis_above"]),
                **({"gap_hj_pembanding": rp(b.get("GAP_HJ")), "gap_hto_pembanding": rp(b.get("GAP_HTO")),
                    "tren_hj": pdm.trend_of(a["GAP_HJ"], b.get("GAP_HJ")),
                    "tren_hto": pdm.trend_of(a["GAP_HTO"], b.get("GAP_HTO"))} if b else {}),
            })
        watch = [{"produk": w["product"], "brand": w["brand"], "gap_hj_awal": rp(w["first"]),
                  "gap_hj_akhir": rp(w["last"])} for w in data["watch_hj"]]
        out["zona"][z] = {"hero": heroes, "kompetitor_menyempit": watch}
    return out


def narrative_prompt(dataset: dict[str, Any], company: str) -> str:
    th = dataset["thresholds"]
    return f"""Anda analis daya saing harga retail untuk {company}. Tulis narasi eksekutif dashboard
berdasarkan DATA berikut (sudah dihitung, per liter, gap = PTPL − kompetitor dalam pasangan KIMAP).

ATURAN
- Bahasa Indonesia formal, ringkas, untuk direksi.
- HANYA pakai angka yang ada di DATA, ditulis persis (mis. "−Rp 9.390/L"). Jangan menghitung angka baru,
  jangan memakai persentase.
- Gap harga negatif = PTPL lebih murah (kompetitif). Gap margin positif = margin PTPL lebih besar bagi bengkel.
- Status HTO: AMAN jika gap < {fmt_id(th['aman_below'])}/L, WATCH di antaranya, KRITIS jika gap > {fmt_id(th['kritis_above'])}.
- ringkasan: 3-4 poin, masing-masing 1 kalimat dengan angka.
- insight_eksekutif: 3 kartu. kategori bergaya "I. CONSUMER VIEW · PROTEKSI HARGA ECERAN",
  "II. OUTLET VIEW · MITIGASI MARGIN", "III. ANOMALI · ...". uraian 1-2 kalimat dengan angka.
- zona: satu entri untuk setiap zona di DATA (nama persis). kondisi 1 kalimat. konsumen_insight dan
  outlet_insight masing-masing 2-3 kartu. konsumen_anomali dan outlet_anomali 1-3 poin singkat
  (mis. gap memburuk, status KRITIS, kompetitor yang gapnya menyempit). Kosongkan jika tidak ada.
- Sebut produk dengan nama di DATA. Jangan menyebut nama tabel atau filter data.

DATA
{json.dumps(_compact(dataset), ensure_ascii=False)}
"""


_MONEY = re.compile(r"[-−–+]?\s*(?:rp\.?\s*)?[-−–+]?\d[\d.,]*\s*(?:/l\b|%)?", re.IGNORECASE)


def ungrounded_numbers(text: str, nums: list[float]) -> list[str]:
    """Angka 'besar' (≥100, bukan tahun) atau persentase di teks yang tidak ada di data."""
    bad = []
    for raw in _MONEY.findall(text or ""):
        value = parse_number(raw)
        if value is None:
            continue
        v = abs(value)
        is_percent = raw.strip().endswith("%")
        if not is_percent and (v < 100 or (2000 <= v <= 2100 and float(v).is_integer())):
            continue
        if not any(abs(v - n) <= max(1.0, 0.006 * n) for n in nums):
            bad.append(raw.strip())
    return bad


def clean_narrative(narr: dict[str, Any], nums: list[float]) -> tuple[dict[str, Any], int]:
    """Buang kalimat/kartu yang memuat angka di luar data."""
    dropped = 0

    def ok_text(t: str) -> bool:
        nonlocal dropped
        if ungrounded_numbers(t, nums):
            dropped += 1
            return False
        return True

    def ok_cards(cards):
        return [c for c in cards or [] if ok_text(f"{c.get('judul', '')} {c.get('uraian', '')}")]

    out = {"ringkasan": [t for t in narr.get("ringkasan") or [] if ok_text(t)],
           "insight_eksekutif": ok_cards(narr.get("insight_eksekutif")), "zona": {}}
    for z in narr.get("zona") or []:
        name = z.get("zona", "")
        out["zona"][name] = {
            "kondisi": z.get("kondisi", "") if ok_text(z.get("kondisi", "")) else "",
            "konsumen_insight": ok_cards(z.get("konsumen_insight")),
            "konsumen_anomali": [t for t in z.get("konsumen_anomali") or [] if ok_text(t)],
            "outlet_insight": ok_cards(z.get("outlet_insight")),
            "outlet_anomali": [t for t in z.get("outlet_anomali") or [] if ok_text(t)],
        }
    return out, dropped


def generate_narrative(dataset: dict[str, Any], company: str) -> dict[str, Any]:
    from .report_engine import _generate_json

    try:
        raw = _generate_json(narrative_prompt(dataset, company), NARRATIVE_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("Narasi dashboard gagal dibuat; dashboard tetap dibuat tanpa narasi")
        return {"ringkasan": [], "insight_eksekutif": [], "zona": {}}
    narr, dropped = clean_narrative(raw, pdm.dataset_numbers(dataset))
    if dropped:
        logger.warning("Membuang %d kalimat narasi dengan angka di luar data", dropped)
    return narr


# ==========================================================================
# Halaman (mengikuti laporan "C-Suite Exec Dashboard" PTPL)
# ==========================================================================
CHIP = {"AMAN": ("✓ KOMPETITIF", "low"), "WATCH": ("⚠ MONITOR", "mid"), "KRITIS": ("⚡ RISK", "high"), "NA": ("NA", "muted")}
GROUP_SUFFIX = {"exec": "(MULTIZONE PERFORMANCE)", "konsumen": "(END-USER RETAIL PRICE)", "outlet": "(OUTLET WHOLESALE & MARGIN)"}


def _hero_pick(heroes: list[dict], limit: int) -> list[dict]:
    """Satu Hero per segmen dulu (urutan daftar Hero), lalu sisanya."""
    first, rest, seen = [], [], set()
    for h in heroes:
        (rest if h["segment"] in seen else first).append(h)
        seen.add(h["segment"])
    return (first + rest)[:limit]


def _group_label(seg: dict, view: str) -> str:
    return f"{seg['label'].upper()} {GROUP_SUFFIX[view]}"


def _row_label(r: dict) -> str:
    if r["kind"] == "hero":
        return f"▸ {pdm.short_name(r['product'])} (Hero)"
    return r["label"]


def _status_cell(status: str) -> tuple[str, str]:
    return status, "status:" + STATUS_TONE[status]


def _table(zone_data: dict, view: str, th: dict, has_b: bool) -> dict[str, Any]:
    if view == "konsumen":
        spec = [("HET PTPL", "HET_P", None), ("HET KOMP", "HET_K", None), ("GAP HET", "GAP_HET", "negatif"),
                ("HJ PTPL", "HJ_P", None), ("HJ KOMP", "HJ_K", None), ("GAP HJ", "GAP_HJ", "negatif")]
        key_gap = "GAP_HJ"
    else:
        spec = [("HTO PTPL", "HTO_P", None), ("HTO KOMP", "HTO_K", None), ("GAP HTO", "GAP_HTO", "negatif"),
                ("HT PTPL", "HT_P", None), ("HT KOMP", "HT_K", None), ("GAP HT", "GAP_HT", "negatif"),
                ("MARG PTPL", "MARG_P", None), ("MARG KOMP", "MARG_K", None), ("GAP MARG", "GAP_MARG", "positif")]
        key_gap = "GAP_HTO"
    cols = ["VISKOSITAS / HERO SKU"] + [c for c, _, _ in spec] + (["TR"] if has_b else []) + ["STATUS"]
    rows = []
    for seg in zone_data["segments"]:
        rows.append({"kind": "group", "cells": [_group_label(seg, view)] + [""] * (len(cols) - 1), "tones": [None] * len(cols)})
        for r in seg["rows"]:
            a, b = r["a"], r["b"]
            cells, tones = [_row_label(r)], [None]
            for _, key, good in spec:
                val = a.get(key)
                cells.append(rp(val, per_liter=False) if key.startswith("GAP") else num(val))
                tones.append(gap_tone(val, good) if good else None)
            if has_b:
                sym, tone = TREND_SYMBOL[pdm.trend_of(a.get(key_gap), (b or {}).get(key_gap))]
                cells.append(sym)
                tones.append(tone)
            cell, tone = _status_cell(pdm.status_of(a.get(key_gap), th["aman_below"], th["kritis_above"]))
            cells.append(cell)
            tones.append(tone)
            rows.append({"kind": r["kind"], "cells": cells, "tones": tones})
    return {"columns": cols, "rows": rows}


def _segment_charts(zone_data: dict, view: str, pa: dict, pb: dict | None) -> list[dict]:
    charts = []
    for seg in zone_data["segments"]:
        heroes = [h for h in zone_data["heroes"] if h["segment"] == seg["segment"]][:5]
        if not heroes:
            continue
        cats = [h["short"] for h in heroes]
        if view == "konsumen":
            series = []
            if pb:
                series.append({"nama": f"{pb['label']} Gap", "nilai": [(h["b"] or {}).get("GAP_HJ") for h in heroes]})
            series.append({"nama": f"{pa['label']} Gap", "nilai": [h["a"]["GAP_HJ"] for h in heroes]})
        else:
            series = [{"nama": "Marg PTPL", "nilai": [h["a"]["MARG_P"] for h in heroes]},
                      {"nama": "Marg Komp", "nilai": [h["a"]["MARG_K"] for h in heroes]}]
        series = [x for x in series if any(v is not None for v in x["nilai"])]
        if series:
            charts.append({"judul": pdm.SEGMENT_CHART.get(seg["segment"], f"SEGMEN {seg['segment']}"), "jenis": "bar",
                           "satuan": "IDR/L", "kategori": cats, "seri": series, "catatan": "",
                           "period_compare": view == "konsumen" and pb is not None})
    return charts


def _kpi_sentence(gap_a: float | None, gap_b: float | None, status: str, metric: str) -> str:
    trend = pdm.trend_of(gap_a, gap_b)
    parts = []
    if trend:
        parts.append({"membaik": f"Gap {metric} membaik dibanding periode pembanding",
                      "memburuk": f"Gap {metric} memburuk dibanding periode pembanding",
                      "stabil": f"Gap {metric} relatif stabil dibanding periode pembanding"}[trend])
    parts.append({"AMAN": "PTPL tetap kompetitif", "WATCH": "selisih harga menipis, perlu dimonitor",
                  "KRITIS": "PTPL lebih mahal dari kompetitor", "NA": "data tidak lengkap"}[status])
    return "; ".join(parts) + "."


def _zone_kpis(zone_data: dict, view: str, th: dict, pa: dict, pb: dict | None) -> list[dict]:
    out = []
    picks = _hero_pick(zone_data["heroes"], 4)
    gap_heroes = picks[:3]
    for h in gap_heroes:
        a, b = h["a"], h["b"] or {}
        key, mlabel = ("GAP_HJ", "HJ") if view == "konsumen" else ("GAP_HTO", "HTO")
        p_key, k_key = ("HJ_P", "HJ_K") if view == "konsumen" else ("HTO_P", "HTO_K")
        status = pdm.status_of(a[key], th["aman_below"], th["kritis_above"])
        lead = f"{pb['label']} {rp(b.get(key))} · " if pb and b.get(key) is not None else ""
        chip, chip_tone = CHIP[status]
        out.append({"label": f"▲ {pdm.card_name(h['product']).upper()} {mlabel} GAP", "value": rp(a[key]),
                    "tone": gap_tone(a[key]), "detail": f"{lead}{pa['label']} PTPL Rp {num(a[p_key])} vs Komp Rp {num(a[k_key])}",
                    "extra": _kpi_sentence(a[key], b.get(key), status, mlabel), "chip": chip, "chip_tone": chip_tone})
    if picks:
        h = picks[0]
        a, b = h["a"], h["b"] or {}
        good = (a["GAP_MARG"] or 0) >= 0
        prev = f" · {pb['label']} margin Rp {num(b.get('MARG_P'))}/L" if pb and b.get("MARG_P") is not None else ""
        out.append({"label": f"▲ {pdm.card_name(h['product']).upper()} MARGIN PTPL", "value": f"Rp {num(a['MARG_P'])}/L",
                    "tone": None, "detail": f"Gap margin {rp(a['GAP_MARG'])}{prev}",
                    "extra": ("Margin outlet PTPL lebih besar dari kompetitor." if good
                              else "Margin outlet PTPL di bawah kompetitor; perlu dimonitor."),
                    "chip": "✓ MARGIN AMAN" if good else "⚠ MONITOR", "chip_tone": "low" if good else "mid"})
    return out


def _watch(items: list[dict], metric: str) -> list[dict]:
    out = []
    for w in items:
        out.append({"product": w["product"], "brand": (w["brand"] or "").upper(), "segment": w["segment"],
                    "metric": f"Gap {metric}",
                    "stats": [(f"{metric} KOMP", None, None), (f"{metric} PTPL", None, None),
                              (f"GAP {metric}", rp(w["last"], False), gap_tone(w["last"]))],
                    "months": [pdm.month_label(m).upper() for m in w["months"]],
                    "values": [rp(v, False) for v in w["values"]], "tones": [gap_tone(v) for v in w["values"]],
                    "caption": f"Gap menyempit dari {rp(w['first'], False)} menjadi {rp(w['last'], False)} per liter."})
    return out


def build_pages(dataset: dict[str, Any], narr: dict[str, Any], company: str) -> list[dict[str, Any]]:
    pa, pb = dataset["period_a"], dataset["period_b"]
    th = dataset["thresholds"]
    vs = f"{pa['label']} vs {pb['label']}" if pb else pa["label"]          # mis. "Q3 2026 vs Q2 2026"
    cmp_ = f"Perbandingan {pb['label']} vs {pa['label']}" if pb else f"Periode {pa['label']}"
    zones = dataset["zones"]
    pages = []

    # ---------------- Executive Summary ----------------
    nas = zones["Nasional"]
    picks = _hero_pick(nas["heroes"], 6)
    zone_cards = []
    for z in pdm.ZONES:
        hs = {h["product"]: h for h in zones[z]["heroes"]}
        metrics = []
        for h in picks[:3]:
            zh = hs.get(h["product"])
            val = zh["a"]["GAP_HJ"] if zh else None
            metrics.append({"label": f"{pdm.card_name(h['product'])} HJ Gap:", "value": rp(val), "tone": gap_tone(val)})
        if picks:
            zh = hs.get(picks[0]["product"])
            val = zh["a"]["MARG_P"] if zh else None
            metrics.append({"label": f"{pdm.card_name(picks[0]['product'])} Margin PTPL:", "value": f"Rp {num(val)}/L", "tone": "low"})
        zone_cards.append({"title": pdm.ZONE_TAB[z].replace("REGION 3,4,5", "REGION 3, 4, 5").replace("REGION 2,6", "REGION 2, 6")
                                    .replace("REGION 1,7", "REGION 1, 7"),
                           "subtitle": pdm.ZONE_NICK[z], "metrics": metrics,
                           "note_label": f"Kondisi {pa['label'].split()[0]}:",
                           "note": (narr["zona"].get(z) or {}).get("kondisi", "")})
    groups = [("VISKOSITAS / HERO SKU", 1)] + [(pdm.ZONE_MATRIX[z], 2) for z in pdm.ZONES] + [("STATUS", 1)]
    cols = [""] + ["GAP HJ", "GAP MARG"] * len(pdm.ZONES) + ["HET/HTO"]
    mrows = []
    for seg in nas["segments"]:
        seg_rows = [r for r in seg["rows"] if r["kind"] == "hero" or any(
            x["kind"] == "hero" and x.get("product") and nas_vis(seg, x) == r["label"] for x in seg["rows"])]
        if not any(r["kind"] == "hero" for r in seg_rows):
            continue
        mrows.append({"kind": "group", "cells": [_group_label(seg, "exec")] + [""] * (len(cols) - 1), "tones": [None] * len(cols)})
        for r in seg_rows:
            cells, tones = [_row_label(r)], [None]
            for z in pdm.ZONES:
                zr = _find_row(zones[z], seg["segment"], r)
                for key, good in (("GAP_HJ", "negatif"), ("GAP_MARG", "positif")):
                    val = zr["a"][key] if zr else None
                    cells.append(rp(val, False))
                    tones.append(gap_tone(val, good))
            cell, tone = _status_cell(pdm.status_of(r["a"]["GAP_HTO"], th["aman_below"], th["kritis_above"]))
            cells.append(cell)
            tones.append(tone)
            mrows.append({"kind": r["kind"], "cells": cells, "tones": tones})
    exec_charts = []
    for key, title in (("GAP_HJ", "KOMPARASI GAP HJ PER ZONA"), ("GAP_MARG", "KOMPARASI GAP MARGIN PER ZONA")):
        series = []
        for z in pdm.ZONES:
            hs = {x["product"]: x for x in zones[z]["heroes"]}
            vals = [hs[h["product"]]["a"][key] if h["product"] in hs else None for h in picks[:4]]
            if any(v is not None for v in vals):
                series.append({"nama": z, "nilai": vals})
        if series:
            exec_charts.append({"judul": title, "jenis": "bar", "satuan": "IDR/L",
                                "kategori": [h["short"] for h in picks[:4]], "seri": series, "catatan": ""})
    pages.append({
        "tab": "★ EXECUTIVE SUMMARY (MULTIZONA)", "kind": "exec", "tag": "BOARD OF DIRECTORS & COMMISSIONERS REPORT",
        "title": f"Executive Summary: Analisis Daya Saing Harga Retail & Margin Advokasi Bengkel (Multizona {vs})",
        "subtitle": f"Pricelist HET/HTO Resmi vs Survey Harga Jual & Tebus Aktual · {cmp_}",
        "zone_cards": zone_cards, "bullets": narr.get("ringkasan", []),
        "sec": {"table": ("INTEGRATED MULTIZONAL PRICE & MARGIN MATRIX", f"{vs.upper()} (IDR/L)"),
                "insights": ("STRATEGIC ACTIONABLE INSIGHTS", "REKOMENDASI C-LEVEL")},
        "table": {"columns": cols, "groups": groups, "rows": mrows,
                  "note": "▸ Gap HJ = PTPL HJ − Komp HJ (negatif = PTPL lebih murah). Gap Marg = Marg PTPL − Marg Komp "
                          "(positif = margin PTPL lebih besar bagi bengkel)."},
        "charts": exec_charts, "insights": narr.get("insight_eksekutif", []),
    })

    # ---------------- Per zona ----------------
    for z in pdm.ZONES:
        data = zones[z]
        zn = narr["zona"].get(z) or {}
        for view in ("konsumen", "outlet"):
            is_c = view == "konsumen"
            pages.append({
                "tab": pdm.ZONE_TAB[z], "kind": "zone", "view": view, "zone": z,
                "tag": "PAGE 1 / 2 — RETAIL OUTLET" if is_c else "PAGE 2 / 2 — OUTLET MARGIN",
                "title": ("Analisa Price Competitiveness Tingkat Konsumen Akhir (HET vs Harga Jual)" if is_c
                          else "Analisa Daya Saing Harga Tebus Outlet (HTO) & Margin Advokasi Bengkel"),
                "subtitle": (f"Pricelist HET Resmi & Survey Harga Jual Aktual · {cmp_} · Toleransi Switching Zone" if is_c
                             else f"Pricelist HTO Resmi, Survey Harga Tebus & Perhitungan Margin Outlet · {cmp_}"),
                "zone_label": f"{pdm.ZONE_TAB[z]} · {pdm.ZONE_NICK[z]}",
                "kpis": _zone_kpis(data, view, th, pa, pb),
                "sec": ({"table": ("DAFTAR VISKOSITAS & SKU FOCUS", f"TABEL HET & HJ {vs.upper()} (IDR/L)"),
                         "charts": ("SHIFT GAP HARGA JUAL", f"VISUALISASI {(pb['label'] + ' GAP VS ') if pb else ''}{pa['label']} GAP".upper()),
                         "insights": ("INSIGHTS HARGA JUAL", "& KOMPETITOR KRITIS"),
                         "watch": ("⚠ PRODUK KOMPETITOR YANG PERLU DIWASPADAI", "HARGA JUAL RETAIL")} if is_c else
                        {"table": ("DAFTAR VISKOSITAS & SKU FOCUS", f"TABEL HTO & MARGIN {vs.upper()} (IDR/L)"),
                         "charts": ("KOMPARASI MARGIN", "PTPL VS KOMPETITOR PER SEGMEN"),
                         "insights": ("INSIGHTS MARGIN BENGKEL", "& TEKANAN DISTRIBUSI"),
                         "watch": ("⚠ PRODUK KOMPETITOR YANG PERLU DIWASPADAI", "WHOLESALE & MARGIN")}),
                "table": {**_table(data, view, th, pb is not None),
                          "note": ("▸ Gap = PTPL − kompetitor (negatif = PTPL lebih murah)" if is_c
                                   else "▸ Gap HTO/HT negatif = PTPL lebih murah · Gap Marg positif = margin PTPL lebih besar")
                                  + (" · TR: ▼ membaik ▲ memburuk ▬ stabil" if pb else "")},
                "charts": _segment_charts(data, view, pa, pb),
                "anomaly_title": ("ANOMALI DAN BATAS RISK CONSUMER" if is_c else "ANOMALI ACUAN HTO DAN MARGIN OUTLET")
                                 + f" ({pa['label'].upper()})",
                "anomaly": zn.get("konsumen_anomali" if is_c else "outlet_anomali", []),
                "insights": zn.get("konsumen_insight" if is_c else "outlet_insight", []),
                "watch": _watch(data["watch_hj" if is_c else "watch_hto"], "HJ" if is_c else "HTO"),
                "footnote": ("Switching Zone Indicator: Gap < Rp 10.000/L (kemasan 0,8–1 L) atau < Rp 50.000/kemasan "
                             "(4–5 L) dianggap rawan memicu switching oleh konsumen akhir yang sensitif harga."
                             if is_c else
                             f"Status HTO: AMAN gap < {fmt_id(th['aman_below'])}/L · WATCH {fmt_id(th['aman_below'])}–0 · KRITIS gap > {fmt_id(th['kritis_above'])}."),
            })
    for p in pages:
        p["footer"] = f"Source Data: Survey Response Report Retail · {vs} · Standardized per liter (IDR/L) · {company}"
        p["topbar"] = f"C-SUITE EXEC DASHBOARD: SURVEY HARGA JUAL VS TEBUS BENGKEL ({(pb['label'] + '–') if pb else ''}{pa['label']})".upper()
    _fill_watch_stats(pages, dataset)
    return pages


def nas_vis(seg: dict, hero_row: dict) -> str:
    """Label baris viskositas yang memuat Hero tersebut (baris tepat sebelum Hero di segmen)."""
    last_visc = None
    for r in seg["rows"]:
        if r["kind"] == "viscosity":
            last_visc = r["label"]
        elif r is hero_row:
            return last_visc or ""
    return ""


def _find_row(zone_data: dict, segment: str, row: dict) -> dict | None:
    for seg in zone_data["segments"]:
        if seg["segment"] != segment:
            continue
        for r in seg["rows"]:
            if r["kind"] == row["kind"] and (r.get("product") == row.get("product") if row["kind"] == "hero"
                                             else r["label"] == row["label"]):
                return r
    return None


def _fill_watch_stats(pages: list[dict], dataset: dict) -> None:
    """Isi kotak HJ/HTO KOMP & PTPL kartu kompetitor dari data bulanan terakhir."""
    for p in pages:
        if p["kind"] != "zone":
            continue
        raw = dataset["zones"][p["zone"]]["watch_hj" if p["view"] == "konsumen" else "watch_hto"]
        for card, w in zip(p["watch"], raw):
            if w.get("last_ptpl") is not None:
                card["stats"][0] = (card["stats"][0][0], num(w["last_komp"]), None)
                card["stats"][1] = (card["stats"][1][0], num(w["last_ptpl"]), None)
            else:
                card["stats"] = card["stats"][2:]
