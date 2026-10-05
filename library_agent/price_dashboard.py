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
# Halaman
# ==========================================================================
def _hero_pick(heroes: list[dict], limit: int) -> list[dict]:
    """Satu Hero per segmen dulu (urutan daftar Hero), lalu sisanya."""
    first, rest, seen = [], [], set()
    for h in heroes:
        (rest if h["segment"] in seen else first).append(h)
        seen.add(h["segment"])
    return (first + rest)[:limit]


def _table(zone_data: dict, view: str, th: dict, has_b: bool) -> dict[str, Any]:
    if view == "konsumen":
        cols = ["Viskositas / Hero SKU", "HET PTPL", "HET KOMP", "GAP HET", "HJ PTPL", "HJ KOMP", "GAP HJ"]
        spec = [("HET_P", None), ("HET_K", None), ("GAP_HET", "negatif"), ("HJ_P", None), ("HJ_K", None), ("GAP_HJ", "negatif")]
        key_gap = "GAP_HJ"
    else:
        cols = ["Viskositas / Hero SKU", "HTO PTPL", "HTO KOMP", "GAP HTO", "MARG PTPL", "MARG KOMP", "GAP MARG"]
        spec = [("HTO_P", None), ("HTO_K", None), ("GAP_HTO", "negatif"), ("MARG_P", None), ("MARG_K", None), ("GAP_MARG", "positif")]
        key_gap = "GAP_HTO"
    if has_b:
        cols.append("TR")
    cols.append("STATUS")
    rows = []
    for seg in zone_data["segments"]:
        rows.append({"kind": "group", "cells": [seg["label"]] + [""] * (len(cols) - 1), "tones": [None] * len(cols)})
        for r in seg["rows"]:
            a, b = r["a"], r["b"]
            cells, tones = [r["label"]], [None]
            for key, good in spec:
                val = a.get(key)
                cells.append(rp(val, per_liter=False) if key.startswith("GAP") else num(val))
                tones.append(gap_tone(val, good) if good else None)
            if has_b:
                sym, tone = TREND_SYMBOL[pdm.trend_of(a.get(key_gap), (b or {}).get(key_gap))]
                cells.append(sym)
                tones.append(tone)
            status = pdm.status_of(a.get(key_gap), th["aman_below"], th["kritis_above"])
            cells.append(status)
            tones.append("status:" + STATUS_TONE[status])
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
                series.append({"nama": f"Gap HJ {pb['label']}", "nilai": [(h["b"] or {}).get("GAP_HJ") for h in heroes]})
            series.append({"nama": f"Gap HJ {pa['label']}", "nilai": [h["a"]["GAP_HJ"] for h in heroes]})
            title = f"Segmen {seg['segment']} · Gap harga jual"
        else:
            series = [{"nama": "Margin PTPL", "nilai": [h["a"]["MARG_P"] for h in heroes]},
                      {"nama": "Margin kompetitor", "nilai": [h["a"]["MARG_K"] for h in heroes]}]
            title = f"Segmen {seg['segment']} · Margin bengkel {pa['label']}"
        series = [s for s in series if any(v is not None for v in s["nilai"])]
        if series:
            charts.append({"judul": title, "jenis": "bar", "satuan": "IDR/L", "kategori": cats, "seri": series,
                           "catatan": "", "period_compare": view == "konsumen" and pb is not None})
    return charts


def _zone_kpis(zone_data: dict, view: str, th: dict, pa: dict, pb: dict | None) -> list[dict]:
    out = []
    for h in _hero_pick(zone_data["heroes"], 4):
        a, b = h["a"], h["b"] or {}
        key = "GAP_HJ" if view == "konsumen" else "GAP_HTO"
        status = pdm.status_of(a[key], th["aman_below"], th["kritis_above"])
        if pb and b.get(key) is not None:
            detail = f"{pb['label']}: {rp(b[key])} → {pa['label']}: {rp(a[key])}"
        elif view == "konsumen":
            detail = f"HJ PTPL {num(a['HJ_P'])} vs komp {num(a['HJ_K'])}"
        else:
            detail = f"HTO PTPL {num(a['HTO_P'])} vs komp {num(a['HTO_K'])}"
        extra = (f"Margin PTPL {num(a['MARG_P'])}/L · gap margin {rp(a['GAP_MARG'])}" if view == "outlet"
                 else f"HJ PTPL {num(a['HJ_P'])} vs komp {num(a['HJ_K'])}")
        out.append({"label": f"{h['short']} · {'GAP HJ' if view == 'konsumen' else 'GAP HTO'}",
                    "value": rp(a[key]), "tone": gap_tone(a[key]), "detail": detail, "extra": extra,
                    "chip": status, "chip_tone": STATUS_TONE[status]})
    return out


def _watch(items: list[dict], metric_label: str) -> list[dict]:
    return [{"product": w["product"], "brand": w["brand"], "segment": w["segment"], "metric": metric_label,
             "months": [pdm.month_label(m) for m in w["months"]], "values": [rp(v, False) for v in w["values"]],
             "tones": [gap_tone(v) for v in w["values"]]} for w in items]


def build_pages(dataset: dict[str, Any], narr: dict[str, Any], company: str) -> list[dict[str, Any]]:
    pa, pb = dataset["period_a"], dataset["period_b"]
    th = dataset["thresholds"]
    periode = f"{pb['label']} vs {pa['label']}" if pb else pa["label"]
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
            metrics.append({"label": f"{h['short']} Gap HJ", "value": rp(val), "tone": gap_tone(val)})
        if picks:
            zh = hs.get(picks[0]["product"])
            val = zh["a"]["MARG_P"] if zh else None
            metrics.append({"label": f"{picks[0]['short']} Margin PTPL", "value": f"Rp {num(val)}/L", "tone": None})
        zone_cards.append({"title": z.upper(), "subtitle": pdm.ZONE_REGIONS[z], "metrics": metrics,
                           "note": (narr["zona"].get(z) or {}).get("kondisi", "")})
    cols = ["Kategori / Hero SKU"]
    for z in pdm.ZONES:
        short = "Nas" if z == "Nasional" else z.replace("Zona ", "Z")
        cols += [f"Gap HJ {short}", f"Gap Marg {short}"]
    cols.append("Status")
    mrows = []
    for seg in nas["segments"]:
        seg_heroes = [h for h in nas["heroes"] if h["segment"] == seg["segment"]]
        if not seg_heroes:
            continue
        mrows.append({"kind": "group", "cells": [seg["label"]] + [""] * (len(cols) - 1), "tones": [None] * len(cols)})
        for h in seg_heroes:
            cells, tones = [h["short"]], [None]
            for z in pdm.ZONES:
                zh = next((x for x in zones[z]["heroes"] if x["product"] == h["product"]), None)
                for key, good in (("GAP_HJ", "negatif"), ("GAP_MARG", "positif")):
                    val = zh["a"][key] if zh else None
                    cells.append(rp(val, False))
                    tones.append(gap_tone(val, good))
            status = pdm.status_of(h["a"]["GAP_HTO"], th["aman_below"], th["kritis_above"])
            cells.append(status)
            tones.append("status:" + STATUS_TONE[status])
            mrows.append({"kind": "hero", "cells": cells, "tones": tones})
    exec_charts = []
    for key, title in (("GAP_HJ", "Komparasi Gap HJ per Zona"), ("GAP_MARG", "Komparasi Gap Margin per Zona")):
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
        "tab": "★ Executive Summary (Multizona)", "kind": "exec", "tag": "EXECUTIVE SUMMARY",
        "title": f"Executive Summary: Daya Saing Harga Retail & Margin Bengkel · Multizona {periode}",
        "subtitle": f"Pricelist HET/HTO resmi vs survei harga jual & tebus aktual · {periode}",
        "zone_cards": zone_cards, "bullets": narr.get("ringkasan", []),
        "table": {"columns": cols, "rows": mrows,
                  "note": "Gap HJ = HJ PTPL − HJ komp (negatif = PTPL lebih murah) · Gap Marg = margin PTPL − margin komp "
                          "(positif = margin PTPL lebih besar) · Status berdasarkan gap HTO nasional."},
        "charts": exec_charts, "insights": narr.get("insight_eksekutif", []),
    })

    # ---------------- Per zona ----------------
    for z in pdm.ZONES:
        data = zones[z]
        zn = narr["zona"].get(z) or {}
        label = f"{z} ({pdm.ZONE_REGIONS[z]})" if z != "Nasional" else "Nasional (Average)"
        for view in ("konsumen", "outlet"):
            is_c = view == "konsumen"
            pages.append({
                "tab": label, "kind": "zone", "view": view, "zone": z,
                "tag": f"PAGE {'1/2 — RETAIL OUTLET' if is_c else '2/2 — OUTLET MARGIN'}",
                "title": ("Analisa Price Competitiveness Tingkat Konsumen Akhir (HET vs Harga Jual)" if is_c
                          else "Analisa Daya Saing Harga Tebus Outlet (HTO) & Margin Bengkel") + f" · {label}",
                "subtitle": (f"Pricelist HET resmi vs survei harga jual aktual · {periode}" if is_c
                             else f"Pricelist HTO resmi vs survei harga tebus & margin bengkel · {periode}"),
                "kpis": _zone_kpis(data, view, th, pa, pb),
                "table": {**_table(data, view, th, pb is not None),
                          "note": ("Gap = PTPL − kompetitor (negatif = PTPL lebih murah)" if is_c
                                   else "Gap HTO negatif = PTPL lebih murah · Gap Marg positif = margin PTPL lebih besar")
                                  + (" · TR: ▼ membaik ▲ memburuk ▬ stabil" if pb else "")},
                "charts": _segment_charts(data, view, pa, pb),
                "anomaly": zn.get("konsumen_anomali" if is_c else "outlet_anomali", []),
                "insights": zn.get("konsumen_insight" if is_c else "outlet_insight", []),
                "watch": _watch(data["watch_hj" if is_c else "watch_hto"], "Gap HJ" if is_c else "Gap HTO"),
            })
    for p in pages:
        p["footer"] = (f"Sumber: Survey Response Report Retail · {periode} · Standardized per liter (IDR/L) · {company}"
                       f" · Status: AMAN gap < {fmt_id(th['aman_below'])}/L · WATCH · KRITIS gap > {fmt_id(th['kritis_above'])}")
    return pages
