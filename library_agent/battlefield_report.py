"""Template "Competitive Battlefield: Planogram × Price Competitiveness" (versi ringkas, 6 halaman).

Disarikan dari laporan MIR "PTPL Competitive Battlefield Q3 2026 (V7, 24 halaman)": kerangka 5 dimensi
(produk, kompetitor, harga, planogram, momentum) dipertahankan; bagian yang butuh data di luar BigQuery
(KLine CAGR, sellout mix, matriks portofolio McKinsey) tidak dipakai.

    01 Ringkasan Eksekutif          KPI status head-to-head · status per segmen (stack) · temuan utama
    02 Battlefield Kategori         exposure per Segmen × Usage × Viskositas (hbar) · tabel + white space
    03 Head-to-head Produk Fokus    matriks keunggulan harga × gap AV · tabel cek Harga / Ekonomi / Planogram
    04 Momentum Kompetitor          pertumbuhan outlet kompetitor (hbar) · ancaman & white space
    05 Sales Region                 double weakness per SR (stack) · ancaman utama per SR
    06 Action Matrix                diagnosis → owner → aksi → metrik · rekomendasi
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .battlefield_data import STATUS_CLS, STATUSES
from .planogram_report import OWNERS, _CARD, _cards, av, clean_narrative, delta_cell, gap, num, pct

logger = logging.getLogger(__name__)
TAG = "RETAIL × PLANOGRAM"
CARD_KEYS = ("ringkasan", "kategori", "head_to_head", "momentum", "regional")
STATUS_COLOR = {"Pemenang Kompetitif": "#15803D", "Gap Eksekusi": "#D97706", "Gap Ekonomi": "#B58012",
                "Gap Ekonomi + Eksekusi": "#EA580C", "Gap Harga": "#1D4ED8", "Double Jeopardy": "#DC2626",
                "Data harga belum tersedia": "#94A3B8"}
ACTIONS = [
    ("Double Jeopardy", "Harga lebih mahal + planogram lemah", "Brand + Sales + Management",
     "Intervensi gabungan: tinjau proposisi harga dan distribusi sekaligus", "Gap AV & rasio carry membaik"),
    ("Gap Harga", "Planogram kuat, harga jual lebih mahal", "Brand / Commercial",
     "Tinjau harga jual & program outlet; jangan ubah distribusi", "Keunggulan harga kembali positif"),
    ("Gap Eksekusi", "Harga kompetitif, planogram lemah", "Sales / Brand Comm.",
     "Coverage, availability, dan visibility di outlet", "Rasio carry & AV naik"),
    ("Gap Ekonomi + Eksekusi", "Margin outlet kalah + planogram lemah", "Brand + Sales",
     "Perbaiki program margin outlet lalu dorong penempatan rak", "Gap margin ≥ 0 dan AV naik"),
    ("Gap Ekonomi", "Harga & planogram kuat, margin outlet kalah", "Brand / Commercial",
     "Tinjau margin/program economics outlet", "Gap margin outlet ≥ 0"),
    ("Pemenang Kompetitif", "Harga, ekonomi, dan planogram kuat", "Brand",
     "Pertahankan dan replikasi ke SR yang masih lemah", "Exposure stabil/naik"),
]


def seg(s: str) -> str:
    return {"COMMERCIAL": "Commercial"}.get(str(s).upper(), str(s).upper())


def rp(v: Any) -> str:
    return "n/a" if v is None else "Rp " + num(round(v))


def check(ok: bool | None) -> dict[str, str]:
    if ok is None:
        return {"t": "n/a", "cls": "fl"}
    return {"t": "✓", "cls": "pos"} if ok else {"t": "✕", "cls": "neg"}


# ==========================================================================
# Narasi
# ==========================================================================
NARRATIVE_SCHEMA = {"type": "object", "properties": {
    "judul_utama": {"type": "string"},
    "ringkasan": {"type": "array", "items": _CARD},
    "kategori": {"type": "array", "items": _CARD},
    "head_to_head": {"type": "array", "items": _CARD},
    "momentum": {"type": "array", "items": _CARD},
    "regional": {"type": "array", "items": _CARD},
    "rekomendasi": {"type": "array", "items": {"type": "object", "properties": {
        "temuan": {"type": "string"}, "implikasi": {"type": "string"}, "aksi": {"type": "string"},
        "owner": {"type": "string", "enum": list(OWNERS)}}, "required": ["temuan", "implikasi", "aksi", "owner"]}},
}, "required": ["judul_utama", "ringkasan", "kategori", "head_to_head", "momentum", "regional", "rekomendasi"]}


def narrative_prompt(ds: dict[str, Any], company: str, request: str = "") -> str:
    from .battlefield_data import compact

    a, b = ds["period"]["a"], ds["period"]["b"] or "-"
    return f"""Anda analis Marketing Intelligence {company}. Tulis narasi laporan "Competitive Battlefield: Planogram ×
Price Competitiveness" {a} dibandingkan {b} untuk Management (C-level), Brand Owner, dan Sales Regional Manager,
berdasarkan DATA berikut (sudah dihitung dari survei harga retail dan survei rak planogram, digabung per KIMAP).

ATURAN
- Bahasa Indonesia formal, ringkas, berorientasi aksi. Setiap "isi" maksimal 2 kalimat dan memuat angka dari DATA,
  ditulis persis dengan format Indonesia (Rp 77.120; 62,4%; +4,3 pp; AV 1,82; 1.329 outlet).
- Jangan menghitung angka baru, jangan menjumlah, jangan membuat perkiraan/kisaran/target/proyeksi.
- Outlet carry = exposure, BUKAN market share. Data survei = asosiasi, bukan sebab-akibat.
- Keunggulan harga (price_adv) = (HJ kompetitor − HJ PTPL) / HJ kompetitor × 100; positif = PTPL lebih murah.
  Gap AV = AV PTPL − AV kompetitor head-to-head; positif = PTPL lebih baik. Gap margin (eco_gap) positif = margin PTPL
  lebih besar. Rasio carry = outlet PTPL / outlet kompetitor × 100 (ambang {ds['ratio_line']:g}%).
- Status: Pemenang Kompetitif, Gap Eksekusi (harga ✓ planogram ✕), Gap Ekonomi (margin ✕), Gap Ekonomi + Eksekusi,
  Gap Harga (harga ✕ planogram ✓), Double Jeopardy (harga ✕ dan planogram ✕).
- Prinsip: jangan merekomendasikan aksi harga untuk masalah yang sebenarnya distribusi/eksekusi, dan sebaliknya.
- White space = kategori tanpa produk PTPL di rak; jangan disebut kesimpulan peluncuran, tetapi kandidat validasi.
- judul_utama: temuan utama satu kalimat (maks 90 karakter).
- ringkasan 3 kartu; kategori 2; head_to_head 2; momentum 2; regional 2 (label pendek huruf kapital).
- rekomendasi 4–6 baris; owner salah satu: Management, Brand Owner, Sales Region; aksi konkret (KIMAP/SR/segmen).
{('- Fokus tambahan dari user: ' + request) if request else ''}

DATA
{json.dumps(compact(ds), ensure_ascii=False)}
"""


def fallback_narrative(ds: dict[str, Any]) -> dict[str, Any]:
    c = ds.get("status_counts", {})
    pairs = ds.get("pairs", [])
    n = ds.get("national", {})
    win, dj = c.get("Pemenang Kompetitif", 0), c.get("Double Jeopardy", 0)
    out: dict[str, Any] = {"judul_utama": f"{win} dari {n.get('pairs', 0)} produk fokus unggul di harga, ekonomi, dan rak"}
    ring = [{"label": "HEAD-TO-HEAD", "judul": f"{win} Pemenang Kompetitif, {dj} Double Jeopardy",
             "isi": f"Dari {n.get('pairs', 0)} KIMAP head-to-head, {c.get('Gap Eksekusi', 0)} Gap Eksekusi dan "
                    f"{c.get('Gap Harga', 0)} Gap Harga.", "nada": "info"}]
    cats = ds.get("categories", [])
    if cats:
        top = cats[0]
        ring.append({"label": "BATTLEFIELD TERBESAR", "judul": f"{top['label']}: {num(top['exposure'])} outlet",
                     "isi": f"Leader {top['leader']} di {num(top['leader_carry'])} outlet; PTPL di "
                            f"{num(top['ptpl_carry'])} outlet.", "nada": "info"})
    ws = ds.get("white_space", [])
    if ws:
        ring.append({"label": "WHITE SPACE", "judul": f"{ws[0]['label']}: {num(ws[0]['exposure'])} outlet kompetitor",
                     "isi": f"Belum ada produk PTPL di kategori ini; leader {ws[0]['leader']}.", "nada": "perhatian"})
    out["ringkasan"] = ring
    out["kategori"] = [{"label": "KATEGORI", "judul": f"{x['label']} {pct(x['delta_pct']) if x['delta_pct'] is not None else ''}",
                        "isi": f"Exposure {num(x['exposure'])} outlet, AV {av(x['av'])}.", "nada": "info"} for x in cats[:2]]
    worst = [p for p in pairs if p["status"] in ("Double Jeopardy", "Gap Harga", "Gap Eksekusi")]
    best = [p for p in pairs if p["status"] == "Pemenang Kompetitif"]
    h2h = []
    if best:
        p = best[0]
        h2h.append({"label": "PEMENANG", "judul": f"{p['ptpl']} vs {p['h2h']}",
                    "isi": f"Keunggulan harga {pct(p['price_adv'])}, gap AV {gap(p['av_gap'])}.", "nada": "positif"})
    if worst:
        p = worst[0]
        h2h.append({"label": p["status"].upper(), "judul": f"{p['ptpl']} vs {p['h2h']}",
                    "isi": f"Keunggulan harga {pct(p['price_adv'])}, gap AV {gap(p['av_gap'])}, rasio carry {pct(p['ratio'])}.",
                    "nada": "kritis"})
    out["head_to_head"] = h2h
    th = ds.get("threats", [])
    out["momentum"] = [{"label": t["type"], "judul": f"{t['brand']} {t['series']}: +{num(t['delta'])} outlet",
                        "isi": f"Outlet {num(t['out_b'])} → {num(t['out_a'])}; ΔAV {gap(t['delta_av'])}.",
                        "nada": "kritis" if t["type"] == "TRUE THREAT" else "perhatian"} for t in th[:2]]
    regs = sorted(ds.get("regions", []), key=lambda r: -r["dw_total"])
    out["regional"] = [{"label": "SALES REGION", "judul": f"{r['sr']}: {r['dw_total']} KIMAP double weakness",
                        "isi": "KIMAP dengan rasio carry dan AV di bawah kompetitor utama di SR ini.",
                        "nada": "perhatian" if r["dw_total"] else "positif"} for r in regs[:2]]
    recs = []
    for p in worst[:3]:
        act = next(a for a in ACTIONS if a[0] == p["status"])
        recs.append({"temuan": f"{p['ptpl']} vs {p['h2h']}: {p['status']}", "implikasi": act[1], "aksi": act[3],
                     "owner": "Sales Region" if p["status"] == "Gap Eksekusi" else "Brand Owner"})
    if ws:
        recs.append({"temuan": f"White space {ws[0]['label']} ({num(ws[0]['exposure'])} outlet)",
                     "implikasi": "Kompetitor aktif di kategori tanpa produk PTPL",
                     "aksi": "Validasi kebutuhan pasar dan kecocokan teknis sebelum keputusan masuk", "owner": "Management"})
    if regs and regs[0]["dw_total"]:
        recs.append({"temuan": f"{regs[0]['sr']} paling banyak double weakness ({regs[0]['dw_total']} KIMAP)",
                     "implikasi": "Distribusi dan kualitas rak sama-sama tertinggal", "aksi": f"Prioritaskan kunjungan & display di {regs[0]['sr']}",
                     "owner": "Sales Region"})
    out["rekomendasi"] = recs or [{"temuan": "Belum ada pasangan dengan gap", "implikasi": "-", "aksi": "Pantau kuartal berikutnya",
                                   "owner": "Management"}]
    return out


def generate_narrative(ds: dict[str, Any], company: str, request: str = "") -> dict[str, Any]:
    from . import battlefield_data as bd
    from .report_engine import _generate_json

    base = fallback_narrative(ds)
    try:
        raw = _generate_json(narrative_prompt(ds, company, request), NARRATIVE_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("Narasi battlefield gagal dibuat; memakai narasi berbasis aturan")
        return base
    narr, dropped = clean_narrative(raw, bd.dataset_numbers(ds), CARD_KEYS)
    if dropped:
        logger.warning("Membuang %d kalimat narasi battlefield dengan angka di luar data", dropped)
    for k, v in base.items():
        if not narr.get(k):
            narr[k] = v
    return narr


# ==========================================================================
# Halaman
# ==========================================================================
def build_pages(ds: dict[str, Any], narr: dict[str, Any], scope: str = "Nasional (SR1–SR7)") -> list[dict[str, Any]]:  # noqa: C901
    pa, pb, has_b = ds["period"]["a"], ds["period"]["b"], ds["has_b"]
    cmp_txt = f"{pb} → {pa}" if has_b else pa
    common = {"tag": TAG, "right": f"{pb} vs {pa} · {scope}" if has_b else f"{pa} · {scope}",
              "source": ds.get("source_label"), "draft": False}
    c = ds.get("status_counts", {})
    n = ds.get("national", {})
    pairs, cats = ds.get("pairs", []), ds.get("categories", [])
    pages = []

    # 01 Ringkasan
    kpis = [
        {"label": "Produk fokus head-to-head", "value": num(n.get("pairs", 0)),
         "mono": f"{num(n.get('with_price', 0))} dengan data harga", "desc": "KIMAP dengan PTPL dan kompetitor di rak.", "tone": "kb"},
        {"label": "Pemenang kompetitif", "value": num(c.get("Pemenang Kompetitif", 0)),
         "mono": "harga ✓ · ekonomi ✓ · planogram ✓", "desc": "Pertahankan dan replikasi.", "tone": "kg"},
        {"label": "Gap eksekusi / ekonomi", "value": num(c.get("Gap Eksekusi", 0) + c.get("Gap Ekonomi", 0)
                                                         + c.get("Gap Ekonomi + Eksekusi", 0)),
         "mono": f"eksekusi {c.get('Gap Eksekusi', 0)} · ekonomi {c.get('Gap Ekonomi', 0)} · keduanya {c.get('Gap Ekonomi + Eksekusi', 0)}",
         "desc": "Harga kompetitif, tetapi rak atau margin outlet tertinggal.", "tone": "kw"},
        {"label": "Gap harga / double jeopardy", "value": num(c.get("Gap Harga", 0) + c.get("Double Jeopardy", 0)),
         "mono": f"gap harga {c.get('Gap Harga', 0)} · double jeopardy {c.get('Double Jeopardy', 0)}",
         "desc": "PTPL lebih mahal di harga jual customer.", "tone": "kr"},
    ]
    segs = list(ds.get("status_by_segment", {}).keys())
    stack = {"type": "stack", "labels": [seg(s) for s in segs],
             "series": [{"name": s, "color": STATUS_COLOR[s], "data": [ds["status_by_segment"][g][s] for g in segs]}
                        for s in STATUSES[:-1] if any(ds["status_by_segment"][g][s] for g in segs)]}
    pages.append({**common, "kicker": "BATTLEFIELD · 01 · RINGKASAN EKSEKUTIF",
                  "title": narr.get("judul_utama") or "Competitive Battlefield",
                  "sub": f"Planogram × Price Competitiveness · {cmp_txt} · head-to-head per KIMAP",
                  "blocks": [{"type": "kpis", "items": kpis},
                             {"type": "grid", "cols": "g-6040", "children": [
                                 [{"type": "sec", "title": "Status head-to-head per segmen", "acc": f"{pa} · jumlah KIMAP"},
                                  {"type": "chart", "size": "lg", "spec": stack}],
                                 [{"type": "sec", "title": "Temuan utama"}, _cards(narr.get("ringkasan", [])[:3])]]},
                             {"type": "cards", "items": [
                                 {"title": "Cara membaca",
                                  "body": "Harga = harga jual customer per liter vs kompetitor head-to-head di KIMAP yang sama. "
                                          "Ekonomi = margin outlet per liter. Planogram = rasio carry PTPL/kompetitor ≥ "
                                          f"{ds['ratio_line']:g}% dan gap AV ≥ 0. Carry outlet = exposure, bukan market share."}]}]})

    # 02 Kategori
    top = [x for x in cats if not x["small"]][:10]
    hb = {"type": "hbar", "labels": [x["label"] for x in top], "unit": "",
          "series": [{"name": f"Exposure {pa}", "data": [x["exposure"] for x in top]},
                     {"name": "Outlet PTPL", "data": [x["ptpl_carry"] for x in top]}]}
    rows = [{"cells": [{"t": x["label"], "cls": "nm"}, num(x["exposure"]), delta_cell(x["delta_pct"], pct),
                       av(x["av"]), delta_cell(x["delta_av"], gap), f"{x['leader']} · {num(x['leader_carry'])}",
                       f"{x['second'] or '—'} · {num(x['second_carry'])}" if x["second"] else "—",
                       num(x["ptpl_carry"]), {"t": "WHITE SPACE", "cls": "h4c"} if x["white_space"] else "—"],
             "cls": "hl" if x["white_space"] else ""} for x in cats[:12]]
    pages.append({**common, "kicker": "BATTLEFIELD · 02 · KATEGORI",
                  "title": (f"{top[0]['label']} battlefield terbesar ({num(top[0]['exposure'])} outlet)" if top else "Battlefield kategori"),
                  "sub": f"Exposure semua brand per Segmen × Usage × Viskositas · {cmp_txt}",
                  "blocks": [{"type": "grid", "cols": "g-4060", "children": [
                      [{"type": "sec", "title": "Exposure kategori vs outlet PTPL", "acc": "10 teratas"},
                       {"type": "chart", "size": "xl", "spec": hb}],
                      [{"type": "sec", "title": "Kategori battlefield", "acc": pa},
                       {"type": "table", "columns": ["Kategori", "Exposure", "Δ outlet", "AV", "Δ AV", "Leader", "2nd",
                                                     "Outlet PTPL", "Catatan"],
                        "widths": [1.7, 0.8, 0.8, 0.6, 0.7, 1.3, 1.3, 0.8, 1], "rows": rows},
                       _cards(narr.get("kategori", [])[:2])]]},
                             {"type": "note", "text": "Exposure = outlet unik yang men-carry kategori (semua brand). Leader/2nd = "
                                                      "brand dengan outlet terbanyak. White space = kategori tanpa produk PTPL di rak."}]})

    # 03 Head-to-head
    pts = [p for p in pairs if p["price_adv"] is not None and p["av_gap"] is not None][:12]
    matrix = {"type": "matrix", "xTitle": "Keunggulan harga jual PTPL (%)", "yTitle": "Gap AV", "xUnit": "%", "yUnit": "",
              "xLine": 0, "yLine": 0, "quadrants": ["PEMENANG", "GAP HARGA", "DOUBLE JEOPARDY", "GAP EKSEKUSI"],
              "points": [{"label": p["ptpl"][:22], "x": p["price_adv"], "y": p["av_gap"], "size": p["out_ptpl"],
                          "color": STATUS_COLOR[p["status"]]} for p in pts]}
    hrows = [{"cells": [{"t": f"{seg(p['segmen'])} {p['viscosity']} · {p['ptpl']}", "cls": "nm"},
                        f"{p['h2h']} {p['h2h_series']}", f"{num(p['out_ptpl'])} / {num(p['out_comp'])}",
                        f"{av(p['av_ptpl'])} / {av(p['av_comp'])}",
                        {**check(p["price_ok"]), "t": f"{check(p['price_ok'])['t']} {pct(p['price_adv'])}"
                         if p["price_adv"] is not None else "n/a"},
                        check(p["eco_ok"]), check(p["plan_ok"]),
                        {"t": p["status"], "cls": STATUS_CLS.get(p["status"], "")},
                        ", ".join(p["weak_sr"][:3]) or "—"]} for p in pairs[:12]]
    worst = next((p for p in pairs if p["status"] == "Double Jeopardy"), None) or \
        next((p for p in pairs if p["status"] in ("Gap Harga", "Gap Eksekusi")), None)
    pages.append({**common, "kicker": "BATTLEFIELD · 03 · HEAD-TO-HEAD PRODUK FOKUS",
                  "title": (f"{worst['ptpl']} vs {worst['h2h']}: {worst['status']}" if worst
                            else "Head-to-head produk fokus PTPL"),
                  "sub": "Harga jual customer × margin outlet × planogram, per KIMAP vs kompetitor dengan carry terbesar",
                  "blocks": [{"type": "grid", "cols": "g-4060", "children": [
                      [{"type": "sec", "title": "Posisi harga × kualitas rak", "acc": f"{pa} · ukuran = outlet PTPL"},
                       {"type": "chart", "size": "xl", "spec": matrix}],
                      [{"type": "sec", "title": "Cek kompetitif per KIMAP", "acc": "12 dengan exposure PTPL terbesar"},
                       {"type": "table", "columns": ["Produk PTPL", "Head-to-head", "Outlet P/K", "AV P/K", "Harga",
                                                     "Ekonomi", "Rak", "Status", "SR lemah"],
                        "widths": [2.2, 1.5, 0.9, 0.8, 0.9, 0.6, 0.5, 1.3, 0.8], "rows": hrows},
                       _cards(narr.get("head_to_head", [])[:2])]]},
                             {"type": "note", "text": "Harga dibandingkan dengan brand head-to-head bila sampelnya cukup "
                                                      f"(≥ {ds['min_price_n']}), selain itu dengan rata-rata kompetitor di KIMAP yang sama. "
                                                      "SR lemah = Sales Region dengan rasio carry dan AV di bawah kompetitor."}]})

    # 04 Momentum & white space
    th = ds.get("threats", [])[:10]
    tb = {"type": "hbar", "labels": [f"{t['brand']} {t['series']}"[:30] for t in th], "unit": "",
          "series": [{"name": f"Tambahan outlet {cmp_txt}", "data": [t["delta"] for t in th]}]}
    trows = [{"cells": [{"t": f"{t['brand']} {t['series']}", "cls": "nm"}, seg(t["segmen"]), t["ptpl_h2h"] or "Tanpa PTPL",
                        num(t["out_b"]), num(t["out_a"]), delta_cell(t["delta"], num), pct(t["growth_pct"]),
                        delta_cell(t["delta_av"], gap),
                        {"t": t["type"], "cls": "h5c" if t["type"] == "TRUE THREAT" else "h4c"}]} for t in th[:8]]
    wrows = [{"cells": [{"t": w["label"], "cls": "nm"}, num(w["exposure"]), av(w["av"]), delta_cell(w["delta_pct"], pct),
                        f"{w['leader']} · {num(w['leader_carry'])}"]} for w in ds.get("white_space", [])[:6]]
    blocks4 = [{"type": "grid", "cols": "g-4060", "children": [
        [{"type": "sec", "title": "Kompetitor dengan pertambahan outlet terbesar", "acc": "10 teratas"},
         {"type": "chart", "size": "xl", "spec": tb} if th else {"type": "note", "text": "Data pembanding tidak tersedia."}],
        [{"type": "sec", "title": "Ancaman kompetitor", "acc": cmp_txt},
         {"type": "table", "columns": ["Brand · series", "Segmen", "PTPL head-to-head", f"Outlet {pb or '-'}", f"Outlet {pa}",
                                       "Δ", "Growth", "Δ AV", "Tipe"],
          "widths": [1.6, 1, 1.4, 0.8, 0.8, 0.6, 0.7, 0.6, 1.3], "rows": trows},
         _cards(narr.get("momentum", [])[:2])]]}]
    if wrows:
        blocks4.append({"type": "sec", "title": "White space — kategori tanpa produk PTPL", "acc": "kandidat validasi"})
        blocks4.append({"type": "table", "columns": ["Kategori", "Exposure kompetitor", "AV", "Δ outlet", "Leader"],
                        "widths": [2, 1, 0.8, 0.8, 1.6], "rows": wrows})
    blocks4.append({"type": "note", "text": "TRUE THREAT = outlet & AV kompetitor naik; DISTRIBUTION THREAT = outlet naik, AV "
                                            "tidak naik. Kompetitor dengan basis < 30 outlet tidak dihitung."})
    pages.append({**common, "kicker": "BATTLEFIELD · 04 · MOMENTUM KOMPETITOR & WHITE SPACE",
                  "title": (f"{th[0]['brand']} {th[0]['series']} tumbuh +{num(th[0]['delta'])} outlet" if th
                            else "Momentum kompetitor"),
                  "sub": "Ancaman dibaca di level brand + series per KIMAP", "blocks": blocks4})

    # 05 Sales Region
    regs = ds.get("regions", [])
    segs5 = ["MCO", "PCO", "COMMERCIAL"]
    rs = {"type": "stack", "labels": [r["sr"] for r in regs],
          "series": [{"name": seg(s), "data": [r["double_weakness"].get(s, 0) for r in regs]} for s in segs5
                     if any(r["double_weakness"].get(s, 0) for r in regs)]}
    rrows = []
    for r in regs:
        t = r.get("top_threat") or {}
        rrows.append({"cells": [{"t": r["sr"], "cls": "nm"}] + [str(r["double_weakness"].get(s, 0)) for s in segs5] +
                      [{"t": str(r["dw_total"]), "cls": "h5c" if r["dw_total"] >= 3 else "h3c" if r["dw_total"] else "h1c"},
                       f"{t.get('brand', '—')} {t.get('series', '')}".strip(), delta_cell(t.get("delta"), num) if t else "—",
                       t.get("type", "—")]})
    has_dw = any(r["dw_total"] for r in regs)
    pages.append({**common, "kicker": "BATTLEFIELD · 05 · SALES REGION",
                  "title": (f"{max(regs, key=lambda r: r['dw_total'])['sr']} paling banyak KIMAP double weakness"
                            if has_dw else "Posisi head-to-head per Sales Region"),
                  "sub": "Double weakness = rasio carry PTPL di bawah ambang DAN AV di bawah kompetitor utama di SR tersebut",
                  "blocks": [{"type": "grid", "cols": "g-4060", "children": [
                      [{"type": "sec", "title": "Double weakness per SR", "acc": f"{pa} · jumlah KIMAP"},
                       {"type": "chart", "size": "xl", "spec": rs} if has_dw else
                       {"type": "note", "text": "Tidak ada KIMAP double weakness di periode ini."}],
                      [{"type": "sec", "title": "Prioritas per SR", "acc": "ancaman kompetitor terbesar"},
                       {"type": "table", "columns": ["SR", "MCO", "PCO", "Commercial", "Total", "Ancaman utama", "Δ outlet", "Tipe"],
                        "widths": [0.6, 0.6, 0.6, 0.8, 0.6, 2, 0.8, 1.4], "rows": rrows},
                       _cards(narr.get("regional", [])[:2])]]}]})

    # 06 Action matrix
    arows = []
    for diag, signal, owner, action, metric in ACTIONS:
        ex = [p for p in pairs if p["status"] == diag]
        arows.append({"cells": [{"t": diag, "cls": "nm"}, signal, str(len(ex)),
                                ", ".join(p["ptpl"] for p in ex[:2]) or "—", owner, action, metric],
                      "cls": "hl" if diag == "Double Jeopardy" and ex else ""})
    rec_rows = [{"cells": [{"t": r["temuan"], "cls": "nm"}, r["implikasi"], r["aksi"], r["owner"]]}
                for r in narr.get("rekomendasi", [])[:6]]
    notes = ["Kunci gabung harga × rak: KIMAP. Harga per liter dari survei retail (filter AVAILABILITY 1, outlier DATA USE); "
             "skor AV dan outlet dari survei planogram (satu outlet satu suara)."]
    if not has_b:
        notes.append("Periode pembanding tidak tersedia; momentum berisi n/a.")
    if not ds.get("has_price"):
        notes.append("Data harga retail tidak tersedia untuk periode ini.")
    pages.append({**common, "kicker": "BATTLEFIELD · 06 · ACTION MATRIX",
                  "title": "Dari diagnosis ke owner: aksi per jenis gap",
                  "sub": "Prinsip: jangan membuat aksi harga untuk masalah distribusi/eksekusi, dan sebaliknya",
                  "blocks": [{"type": "table", "columns": ["Diagnosis", "Sinyal", "Jumlah", "Contoh produk", "Owner", "Aksi",
                                                           "Metrik sukses"],
                              "widths": [1.3, 1.6, 0.5, 1.9, 1.2, 2.2, 1.4], "rows": arows},
                             {"type": "sec", "title": "Rekomendasi", "acc": "Management · Brand Owner · Sales Region"},
                             {"type": "table", "columns": ["Temuan", "Implikasi", "Aksi", "Owner"],
                              "widths": [2.2, 2.2, 2.6, 1], "rows": rec_rows},
                             {"type": "note", "text": " ".join(notes)}]})
    return pages
