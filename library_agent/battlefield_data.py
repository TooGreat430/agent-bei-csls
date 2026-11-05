"""Analisis silang RETAIL (harga) × PLANOGRAM (rak) — "Competitive Battlefield".

Hanya kombinasi Retail × Planogram yang didukung (Industri tidak punya kunci produk yang sama).
Kunci gabung: KIMAP (retail) = PAIR_KIMAP (planogram). Semua angka dihitung di sini dengan pandas.

Per KIMAP (head-to-head PTPL vs kompetitor utama = brand kompetitor dengan carry terbesar di KIMAP itu):
- HARGA (sudut pandang customer): keunggulan harga jual = (HJ/L kompetitor − HJ/L PTPL) / HJ/L kompetitor × 100.
  Pembanding = brand head-to-head bila sampel harganya cukup, selain itu rata-rata kompetitor di KIMAP yang sama.
  ✓ jika PTPL lebih murah.
- EKONOMI OUTLET: gap margin/L = margin PTPL − margin kompetitor. ✓ jika ≥ 0.
- PLANOGRAM: rasio carry PTPL/kompetitor ≥ ambang (default 70%) DAN gap AV ≥ 0 -> ✓.
- Status: Pemenang Kompetitif · Gap Eksekusi · Gap Ekonomi · Gap Ekonomi + Eksekusi · Gap Harga ·
  Double Jeopardy (harga ✕ dan planogram ✕) · Data harga belum tersedia.
Kategori (Segmen × Usage × Viskositas): exposure semua brand, AV, leader; tanpa PTPL = WHITE SPACE.
Momentum kompetitor (kuartal pembanding → berjalan): TRUE THREAT (outlet ↑, AV ↑), DISTRIBUTION THREAT (outlet ↑,
AV tidak naik), CONVERSION WINDOW (outlet ↓, AV ↓), selain itu MONITOR.
Carry outlet = exposure, BUKAN market share. Data survei = asosiasi, bukan sebab-akibat.
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from .planogram_data import SR_ORDER, _r

SOURCE_LABEL = "Survey Response Report Retail × Planogram Marketing Intelligence (VM_PLANOGRAM)"
STATUSES = ["Pemenang Kompetitif", "Gap Eksekusi", "Gap Ekonomi", "Gap Ekonomi + Eksekusi", "Gap Harga",
            "Double Jeopardy", "Data harga belum tersedia"]
STATUS_CLS = {"Pemenang Kompetitif": "h2c", "Gap Eksekusi": "h3c", "Gap Ekonomi": "h3c",
              "Gap Ekonomi + Eksekusi": "h4c", "Gap Harga": "h4c", "Double Jeopardy": "h5c"}
SEG_ORDER = ["MCO", "PCO", "COMMERCIAL"]

RETAIL_SQL = """
WITH base AS (
  SELECT
    SUBSTR(CAST(DT_PR AS STRING), 1, 10) AS D,
    CONCAT('SR', REGEXP_REPLACE(CAST(SALES_REGION_CUSTOMER AS STRING), r'\\.0$', '')) AS SR,
    UPPER(TRIM(CAST(SEGMENT AS STRING))) AS SEGMENT, UPPER(TRIM(CAST(USED_FOR AS STRING))) AS USAGE,
    UPPER(TRIM(CAST(VISCOSITY AS STRING))) AS VISCOSITY, TRIM(CAST(KIMAP AS STRING)) AS KIMAP,
    UPPER(TRIM(BRAND)) AS BRAND, UPPER(TRIM(QNR)) AS QNR,
    SAFE_DIVIDE(CAST(HARGA_JUAL AS FLOAT64), {content}) AS HJ_L,
    SAFE_DIVIDE(CAST(HTO AS FLOAT64), {content}) AS HTO_L,
    SAFE_DIVIDE(CAST(MARGIN_SURVEY AS FLOAT64), {content}) AS MARG_L
  FROM `{table}`
  WHERE AVAILABILITY = '1' AND OUTLIER_HTO = 'DATA USE' AND OUTLIER_HET = 'DATA USE'
    AND KIMAP IS NOT NULL AND {content} > 0
    AND (SUBSTR(CAST(DT_PR AS STRING), 1, 10) BETWEEN @a_start AND @a_end
         OR SUBSTR(CAST(DT_PR AS STRING), 1, 10) BETWEEN @b_start AND @b_end)
)
SELECT IF(D BETWEEN @a_start AND @a_end, 'A', 'B') AS PERIOD, SR, SEGMENT, USAGE, VISCOSITY, KIMAP, BRAND, QNR,
  SUM(HJ_L) AS S_HJ, COUNT(HJ_L) AS N_HJ, SUM(HTO_L) AS S_HTO, COUNT(HTO_L) AS N_HTO,
  SUM(MARG_L) AS S_MARG, COUNT(MARG_L) AS N_MARG
FROM base
GROUP BY PERIOD, SR, SEGMENT, USAGE, VISCOSITY, KIMAP, BRAND, QNR
"""
PRICE_COLS = ["PERIOD", "SR", "SEGMENT", "USAGE", "VISCOSITY", "KIMAP", "BRAND", "QNR",
              "S_HJ", "N_HJ", "S_HTO", "N_HTO", "S_MARG", "N_MARG"]


# ==========================================================================
# Ambil data
# ==========================================================================
def fetch_retail(period_a: dict, period_b: dict | None, table: str) -> pd.DataFrame:
    from google.cloud import bigquery

    from .clients import bigquery_client
    from .price_data import VALID_CONTENT_SQL, normalize_rows

    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", table):
        raise ValueError("Nama tabel tidak valid.")
    pb = period_b or {"start": "0000-00-00", "end": "0000-00-00"}
    params = [bigquery.ScalarQueryParameter(n, "STRING", v) for n, v in (
        ("a_start", period_a["start"]), ("a_end", period_a["end"]), ("b_start", pb["start"]), ("b_end", pb["end"]))]
    job = bigquery_client().query(RETAIL_SQL.format(table=table, content=VALID_CONTENT_SQL),
                                  job_config=bigquery.QueryJobConfig(query_parameters=params))
    return pd.DataFrame(normalize_rows([dict(r.items()) for r in job.result()]), columns=PRICE_COLS)


def retail_rows_from_frame(prepared: pd.DataFrame, period_a: dict, period_b: dict | None) -> pd.DataFrame:
    """Frame retail (sudah di-prepare data_engine) -> baris agregat seperti fetch_retail()."""
    from .data_engine import PlanError, _col, region_number

    c = lambda n: _col(prepared, n)  # noqa: E731
    need = ["DT_PR", "SALES_REGION_CUSTOMER", "SEGMENT", "VISCOSITY", "KIMAP", "BRAND"]
    missing = [n for n in need if not c(n)] + [n for n in ("HJ_L",) if n not in prepared.columns]
    if missing:
        raise PlanError(f"File retail tidak lengkap untuk analisis silang (kolom hilang: {', '.join(missing)}).")
    d = prepared.copy()
    day = d[c("DT_PR")].astype(str).str.slice(0, 10)
    in_a = day.between(period_a["start"], period_a["end"])
    in_b = day.between(period_b["start"], period_b["end"]) if period_b else pd.Series(False, index=d.index)
    d = d[in_a | in_b].copy()
    out = pd.DataFrame({
        "PERIOD": in_a[d.index].map({True: "A", False: "B"}),
        "SR": "SR" + region_number(d[c("SALES_REGION_CUSTOMER")]),
        "SEGMENT": d[c("SEGMENT")].astype(str).str.strip().str.upper(),
        "USAGE": d[c("USED_FOR")].astype(str).str.strip().str.upper() if c("USED_FOR") else "",
        "VISCOSITY": d[c("VISCOSITY")].astype(str).str.strip().str.upper(),
        "KIMAP": d[c("KIMAP")].astype(str).str.strip().str.replace(r"\.0$", "", regex=True),
        "BRAND": d[c("BRAND")].astype(str).str.strip().str.upper(),
        "QNR": d[c("QNR")].astype(str).str.strip().str.upper() if c("QNR") else "",
        "HJ": d["HJ_L"], "HTO": d["HTO_L"] if "HTO_L" in d else float("nan"),
        "MARG": d["MARG_L"] if "MARG_L" in d else float("nan")})
    g = out.groupby(PRICE_COLS[:8], dropna=False)
    agg = g.agg(S_HJ=("HJ", "sum"), N_HJ=("HJ", "count"), S_HTO=("HTO", "sum"), N_HTO=("HTO", "count"),
                S_MARG=("MARG", "sum"), N_MARG=("MARG", "count")).reset_index()
    return agg[PRICE_COLS]


# ==========================================================================
# Helper perhitungan
# ==========================================================================
def _mean(df: pd.DataFrame, metric: str) -> tuple[float | None, int]:
    n = int(df[f"N_{metric}"].sum()) if not df.empty else 0
    return (_r(df[f"S_{metric}"].sum() / n, 0) if n else None), n


def _seg_label(seg: str, usage: str = "", visc: str = "") -> str:
    s = {"COMMERCIAL": "Commercial"}.get(str(seg).upper(), str(seg).upper())
    u = str(usage or "").title()
    return " ".join(x for x in (s, u, str(visc or "")) if x and x != "Nan")


def _threat(d_carry: int | None, d_av: float | None) -> str:
    if d_carry is None:
        return "n/a"
    if d_carry > 0 and (d_av or 0) > 0:
        return "TRUE THREAT"
    if d_carry > 0:
        return "DISTRIBUTION THREAT"
    if d_carry < 0 and (d_av or 0) < 0:
        return "CONVERSION WINDOW"
    return "MONITOR"


def classify(price_ok: bool | None, eco_ok: bool | None, plan_ok: bool) -> str:
    if price_ok is None:
        return "Data harga belum tersedia"
    if price_ok and plan_ok:
        return "Gap Ekonomi" if eco_ok is False else "Pemenang Kompetitif"
    if price_ok:
        return "Gap Ekonomi + Eksekusi" if eco_ok is False else "Gap Eksekusi"
    return "Gap Harga" if plan_ok else "Double Jeopardy"


def _momentum(A: pd.DataFrame, B: pd.DataFrame, min_base: int) -> list[dict]:
    """Momentum kompetitor per brand × series × KIMAP (outlet unik & AV)."""
    out = []
    ca, cb = A[~A["IS_PTPL"] & A["PAIR_KIMAP"].notna()], B[~B["IS_PTPL"] & B["PAIR_KIMAP"].notna()]
    if ca.empty or cb.empty:
        return out
    ga = ca.groupby(["BRAND", "SERIES", "PAIR_KIMAP"]).agg(out_a=("OUTLET_ID", "nunique"), av_a=("AV", "mean"))
    gb = cb.groupby(["BRAND", "SERIES", "PAIR_KIMAP"]).agg(out_b=("OUTLET_ID", "nunique"), av_b=("AV", "mean"))
    m = ga.join(gb, how="inner").reset_index()
    m = m[m["out_b"] >= min_base]
    ptpl = A[A["IS_PTPL"] & A["PAIR_KIMAP"].notna()].groupby("PAIR_KIMAP")["SERIES"].agg(
        lambda s: s.value_counts().index[0])
    seg = A[A["PAIR_KIMAP"].notna()].groupby("PAIR_KIMAP")["SEGMENT"].agg(lambda s: s.value_counts().index[0])
    for r in m.itertuples(index=False):
        d = int(r.out_a - r.out_b)
        dav = _r(r.av_a - r.av_b, 2)
        out.append({"brand": r.BRAND, "series": r.SERIES, "kimap": r.PAIR_KIMAP, "segmen": seg.get(r.PAIR_KIMAP, ""),
                    "ptpl_h2h": str(ptpl.get(r.PAIR_KIMAP)).title() if r.PAIR_KIMAP in ptpl.index else None,
                    "out_b": int(r.out_b), "out_a": int(r.out_a), "delta": d, "growth_pct": _r(d / r.out_b * 100),
                    "delta_av": dav, "type": _threat(d, dav)})
    return out


# ==========================================================================
# Dataset
# ==========================================================================
def build_dataset(plan_rows: pd.DataFrame, price_rows: pd.DataFrame, period_a: dict, period_b: dict | None,
                  ratio_line: float = 70, min_price_n: int = 10, min_carry: int = 30,
                  notes: dict | None = None) -> dict[str, Any]:  # noqa: C901
    eng = plan_rows[plan_rows["IS_OLI_MESIN"].fillna(False).astype(bool)].copy() if not plan_rows.empty else plan_rows
    for col in ("SERIES", "BRAND"):
        if col in eng:
            eng[col] = eng[col].astype(str)
    A = eng[eng["PERIOD"] == "A"]
    B = eng[eng["PERIOD"] == "B"]
    PA = price_rows[price_rows["PERIOD"] == "A"] if not price_rows.empty else price_rows
    PB = price_rows[price_rows["PERIOD"] == "B"] if not price_rows.empty else price_rows
    has_b = period_b is not None and not B.empty
    ds: dict[str, Any] = {"period": {"a": period_a["label"], "b": period_b["label"] if period_b else None},
                          "has_b": has_b, "has_plan": not A.empty, "has_price": not PA.empty,
                          "source_label": SOURCE_LABEL, "ratio_line": ratio_line, "min_price_n": min_price_n,
                          "notes": dict(notes or {})}
    if A.empty:
        return ds

    # --- kategori (planogram) ---
    cats = []
    for (seg, usage, visc), g in A.groupby(["SEGMENT", "USAGE", "VISCOSITY"]):
        gb = B[(B["SEGMENT"] == seg) & (B["USAGE"] == usage) & (B["VISCOSITY"] == visc)] if has_b else B.iloc[0:0]
        expo_a, expo_b = int(g["OUTLET_ID"].nunique()), (int(gb["OUTLET_ID"].nunique()) if not gb.empty else None)
        brands = g.groupby("BRAND")["OUTLET_ID"].nunique().sort_values(ascending=False)
        ptpl = int(g[g["IS_PTPL"]]["OUTLET_ID"].nunique())
        av_a = _r(g["AV"].mean(), 2)
        av_b = _r(gb["AV"].mean(), 2) if not gb.empty else None
        cats.append({"segmen": seg, "usage": usage, "viscosity": str(visc), "label": _seg_label(seg, usage, visc),
                     "exposure": expo_a, "exposure_b": expo_b,
                     "delta_pct": _r((expo_a - expo_b) / expo_b * 100) if expo_b else None,
                     "av": av_a, "delta_av": _r(av_a - av_b, 2) if av_a is not None and av_b is not None else None,
                     "leader": brands.index[0] if len(brands) else None, "leader_carry": int(brands.iloc[0]) if len(brands) else 0,
                     "second": brands.index[1] if len(brands) > 1 else None,
                     "second_carry": int(brands.iloc[1]) if len(brands) > 1 else None,
                     "ptpl_carry": ptpl, "white_space": ptpl == 0, "small": expo_a < min_carry})
    cats.sort(key=lambda c: -c["exposure"])
    ds["categories"] = cats
    ds["white_space"] = [c for c in cats if c["white_space"] and not c["small"]]

    # --- harga nasional per KIMAP × brand ---
    def price_for(P: pd.DataFrame, kimap: str, brand: str | None, comp_avg: bool = False) -> dict:
        if P.empty:
            return {}
        k = P[P["KIMAP"] == kimap]
        k = k[k["BRAND"] != "PERTAMINA"] if comp_avg else k[k["BRAND"] == brand]
        hj, n = _mean(k, "HJ")
        marg, nm = _mean(k, "MARG")
        hto, _ = _mean(k, "HTO")
        return {"hj": hj, "n": n, "marg": marg, "n_marg": nm, "hto": hto}

    def ptpl_name(kimap: str) -> str | None:
        k = PA[(PA["KIMAP"] == kimap) & (PA["BRAND"] == "PERTAMINA")] if not PA.empty else PA
        if k.empty:
            return None
        name = str(k.groupby("QNR")["N_HJ"].sum().sort_values(ascending=False).index[0])
        return re.sub(r"^PERTAMINA\s+", "", name.upper()).title()

    # --- pasangan head-to-head per KIMAP ---
    pairs = []
    ka = A[A["PAIR_KIMAP"].notna()]
    for kimap, g in ka.groupby("PAIR_KIMAP"):
        p, q = g[g["IS_PTPL"]], g[~g["IS_PTPL"]]
        if p.empty or q.empty:
            continue
        carry = q.groupby("BRAND")["OUTLET_ID"].nunique().sort_values(ascending=False)
        h2h = carry.index[0]
        hq = q[q["BRAND"] == h2h]
        cp, cc = int(p["OUTLET_ID"].nunique()), int(carry.iloc[0])
        av_p, av_c = _r(p["AV"].mean(), 2), _r(hq["AV"].mean(), 2)
        ratio = _r(cp / cc * 100) if cc else None
        av_gap = _r(av_p - av_c, 2) if av_p is not None and av_c is not None else None
        plan_ok = bool(ratio is not None and ratio >= ratio_line and av_gap is not None and av_gap >= 0)
        pp_, pc = price_for(PA, kimap, "PERTAMINA"), price_for(PA, kimap, h2h)
        basis = h2h
        if (pc.get("n") or 0) < min_price_n:
            pc, basis = price_for(PA, kimap, None, comp_avg=True), "rata-rata kompetitor KIMAP"
        price_ok = adv = None
        if pp_.get("hj") and pc.get("hj") and (pp_.get("n") or 0) >= min_price_n and (pc.get("n") or 0) >= min_price_n:
            adv = _r((pc["hj"] - pp_["hj"]) / pc["hj"] * 100)
            price_ok = adv > 0
        eco_gap = eco_ok = None
        if pp_.get("marg") is not None and pc.get("marg") is not None and pp_.get("n_marg") and pc.get("n_marg"):
            eco_gap = _r(pp_["marg"] - pc["marg"], 0)
            eco_ok = eco_gap >= 0
        # periode pembanding (momentum posisi)
        adv_b = av_gap_b = out_c_b = av_c_b = None
        if has_b:
            gb = B[B["PAIR_KIMAP"] == kimap]
            pb_, qb = gb[gb["IS_PTPL"]], gb[gb["BRAND"] == h2h]
            if not pb_.empty and not qb.empty:
                av_gap_b = _r(_r(pb_["AV"].mean(), 2) - _r(qb["AV"].mean(), 2), 2)
            if not qb.empty:
                out_c_b, av_c_b = int(qb["OUTLET_ID"].nunique()), _r(qb["AV"].mean(), 2)
            ppb = price_for(PB, kimap, "PERTAMINA")
            pcb = price_for(PB, kimap, h2h) if basis == h2h else price_for(PB, kimap, None, comp_avg=True)
            if ppb.get("hj") and pcb.get("hj") and (ppb.get("n") or 0) >= min_price_n and (pcb.get("n") or 0) >= min_price_n:
                adv_b = _r((pcb["hj"] - ppb["hj"]) / pcb["hj"] * 100)
        # sinyal regional: SR dengan carry & AV sama-sama lemah
        weak_sr = []
        for sr, gs in g.groupby("SR"):
            ps, qs = gs[gs["IS_PTPL"]], gs[gs["BRAND"] == h2h]
            if ps.empty or qs.empty:
                continue
            r_ = ps["OUTLET_ID"].nunique() / max(qs["OUTLET_ID"].nunique(), 1) * 100
            if r_ < ratio_line and ps["AV"].mean() < qs["AV"].mean():
                weak_sr.append(sr)
        d_out = (cc - out_c_b) if out_c_b is not None else None
        d_av = _r(av_c - av_c_b, 2) if av_c is not None and av_c_b is not None else None
        pairs.append({
            "kimap": str(kimap), "segmen": str(g["SEGMENT"].mode().iloc[0]), "usage": str(g["USAGE"].mode().iloc[0]),
            "viscosity": str(g["VISCOSITY"].mode().iloc[0]),
            "ptpl": ptpl_name(kimap) or str(p["SERIES"].mode().iloc[0]).title(),
            "h2h": h2h, "h2h_series": str(hq["SERIES"].mode().iloc[0]).title(), "price_basis": basis,
            "out_ptpl": cp, "out_comp": cc, "ratio": ratio, "av_ptpl": av_p, "av_comp": av_c, "av_gap": av_gap,
            "hj_ptpl": pp_.get("hj"), "hj_comp": pc.get("hj"), "n_price_ptpl": pp_.get("n", 0),
            "n_price_comp": pc.get("n", 0), "price_adv": adv, "price_ok": price_ok,
            "marg_ptpl": pp_.get("marg"), "marg_comp": pc.get("marg"), "eco_gap": eco_gap, "eco_ok": eco_ok,
            "plan_ok": plan_ok, "status": classify(price_ok, eco_ok, plan_ok),
            "price_adv_b": adv_b, "av_gap_b": av_gap_b,
            "price_adv_delta": _r(adv - adv_b) if adv is not None and adv_b is not None else None,
            "av_gap_delta": _r(av_gap - av_gap_b, 2) if av_gap is not None and av_gap_b is not None else None,
            "comp_delta_out": d_out, "comp_delta_av": d_av, "comp_threat": _threat(d_out, d_av),
            "weak_sr": weak_sr, "small": cp + cc < min_carry})
    pairs.sort(key=lambda x: -x["out_ptpl"])
    ds["pairs"] = pairs
    counts = {s: sum(1 for p in pairs if p["status"] == s) for s in STATUSES}
    ds["status_counts"] = counts
    ds["status_by_segment"] = {seg: {s: sum(1 for p in pairs if p["segmen"] == seg and p["status"] == s)
                                     for s in STATUSES} for seg in SEG_ORDER if any(p["segmen"] == seg for p in pairs)}

    # --- momentum kompetitor ---
    mom = _momentum(A, B, 30) if has_b else []
    ds["threats"] = sorted([m for m in mom if m["delta"] > 0], key=lambda m: -m["delta"])[:12]
    ds["conversion"] = sorted([m for m in mom if m["type"] == "CONVERSION WINDOW"], key=lambda m: m["delta"])[:6]

    # --- regional ---
    regions = []
    for sr in SR_ORDER:
        gs = ka[ka["SR"] == sr]
        if gs.empty:
            continue
        dw = {seg: 0 for seg in SEG_ORDER}
        for kimap, gk in gs.groupby("PAIR_KIMAP"):
            p, q = gk[gk["IS_PTPL"]], gk[~gk["IS_PTPL"]]
            if p.empty or q.empty:
                continue
            top = q.groupby("BRAND")["OUTLET_ID"].nunique().sort_values(ascending=False)
            hq = q[q["BRAND"] == top.index[0]]
            ratio = p["OUTLET_ID"].nunique() / max(int(top.iloc[0]), 1) * 100
            if ratio < ratio_line and p["AV"].mean() < hq["AV"].mean():
                seg = str(gk["SEGMENT"].mode().iloc[0])
                dw[seg] = dw.get(seg, 0) + 1
        top_threat = None
        if has_b:
            ms = _momentum(A[A["SR"] == sr], B[B["SR"] == sr], 10)
            ups = sorted([m for m in ms if m["delta"] > 0], key=lambda m: -m["delta"])
            top_threat = ups[0] if ups else None
        regions.append({"sr": sr, "double_weakness": dw, "dw_total": sum(dw.values()), "top_threat": top_threat})
    ds["regions"] = regions
    ds["national"] = {"pairs": len(pairs), "with_price": sum(1 for p in pairs if p["price_ok"] is not None),
                      "outlets": int(A["OUTLET_ID"].nunique()), "white_space": len(ds["white_space"]),
                      "categories": len(cats)}
    return ds


def dataset_numbers(ds: dict[str, Any]) -> list[float]:
    from .planogram_data import dataset_numbers as dn

    return dn(ds)


def compact(ds: dict[str, Any], n_pairs: int = 15) -> dict[str, Any]:
    """Ringkasan dataset untuk Gemini (narasi/insight) — angka apa adanya."""
    keep = ("kimap", "segmen", "usage", "viscosity", "ptpl", "h2h", "h2h_series", "price_basis", "out_ptpl", "out_comp",
            "ratio", "av_ptpl", "av_comp", "av_gap", "hj_ptpl", "hj_comp", "price_adv", "eco_gap", "status",
            "price_adv_delta", "av_gap_delta", "comp_delta_out", "comp_threat", "weak_sr")
    return {"periode": ds["period"], "nasional": ds.get("national"), "jumlah_status": ds.get("status_counts"),
            "status_per_segmen": ds.get("status_by_segment"),
            "kategori_teratas": ds.get("categories", [])[:12], "white_space": ds.get("white_space", [])[:8],
            "pasangan_head_to_head": [{k: p.get(k) for k in keep} for p in ds.get("pairs", [])[:n_pairs]],
            "ancaman_kompetitor": ds.get("threats", [])[:10], "conversion_window": ds.get("conversion", [])[:5],
            "regional": ds.get("regions", []), "catatan_data": ds.get("notes", {})}


def _nan_safe(v):
    return None if isinstance(v, float) and math.isnan(v) else v
