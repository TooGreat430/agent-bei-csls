"""Monthly Purchase Behavior RFM untuk outlet Retail (Bengkel & Toko Oli) — dihitung KODE dari datamart sell-out.

Sumber aturan: "PTPL RFM Outlet Analysis — Master Prompt v1.0" dan "Metodologi & Panduan Report (SR7 v5) v1.0".

Alur:
1. BigQuery (SALES_OUT_DAILY) diagregasi DI BIGQUERY menjadi satu baris per Customer Code dengan volume per bulan
   (pivot), region & tipe outlet dominan, dan himpunan seri produk per periode — jadi tidak ada batas 300 baris dan
   tidak lewat tanya-jawab Data Agent. Hasil query disimpan sementara (cache) di bucket agar 7 region + nasional
   tidak query ulang.
2. pandas menghitung R/F/M, threshold P20–P80 baseline (per region, atau nasional untuk laporan nasional), 12 segmen
   first-match + validasi 125 kombinasi, momentum, matriks 12×12, produk, daftar outlet prioritas, dan audit.

Definisi (ringkas):
- Grain: Customer Code × bulan (transaksi harian dijumlah per bulan). Bulan aktif = volume bersih bulan itu > 0.
- Snapshot baseline: Jan–Des tahun sebelum cut-off (12 bulan). Snapshot YTD: Jan–bulan cut-off (mis. 9 bulan).
- R = jarak bulan dari bulan pembelian positif terakhir ke bulan cut-off snapshot (band tetap R5..R1).
- F = bulan aktif ÷ jumlah bulan snapshot. M = volume bersih snapshot ÷ jumlah bulan snapshot.
- Threshold F/M = P20/P40/P60/P80 baseline (numpy linear), dipakai sama untuk kedua snapshot.
  Konvensi batas: nilai SAMA DENGAN threshold masuk skor yang lebih tinggi (skor = 1 + jumlah threshold ≤ nilai).
- Baseline tanpa pembelian di YTD: skor F = 1 dan M = 1 (special case standar).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import re
import time
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_TABLE = "ptpl-curated-prd.DATAMART.SALES_OUT_DAILY"
DEFAULT_STORE_TYPES = ["OTO-5", "OTO-6", "OTO-7", "OTO-8", "OTO-9", "OTO-10", "OTO-13"]
STORE_TYPE_GROUP = {"OTO-5": "Toko Oli", "OTO-6": "Toko Oli", "OTO-7": "Bengkel", "OTO-8": "Bengkel",
                    "OTO-9": "Bengkel", "OTO-10": "Bengkel", "OTO-13": "Bengkel"}
PLACEHOLDER_IDS = ("", "(blank)", "blank", "-", "n/a", "na", "null", "none", "#n/a")
CACHE_TTL = 12 * 3600
REGISTER_FULL_MAX = 25000          # di atas ini sheet snapshot terpisah dilewati (sudah ada di master)
MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

SEGMENTS = ["Champions", "Can't Lose Them", "Lost", "At Risk", "Hibernating", "Dormant Low Value", "Need Attention",
            "Mid-Recency Watchlist", "Recent Low Monetary", "Loyal Customers", "Potential Loyalists", "New Customers"]
SEGMENT_RULES = ["R ≥ 4, F ≥ 4, M ≥ 4", "R ≤ 2, F ≥ 4, M ≥ 4", "R = 1, F = 1", "R ≤ 2, F ≥ 3, M ≥ 3",
                 "R ≤ 2, F ≤ 2", "R ≤ 2, F ≥ 3, M ≤ 2", "R = 3, F ≥ 3, M ≥ 3", "R = 3, kombinasi tersisa",
                 "R ≥ 4, F ≥ 4, M ≤ 2", "R ≥ 4, F ≥ 4, M = 3", "R ≥ 4, F = 2 atau 3, M berapa pun",
                 "R ≥ 4, F = 1, M berapa pun"]
R_BANDS = [("R5", "0 bulan"), ("R4", "1 bulan"), ("R3", "2–3 bulan"), ("R2", "4–6 bulan"), ("R1", "> 6 bulan")]
PRIORITY_SEGMENTS = ["Champions", "Loyal Customers", "Potential Loyalists", "Need Attention", "At Risk", "Can't Lose Them"]
RECOVERY_SEGMENTS = ["Can't Lose Them", "At Risk", "Hibernating", "Lost"]


# ==========================================================================
# Konfigurasi & periode
# ==========================================================================
def config() -> dict[str, Any]:
    from .config import live

    stypes = live("rfm_store_types") or DEFAULT_STORE_TYPES
    if isinstance(stypes, str):
        stypes = [s.strip() for s in stypes.split(",") if s.strip()]
    return {"table": live("rfm_table") or DEFAULT_TABLE,
            "store_types": [str(s).strip().upper() for s in stypes],
            "series_column": (live("rfm_series_column") or "PRODUCT_SEGMENT").strip(),
            "exclude_pattern": live("rfm_exclude_pattern") or "MEDITRAN SX BIO",
            "cutoff": str(live("rfm_cutoff") or "2026-09")}


def parse_cutoff(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{4})[-/ ]?(\d{1,2})\s*", str(text or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"Cut-off '{text}' tidak valid. Pakai format YYYY-MM, mis. 2026-09.")
    return int(m.group(1)), int(m.group(2))


def window(cutoff: str) -> dict[str, Any]:
    """Periode standar: baseline = tahun sebelum cut-off (12 bulan), YTD = Jan s.d. bulan cut-off."""
    y1, cm = parse_cutoff(cutoff)
    y0 = y1 - 1
    months = [(y0, m) for m in range(1, 13)] + [(y1, m) for m in range(1, cm + 1)]
    return {"y0": y0, "y1": y1, "cm": cm, "months": months,
            "base": [(y0, m) for m in range(1, 13)], "ytd": [(y1, m) for m in range(1, cm + 1)],
            "ytd_prev": [(y0, m) for m in range(1, cm + 1)],
            "start": date(y0, 1, 1), "end": _month_end(y1, cm),
            "label_base": f"Jan–Des {y0}", "label_ytd": f"Jan–{MONTHS_ID[cm - 1]} {y1}",
            "label_ytd_prev": f"Jan–{MONTHS_ID[cm - 1]} {y0}", "n_ytd": cm,
            "quarters": [q for q in range(1, 5) if q * 3 <= cm]}


def _month_end(y: int, m: int) -> date:
    first_next = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return date.fromordinal(first_next.toordinal() - 1)


def mcol(y: int, m: int) -> str:
    return f"m_{y}_{m:02d}"


def mlabel(y: int, m: int) -> str:
    return f"{MONTHS_ID[m - 1]} {y}"


def region_key(name: Any) -> str:
    """'REGION I' / 'Region 1' / 'SR1' / 'Sales Region VII' -> 'SR1'..'SR7' (lainnya: nama apa adanya, huruf besar)."""
    s = str(name or "").strip().upper()
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
    m = re.search(r"(?:SR|REGION|REG|R)\s*[-_.]?\s*(VIII|VII|VI|IV|V|III|II|I|\d+)\b", s)
    if m:
        tok = m.group(1)
        return f"SR{roman.get(tok, tok)}"
    if s in roman:
        return f"SR{roman[s]}"
    return s


# ==========================================================================
# SQL (agregasi di BigQuery)
# ==========================================================================
def _ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError(f"Nama kolom tidak valid: {name}")
    return name


def _table(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name or "") or name.count(".") != 2:
        raise ValueError(f"Nama tabel tidak valid: {name}")
    return name


def _base_ctes(cfg: dict, win: dict) -> str:
    series = _ident(cfg["series_column"])
    placeholders = ", ".join(f"'{p}'" for p in PLACEHOLDER_IDS)
    return f"""
src AS (
  SELECT TRIM(CUSTOMER_CODE) AS cust, CUSTOMER_NAME AS cname, REGION_NAME AS region,
         UPPER(TRIM(STORETYPE_CODE)) AS stype, STORETYPE_NAME AS stype_name,
         {series} AS series, PRODUCT_NAME AS product, DATE_TRUNC(DT_PR, MONTH) AS m,
         CAST(TOTAL_VOL_KL_DELIVERED AS FLOAT64) AS vol
  FROM `{_table(cfg['table'])}`
  WHERE DT_PR BETWEEN @start AND @end
),
flag AS (
  SELECT *, (cust IS NULL OR LOWER(cust) IN ({placeholders})) AS bad_id,
         REGEXP_CONTAINS(UPPER(CONCAT(IFNULL(series, ''), ' ', IFNULL(product, ''))), @exclude) AS excl
  FROM src
),
valid AS (SELECT * FROM flag WHERE NOT bad_id AND NOT excl),
o_type AS (
  SELECT cust, ARRAY_AGG(STRUCT(stype, stype_name) ORDER BY v DESC, stype LIMIT 1)[OFFSET(0)] AS t
  FROM (SELECT cust, stype, ANY_VALUE(stype_name) AS stype_name, SUM(ABS(vol)) AS v FROM valid GROUP BY cust, stype)
  GROUP BY cust
),
o_region AS (
  SELECT cust, ARRAY_AGG(region ORDER BY v DESC, region LIMIT 1)[OFFSET(0)] AS region, COUNT(*) AS n_region
  FROM (SELECT cust, region, SUM(ABS(vol)) AS v FROM valid GROUP BY cust, region) GROUP BY cust
),
o_name AS (SELECT cust, ARRAY_AGG(cname IGNORE NULLS ORDER BY m DESC LIMIT 1)[SAFE_OFFSET(0)] AS cname FROM valid GROUP BY cust),
outlets AS (
  SELECT t.cust, t.t.stype AS stype, t.t.stype_name AS stype_name, r.region, r.n_region, n.cname
  FROM o_type t JOIN o_region r USING (cust) LEFT JOIN o_name n USING (cust)
  WHERE t.t.stype IN UNNEST(@stypes)
),
cm AS (SELECT cust, m, SUM(vol) AS v FROM valid WHERE cust IN (SELECT cust FROM outlets) GROUP BY cust, m),
cohort AS (SELECT DISTINCT cust FROM cm WHERE EXTRACT(YEAR FROM m) = {win['y0']} AND v > 0)"""


def outlet_sql(cfg: dict, win: dict) -> str:
    pivots = ",\n    ".join(f"SUM(IF(cm.m = DATE '{y}-{m:02d}-01', cm.v, 0)) AS {mcol(y, m)}" for y, m in win["months"])
    return f"""WITH {_base_ctes(cfg, win)},
cs AS (
  SELECT v.cust, v.series,
         SUM(IF(v.m BETWEEN @prev_start AND @prev_end, v.vol, 0)) AS vp,
         SUM(IF(v.m BETWEEN @cur_start AND @cur_end, v.vol, 0)) AS vc
  FROM valid v WHERE v.cust IN (SELECT cust FROM outlets) GROUP BY v.cust, v.series
),
sets AS (
  SELECT cust, STRING_AGG(IF(vp > 0, series, NULL), '|' ORDER BY series) AS s_prev,
         STRING_AGG(IF(vc > 0, series, NULL), '|' ORDER BY series) AS s_cur
  FROM cs GROUP BY cust
)
SELECT o.cust, o.cname, o.region, o.n_region, o.stype, o.stype_name, s.s_prev, s.s_cur,
    {pivots}
FROM outlets o JOIN cm USING (cust) LEFT JOIN sets s USING (cust)
GROUP BY o.cust, o.cname, o.region, o.n_region, o.stype, o.stype_name, s.s_prev, s.s_cur"""


def series_sql(cfg: dict, win: dict) -> str:
    return f"""WITH {_base_ctes(cfg, win)}
SELECT v.series, o.region, (c.cust IS NOT NULL) AS in_cohort,
       SUM(IF(v.m BETWEEN @prev_start AND @prev_end, v.vol, 0)) AS vol_prev,
       SUM(IF(v.m BETWEEN @cur_start AND @cur_end, v.vol, 0)) AS vol_cur
FROM valid v JOIN outlets o USING (cust) LEFT JOIN cohort c USING (cust)
GROUP BY v.series, o.region, in_cohort"""


def audit_sql(cfg: dict, win: dict) -> str:
    return f"""WITH {_base_ctes(cfg, win)}
SELECT
  (SELECT COUNT(*) FROM flag) AS rows_total,
  (SELECT COUNTIF(bad_id) FROM flag) AS rows_bad_id,
  (SELECT COUNTIF(NOT bad_id AND excl) FROM flag) AS rows_excluded_series,
  (SELECT IFNULL(SUM(IF(NOT bad_id AND excl, vol, 0)), 0) FROM flag) AS vol_excluded_series,
  (SELECT COUNTIF(vol < 0) FROM valid) AS rows_negative,
  (SELECT COUNTIF(vol = 0) FROM valid) AS rows_zero,
  (SELECT COUNTIF(vol IS NULL) FROM valid) AS rows_null_volume,
  (SELECT COUNT(DISTINCT cust) FROM valid) AS outlets_all_types,
  (SELECT COUNT(*) FROM outlets) AS outlets_selected_types,
  (SELECT COUNTIF(n_region > 1) FROM outlets) AS outlets_multi_region,
  (SELECT IFNULL(SUM(vol), 0) FROM valid) AS vol_all_types,
  (SELECT IFNULL(SUM(vol), 0) FROM valid WHERE cust IN (SELECT cust FROM outlets)) AS vol_selected_types,
  (SELECT CAST(MIN(m) AS STRING) FROM valid) AS first_month,
  (SELECT CAST(MAX(m) AS STRING) FROM valid) AS last_month,
  (SELECT COUNT(DISTINCT series) FROM valid WHERE cust IN (SELECT cust FROM outlets)) AS n_series,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(region, n) ORDER BY region))
     FROM (SELECT region, COUNT(*) AS n FROM outlets GROUP BY region)) AS regions_json,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(stype, n) ORDER BY n DESC))
     FROM (SELECT t.stype AS stype, COUNT(*) AS n FROM o_type GROUP BY 1)) AS store_types_json"""


def _params(cfg: dict, win: dict):
    from google.cloud import bigquery

    y0, y1, cm = win["y0"], win["y1"], win["cm"]
    pat = "|".join(re.escape(p.strip().upper()) for p in str(cfg["exclude_pattern"]).split("|") if p.strip()) or "^$"
    return [bigquery.ScalarQueryParameter("start", "DATE", win["start"]),
            bigquery.ScalarQueryParameter("end", "DATE", win["end"]),
            bigquery.ScalarQueryParameter("prev_start", "DATE", date(y0, 1, 1)),
            bigquery.ScalarQueryParameter("prev_end", "DATE", date(y0, cm, 1)),
            bigquery.ScalarQueryParameter("cur_start", "DATE", date(y1, 1, 1)),
            bigquery.ScalarQueryParameter("cur_end", "DATE", date(y1, cm, 1)),
            bigquery.ScalarQueryParameter("exclude", "STRING", pat),
            bigquery.ArrayQueryParameter("stypes", "STRING", cfg["store_types"])]


def _run(sql: str, params) -> list[dict]:
    from google.cloud import bigquery

    from .clients import bigquery_client

    job = bigquery_client().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    return [dict(r.items()) for r in job.result(page_size=20000)]


def _run_many(sqls: list[str], params) -> list[list[dict]]:
    """Kirim semua query sekaligus (berjalan paralel di BigQuery), lalu ambil hasilnya satu per satu."""
    from google.cloud import bigquery

    from .clients import bigquery_client

    client = bigquery_client()
    jobs = [client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)) for sql in sqls]
    return [[dict(r.items()) for r in job.result(page_size=20000)] for job in jobs]


# ==========================================================================
# Ambil data (dengan cache di bucket)
# ==========================================================================
def _cache_path(cfg: dict) -> str:
    from .config import _internal

    key = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    return _internal(f"rfm_cache/{key}.json.gz")


def fetch(cfg: dict | None = None, refresh: bool = False) -> dict[str, Any]:
    """{'outlets': DataFrame, 'series': DataFrame, 'audit': dict, 'fetched_at': str, 'cfg': dict}."""
    from .clients import storage_client
    from .config import settings

    cfg = dict(cfg or config())
    win = window(cfg["cutoff"])
    blob = None
    try:
        blob = storage_client().bucket(settings.bucket).blob(_cache_path(cfg))
        if not refresh and blob.exists():
            blob.reload()
            age = time.time() - blob.updated.timestamp()
            if age < CACHE_TTL:
                raw = json.loads(gzip.decompress(blob.download_as_bytes()))
                return _unpack(raw)
    except Exception:  # noqa: BLE001
        logger.warning("Cache RFM tidak terbaca; query ulang", exc_info=True)
    params = _params(cfg, win)
    t0 = time.time()
    outlets, series, audit_rows = _run_many([outlet_sql(cfg, win), series_sql(cfg, win), audit_sql(cfg, win)], params)
    audit = (audit_rows or [{}])[0]
    logger.info("Query RFM selesai: %d outlet, %d baris seri, %.1fs", len(outlets), len(series), time.time() - t0)
    raw = {"outlets": outlets, "series": series, "audit": audit, "cfg": cfg,
           "fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    try:
        if blob is not None:
            blob.upload_from_string(gzip.compress(json.dumps(raw, default=_json_default).encode()),
                                    content_type="application/gzip")
    except Exception:  # noqa: BLE001
        logger.warning("Cache RFM gagal disimpan", exc_info=True)
    return _unpack(json.loads(json.dumps(raw, default=_json_default)))


def _json_default(v):
    if isinstance(v, (date,)):
        return v.isoformat()
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return str(v)


def _unpack(raw: dict) -> dict[str, Any]:
    return {"outlets": pd.DataFrame(raw.get("outlets") or []), "series": pd.DataFrame(raw.get("series") or []),
            "audit": raw.get("audit") or {}, "cfg": raw.get("cfg") or {}, "fetched_at": raw.get("fetched_at", "")}


# ==========================================================================
# Perhitungan RFM
# ==========================================================================
def r_score(months: pd.Series) -> pd.Series:
    m = months.astype(float)
    return pd.Series(np.select([m <= 0, m <= 1, m <= 3, m <= 6], [5, 4, 3, 2], default=1), index=months.index).astype(int)


def thresholds(values: pd.Series) -> list[float]:
    v = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(v):
        return [0.0, 0.0, 0.0, 0.0]
    return [float(x) for x in np.percentile(v, [20, 40, 60, 80])]


def quint_score(values: pd.Series, cuts: list[float]) -> pd.Series:
    v = pd.to_numeric(values, errors="coerce").fillna(-np.inf).to_numpy(dtype=float)
    s = 1 + sum((v >= c).astype(int) for c in cuts)
    return pd.Series(s, index=values.index).astype(int)


def segment_conditions(r, f, m) -> list:
    return [(r >= 4) & (f >= 4) & (m >= 4), (r <= 2) & (f >= 4) & (m >= 4), (r == 1) & (f == 1),
            (r <= 2) & (f >= 3) & (m >= 3), (r <= 2) & (f <= 2), (r <= 2) & (f >= 3) & (m <= 2),
            (r == 3) & (f >= 3) & (m >= 3), (r == 3), (r >= 4) & (f >= 4) & (m <= 2),
            (r >= 4) & (f >= 4) & (m == 3), (r >= 4) & ((f == 2) | (f == 3)), (r >= 4) & (f == 1)]


def assign_segments(r: pd.Series, f: pd.Series, m: pd.Series) -> pd.Series:
    r, f, m = (np.asarray(x, dtype=int) for x in (r, f, m))
    idx = np.select(segment_conditions(r, f, m), list(range(12)), default=-1)
    return pd.Series([SEGMENTS[i] if i >= 0 else "UNASSIGNED" for i in idx])


def validate_125() -> dict[str, Any]:
    rows, unassigned, overlaps = [], 0, 0
    for r in range(1, 6):
        for f in range(1, 6):
            for m in range(1, 6):
                hits = [i for i, c in enumerate(segment_conditions(np.array([r]), np.array([f]), np.array([m]))) if c[0]]
                if not hits:
                    unassigned += 1
                if len(hits) > 1:
                    overlaps += 1
                rows.append({"R": r, "F": f, "M": m, "segment": SEGMENTS[hits[0]] if hits else "UNASSIGNED",
                             "matching_rules": len(hits), "rules": ", ".join(f"{i + 1:02d}" for i in hits)})
    return {"tested": len(rows), "unassigned": unassigned, "overlaps_resolved": overlaps, "rows": rows,
            "status": "PASS" if unassigned == 0 and len(rows) == 125 else "FAIL"}


def months_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def _last_positive(df: pd.DataFrame, months: list[tuple[int, int]]) -> pd.Series:
    """Bulan positif terakhir (indeks dalam `months`), -1 bila tidak ada."""
    pos = (df[[mcol(*ym) for ym in months]].to_numpy(dtype=float) > 0)
    any_pos = pos.any(axis=1)
    last = np.where(any_pos, pos.shape[1] - 1 - np.argmax(pos[:, ::-1], axis=1), -1)
    return pd.Series(last, index=df.index)


def prepare_outlets(raw: pd.DataFrame, win: dict) -> pd.DataFrame:
    df = raw.copy()
    for ym in win["months"]:
        c = mcol(*ym)
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0) if c in df else 0.0
    for c in ("cname", "region", "stype", "stype_name", "s_prev", "s_cur"):
        if c not in df:
            df[c] = ""
        df[c] = df[c].fillna("").astype(str)
    df["region_key"] = df["region"].map(region_key)
    df["stype_group"] = df["stype"].map(STORE_TYPE_GROUP).fillna("Lainnya")
    return df.reset_index(drop=True)


def compute(raw_outlets: pd.DataFrame, raw_series: pd.DataFrame, audit_sql_row: dict, cutoff: str,
            scope: str = "", thresholds_scope: str = "") -> dict[str, Any]:  # noqa: C901
    """Hitung seluruh isi laporan untuk satu cakupan ('' = nasional, atau 'SR3' dst.)."""
    win = window(cutoff)
    all_df = prepare_outlets(raw_outlets, win)
    scope_key = region_key(scope) if scope else ""
    df = all_df[all_df["region_key"] == scope_key].copy() if scope_key else all_df.copy()
    if df.empty:
        regions = sorted(all_df["region_key"].unique().tolist())
        raise ValueError(f"Tidak ada outlet untuk region '{scope}'. Region tersedia: {', '.join(regions)}")
    df = df.reset_index(drop=True)
    base_c = [mcol(*ym) for ym in win["base"]]
    ytd_c = [mcol(*ym) for ym in win["ytd"]]
    prev_c = [mcol(*ym) for ym in win["ytd_prev"]]
    all_c = [mcol(*ym) for ym in win["months"]]
    nb, ny = len(base_c), len(ytd_c)

    pos_any = (df[all_c].to_numpy() > 0).any(axis=1)
    no_positive = int((~pos_any).sum())
    df = df[pos_any].reset_index(drop=True)
    df["baseline"] = (df[base_c].to_numpy() > 0).any(axis=1)
    df["active_ytd"] = (df[ytd_c].to_numpy() > 0).any(axis=1)
    df["entrant"] = ~df["baseline"] & df["active_ytd"]
    df["vol_base"] = df[base_c].sum(axis=1)
    df["vol_ytd"] = df[ytd_c].sum(axis=1)
    df["vol_ytd_prev"] = df[prev_c].sum(axis=1)

    # ---- snapshot baseline (12 bulan)
    df["act_base"] = (df[base_c].to_numpy() > 0).sum(axis=1)
    df["F_base"] = df["act_base"] / nb
    df["M_base"] = df["vol_base"] / nb
    lb = _last_positive(df, win["base"])
    df["last_base"] = [mlabel(*win["base"][i]) if i >= 0 else "" for i in lb]
    df["Rm_base"] = [months_between(win["base"][i], win["base"][-1]) if i >= 0 else np.nan for i in lb]

    # ---- snapshot YTD (recency memakai histori s.d. cut-off)
    df["act_ytd"] = (df[ytd_c].to_numpy() > 0).sum(axis=1)
    df["F_ytd"] = df["act_ytd"] / ny
    df["M_ytd"] = df["vol_ytd"] / ny
    la = _last_positive(df, win["months"])
    df["last_ytd"] = [mlabel(*win["months"][i]) if i >= 0 else "" for i in la]
    df["Rm_ytd"] = [months_between(win["months"][i], win["months"][-1]) if i >= 0 else np.nan for i in la]

    base = df[df["baseline"]]
    if base.empty:
        raise ValueError("Tidak ada outlet baseline (pembelian positif di tahun dasar) pada cakupan ini.")
    # threshold: cakupan sendiri (region) atau cakupan lain bila diminta (mis. nasional)
    cut_df = base
    if thresholds_scope and region_key(thresholds_scope) != scope_key:
        ref = prepare_outlets(raw_outlets, win)
        ref = ref[(ref[base_c].to_numpy() > 0).any(axis=1)]
        if thresholds_scope.upper() not in ("NASIONAL", "NATIONAL", "ALL"):
            ref = ref[ref["region_key"] == region_key(thresholds_scope)]
        cut_df = pd.DataFrame({"F_base": (ref[base_c].to_numpy() > 0).sum(axis=1) / nb,
                               "M_base": ref[base_c].sum(axis=1) / nb})
    f_cut, m_cut = thresholds(cut_df["F_base"]), thresholds(cut_df["M_base"])

    df["R_base"] = r_score(df["Rm_base"].fillna(99))
    df["Fs_base"] = quint_score(df["F_base"], f_cut)
    df["Ms_base"] = quint_score(df["M_base"], m_cut)
    df["R_ytd"] = r_score(df["Rm_ytd"].fillna(99))
    df["Fs_ytd"] = quint_score(df["F_ytd"], f_cut)
    df["Ms_ytd"] = quint_score(df["M_ytd"], m_cut)
    inactive = df["baseline"] & ~df["active_ytd"]
    df.loc[inactive, ["Fs_ytd", "Ms_ytd"]] = 1                       # special case standar
    df["seg_base"] = np.where(df["baseline"], assign_segments(df["R_base"], df["Fs_base"], df["Ms_base"]), "")
    df["seg_ytd"] = assign_segments(df["R_ytd"], df["Fs_ytd"], df["Ms_ytd"])
    df["code_base"] = np.where(df["baseline"], df["R_base"].astype(str) + df["Fs_base"].astype(str) + df["Ms_base"].astype(str), "")
    df["code_ytd"] = df["R_ytd"].astype(str) + df["Fs_ytd"].astype(str) + df["Ms_ytd"].astype(str)
    df["score_base"] = np.where(df["baseline"], df["R_base"] + df["Fs_base"] + df["Ms_base"], 0)
    df["score_ytd"] = df["R_ytd"] + df["Fs_ytd"] + df["Ms_ytd"]
    df["momentum"] = np.where(~df["baseline"], "Entrant",
                              np.where(df["score_ytd"] > df["score_base"], "Improved",
                                       np.where(df["score_ytd"] == df["score_base"], "Stable", "Deteriorated")))
    df["migration"] = np.where(df["baseline"], df["seg_base"] + " → " + df["seg_ytd"], "Dataset Entrant")
    snap = df[df["baseline"] | df["entrant"]]                         # populasi snapshot YTD

    res: dict[str, Any] = {"scope": scope_key or "NASIONAL", "scope_label": _scope_label(df, scope_key),
                           "window": {k: win[k] for k in ("y0", "y1", "cm", "label_base", "label_ytd", "label_ytd_prev",
                                                          "n_ytd")},
                           "thresholds": {"F": f_cut, "M": m_cut,
                                          "basis": (f"baseline {win['y0']} " +
                                                    ("nasional" if (thresholds_scope or "").upper() in ("NASIONAL", "NATIONAL", "ALL")
                                                     or not scope_key else (thresholds_scope or scope_key).upper())),
                                          "n_baseline": int(len(cut_df)), "method": "numpy percentile (linear), "
                                          "batas inklusif: nilai = threshold masuk skor lebih tinggi"}}

    # ---- KPI & populasi
    vol_ytd_total, vol_prev_total = float(df["vol_ytd"].sum()), float(df["vol_ytd_prev"].sum())
    coh = df[df["baseline"]]
    coh_ytd, coh_prev = float(coh["vol_ytd"].sum()), float(coh["vol_ytd_prev"].sum())
    ent_ytd = float(df.loc[df["entrant"], "vol_ytd"].sum())
    res["kpi"] = {
        "outlets_valid": int(len(df)), "outlets_baseline": int(df["baseline"].sum()),
        "outlets_entrants": int(df["entrant"].sum()), "outlets_inactive_baseline": int(inactive.sum()),
        "outlets_snapshot_ytd": int(len(snap)), "outlets_active_ytd": int(df["active_ytd"].sum()),
        "vol_ytd": vol_ytd_total, "vol_ytd_prev": vol_prev_total, "vol_base_fy": float(df["vol_base"].sum()),
        "yoy_total_pct": _pct(vol_ytd_total, vol_prev_total),
        "vol_cohort_ytd": coh_ytd, "vol_cohort_ytd_prev": coh_prev, "yoy_cohort_pct": _pct(coh_ytd, coh_prev),
        "vol_entrants_ytd": ent_ytd, "entrant_share_pct": _share(ent_ytd, vol_ytd_total),
        "vol_per_active_outlet_month": _safe_div(vol_ytd_total, int((df[ytd_c].to_numpy() > 0).sum())),
    }

    # ---- segmen (snapshot YTD)
    seg = []
    for s in SEGMENTS:
        part = snap[snap["seg_ytd"] == s]
        seg.append({"segment": s, "outlets": int(len(part)), "outlet_share": _share(len(part), len(snap)),
                    "vol_ytd": float(part["vol_ytd"].sum()), "vol_share": _share(part["vol_ytd"].sum(), snap["vol_ytd"].sum()),
                    "avg_m": float(part["M_ytd"].mean()) if len(part) else 0.0})
    res["segments"] = seg
    res["segments_base"] = [{"segment": s, "outlets": int((coh["seg_base"] == s).sum()),
                             "vol_base": float(coh.loc[coh["seg_base"] == s, "vol_base"].sum())} for s in SEGMENTS]

    # ---- momentum & migrasi (cohort baseline saja)
    mom = coh["momentum"].value_counts()
    res["momentum"] = [{"status": k, "outlets": int(mom.get(k, 0)), "share": _share(mom.get(k, 0), len(coh))}
                       for k in ("Improved", "Stable", "Deteriorated")]
    mat = pd.crosstab(coh["seg_base"], coh["seg_ytd"]).reindex(index=SEGMENTS, columns=SEGMENTS, fill_value=0)
    res["migration"] = {"rows": SEGMENTS, "cols": SEGMENTS, "cells": mat.to_numpy(dtype=int).tolist(),
                        "total": int(mat.to_numpy().sum()), "cohort": int(len(coh)),
                        "reconciled": int(mat.to_numpy().sum()) == int(len(coh)),
                        "stayed": int(np.trace(mat.to_numpy()))}
    top_moves = []
    for i, a in enumerate(SEGMENTS):
        for j, b in enumerate(SEGMENTS):
            if i != j and mat.iat[i, j]:
                top_moves.append({"dari": a, "ke": b, "outlets": int(mat.iat[i, j])})
    res["migration"]["top_moves"] = sorted(top_moves, key=lambda x: -x["outlets"])[:8]

    # ---- tren bulanan & kuartal
    res["monthly"] = {"labels": MONTHS_ID,
                      "prev": [float(df[mcol(win["y0"], m)].sum()) for m in range(1, 13)],
                      "cur": [float(df[mcol(win["y1"], m)].sum()) for m in range(1, win["cm"] + 1)],
                      "active_prev": [int((df[mcol(win["y0"], m)] > 0).sum()) for m in range(1, 13)],
                      "active_cur": [int((df[mcol(win["y1"], m)] > 0).sum()) for m in range(1, win["cm"] + 1)]}
    q = []
    for qi in win["quarters"]:
        cols0 = [mcol(win["y0"], m) for m in range(qi * 3 - 2, qi * 3 + 1)]
        cols1 = [mcol(win["y1"], m) for m in range(qi * 3 - 2, qi * 3 + 1)]
        v0, v1 = float(df[cols0].sum().sum()), float(df[cols1].sum().sum())
        a0 = int((df[cols0].to_numpy() > 0).any(axis=1).sum())
        a1 = int((df[cols1].to_numpy() > 0).any(axis=1).sum())
        q.append({"quarter": f"Q{qi}", "vol_prev": v0, "vol_cur": v1, "yoy_pct": _pct(v1, v0),
                  "active_prev": a0, "active_cur": a1})
    res["quarters"] = q

    # ---- tipe outlet & region
    res["store_types"] = _group_table(df, "stype", extra="stype_name")
    if not scope_key:
        res["regions"] = _group_table(df, "region_key", extra="region")
        reg_seg = []
        for rk, part in snap.groupby("region_key"):
            row = {"region": rk, "outlets": int(len(part))}
            for s in SEGMENTS:
                row[s] = int((part["seg_ytd"] == s).sum())
            reg_seg.append(row)
        res["region_segments"] = sorted(reg_seg, key=lambda r: r["region"])

    # ---- produk
    res["products"] = _products(raw_series, df, snap, coh, scope_key, all_df)

    # ---- daftar outlet prioritas
    cols = ["cust", "cname", "stype", "region_key"]
    champ = snap[snap["seg_ytd"] == "Champions"].nlargest(20, "vol_ytd")
    res["top_champions"] = [{**_ident_row(r, cols), "vol_ytd": float(r["vol_ytd"]), "M": float(r["M_ytd"]),
                             "F": float(r["F_ytd"]), "seg_base": r["seg_base"] or "Dataset Entrant"} for _, r in champ.iterrows()]
    dec = coh.assign(chg=coh["vol_ytd"] - coh["vol_ytd_prev"])
    dec = dec[dec["chg"] < 0].nsmallest(20, "chg")
    res["top_declines"] = [{**_ident_row(r, cols), "vol_prev": float(r["vol_ytd_prev"]), "vol_cur": float(r["vol_ytd"]),
                            "change": float(r["chg"]), "pct": _pct(r["vol_ytd"], r["vol_ytd_prev"]),
                            "seg_base": r["seg_base"], "seg_ytd": r["seg_ytd"]} for _, r in dec.iterrows()]
    rec = coh[coh["seg_ytd"].isin(RECOVERY_SEGMENTS)].nlargest(20, "vol_base")
    res["recovery"] = [{**_ident_row(r, cols), "vol_base": float(r["vol_base"]), "vol_cur": float(r["vol_ytd"]),
                        "seg_base": r["seg_base"], "seg_ytd": r["seg_ytd"], "last": r["last_ytd"]} for _, r in rec.iterrows()]

    # ---- playbook: whitespace seri di segmen bernilai tinggi (hanya hitungan dari data)
    hv = snap[snap["seg_ytd"].isin(["Champions", "Loyal Customers"])]
    ws = []
    for p in res["products"]["top"][:5]:
        has = hv["s_cur"].map(lambda s, n=p["series"]: n in s.split("|"))
        ws.append({"series": p["series"], "high_value_outlets": int(len(hv)), "not_buying": int((~has).sum()),
                   "not_buying_share": _share((~has).sum(), len(hv))})
    res["whitespace"] = ws

    # ---- audit & validasi
    v125 = validate_125()
    res["validation_125"] = {k: v for k, v in v125.items() if k != "rows"}
    a = dict(audit_sql_row or {})
    res["audit"] = {**{k: _num(v) for k, v in a.items() if not str(k).endswith("_json")},
                    "regions": _loads(a.get("regions_json")), "store_types_all": _loads(a.get("store_types_json")),
                    "outlets_no_positive_purchase": no_positive,
                    "outlets_in_scope": int(len(df) + no_positive)}
    res["checks"] = {"migration_reconciled": res["migration"]["reconciled"],
                     "segments_reconciled": sum(s["outlets"] for s in seg) == len(snap),
                     "rules_125": v125["status"], "unassigned_outlets": int((snap["seg_ytd"] == "UNASSIGNED").sum())}
    res["register"] = df                                               # DataFrame (untuk Excel, bukan JSON)
    res["rule_rows"] = v125["rows"]
    return res


def _scope_label(df: pd.DataFrame, key: str) -> str:
    if not key:
        return "Nasional"
    names = df["region"].replace("", np.nan).dropna()
    raw = names.mode().iat[0] if len(names) else key
    return f"Sales Region {key[2:]} ({raw})" if key.startswith("SR") else str(raw)


def _ident_row(r, cols) -> dict:
    return {"code": r["cust"], "name": r["cname"] or "-", "type": r["stype"], "region": r["region_key"]}


def _group_table(df: pd.DataFrame, key: str, extra: str = "") -> list[dict]:
    out = []
    for k, part in df.groupby(key):
        out.append({"key": k, "label": part[extra].mode().iat[0] if extra and len(part) else k,
                    "outlets": int(len(part)), "baseline": int(part["baseline"].sum()), "entrants": int(part["entrant"].sum()),
                    "vol_ytd": float(part["vol_ytd"].sum()), "vol_ytd_prev": float(part["vol_ytd_prev"].sum()),
                    "yoy_pct": _pct(part["vol_ytd"].sum(), part["vol_ytd_prev"].sum()),
                    "vol_share": _share(part["vol_ytd"].sum(), df["vol_ytd"].sum())})
    return sorted(out, key=lambda r: -r["vol_ytd"])


def _products(raw_series: pd.DataFrame, df: pd.DataFrame, snap: pd.DataFrame, coh: pd.DataFrame, scope_key: str,
              all_df: pd.DataFrame) -> dict[str, Any]:
    s = raw_series.copy() if raw_series is not None else pd.DataFrame()
    out: dict[str, Any] = {"top": [], "growth": [], "table": [], "penetration": {}, "adoption": []}
    if s.empty:
        return out
    for c in ("vol_prev", "vol_cur"):
        s[c] = pd.to_numeric(s[c], errors="coerce").fillna(0.0)
    s["series"] = s["series"].fillna("(tanpa seri)").astype(str)
    s["region_key"] = s["region"].map(region_key)
    s["in_cohort"] = s["in_cohort"].astype(str).str.lower().isin(["true", "1"])
    if scope_key:
        s = s[s["region_key"] == scope_key]
    tot = s.groupby("series")[["vol_prev", "vol_cur"]].sum()
    co = s[s["in_cohort"]].groupby("series")[["vol_prev", "vol_cur"]].sum().reindex(tot.index, fill_value=0.0)
    total_cur = float(tot["vol_cur"].sum())
    sets_cur = snap["s_cur"].map(lambda x: set(filter(None, x.split("|"))))
    coh_prev = coh["s_prev"].map(lambda x: set(filter(None, x.split("|"))))
    coh_cur = coh["s_cur"].map(lambda x: set(filter(None, x.split("|"))))
    rows = []
    for name, r in tot.iterrows():
        buyers = int(sets_cur.map(lambda st, n=name: n in st).sum())
        adopted = int(sum(1 for a, b in zip(coh_prev, coh_cur) if name not in a and name in b))
        disc = int(sum(1 for a, b in zip(coh_prev, coh_cur) if name in a and name not in b))
        rows.append({"series": name, "vol_cur": float(r["vol_cur"]), "vol_prev": float(r["vol_prev"]),
                     "yoy_pct": _pct(r["vol_cur"], r["vol_prev"]), "share": _share(r["vol_cur"], total_cur),
                     "cohort_cur": float(co.at[name, "vol_cur"]), "cohort_prev": float(co.at[name, "vol_prev"]),
                     "cohort_yoy_pct": _pct(co.at[name, "vol_cur"], co.at[name, "vol_prev"]),
                     "buyers": buyers, "penetration": _share(buyers, len(snap)), "adopted": adopted,
                     "discontinued": disc, "net_adoption": adopted - disc})
    rows.sort(key=lambda r: -r["vol_cur"])
    out["table"] = rows
    out["top"] = rows[:10]
    base_min = 0.005 * float(co["vol_prev"].sum())                     # basis bermakna: ≥ 0,5% volume cohort tahun dasar
    grow = [r for r in rows if r["cohort_prev"] > 0 and r["cohort_prev"] >= base_min and r["cohort_yoy_pct"] is not None]
    out["growth"] = sorted(grow, key=lambda r: -r["cohort_yoy_pct"])[:10]
    out["growth_min_base"] = base_min
    top8 = [r["series"] for r in rows[:8]]
    pen = {}
    for seg in PRIORITY_SEGMENTS:
        part = sets_cur[snap["seg_ytd"] == seg]
        pen[seg] = {"outlets": int(len(part)),
                    "values": [_share(part.map(lambda st, n=n: n in st).sum(), len(part)) if len(part) else None for n in top8]}
    out["penetration"] = {"series": top8, "segments": pen}
    out["adoption"] = sorted(rows, key=lambda r: -(r["adopted"] + r["discontinued"]))[:12]
    return out


# ==========================================================================
# Utilitas
# ==========================================================================
def _safe_div(a, b):
    return float(a) / float(b) if b else None


def _pct(cur, prev):
    cur, prev = float(cur or 0), float(prev or 0)
    return (cur - prev) / abs(prev) * 100 if prev else None


def _share(part, total):
    return float(part) / float(total) * 100 if total else 0.0


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 1e15 else f
    except (TypeError, ValueError):
        return v


def _loads(text):
    try:
        return json.loads(text) if text else []
    except (TypeError, ValueError):
        return []


def numbers_pool(res: dict[str, Any]) -> list[float]:
    """Semua angka di hasil (untuk pemeriksa angka narasi)."""
    pool: set[float] = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float, np.integer, np.floating)):
            v = abs(float(x))
            if np.isfinite(v):
                pool.update({round(v, 2), round(v, 1), round(v), round(v * 100, 2)})
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("register", "rule_rows"):
                    walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk({k: v for k, v in res.items() if k not in ("register", "rule_rows")})
    return sorted(pool)


def compact(res: dict[str, Any]) -> dict[str, Any]:
    """Ringkasan untuk model penulis narasi (tanpa daftar outlet panjang)."""
    p = res["products"]
    return {"cakupan": res["scope_label"], "periode": res["window"], "kpi": res["kpi"],
            "threshold": res["thresholds"], "segmen_ytd": res["segments"], "momentum": res["momentum"],
            "perpindahan_terbesar": res["migration"]["top_moves"], "tetap_di_segmen": res["migration"]["stayed"],
            "kuartal": res["quarters"], "tipe_outlet": res["store_types"], "region": res.get("regions"),
            "produk_top": p.get("top", [])[:8], "produk_tumbuh": p.get("growth", [])[:5],
            "adopsi": [{k: r[k] for k in ("series", "adopted", "discontinued", "net_adoption")} for r in p.get("adoption", [])[:6]],
            "whitespace_segmen_bernilai": res["whitespace"],
            "top3_champions": res["top_champions"][:3], "top3_penurunan": res["top_declines"][:3]}


def to_json_safe(x):
    """Konversi nilai numpy/NaN agar aman disimpan sebagai JSON."""
    if isinstance(x, dict):
        return {k: to_json_safe(v) for k, v in x.items() if k != "register"}
    if isinstance(x, (list, tuple)):
        return [to_json_safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(float(x)) else float(x)
    return x


def register_excel(res: dict[str, Any]) -> bytes:
    """Calculation workbook / outlet register (sheet sesuai bab 12 panduan)."""
    from openpyxl import Workbook

    df: pd.DataFrame = res["register"]
    wb = Workbook(write_only=True)

    def sheet(name, header, rows):
        ws = wb.create_sheet(name)
        ws.append(header)
        for r in rows:
            ws.append([None if (isinstance(v, float) and not np.isfinite(v)) else v for v in r])

    w = res["window"]
    master_cols = ["cust", "cname", "region", "region_key", "stype", "stype_name", "baseline", "entrant",
                   "act_base", "F_base", "vol_base", "M_base", "last_base", "Rm_base", "R_base", "Fs_base", "Ms_base",
                   "code_base", "seg_base", "act_ytd", "F_ytd", "vol_ytd", "M_ytd", "last_ytd", "Rm_ytd", "R_ytd",
                   "Fs_ytd", "Ms_ytd", "code_ytd", "seg_ytd", "score_base", "score_ytd", "momentum", "migration",
                   "vol_ytd_prev"]
    header = ["Customer Code", "Customer Name", "Region (sumber)", "Region", "Store Type", "Store Type Name",
              f"Baseline {w['y0']}", "Dataset Entrant", f"Bulan aktif {w['y0']}", f"F {w['y0']}", f"Volume {w['y0']} (KL)",
              f"M {w['y0']} (KL/bln)", f"Pembelian terakhir {w['y0']}", f"Recency {w['y0']} (bln)", f"R {w['y0']}",
              f"F skor {w['y0']}", f"M skor {w['y0']}", f"RFM {w['y0']}", f"Segmen {w['y0']}", "Bulan aktif YTD",
              "F YTD", "Volume YTD (KL)", "M YTD (KL/bln)", "Pembelian terakhir (s.d. cut-off)", "Recency YTD (bln)",
              "R YTD", "F skor YTD", "M skor YTD", "RFM YTD", "Segmen YTD", f"Skor total {w['y0']}", "Skor total YTD",
              "Momentum", "Migrasi", f"Volume {w['label_ytd_prev']} (KL)"]
    sheet("Outlet RFM Master", header, df[master_cols].astype(object).to_numpy().tolist())
    b = df[df["baseline"]]
    big = len(df) > REGISTER_FULL_MAX
    if big:      # laporan nasional besar: sheet snapshot/migrasi = subset kolom master; dilewati agar cepat & ringan
        sheet("Catatan", ["Catatan"], [[f"{len(df):,} outlet: sheet Snapshot {w['y0']}, Snapshot YTD, dan Migration Cohort "
                                        "tidak dipisah karena seluruh kolomnya sudah ada di 'Outlet RFM Master' (filter "
                                        f"kolom 'Baseline {w['y0']}' / 'Dataset Entrant'). Register per region memuat "
                                        "sheet lengkap."]])
    if not big:
        _snapshot_sheets(sheet, df, b, w)
    sheet("125 Rule Validation", ["R", "F", "M", "Segmen", "Jumlah aturan cocok", "Aturan cocok (urutan)"],
          ([r["R"], r["F"], r["M"], r["segment"], r["matching_rules"], r["rules"]] for r in res["rule_rows"]))
    t = res["thresholds"]
    sref = [["R5", "Recency 0 bulan", ""], ["R4", "Recency 1 bulan", ""], ["R3", "Recency 2–3 bulan", ""],
            ["R2", "Recency 4–6 bulan", ""], ["R1", "Recency > 6 bulan", ""]]
    for i, p in enumerate(("P20", "P40", "P60", "P80")):
        sref.append([f"F {p}", t["F"][i], t["basis"]])
    for i, p in enumerate(("P20", "P40", "P60", "P80")):
        sref.append([f"M {p} (KL/bln)", t["M"][i], t["basis"]])
    sref += [["Metode", t["method"], ""], ["Populasi baseline threshold", t["n_baseline"], ""],
             ["Special case", "Baseline tanpa pembelian YTD: F skor = 1, M skor = 1", ""]]
    sheet("Scoring Reference", ["Item", "Nilai (presisi penuh)", "Basis"], sref)
    sheet("Data Audit", ["Item", "Nilai"], ([k, json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v]
                                           for k, v in {**res["audit"], **res["checks"],
                                                        "validasi_125": json.dumps(res["validation_125"])}.items()))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _snapshot_sheets(sheet, df: pd.DataFrame, b: pd.DataFrame, w: dict) -> None:
    sheet(f"Snapshot {w['y0']}", ["Customer Code", "Bulan aktif", "F", "Volume (KL)", "M", "Recency (bln)", "R", "F skor",
                                  "M skor", "RFM", "Segmen"],
          b[["cust", "act_base", "F_base", "vol_base", "M_base", "Rm_base", "R_base", "Fs_base", "Ms_base", "code_base",
             "seg_base"]].itertuples(index=False, name=None))
    s = df[df["baseline"] | df["entrant"]]
    sheet("Snapshot YTD", ["Customer Code", "Kohort", "Bulan aktif", "F", "Volume (KL)", "M", "Recency (bln)", "R",
                           "F skor", "M skor", "RFM", "Segmen"],
          ((r.cust, "Baseline" if r.baseline else "Entrant", r.act_ytd, r.F_ytd, r.vol_ytd, r.M_ytd, r.Rm_ytd, r.R_ytd,
            r.Fs_ytd, r.Ms_ytd, r.code_ytd, r.seg_ytd) for r in s.itertuples()))
    sheet("Migration Cohort", ["Customer Code", f"Segmen {w['y0']}", "Segmen YTD", f"Skor {w['y0']}", "Skor YTD",
                               "Momentum"],
          b[["cust", "seg_base", "seg_ytd", "score_base", "score_ytd", "momentum"]].itertuples(index=False, name=None))
