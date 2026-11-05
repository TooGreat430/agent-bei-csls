"""Template laporan "Kinerja Planogram PTPL vs Kompetitor" (kuartal berjalan vs kuartal sebelumnya).

Isi tetap (6 halaman), angka dari planogram_data (pandas), narasi dari model utama (Gemini 4 Argon) yang
dicek: kalimat dengan angka di luar data dibuang; jika narasi gagal, dipakai narasi berbasis aturan.

    01 Ringkasan Eksekutif        KPI · ND per segmen (dumbbell) · insight
    02 Sebaran Outlet per SR      carry PTPL vs leader (bar) · ND per SR (dumbbell) · tabel SR
    03 Posisi per Viskositas      perubahan ND (hbar) · tabel viskositas
    04 Availability & Visibility  KPI A/V · matriks KIMAP (rasio carry × gap AV) · gap AV per SR · tabel KIMAP
    05 Analisa Whitespace         whitespace per SR (hbar) · komposisi per segmen (stack) · tabel KIMAP
    06 Rekomendasi                Temuan | Implikasi | Aksi | Owner · prioritas Sales Region

Audiens: Management (C-level), Brand Owner, Sales Regional Manager.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .report_render import fmt_id

logger = logging.getLogger(__name__)
TAG = "PLANOGRAM"
TONE = {"positif": "ig", "perhatian": "iw", "kritis": "ir", "info": "ib"}
OWNERS = ("Management", "Brand Owner", "Sales Region")
SEG_LABEL = {"MCO AUTOMATIC": "MCO · Automatic", "MCO MANUAL": "MCO · Manual", "PCO GASOLINE": "PCO · Gasoline",
             "COMMERCIAL DIESEL": "Commercial · Diesel"}


# ==========================================================================
# Format angka Indonesia
# ==========================================================================
def num(v: Any) -> str:
    return "n/a" if v is None else fmt_id(float(v)).replace("−", "-")


def pct(v: Any) -> str:
    return "n/a" if v is None else f"{v:.1f}".replace(".", ",") + "%"


def pp(v: Any) -> str:
    return "n/a" if v is None else ("+" if v > 0 else "") + f"{v:.1f}".replace(".", ",") + " pp"


def av(v: Any) -> str:
    return "n/a" if v is None else f"{v:.2f}".replace(".", ",")


def gap(v: Any) -> str:
    return "n/a" if v is None else ("+" if v > 0 else "") + f"{v:.2f}".replace(".", ",")


def seg(name: str) -> str:
    return SEG_LABEL.get(str(name).upper(), str(name).title())


def mom_badge(m: str) -> dict[str, str]:
    return {"NAIK": {"text": "▲ NAIK", "tone": "b-g"}, "TURUN": {"text": "▼ TURUN", "tone": "b-r"},
            "STABIL": {"text": "▬ STABIL", "tone": "b-n"}}.get(m, {"text": "n/a", "tone": "b-n"})


def mom_cell(m: str) -> dict[str, str]:
    return {"NAIK": {"t": "▲ NAIK", "cls": "up"}, "TURUN": {"t": "▼ TURUN", "cls": "dn"},
            "STABIL": {"t": "▬ STABIL", "cls": "fl"}}.get(m, {"t": "n/a", "cls": "fl"})


def delta_cell(v: Any, fmt=pp) -> dict[str, str]:
    if v is None:
        return {"t": "n/a", "cls": "fl"}
    return {"t": fmt(v), "cls": "up" if v > 0 else "dn" if v < 0 else "fl"}


# ==========================================================================
# Narasi (Gemini 4 Argon) + pengecekan angka
# ==========================================================================
_CARD = {"type": "object", "properties": {
    "label": {"type": "string"}, "judul": {"type": "string"}, "isi": {"type": "string"},
    "nada": {"type": "string", "enum": ["positif", "perhatian", "kritis", "info"]}},
    "required": ["label", "judul", "isi", "nada"]}
NARRATIVE_SCHEMA = {"type": "object", "properties": {
    "judul_utama": {"type": "string"},
    "ringkasan": {"type": "array", "items": _CARD},
    "sebaran": {"type": "array", "items": _CARD},
    "viskositas": {"type": "array", "items": _CARD},
    "av": {"type": "array", "items": _CARD},
    "whitespace": {"type": "array", "items": _CARD},
    "rekomendasi": {"type": "array", "items": {"type": "object", "properties": {
        "temuan": {"type": "string"}, "implikasi": {"type": "string"}, "aksi": {"type": "string"},
        "owner": {"type": "string", "enum": list(OWNERS)}}, "required": ["temuan", "implikasi", "aksi", "owner"]}},
}, "required": ["judul_utama", "ringkasan", "sebaran", "viskositas", "av", "whitespace", "rekomendasi"]}


def _compact(ds: dict[str, Any]) -> dict[str, Any]:
    keep = ("sr", "zona", "a", "b", "nd_delta", "nd_momentum", "av_gap_delta", "av_momentum", "top_ws", "small")
    return {"periode": ds["period"], "nasional": ds["national"],
            "per_sr": [{k: r.get(k) for k in keep} for r in ds["regions"]],
            "per_segmen": ds["segments"], "per_viskositas_12_teratas": ds["viscosities"][:12],
            "per_kimap_12_teratas": ds["kimaps"][:12],
            "kimap_whitespace_teratas": sorted(ds["kimaps"], key=lambda k: -k["ws_a"])[:8],
            "catatan_data": {k: v for k, v in ds.get("notes", {}).items() if k != "added_columns"}}


def narrative_prompt(ds: dict[str, Any], company: str, request: str = "") -> str:
    a, b = ds["period"]["a"], ds["period"]["b"] or "-"
    return f"""Anda analis Marketing Intelligence {company}. Tulis narasi laporan "Kinerja Planogram PTPL vs Kompetitor"
{a} dibandingkan {b} untuk Management (C-level), Brand Owner, dan Sales Regional Manager, berdasarkan DATA berikut
(sudah dihitung dari survei rak outlet VM_PLANOGRAM).

ATURAN
- Bahasa Indonesia formal, ringkas, berorientasi aksi. Setiap "isi" maksimal 2 kalimat dan memuat angka.
- HANYA pakai angka yang ada di DATA, ditulis persis dengan format Indonesia (62,4%; +2,2 pp; AV 2,17; 1.329 outlet).
  Jangan menghitung angka baru, jangan menjumlah, jangan membuat perkiraan/kisaran/target/proyeksi.
- Outlet carry = jumlah outlet yang menjual (EXPOSURE), BUKAN market share. Jangan pernah menyebut market share.
- ND = carry brand / total carry semua brand di segmen-viskositas yang sama. Momentum ND: Δ ≥ +2 pp NAIK, ≤ −2 pp TURUN,
  selain itu STABIL. Gap AV = AV PTPL − AV kompetitor dalam KIMAP yang sama (positif = PTPL lebih baik); momentum ±0,10.
- Whitespace = outlet survei yang men-carry kompetitor di suatu KIMAP tetapi tidak men-carry PTPL di KIMAP itu.
- Kuadran KIMAP: DEFEND (rasio carry PTPL/leader ≥ {ds['carry_ratio_line']:g}% dan gap AV ≥ 0), EXPAND (rasio rendah,
  gap AV ≥ 0), FIX AV (rasio tinggi, gap AV < 0), FIX & EXPAND (keduanya lemah).
- Data "small": true = sampel kecil; jangan dijadikan kesimpulan. Data survei = asosiasi, bukan sebab-akibat.
- Jika catatan_data berisi 2T_perlu_ditarik_ulang, jangan menyimpulkan PTPL absen di 2T.
- judul_utama: temuan utama satu kalimat (maks 90 karakter).
- ringkasan 3 kartu; sebaran 2; viskositas 2; av 2; whitespace 2 (label pendek huruf kapital, mis. "SEBARAN OUTLET").
- rekomendasi 4–6 baris; owner salah satu: Management, Brand Owner, Sales Region; aksi konkret (SR/KIMAP/segmen).
{('- Fokus tambahan dari user: ' + request) if request else ''}

DATA
{json.dumps(_compact(ds), ensure_ascii=False)}
"""


CARD_KEYS = ("ringkasan", "sebaran", "viskositas", "av", "whitespace")


def clean_narrative(raw: dict[str, Any], nums: list[float], card_keys: tuple[str, ...] = CARD_KEYS) -> tuple[dict[str, Any], int]:
    from .price_dashboard import ungrounded_numbers

    dropped = 0

    def ok(text: str) -> bool:
        nonlocal dropped
        if ungrounded_numbers(text, nums):
            dropped += 1
            return False
        return True

    out: dict[str, Any] = {"judul_utama": raw.get("judul_utama", "") if ok(raw.get("judul_utama", "")) else ""}
    for key in card_keys:
        out[key] = [c for c in raw.get(key) or [] if ok(f"{c.get('judul', '')} {c.get('isi', '')}")]
    out["rekomendasi"] = [r for r in raw.get("rekomendasi") or []
                          if r.get("owner") in OWNERS and ok(" ".join(str(r.get(k, "")) for k in ("temuan", "implikasi", "aksi")))]
    return out, dropped


def fallback_narrative(ds: dict[str, Any]) -> dict[str, Any]:
    """Narasi berbasis aturan (dipakai jika model gagal atau bagian narasi kosong)."""
    n, pa, pb = ds["national"], ds["period"]["a"], ds["period"]["b"]
    na = n["a"]
    regs = ds["regions"]
    out: dict[str, Any] = {"judul_utama": f"ND PTPL {pct(na['nd'])} di {pa}; gap AV {gap(na['av_gap'])} vs kompetitor"}
    ring = [{"label": "SEBARAN OUTLET", "judul": f"ND PTPL {pct(na['nd'])} ({n['nd_momentum']})",
             "isi": f"PTPL di-carry {num(na['carry_ptpl'])} outlet di {pa}"
                    + (f"; ND berubah {pp(n['nd_delta'])} dari {pb}." if n["nd_delta"] is not None else "."),
             "nada": "positif" if n["nd_momentum"] == "NAIK" else "kritis" if n["nd_momentum"] == "TURUN" else "info"},
            {"label": "AVAILABILITY & VISIBILITY", "judul": f"Gap AV {gap(na['av_gap'])} dalam KIMAP yang sama",
             "isi": f"AV PTPL {av(na['av_ptpl'])} vs kompetitor {av(na['av_komp'])}; PTPL unggul di "
                    f"{n.get('kimap_unggul', 0)} dari {n.get('kimap_count', 0)} KIMAP.",
             "nada": "positif" if (na["av_gap"] or 0) >= 0 else "kritis"},
            {"label": "WHITESPACE", "judul": f"{num(na['ws_outlets'])} outlet whitespace",
             "isi": f"Ada {num(na['ws_pairs'])} peluang outlet × KIMAP di mana kompetitor di-carry tetapi PTPL belum.",
             "nada": "perhatian"}]
    out["ringkasan"] = ring
    rd = [r for r in regs if r["nd_delta"] is not None]
    seb = []
    if rd:
        best, worst = max(rd, key=lambda r: r["nd_delta"]), min(rd, key=lambda r: r["nd_delta"])
        seb.append({"label": "SR TERKUAT", "judul": f"{best['sr']} ND {pct(best['a']['nd'])} ({pp(best['nd_delta'])})",
                    "isi": f"{best['sr']} mencatat perubahan ND terbesar {pp(best['nd_delta'])} dari {pb}.", "nada": "positif"})
        seb.append({"label": "SR PERLU PERHATIAN", "judul": f"{worst['sr']} ND {pct(worst['a']['nd'])} ({pp(worst['nd_delta'])})",
                    "isi": f"{worst['sr']} mencatat perubahan ND terendah {pp(worst['nd_delta'])}; leader kompetitor "
                           f"{worst['a']['leader']} di {num(worst['a']['leader_carry'])} outlet.", "nada": "kritis"
                    if worst["nd_momentum"] == "TURUN" else "perhatian"})
    out["sebaran"] = seb
    vd = [v for v in ds["viscosities"] if v["nd_delta"] is not None and not v["small"]]
    vis = []
    if vd:
        up, dn = max(vd, key=lambda v: v["nd_delta"]), min(vd, key=lambda v: v["nd_delta"])
        vis.append({"label": "VISKOSITAS NAIK", "judul": f"{seg(up['segmen'])} {up['viscosity']} {pp(up['nd_delta'])}",
                    "isi": f"ND PTPL {pct(up['nd_b'])} → {pct(up['nd_a'])}.", "nada": "positif"})
        vis.append({"label": "VISKOSITAS TURUN", "judul": f"{seg(dn['segmen'])} {dn['viscosity']} {pp(dn['nd_delta'])}",
                    "isi": f"ND PTPL {pct(dn['nd_b'])} → {pct(dn['nd_a'])}; leader {dn['leader']} di "
                           f"{num(dn['leader_carry'])} outlet.", "nada": "kritis" if dn["nd_momentum"] == "TURUN" else "perhatian"})
    out["viskositas"] = vis
    kd = [k for k in ds["kimaps"] if k["gap_a"] is not None and not k["small"]]
    avc = []
    if kd:
        lo = min(kd, key=lambda k: k["gap_a"])
        hi = max(kd, key=lambda k: k["gap_a"])
        avc.append({"label": "KIMAP TERKUAT", "judul": f"{hi['label']} gap AV {gap(hi['gap_a'])}",
                    "isi": f"AV PTPL {av(hi['av_ptpl'])} vs kompetitor {av(hi['av_komp'])}.", "nada": "positif"})
        avc.append({"label": "KIMAP TERLEMAH", "judul": f"{lo['label']} gap AV {gap(lo['gap_a'])}",
                    "isi": f"AV PTPL {av(lo['av_ptpl'])} vs kompetitor {av(lo['av_komp'])}; kuadran {lo['quadrant']}.",
                    "nada": "kritis" if lo["gap_a"] < 0 else "perhatian"})
    out["av"] = avc
    wk = sorted(ds["kimaps"], key=lambda k: -k["ws_a"])
    wsr = sorted(regs, key=lambda r: -r["a"]["ws_outlets"])
    wsc = []
    if wsr:
        wsc.append({"label": "WHITESPACE PER SR", "judul": f"{wsr[0]['sr']}: {num(wsr[0]['a']['ws_outlets'])} outlet",
                    "isi": f"{wsr[0]['sr']} memiliki whitespace terbanyak; KIMAP utama "
                           f"{(wsr[0]['top_ws'] or {}).get('label', 'n/a')}.", "nada": "perhatian"})
    if wk and wk[0]["ws_a"]:
        wsc.append({"label": "WHITESPACE PER KIMAP", "judul": f"{wk[0]['label']}: {num(wk[0]['ws_a'])} outlet",
                    "isi": f"Kompetitor {wk[0]['leader']} di-carry di {num(wk[0]['leader_carry'])} outlet pada KIMAP ini.",
                    "nada": "perhatian"})
    out["whitespace"] = wsc
    recs = []
    if wsr:
        recs.append({"temuan": f"Whitespace terbanyak di {wsr[0]['sr']} ({num(wsr[0]['a']['ws_outlets'])} outlet)",
                     "implikasi": "Outlet sudah menjual kompetitor di KIMAP yang sama, PTPL belum hadir",
                     "aksi": f"Prioritaskan penetrasi {(wsr[0]['top_ws'] or {}).get('label', 'KIMAP utama')} di {wsr[0]['sr']}",
                     "owner": "Sales Region"})
    if kd:
        recs.append({"temuan": f"{lo['label']} gap AV {gap(lo['gap_a'])}", "implikasi": "Display PTPL tertinggal di rak",
                     "aksi": f"Perbaiki availability & visibility {lo['label']}", "owner": "Brand Owner"})
    if vd:
        recs.append({"temuan": f"{seg(dn['segmen'])} {dn['viscosity']} ND {pp(dn['nd_delta'])}",
                     "implikasi": f"Leader {dn['leader']} lebih luas sebarannya", "aksi": "Tinjau program outlet untuk viskositas ini",
                     "owner": "Brand Owner"})
    recs.append({"temuan": f"ND PTPL nasional {pct(na['nd'])} ({n['nd_momentum']})",
                 "implikasi": "Posisi exposure PTPL di rak outlet survei", "aksi": "Pantau momentum ND per SR setiap kuartal",
                 "owner": "Management"})
    out["rekomendasi"] = recs
    return out


def generate_narrative(ds: dict[str, Any], company: str, request: str = "") -> dict[str, Any]:
    from . import planogram_data as pdm
    from .report_engine import _generate_json

    base = fallback_narrative(ds)
    try:
        raw = _generate_json(narrative_prompt(ds, company, request), NARRATIVE_SCHEMA)
    except Exception:  # noqa: BLE001
        logger.exception("Narasi planogram gagal dibuat; memakai narasi berbasis aturan")
        return base
    narr, dropped = clean_narrative(raw, pdm.dataset_numbers(ds))
    if dropped:
        logger.warning("Membuang %d kalimat narasi planogram dengan angka di luar data", dropped)
    for key, val in base.items():   # bagian kosong diisi narasi berbasis aturan
        if not narr.get(key):
            narr[key] = val
    return narr


# ==========================================================================
# Halaman
# ==========================================================================
def _cards(items: list[dict]) -> dict[str, Any]:
    return {"type": "insights", "items": [{"tone": TONE.get(c.get("nada"), "ib"), "label": c.get("label", ""),
                                           "title": c.get("judul", ""), "body": c.get("isi", "")} for c in items]}


def build_pages(ds: dict[str, Any], narr: dict[str, Any], scope: str = "Nasional (SR1–SR7)") -> list[dict[str, Any]]:  # noqa: C901
    pa, pb = ds["period"]["a"], ds["period"]["b"]
    has_b = ds["has_b"]
    n, na, nb = ds["national"], ds["national"]["a"], ds["national"].get("b") or {}
    right = f"{pb} vs {pa} · {scope}" if has_b else f"{pa} · {scope}"
    src = ds.get("source_label", "Planogram Marketing Intelligence (VM_PLANOGRAM)")
    common = {"tag": TAG, "right": right, "source": src}
    cmp_txt = f"{pb} → {pa}" if has_b else pa

    def mono(a, b, f):
        return f"{pb} {f(b)} → {pa} {f(a)}" if has_b else f"{pa} {f(a)}"

    regs, segs = ds["regions"], ds["segments"]
    kim = [k for k in ds["kimaps"] if k["gap_a"] is not None]
    pages = []

    # 01 Ringkasan
    kpis = [
        {"label": "Outlet carry PTPL", "value": num(na["carry_ptpl"]), "mono": mono(na["carry_ptpl"], nb.get("carry_ptpl"), num),
         "desc": f"dari {num(na['outlets'])} outlet survei {pa}.", "tone": "kb"},
        {"label": "ND PTPL · oli mesin", "value": pct(na["nd"]), "mono": mono(na["nd"], nb.get("nd"), pct),
         "desc": f"Leader kompetitor: {na['leader']} ({num(na['leader_carry'])} outlet).",
         "tone": {"NAIK": "kg", "TURUN": "kr"}.get(n["nd_momentum"], "kw"), "badge": mom_badge(n["nd_momentum"])},
        {"label": "Gap AV vs kompetitor", "value": gap(na["av_gap"]), "mono": f"AV PTPL {av(na['av_ptpl'])} · kompetitor {av(na['av_komp'])}",
         "desc": f"PTPL unggul di {n.get('kimap_unggul', 0)} dari {n.get('kimap_count', 0)} KIMAP.",
         "tone": "kg" if (na["av_gap"] or 0) >= 0 else "kr", "badge": mom_badge(n["av_momentum"])},
        {"label": "Whitespace outlet", "value": num(na["ws_outlets"]), "mono": mono(na["ws_outlets"], nb.get("ws_outlets"), num),
         "desc": f"{num(na['ws_pairs'])} peluang outlet × KIMAP tanpa PTPL.", "tone": "kw"},
    ]
    seg_chart = {"type": "dumbbell", "fromName": pb or "", "toName": pa, "unit": "%", "deltaUnit": " pp",
                 "labels": [seg(s["segmen"]) for s in segs], "from": [s["nd_b"] for s in segs],
                 "to": [s["nd_a"] for s in segs]} if has_b else \
        {"type": "bar", "labels": [seg(s["segmen"]) for s in segs], "unit": "%",
         "series": [{"name": f"ND PTPL {pa}", "data": [s["nd_a"] for s in segs]}]}
    pages.append({**common, "kicker": "PLANOGRAM · 01 · RINGKASAN EKSEKUTIF",
                  "title": narr.get("judul_utama") or f"ND PTPL {pct(na['nd'])} di {pa}",
                  "sub": f"Kinerja planogram PTPL vs kompetitor · {cmp_txt} · outlet survei {num(na['outlets'])}",
                  "blocks": [{"type": "kpis", "items": kpis},
                             {"type": "grid", "cols": "g-6040", "children": [
                                 [{"type": "sec", "title": f"ND PTPL per segmen {cmp_txt}", "acc": "oli mesin"},
                                  {"type": "chart", "size": "xl", "spec": seg_chart}],
                                 [{"type": "sec", "title": "Temuan utama"}, _cards(narr.get("ringkasan", [])[:3])]]},
                             {"type": "note", "text": "Outlet carry = exposure outlet (bukan market share). ND = carry brand / "
                                                      "total carry semua brand di segmen-viskositas yang sama. Gap AV = AV PTPL − "
                                                      "AV kompetitor dalam PAIR_KIMAP yang sama (skala 1–5)."}]})

    # 02 Sebaran per SR
    sr_bar = {"type": "bar", "labels": [r["sr"] for r in regs], "unit": "",
              "series": [{"name": "Carry PTPL", "data": [r["a"]["carry_ptpl"] for r in regs]},
                         {"name": "Carry leader kompetitor", "data": [r["a"]["leader_carry"] for r in regs]}]}
    sr_nd = {"type": "dumbbell", "fromName": pb or "", "toName": pa, "unit": "%", "deltaUnit": " pp",
             "labels": [r["sr"] for r in regs], "from": [r["b"].get("nd") for r in regs], "to": [r["a"]["nd"] for r in regs]} \
        if has_b else {"type": "hbar", "labels": [r["sr"] for r in regs], "unit": "%",
                       "series": [{"name": "ND PTPL", "data": [r["a"]["nd"] for r in regs]}]}
    rows = []
    for r in regs:
        rows.append({"cells": [{"t": f"{r['sr']} · {r['zona'] or ''}", "cls": "nm"}, num(r["a"]["outlets"]),
                               num(r["b"].get("carry_ptpl")) if has_b else "n/a", num(r["a"]["carry_ptpl"]),
                               pct(r["b"].get("nd")) if has_b else "n/a", pct(r["a"]["nd"]), delta_cell(r["nd_delta"]),
                               mom_cell(r["nd_momentum"]), f"{r['a']['leader'] or 'n/a'} · {num(r['a']['leader_carry'])}"]
                     + ([] if not r["small"] else []), "cls": "hl" if r["nd_momentum"] == "TURUN" else ""})
    worst = min((r for r in regs if r["nd_delta"] is not None), key=lambda r: r["nd_delta"], default=None)
    pages.append({**common, "kicker": "PLANOGRAM · 02 · SEBARAN OUTLET",
                  "title": (f"ND PTPL {n['nd_momentum'].lower()} {pp(n['nd_delta'])}; {worst['sr']} terendah {pp(worst['nd_delta'])}"
                            if worst else f"Sebaran outlet PTPL per Sales Region {pa}"),
                  "sub": f"Outlet carry & ND PTPL per Sales Region · {cmp_txt}",
                  "blocks": [{"type": "grid", "cols": "g2", "children": [
                      [{"type": "sec", "title": f"Carry PTPL vs leader kompetitor per SR", "acc": pa},
                       {"type": "chart", "size": "xl", "spec": sr_bar}],
                      [{"type": "sec", "title": f"ND PTPL per SR", "acc": cmp_txt},
                       {"type": "chart", "size": "xl", "spec": sr_nd}]]},
                             {"type": "grid", "cols": "g-6040", "children": [
                                 [{"type": "table", "columns": ["Sales Region", "Outlet survei", f"Carry {pb or '-'}",
                                                                f"Carry {pa}", f"ND {pb or '-'}", f"ND {pa}", "Δ ND",
                                                                "Momentum", "Leader kompetitor"],
                                   "widths": [1.5, 1, 1, 1, 1, 1, 1, 1.1, 1.6], "rows": rows}],
                                 [_cards(narr.get("sebaran", [])[:2])]]},
                             {"type": "note", "text": "Momentum ND: Δ ≥ +2 pp NAIK, ≤ −2 pp TURUN, selain itu STABIL. "
                                                      "Baris kuning = momentum TURUN."}]})

    # 03 Viskositas
    vd = [v for v in ds["viscosities"] if not v["small"]]
    movers = sorted([v for v in vd if v["nd_delta"] is not None], key=lambda v: -abs(v["nd_delta"]))[:10]
    movers.sort(key=lambda v: -v["nd_delta"])
    vchart = {"type": "hbar", "labels": [f"{seg(v['segmen'])} {v['viscosity']}" for v in movers], "unit": " pp",
              "series": [{"name": "Δ ND", "data": [v["nd_delta"] for v in movers]}]} if movers else \
        {"type": "hbar", "labels": [f"{seg(v['segmen'])} {v['viscosity']}" for v in vd[:10]], "unit": "%",
         "series": [{"name": "ND PTPL", "data": [v["nd_a"] for v in vd[:10]]}]}
    vrows = [{"cells": [{"t": f"{seg(v['segmen'])} · {v['viscosity']}", "cls": "nm"}, num(v["total_carry"]),
                        num(v["carry_ptpl_a"]), f"{v['leader'] or 'n/a'} · {num(v['leader_carry'])}",
                        pct(v["nd_b"]) if has_b else "n/a", pct(v["nd_a"]), delta_cell(v["nd_delta"]),
                        mom_cell(v["nd_momentum"]), "sampel kecil" if v["small"] else ""],
              "cls": "hl" if v["nd_momentum"] == "TURUN" else ""} for v in ds["viscosities"][:12]]
    pages.append({**common, "kicker": "PLANOGRAM · 03 · POSISI PER VISKOSITAS",
                  "title": (f"{seg(movers[-1]['segmen'])} {movers[-1]['viscosity']} paling tertekan ({pp(movers[-1]['nd_delta'])})"
                            if movers and movers[-1]["nd_delta"] < 0 else f"Posisi ND PTPL per viskositas {pa}"),
                  "sub": f"ND PTPL per segmen-viskositas · {cmp_txt} · 12 viskositas dengan carry terbesar",
                  "blocks": [{"type": "grid", "cols": "g-4060", "children": [
                      [{"type": "sec", "title": "Perubahan ND terbesar" if movers else "ND PTPL per viskositas",
                        "acc": "10 teratas"}, {"type": "chart", "size": "xl", "spec": vchart}],
                      [{"type": "sec", "title": "Carry & ND per viskositas", "acc": pa},
                       {"type": "table", "columns": ["Segmen · viskositas", "Total carry", "Carry PTPL", "Leader kompetitor",
                                                     f"ND {pb or '-'}", f"ND {pa}", "Δ ND", "Momentum", "Catatan"],
                        "widths": [1.8, 0.9, 0.9, 1.5, 0.9, 0.9, 0.9, 1, 0.9], "rows": vrows}]]},
                             _cards(narr.get("viskositas", [])[:2]),
                             {"type": "note", "text": f"Viskositas dengan total carry < {ds['min_carry']} ditandai sampel kecil "
                                                      "dan tidak dipakai untuk kesimpulan."
                                                      + (" 2T: viskositas PTPL '20' dan kompetitor 'NO VISCOSITY' "
                                                         "dinormalisasi menjadi 2T." if ds['notes'].get('viskositas_2T_dinormalisasi') else "")}]})

    # 04 Availability & Visibility
    top_k = [k for k in kim if not k["small"]][:10] or kim[:10]
    matrix = {"type": "matrix", "xTitle": "Rasio carry PTPL / leader kompetitor (%)", "yTitle": "Gap AV",
              "xUnit": "%", "yUnit": "", "xLine": ds["carry_ratio_line"], "yLine": 0,
              "quadrants": ["DEFEND", "EXPAND", "FIX & EXPAND", "FIX AV"],
              "points": [{"label": k["label"][:22], "x": k["ratio"], "y": k["gap_a"], "size": k["outlets"]}
                         for k in top_k if k["ratio"] is not None]}
    sr_gap = {"type": "hbar", "labels": [r["sr"] for r in regs], "unit": "",
              "series": [{"name": f"Gap AV {pa}", "data": [r["a"]["av_gap"] for r in regs]}]}
    av_kpis = [
        {"label": "Availability PTPL vs kompetitor", "value": av(na["a_ptpl"]), "mono": f"kompetitor {av(na['a_komp'])}",
         "desc": "Skor 1–5 dalam KIMAP yang sama.", "tone": "kg" if (na["a_ptpl"] or 0) >= (na["a_komp"] or 0) else "kr"},
        {"label": "Visibility PTPL vs kompetitor", "value": av(na["v_ptpl"]), "mono": f"kompetitor {av(na['v_komp'])}",
         "desc": "Skor 1–5 dalam KIMAP yang sama.", "tone": "kg" if (na["v_ptpl"] or 0) >= (na["v_komp"] or 0) else "kr"},
        {"label": "Gap AV", "value": gap(na["av_gap"]), "mono": mono(na["av_gap"], nb.get("av_gap"), gap),
         "desc": f"Perubahan {gap(n['av_gap_delta'])}." if n["av_gap_delta"] is not None else "Tanpa pembanding.",
         "tone": "kg" if (na["av_gap"] or 0) >= 0 else "kr", "badge": mom_badge(n["av_momentum"])},
        {"label": "KIMAP PTPL tertinggal", "value": num(n.get("kimap_kalah", 0)),
         "mono": f"dari {num(n.get('kimap_count', 0))} KIMAP head-to-head", "desc": "Gap AV negatif di KIMAP tersebut.",
         "tone": "kr" if n.get("kimap_kalah") else "kg"},
    ]
    krows = [{"cells": [{"t": k["label"], "cls": "nm"}, seg(k["segmen"]), av(k["av_ptpl"]), av(k["av_komp"]),
                        gap(k["gap_b"]) if has_b else "n/a", {"t": gap(k["gap_a"]), "cls": "pos" if k["gap_a"] >= 0 else "neg"},
                        mom_cell(k["av_momentum"]), pct(k["ratio"]), {"t": k["quadrant"] or "n/a",
                                                                      "cls": {"DEFEND": "h2c", "EXPAND": "h3c", "FIX AV": "h4c",
                                                                              "FIX & EXPAND": "h5c"}.get(k["quadrant"], "")}]}
             for k in top_k]
    weakest = min(top_k, key=lambda k: k["gap_a"]) if top_k else None
    pages.append({**common, "kicker": "PLANOGRAM · 04 · AVAILABILITY & VISIBILITY",
                  "title": (f"AV PTPL {gap(na['av_gap'])} vs kompetitor; {weakest['label']} terlemah ({gap(weakest['gap_a'])})"
                            if weakest else f"Availability & visibility PTPL {pa}"),
                  "sub": f"Skor AV PTPL vs kompetitor dalam PAIR_KIMAP yang sama · {cmp_txt}",
                  "blocks": [{"type": "kpis", "items": av_kpis},
                             {"type": "grid", "cols": "g-6040", "children": [
                                 [{"type": "sec", "title": "Matriks KIMAP: jangkauan × kualitas rak", "acc": f"{pa} · 10 KIMAP terbesar"},
                                  {"type": "chart", "size": "xl", "spec": matrix}],
                                 [{"type": "sec", "title": "Gap AV per SR", "acc": pa},
                                  {"type": "chart", "size": "xl", "spec": sr_gap}]]},
                             {"type": "grid", "cols": "g-6040", "children": [
                                 [{"type": "table", "columns": ["KIMAP (produk PTPL)", "Segmen", "AV PTPL", "AV komp.",
                                                                f"Gap {pb or '-'}", f"Gap {pa}", "Momentum", "Rasio carry", "Kuadran"],
                                   "widths": [1.9, 1.2, 0.8, 0.8, 0.8, 0.8, 1, 0.9, 1.1], "rows": krows}],
                                 [_cards(narr.get("av", [])[:2])]]},
                             {"type": "note", "text": f"Kuadran: garis vertikal rasio carry PTPL/leader {ds['carry_ratio_line']:g}%, "
                                                      "garis horizontal gap AV 0. DEFEND = jangkauan & rak kuat; EXPAND = rak baik, "
                                                      "jangkauan kurang; FIX AV = jangkauan luas, rak kalah; FIX & EXPAND = keduanya lemah."}]})

    # 05 Whitespace
    ws_regs = sorted(regs, key=lambda r: -r["a"]["ws_outlets"])
    ws_chart = {"type": "hbar", "labels": [r["sr"] for r in ws_regs], "unit": "",
                "series": [{"name": f"Outlet whitespace {pa}", "data": [r["a"]["ws_outlets"] for r in ws_regs]}]}
    seg_names = sorted({s for r in regs for s in r["ws_by_segment"]})
    ws_stack = {"type": "stack", "labels": [r["sr"] for r in regs],
                "series": [{"name": seg(s), "data": [r["ws_by_segment"].get(s, 0) for r in regs]} for s in seg_names]}
    wk = [k for k in sorted(ds["kimaps"], key=lambda k: -k["ws_a"]) if k["ws_a"]][:10]
    wrows = [{"cells": [{"t": k["label"], "cls": "nm"}, seg(k["segmen"]), num(k["ws_b"]) if has_b else "n/a",
                        num(k["ws_a"]), delta_cell((k["ws_a"] - k["ws_b"]) if has_b and k["ws_b"] is not None else None, num),
                        f"{k['leader'] or 'n/a'} · {num(k['leader_carry'])}", num(k["carry_ptpl"]), gap(k["gap_a"])]}
             for k in wk]
    for r in wrows:   # whitespace naik = memburuk (merah)
        c = r["cells"][4]
        if c.get("cls") in ("up", "dn"):
            c["cls"] = "dn" if c["cls"] == "up" else "up"
    pages.append({**common, "kicker": "PLANOGRAM · 05 · ANALISA WHITESPACE",
                  "title": (f"{num(na['ws_outlets'])} outlet whitespace; terbanyak di {ws_regs[0]['sr']}"
                            if ws_regs else f"Analisa whitespace {pa}"),
                  "sub": "Outlet survei yang men-carry kompetitor di suatu KIMAP tetapi belum men-carry PTPL di KIMAP itu",
                  "blocks": [{"type": "grid", "cols": "g2", "children": [
                      [{"type": "sec", "title": "Outlet whitespace per SR", "acc": pa},
                       {"type": "chart", "size": "xl", "spec": ws_chart}],
                      [{"type": "sec", "title": "Komposisi peluang per segmen", "acc": "outlet × KIMAP"},
                       {"type": "chart", "size": "xl", "spec": ws_stack}]]},
                             {"type": "grid", "cols": "g-6040", "children": [
                                 [{"type": "table", "columns": ["KIMAP (produk PTPL)", "Segmen", f"WS {pb or '-'}", f"WS {pa}",
                                                                "Δ", "Leader kompetitor", "Carry PTPL", "Gap AV"],
                                   "widths": [1.9, 1.2, 0.8, 0.8, 0.8, 1.5, 0.9, 0.8], "rows": wrows}],
                                 [_cards(narr.get("whitespace", [])[:2])]]},
                             {"type": "note", "text": "WS = jumlah outlet whitespace. Δ whitespace positif (merah) berarti "
                                                      "peluang yang belum tergarap bertambah."}]})

    # 06 Rekomendasi
    rec_rows = [{"cells": [{"t": r["temuan"], "cls": "nm"}, r["implikasi"], r["aksi"], r["owner"]]}
                for r in narr.get("rekomendasi", [])[:6]]
    prio = []
    for r in sorted(regs, key=lambda r: -r["a"]["ws_outlets"]):
        prio.append({"cells": [{"t": f"{r['sr']} · {r['zona'] or ''}", "cls": "nm"}, num(r["a"]["ws_outlets"]),
                               delta_cell(r["nd_delta"]), mom_cell(r["nd_momentum"]),
                               {"t": gap(r["a"]["av_gap"]), "cls": "pos" if (r["a"]["av_gap"] or 0) >= 0 else "neg"},
                               (r["top_ws"] or {}).get("label", "n/a"), num((r["top_ws"] or {}).get("outlets"))]})
    notes = [f"Data: survei rak outlet {cmp_txt}; baris berulang dirata-rata per outlet × brand × series × viskositas × KIMAP."]
    exc = ds["notes"].get("excluded") or {}
    if exc:
        notes.append("Baris dikecualikan: " + "; ".join(f"{k} {num(v)}" for k, v in exc.items()) + ".")
    if ds["notes"].get("2T_perlu_ditarik_ulang"):
        notes.append("2T perlu ditarik ulang: pencatatan viskositas 2T PTPL dan kompetitor berbeda.")
    if not has_b:
        notes.append("Data periode pembanding tidak tersedia, sehingga kolom perubahan berisi n/a.")
    pages.append({**common, "kicker": "PLANOGRAM · 06 · REKOMENDASI",
                  "title": "Rekomendasi & prioritas aksi per audiens",
                  "sub": "Management (C-level) · Brand Owner · Sales Regional Manager — hanya berdasarkan data laporan ini",
                  "blocks": [{"type": "sec", "title": "Temuan → aksi", "acc": "owner"},
                             {"type": "table", "columns": ["Temuan", "Implikasi", "Aksi", "Owner"],
                              "widths": [2.2, 2.2, 2.6, 1], "rows": rec_rows},
                             {"type": "sec", "title": "Prioritas Sales Region", "acc": "urut whitespace terbanyak"},
                             {"type": "table", "columns": ["Sales Region", "Outlet whitespace", "Δ ND", "Momentum ND",
                                                           "Gap AV", "KIMAP whitespace utama", "Outlet"],
                              "widths": [1.3, 1, 0.9, 1, 0.8, 2, 0.7], "rows": prio},
                             {"type": "note", "text": " ".join(notes)}]})
    return pages
