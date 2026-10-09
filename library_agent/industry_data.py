"""Data laporan daya saing harga INDUSTRI (B2B) dari survei industri BigQuery.

Mengikuti one-pager "Price Competitiveness Analysis — B2B Segment" milik PTPL:
- Gap (%) = (harga kompetitor per liter − HTD PTPL + 3%) ÷ (HTD PTPL + 3%) × 100.
- POSITIF = PTPL kompetitif; NEGATIF = kompetitor lebih murah. (KEBALIKAN dari laporan retail.)
- Gap zona: rata-rata harga kompetitor vs rata-rata HTD+3% pada baris yang sama.
- Gap segmen customer (channel): rata-rata gap per baris yang tersedia.
- KPI kategori = rata-rata sederhana produk × zona; KPI segmen = rata-rata sederhana produk × segmen.
- Lampu lalu lintas: > 10% hijau, 0–10% kuning, < 0% merah.
- Filter wajib survei industri: data_status = 'OK' dan htd_ptpl tidak kosong.
- Zona: Zona 1 = SR 3,4,5 · Zona 2 = SR 2,6 · Zona 3 = SR 1,7.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .price_data import MONTHS_ID, normalize_rows, parse_period

STAGES = ["EARLY", "NEXT"]
STAGE_LABEL = {"EARLY": "Early Stage", "NEXT": "Next Stage"}
STAGE_HINT = {"EARLY": "(identifying needs, supplier selection, supplier listing)", "NEXT": "(tahap lanjutan penawaran)"}
ZONES = ["Zona 1", "Zona 2", "Zona 3"]
ZONE_SUB = {"Zona 1": "(R3,4,5)", "Zona 2": "(R2,6)", "Zona 3": "(R1,7)"}
CHANNELS = ["Agro", "Construction", "Fleet", "Manufacturing", "Marine", "Mining"]
# Nama di data -> nama tampilan template (mis. data "Manufacture" = "Manufacturing").
SEGMENT_ALIAS = {"MANUFACTURE": "Manufacturing", "MANUFACTURING": "Manufacturing"}
CATEGORY_ORDER = ["HDDO", "Hydraulic", "Gear & Trans", "Marine", "Grease"]
def segment_name(raw: str) -> str:
    key = (raw or "").strip().upper()
    return SEGMENT_ALIAS.get(key, (raw or "").strip().title())


DEFAULT_FOCUS = [
    "Meditran SX Plus 15W40|HDDO", "Meditran S|HDDO", "Turalik 52|Hydraulic", "Rored HDA 90|Gear & Trans",
    "Masri RG 320|Gear & Trans", "Medripal 412|Marine", "Grease Pertamina SGX-NL 2|Grease",
    "Grease Pertamina EPX NL 2|Grease",
]
SOURCE_LABEL = "Survey Response Report Industry"


# ==========================================================================
# Produk fokus & pencocokan nama
# ==========================================================================
def _key(text: str) -> str:
    t = re.sub(r"\bPERTAMINA\b", " ", (text or "").upper())
    return re.sub(r"[^A-Z0-9]", "", t)


def parse_focus(entries: list[str]) -> list[dict[str, str]]:
    """'Nama|Kategori[|alias1;alias2]' -> [{name, category, keys}]."""
    out = []
    for e in entries or []:
        parts = [p.strip() for p in str(e).split("|")]
        if not parts[0]:
            continue
        aliases = [a.strip() for a in (parts[2].split(";") if len(parts) > 2 else []) if a.strip()]
        out.append({"name": parts[0], "category": parts[1] if len(parts) > 1 else "Lainnya",
                    "keys": [_key(parts[0])] + [_key(a) for a in aliases]})
    return out


def match_product(raw: str, focus: list[dict[str, str]]) -> str | None:
    """Cocokkan nama produk PTPL di data ke produk fokus (persis, lalu awalan terpanjang)."""
    k = _key(raw)
    if not k:
        return None
    best, best_len = None, 0
    for f in focus:
        for fk in f["keys"]:
            if k == fk:
                return f["name"]
            if fk and k.startswith(fk) and len(fk) > best_len:
                best, best_len = f["name"], len(fk)
    return best


def category_label(products: list[str]) -> str:
    """'Meditran SX Plus 15W40','Meditran S' -> 'Meditran Series'; 'Rored HDA 90','Masri RG 320' -> 'Rored / Masri'."""
    if not products:
        return ""
    if products[0].upper().startswith("GREASE"):
        return " ".join(products[0].split()[:2])
    firsts = []
    for p in products:
        w = p.split()[0]
        if w not in firsts:
            firsts.append(w)
    return f"{firsts[0]} Series" if len(firsts) == 1 else " / ".join(firsts)


def short_name(name: str) -> str:
    return {"Meditran SX Plus 15W40": "Meditran SX Plus", "Grease Pertamina SGX-NL 2": "Grease SGX-NL 2",
            "Grease Pertamina EPX NL 2": "Grease EPX NL 2"}.get(name, name)


def month_name(ym: str) -> str:
    y, m = ym.split("-")
    full = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
            "November", "Desember"]
    return f"{full[int(m) - 1]} {y}"


def previous_month(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


# ==========================================================================
# SQL
# ==========================================================================
SQL = """
SELECT
  IF(SUBSTR(CAST(dt_pr AS STRING), 1, 10) BETWEEN @a_start AND @a_end, 'A', 'B') AS PERIOD,
  UPPER(CAST(main_stage AS STRING)) AS STAGE,
  CASE
    WHEN CAST(sales_region_customer AS STRING) IN ('3','4','5') THEN 'Zona 1'
    WHEN CAST(sales_region_customer AS STRING) IN ('2','6') THEN 'Zona 2'
    WHEN CAST(sales_region_customer AS STRING) IN ('1','7') THEN 'Zona 3'
  END AS ZONE,
  CAST({segment} AS STRING) AS CHANNEL,
  CAST(produk_ptpl AS STRING) AS PRODUCT,
  UPPER(CAST(brand AS STRING)) AS BRAND,
  CAST(harga_kompetitor_per_liter AS FLOAT64) AS PRICE,
  CAST({htd} AS FLOAT64) AS HTD_PLUS
FROM `{table}`
WHERE data_status = 'OK' AND htd_ptpl IS NOT NULL
  AND UPPER(CAST(main_stage AS STRING)) IN ('EARLY', 'NEXT')
  AND (SUBSTR(CAST(dt_pr AS STRING), 1, 10) BETWEEN @a_start AND @a_end
       OR SUBSTR(CAST(dt_pr AS STRING), 1, 10) BETWEEN @b_start AND @b_end)
  AND harga_kompetitor_per_liter > 0 AND {htd} IS NOT NULL AND {htd} > 0
  AND LOWER(TRIM(IFNULL(produk_kompetitor, ''))) NOT IN ('', 'tidak ada')
"""


def fetch(period_a: dict, period_b: dict | None, table: str, htd_column: str,
          segment_column: str = "channel") -> list[dict]:
    from google.cloud import bigquery

    from .clients import bigquery_client

    for name in (table, htd_column, segment_column):
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
            raise ValueError(f"Nama tidak valid: {name}")
    params = [
        bigquery.ScalarQueryParameter("a_start", "STRING", period_a["start"]),
        bigquery.ScalarQueryParameter("a_end", "STRING", period_a["end"]),
        bigquery.ScalarQueryParameter("b_start", "STRING", period_b["start"] if period_b else "0000-00-00"),
        bigquery.ScalarQueryParameter("b_end", "STRING", period_b["end"] if period_b else "0000-00-00"),
    ]
    job = bigquery_client().query(SQL.format(table=table, htd=htd_column, segment=segment_column),
                                  job_config=bigquery.QueryJobConfig(query_parameters=params))
    return normalize_rows([dict(r) for r in job.result()])


# ==========================================================================
# Perhitungan (logika murni)
# ==========================================================================
def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def tone(v: float | None) -> str:
    if v is None:
        return "na"
    return "red" if v < 0 else ("amber" if v <= 10 else "green")


def _cell(rows: list[dict], prev_rows: list[dict], mode: str) -> dict[str, Any] | None:
    """mode 'zone': gap rata-rata harga vs rata-rata HTD+3%; mode 'segment': rata-rata gap per baris."""
    def gap(rs):
        if not rs:
            return None
        if mode == "zone":
            p, h = _mean([r["PRICE"] for r in rs]), _mean([r["HTD_PLUS"] for r in rs])
            return (p - h) / h * 100 if p is not None and h else None
        return _mean([(r["PRICE"] - r["HTD_PLUS"]) / r["HTD_PLUS"] * 100 for r in rs])

    cur = gap(rows)
    if cur is None and not prev_rows:
        return None
    prices = [r["PRICE"] for r in rows]
    return {"current": round(cur, 2) if cur is not None else None,
            "prev": round(gap(prev_rows), 2) if gap(prev_rows) is not None else None,
            "max": max(prices) if prices else None, "avg": _mean(prices), "min": min(prices) if prices else None,
            "brands": sorted({r["BRAND"] for r in rows if r.get("BRAND")}), "n": len(rows)}


def build_dataset(rows: list[dict], focus_entries: list[str], competitors: list[str],
                  period_a: dict, period_b: dict | None, segments_focus: list[str] | None = None) -> dict[str, Any]:
    focus = parse_focus(focus_entries)
    comp = {c.upper() for c in competitors or []}
    rows = normalize_rows(rows)
    clean, unmatched = [], set()
    for r in rows:
        if comp and (r.get("BRAND") or "") not in comp:
            continue
        if not r.get("PRICE") or r["PRICE"] <= 0 or not r.get("HTD_PLUS") or r["HTD_PLUS"] <= 0:
            continue
        name = match_product(r.get("PRODUCT") or "", focus)
        if not name:
            unmatched.add(r.get("PRODUCT"))
            continue
        clean.append(dict(r, FOCUS=name))
    idx = defaultdict(list)
    for r in clean:
        idx[(r["STAGE"], r["PERIOD"], "zone", r["FOCUS"], r.get("ZONE"))].append(r)
        idx[(r["STAGE"], r["PERIOD"], "seg", r["FOCUS"], segment_name(r.get("CHANNEL")))].append(r)
    names = [f["name"] for f in focus]
    cat_of = {f["name"]: f["category"] for f in focus}
    # Segmen yang ditampilkan = segmen fokus (pengaturan; default 6 segmen template), urutan dipertahankan.
    focus_segments = [segment_name(x) for x in (segments_focus or CHANNELS)]
    segments = list(dict.fromkeys(focus_segments))
    stages = {}
    for st in STAGES:
        t1 = {p: {z: _cell(idx[(st, "A", "zone", p, z)], idx[(st, "B", "zone", p, z)], "zone") for z in ZONES} for p in names}
        t2 = {c: {p: _cell(idx[(st, "A", "seg", p, c)], idx[(st, "B", "seg", p, c)], "segment") for p in names}
              for c in segments}
        kpi = {}
        for cat in [c for c in CATEGORY_ORDER if c in cat_of.values()] + sorted(set(cat_of.values()) - set(CATEGORY_ORDER)):
            prods = [p for p in names if cat_of[p] == cat]
            cells = [(p, z, t1[p][z]) for p in prods for z in ZONES if t1[p][z]]
            cur = _mean([c["current"] for _, _, c in cells])
            prev = _mean([c["prev"] for _, _, c in cells])
            zone_avg = {z: _mean([t1[p][z]["current"] for p in prods if t1[p][z]]) for z in ZONES}
            zone_avg = {z: v for z, v in zone_avg.items() if v is not None}
            kpi[cat] = {"current": cur, "prev": prev, "label": category_label(prods),
                        "best_zone": max(zone_avg, key=zone_avg.get) if zone_avg else None,
                        "worst_zone": min(zone_avg, key=zone_avg.get) if zone_avg else None, "zone_avg": zone_avg}
        seg_avg = {c: _mean([t2[c][p]["current"] for p in names if t2[c][p]]) for c in segments}
        seg_prev = {c: _mean([t2[c][p]["prev"] for p in names if t2[c][p]]) for c in segments}
        seg_n = {c: sum(1 for p in names if t2[c][p] and t2[c][p]["current"] is not None) for c in segments}
        seg_avg = {c: v for c, v in seg_avg.items() if v is not None}
        low = min(seg_avg, key=seg_avg.get) if seg_avg else None
        kpi["segment"] = {"name": low, "current": seg_avg.get(low), "prev": seg_prev.get(low), "n": seg_n.get(low, 0)}
        stages[st] = {"table1": t1, "table2": t2, "kpi": kpi,
                      "has_data": any(c for row in t1.values() for c in row.values())}
    return {"period_a": period_a, "period_b": period_b, "focus": focus, "stages": stages, "segments": segments,
            "unmatched": sorted(u for u in unmatched if u)[:20],
            "has_data": any(s["has_data"] for s in stages.values())}


def dataset_numbers(ds: dict) -> list[float]:
    nums: list[float] = []
    for st in ds["stages"].values():
        cells = [c for row in st["table1"].values() for c in row.values() if c] + \
                [c for row in st["table2"].values() for c in row.values() if c]
        for c in cells:
            for k in ("current", "prev", "max", "avg", "min"):
                if c.get(k) is not None:
                    nums.append(abs(c[k]))
            if c.get("current") is not None and c.get("prev") is not None:
                nums.append(abs(c["current"] - c["prev"]))
        for k, v in st["kpi"].items():
            for key in ("current", "prev"):
                if v.get(key) is not None:
                    nums.append(abs(v[key]))
            if v.get("current") is not None and v.get("prev") is not None:
                nums.append(abs(v["current"] - v["prev"]))
            for zv in (v.get("zone_avg") or {}).values():
                nums.append(abs(zv))
    return sorted(set(round(n, 2) for n in nums))


def month_period(text: str) -> dict:
    """Periode bulanan: '2026-08' atau 'Agustus 2026' (dinormalkan oleh agent ke YYYY-MM)."""
    p = parse_period(text)
    if len(p["months"]) != 1:
        raise ValueError("Laporan industri bersifat bulanan. Gunakan satu bulan, mis. 2026-08.")
    ym = p["months"][0]
    p["label"] = month_name(ym)
    p["short"] = MONTHS_ID[int(ym[5:]) - 1]
    return p
