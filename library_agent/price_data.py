"""Data dashboard daya saing harga: periode, query BigQuery, dan perhitungan angka.

Semua angka di dashboard dihitung di sini (bukan oleh Gemini). Aturan mengikuti Data Agent
"Marketing Intelligence":
- Filter wajib: AVAILABILITY = '1', OUTLIER_HTO = 'DATA USE', OUTLIER_HET = 'DATA USE'.
- Harga dinormalisasi per liter (harga / CONTENT).
- Perbandingan PTPL vs kompetitor hanya di dalam pasangan KIMAP yang sama.
- Zona 1 = SR 3,4,5 · Zona 2 = SR 2,6 · Zona 3 = SR 1,7 · Nasional = SR 1-7.
- Gap = PTPL - kompetitor (negatif = PTPL lebih murah). Gap margin: positif = margin PTPL lebih besar.
- Tren: perubahan relatif dalam ±2% = stabil; gap makin negatif = membaik; makin positif = memburuk.
- Status: AMAN jika gap < ambang aman (default -5.000/L), KRITIS jika gap > 0, selain itu WATCH.
"""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from typing import Any

ZONES = ["Nasional", "Zona 1", "Zona 2", "Zona 3"]
ZONE_REGIONS = {"Nasional": "Region 1-7", "Zona 1": "Region 3, 4, 5", "Zona 2": "Region 2, 6", "Zona 3": "Region 1, 7"}
SEGMENT_ORDER = ["MCO", "PCO", "COMMERCIAL", "GEAR"]
SEGMENT_LABEL = {"MCO": "MCO · Motor Cycle Oil", "PCO": "PCO · Passenger Car Oil",
                 "COMMERCIAL": "Commercial · Diesel Engine Oil", "GEAR": "Gear · Transmission & Axle Oil"}
MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
METRICS = ("HET", "HJ", "HTO", "HT", "MARG")
MAX_VISCOSITIES_PER_SEGMENT = 4


# ==========================================================================
# Periode
# ==========================================================================
def parse_period(text: str) -> dict[str, Any]:
    """'2026-Q3' / 'Q3 2026' / '2026-07' / '2026-04:2026-06' -> {label, start, end, months}."""
    raw = (text or "").strip().upper().replace("..", ":").replace(" S/D ", ":").replace(" - ", ":")
    m = re.fullmatch(r"(\d{4})\s*-?\s*Q([1-4])|Q([1-4])\s*-?\s*(\d{4})", raw)
    if m:
        year = int(m.group(1) or m.group(4))
        q = int(m.group(2) or m.group(3))
        start_m, end_m = 3 * q - 2, 3 * q
        return _range(year, start_m, year, end_m, f"Q{q} {year}")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})\s*:\s*(\d{4})-(\d{1,2})", raw)
    if m:
        y1, m1, y2, m2 = map(int, m.groups())
        if (y1, m1) > (y2, m2):
            y1, m1, y2, m2 = y2, m2, y1, m1
        label = (f"{MONTHS_ID[m1 - 1]}–{MONTHS_ID[m2 - 1]} {y2}" if y1 == y2
                 else f"{MONTHS_ID[m1 - 1]} {y1}–{MONTHS_ID[m2 - 1]} {y2}")
        return _range(y1, m1, y2, m2, label)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", raw)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return _range(y, mo, y, mo, f"{MONTHS_ID[mo - 1]} {y}")
    raise ValueError(f"Format periode tidak dikenali: '{text}'. Gunakan mis. 2026-Q3, 2026-07, atau 2026-04:2026-06.")


def _range(y1: int, m1: int, y2: int, m2: int, label: str) -> dict[str, Any]:
    if not (1 <= m1 <= 12 and 1 <= m2 <= 12):
        raise ValueError("Bulan harus 1-12.")
    months = []
    y, mo = y1, m1
    while (y, mo) <= (y2, m2):
        months.append(f"{y:04d}-{mo:02d}")
        mo += 1
        if mo == 13:
            y, mo = y + 1, 1
    last_day = calendar.monthrange(y2, m2)[1]
    return {"label": label, "start": f"{y1:04d}-{m1:02d}-01", "end": f"{y2:04d}-{m2:02d}-{last_day:02d}",
            "months": months}


def month_label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{MONTHS_ID[int(m) - 1]}-{y[2:]}"


# ==========================================================================
# SQL
# ==========================================================================
_BASE = """
base AS (
  SELECT
    SUBSTR(CAST(DT_PR AS STRING), 1, 10) AS D,
    CASE
      WHEN CAST(SALES_REGION_CUSTOMER AS STRING) IN ('3','4','5') THEN 'Zona 1'
      WHEN CAST(SALES_REGION_CUSTOMER AS STRING) IN ('2','6') THEN 'Zona 2'
      WHEN CAST(SALES_REGION_CUSTOMER AS STRING) IN ('1','7') THEN 'Zona 3'
    END AS ZONE_NAME,
    UPPER(SEGMENT) AS SEGMENT, VISCOSITY, KIMAP, UPPER(BRAND) AS BRAND, UPPER(QNR) AS QNR,
    SAFE_DIVIDE(HET, CONTENT) AS HET_L, SAFE_DIVIDE(HARGA_JUAL, CONTENT) AS HJ_L,
    SAFE_DIVIDE(HTO, CONTENT) AS HTO_L, SAFE_DIVIDE(HARGA_TEBUS, CONTENT) AS HT_L,
    SAFE_DIVIDE(MARGIN_SURVEY, CONTENT) AS MARG_L
  FROM `{table}`
  WHERE AVAILABILITY = '1' AND OUTLIER_HTO = 'DATA USE' AND OUTLIER_HET = 'DATA USE'
    AND KIMAP IS NOT NULL AND CONTENT > 0
    AND (SUBSTR(CAST(DT_PR AS STRING), 1, 10) BETWEEN @a_start AND @a_end
         OR SUBSTR(CAST(DT_PR AS STRING), 1, 10) BETWEEN @b_start AND @b_end)
)"""

AGG_SQL = """WITH""" + _BASE + """
SELECT
  IF(D BETWEEN @a_start AND @a_end, 'A', 'B') AS PERIOD, Z AS ZONE, SEGMENT, VISCOSITY, KIMAP,
  IF(BRAND = 'PERTAMINA', 'PTPL', 'KOMP') AS SIDE,
  IF(BRAND = 'PERTAMINA', QNR, '') AS PRODUCT,
  AVG(HET_L) AS HET, AVG(HJ_L) AS HJ, AVG(HTO_L) AS HTO, AVG(HT_L) AS HT, AVG(MARG_L) AS MARG,
  COUNT(*) AS N
FROM base, UNNEST([ZONE_NAME, 'Nasional']) AS Z
WHERE ZONE_NAME IS NOT NULL
GROUP BY PERIOD, ZONE, SEGMENT, VISCOSITY, KIMAP, SIDE, PRODUCT
"""

MONTHLY_SQL = """WITH""" + _BASE + """,
hero_kimap AS (SELECT DISTINCT KIMAP FROM base WHERE BRAND = 'PERTAMINA' AND QNR IN UNNEST(@heroes))
SELECT
  SUBSTR(D, 1, 7) AS MONTH, Z AS ZONE, SEGMENT, KIMAP,
  IF(BRAND = 'PERTAMINA', 'PTPL', 'KOMP') AS SIDE,
  QNR AS PRODUCT, ANY_VALUE(BRAND) AS BRAND,
  AVG(HJ_L) AS HJ, AVG(HTO_L) AS HTO
FROM base, UNNEST([ZONE_NAME, 'Nasional']) AS Z
WHERE ZONE_NAME IS NOT NULL AND KIMAP IN (SELECT KIMAP FROM hero_kimap)
GROUP BY MONTH, ZONE, SEGMENT, KIMAP, SIDE, PRODUCT
"""


def fetch(period_a: dict[str, Any], period_b: dict[str, Any] | None, heroes: list[str],
          table: str) -> tuple[list[dict], list[dict]]:
    """Jalankan dua query BigQuery. Hasil: (baris agregat, baris bulanan)."""
    from google.cloud import bigquery

    from .clients import bigquery_client

    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", table):
        raise ValueError("Nama tabel tidak valid.")
    params = [
        bigquery.ScalarQueryParameter("a_start", "STRING", period_a["start"]),
        bigquery.ScalarQueryParameter("a_end", "STRING", period_a["end"]),
        bigquery.ScalarQueryParameter("b_start", "STRING", period_b["start"] if period_b else "0000-00-00"),
        bigquery.ScalarQueryParameter("b_end", "STRING", period_b["end"] if period_b else "0000-00-00"),
        bigquery.ArrayQueryParameter("heroes", "STRING", list(heroes)),
    ]
    config = bigquery.QueryJobConfig(query_parameters=params)
    client = bigquery_client()
    agg = [dict(r) for r in client.query(AGG_SQL.format(table=table), job_config=config).result()]
    monthly = [dict(r) for r in client.query(MONTHLY_SQL.format(table=table), job_config=config).result()]
    return agg, monthly


# ==========================================================================
# Perhitungan (logika murni)
# ==========================================================================
def short_name(product: str) -> str:
    name = re.sub(r"^PERTAMINA\s+", "", (product or "").upper())
    return re.sub(r"\s*(\d+(?:\.\d+)?)\s*LITER$", r" \1L", name).strip()


def status_of(gap: float | None, aman_below: float, kritis_above: float) -> str:
    if gap is None:
        return "NA"
    if gap < aman_below:
        return "AMAN"
    if gap > kritis_above:
        return "KRITIS"
    return "WATCH"


def trend_of(gap_a: float | None, gap_b: float | None) -> str:
    """'membaik' | 'memburuk' | 'stabil' | '' (tanpa pembanding)."""
    if gap_a is None or gap_b is None:
        return ""
    denom = abs((gap_a + gap_b) / 2) or 1.0
    change = (gap_a - gap_b) / denom
    if abs(change) <= 0.02:
        return "stabil"
    return "memburuk" if change > 0 else "membaik"


def _avg(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _pairs(agg: list[dict], period: str, zone: str) -> list[dict]:
    """Pasangan PTPL vs rata-rata kompetitor dalam KIMAP yang sama."""
    komp: dict[str, dict] = {}
    ptpl: list[dict] = []
    for r in agg:
        if r["PERIOD"] != period or r["ZONE"] != zone:
            continue
        if r["SIDE"] == "KOMP":
            komp[r["KIMAP"]] = r
        else:
            ptpl.append(r)
    out = []
    for p in ptpl:
        k = komp.get(p["KIMAP"])
        if not k:
            continue
        row = {"segment": (p["SEGMENT"] or "").upper(), "viscosity": p["VISCOSITY"] or "-",
               "kimap": p["KIMAP"], "product": p["PRODUCT"], "n": (p.get("N") or 0) + (k.get("N") or 0)}
        for m in METRICS:
            pv, kv = p.get(m), k.get(m)
            row[f"{m}_P"], row[f"{m}_K"] = pv, kv
            row[f"GAP_{m}"] = (pv - kv) if pv is not None and kv is not None else None
        out.append(row)
    return out


def _combine(rows: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for m in METRICS:
        for suffix in ("_P", "_K"):
            out[m + suffix] = _avg([r[m + suffix] for r in rows])
        out["GAP_" + m] = _avg([r["GAP_" + m] for r in rows])
    out["n"] = sum(r["n"] for r in rows)
    return out


def build_zone(agg: list[dict], zone: str, heroes: list[str], has_compare: bool) -> dict[str, Any]:
    """Baris tabel (viskositas rata-rata + Hero) per segmen untuk satu zona, periode A dan B."""
    pairs_a, pairs_b = _pairs(agg, "A", zone), _pairs(agg, "B", zone) if has_compare else []
    hero_set = [h.upper() for h in heroes]

    def index(pairs):
        visc, hero = defaultdict(list), defaultdict(list)
        for p in pairs:
            visc[(p["segment"], p["viscosity"])].append(p)
            if p["product"] in hero_set:
                hero[p["product"]].append(p)
        return visc, hero

    visc_a, hero_a = index(pairs_a)
    visc_b, hero_b = index(pairs_b)
    segments = []
    for seg in sorted({p["segment"] for p in pairs_a}, key=lambda s: (SEGMENT_ORDER.index(s) if s in SEGMENT_ORDER else 9, s)):
        hero_in_seg = [h for h in hero_set if h in hero_a and hero_a[h][0]["segment"] == seg]
        hero_visc = {hero_a[h][0]["viscosity"] for h in hero_in_seg}
        viscs = sorted({v for (s, v) in visc_a if s == seg},
                       key=lambda v: (v not in hero_visc, -sum(p["n"] for p in visc_a[(seg, v)])))
        viscs = sorted(viscs[:max(MAX_VISCOSITIES_PER_SEGMENT, len(hero_visc))])
        rows = []
        for v in viscs:
            a = _combine(visc_a[(seg, v)])
            b = _combine(visc_b[(seg, v)]) if visc_b.get((seg, v)) else None
            rows.append({"kind": "viscosity", "label": f"{v} (Viscosity Avg)", "a": a, "b": b})
            for h in hero_in_seg:
                if hero_a[h][0]["viscosity"] == v:
                    hb = _combine(hero_b[h]) if hero_b.get(h) else None
                    rows.append({"kind": "hero", "label": f"{short_name(h)} (Hero)", "product": h,
                                 "a": _combine(hero_a[h]), "b": hb})
        segments.append({"segment": seg, "label": SEGMENT_LABEL.get(seg, seg), "rows": rows})
    heroes_data = [{"product": h, "short": short_name(h), "segment": hero_a[h][0]["segment"],
                    "a": _combine(hero_a[h]), "b": _combine(hero_b[h]) if hero_b.get(h) else None}
                   for h in hero_set if h in hero_a]
    return {"zone": zone, "segments": segments, "heroes": heroes_data}


def watchlist(monthly: list[dict], zone: str, metric: str, top: int = 3) -> list[dict]:
    """Produk kompetitor dengan gap (PTPL - kompetitor) paling menyempit antar bulan."""
    ptpl = defaultdict(list)
    for r in monthly:
        if r["ZONE"] == zone and r["SIDE"] == "PTPL" and r.get(metric) is not None:
            ptpl[(r["KIMAP"], r["MONTH"])].append(r[metric])
    series: dict[tuple, dict] = {}
    for r in monthly:
        if r["ZONE"] != zone or r["SIDE"] != "KOMP" or r.get(metric) is None:
            continue
        p = _avg(ptpl.get((r["KIMAP"], r["MONTH"]), []))
        if p is None:
            continue
        key = (r["KIMAP"], r["PRODUCT"])
        item = series.setdefault(key, {"product": r["PRODUCT"], "brand": r.get("BRAND") or "",
                                       "segment": (r.get("SEGMENT") or "").upper(), "points": {}})
        item["points"][r["MONTH"]] = p - r[metric]
    out = []
    for item in series.values():
        months = sorted(item["points"])
        if len(months) < 2:
            continue
        first, last = item["points"][months[0]], item["points"][months[-1]]
        narrowing = last - first
        if narrowing <= 0:
            continue
        out.append({"product": item["product"], "brand": item["brand"], "segment": item["segment"],
                    "months": months[-6:], "values": [item["points"][m] for m in months[-6:]],
                    "first": first, "last": last, "change": narrowing})
    out.sort(key=lambda x: -x["change"])
    return out[:top]


def build_dataset(agg: list[dict], monthly: list[dict], heroes: list[str],
                  period_a: dict[str, Any], period_b: dict[str, Any] | None,
                  aman_below: float = -5000.0, kritis_above: float = 0.0) -> dict[str, Any]:
    has_compare = period_b is not None
    zones = {}
    for z in ZONES:
        data = build_zone(agg, z, heroes, has_compare)
        data["watch_hj"] = watchlist(monthly, z, "HJ")
        data["watch_hto"] = watchlist(monthly, z, "HTO")
        zones[z] = data
    return {"period_a": period_a, "period_b": period_b, "zones": zones,
            "thresholds": {"aman_below": aman_below, "kritis_above": kritis_above},
            "has_data": any(zones[z]["segments"] for z in ZONES)}


def dataset_numbers(dataset: dict[str, Any]) -> list[float]:
    """Semua angka di dataset (untuk memeriksa angka di narasi)."""
    nums: list[float] = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            nums.append(abs(float(node)))

    walk(dataset["zones"])
    # selisih antar periode juga boleh disebut
    for z in dataset["zones"].values():
        for h in z["heroes"]:
            if h["b"]:
                for m in METRICS:
                    a, b = h["a"].get("GAP_" + m), h["b"].get("GAP_" + m)
                    if a is not None and b is not None:
                        nums.append(abs(a - b))
    return sorted(set(round(n, 2) for n in nums))
