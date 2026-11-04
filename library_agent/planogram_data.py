"""Data laporan kinerja planogram PTPL vs kompetitor (template planogram).

Semua angka dihitung di sini dengan pandas (bukan oleh Gemini). Sumber: tabel VM_PLANOGRAM di BigQuery atau
file CSV/Excel unggahan dengan skema yang sama. Aturan mengikuti Planogram Marketing Intelligence:

- PTPL = BRAND 'PERTAMINA'. Outlet carry = jumlah outlet unik yang menjual (EXPOSURE, bukan market share).
- ND = carry brand / total carry semua brand di SEGMENT + USAGE + VISCOSITY yang sama × 100.
- "Satu outlet satu suara": baris yang berulang dirata-rata dulu per kuartal × outlet × brand × series ×
  viskositas × KIMAP, baru dihitung rata-rata antar outlet.
- Perbandingan head-to-head (skor AV, rasio carry, whitespace) HANYA di dalam PAIR_KIMAP yang sama; baris tanpa
  KIMAP tetap dihitung untuk sebaran outlet dan ND.
- Gap AV = AV PTPL − AV kompetitor (positif = PTPL lebih baik). Momentum ND ±2 pp, momentum gap AV ±0,10.
- Whitespace = outlet survei yang men-carry kompetitor di suatu KIMAP tetapi tidak men-carry PTPL di KIMAP itu.
- Periode dari DT_PR. SR1–SR7 dari REGION I–VII; Zona 1 = SR3,4,5 · Zona 2 = SR2,6 · Zona 3 = SR1,7.
- Hanya oli mesin (MCO/PCO/Commercial; bukan 90, 140, GEAR, OTHER) yang masuk kesimpulan.
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

SOURCE_LABEL = "Planogram Marketing Intelligence (VM_PLANOGRAM)"
SR_ORDER = [f"SR{i}" for i in range(1, 8)]
QUADRANTS = ["DEFEND", "EXPAND", "FIX & EXPAND", "FIX AV"]   # kanan atas, kiri atas, kiri bawah, kanan bawah
KEYS = ["PERIOD", "OUTLET_ID", "SR", "ZONA", "SEGMENT", "USAGE", "SEGMEN_USAGE", "VISCOSITY", "BRAND", "SERIES",
        "PAIR_KIMAP", "IS_PTPL", "IS_OLI_MESIN"]

FETCH_SQL = """
SELECT
  IF(DT_PR BETWEEN @a_start AND @a_end, 'A', 'B') AS PERIOD_RAW,
  CAST(OUTLET_ID AS STRING) AS OUTLET_ID, REGION, SEGMENT, USAGE, VISCOSITY, BRAND, SERIES,
  CAST(PAIR_KIMAP AS STRING) AS PAIR_KIMAP,
  AVG(AVAILABILITY_SCORE) AS AVAILABILITY_SCORE, AVG(VISIBILITY_SCORE) AS VISIBILITY_SCORE, AVG(AV_SCORE) AS AV_SCORE,
  CAST(MIN(DT_PR) AS STRING) AS DT_PR
FROM `{table}`
WHERE DT_PR BETWEEN @a_start AND @a_end OR DT_PR BETWEEN @b_start AND @b_end
GROUP BY PERIOD_RAW, OUTLET_ID, REGION, SEGMENT, USAGE, VISCOSITY, BRAND, SERIES, PAIR_KIMAP
"""


# ==========================================================================
# Periode
# ==========================================================================
def parse_period(text: str) -> dict[str, Any]:
    from .price_data import parse_period as pp

    return pp(text)


def previous_period(period: dict[str, Any]) -> dict[str, Any] | None:
    """Kuartal sebelumnya untuk periode kuartal ('Q3 2026' -> Q2 2026); None untuk periode lain."""
    m = re.fullmatch(r"Q([1-4]) (\d{4})", period.get("label", ""))
    if not m:
        return None
    q, y = int(m.group(1)), int(m.group(2))
    q, y = (q - 1, y) if q > 1 else (4, y - 1)
    return parse_period(f"{y}-Q{q}")


# ==========================================================================
# Ambil & siapkan baris
# ==========================================================================
def fetch(period_a: dict, period_b: dict | None, table: str) -> pd.DataFrame:
    """Baris VM_PLANOGRAM (sudah dirata-rata per outlet × brand × series × viskositas × KIMAP) untuk dua periode."""
    from google.cloud import bigquery

    from .clients import bigquery_client

    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", table):
        raise ValueError("Nama tabel tidak valid.")
    pb = period_b or period_a
    params = [bigquery.ScalarQueryParameter(n, "DATE", v) for n, v in (
        ("a_start", period_a["start"]), ("a_end", period_a["end"]), ("b_start", pb["start"]), ("b_end", pb["end"]))]
    job = bigquery_client().query(FETCH_SQL.format(table=table),
                                  job_config=bigquery.QueryJobConfig(query_parameters=params))
    rows = [dict(r.items()) for r in job.result()]
    return pd.DataFrame(rows)


def to_rows(prepared: pd.DataFrame, period_a: dict, period_b: dict | None) -> pd.DataFrame:
    """Frame planogram yang sudah di-prepare -> baris unik per periode (A/B) dengan skor rata-rata."""
    from .data_engine import _col

    c = lambda n: _col(prepared, n)  # noqa: E731
    need = ["OUTLET_ID", "BRAND", "SERIES", "VISCOSITY", "SEGMENT", "USAGE", "DT_PR"]
    missing = [n for n in need if not c(n)] + [n for n in ("SR", "AV") if n not in prepared.columns]
    if missing:
        from .data_engine import PlanError

        raise PlanError(f"Data planogram tidak lengkap untuk laporan (kolom hilang: {', '.join(missing)}).")
    d = prepared.copy()
    day = d[c("DT_PR")].astype(str).str.slice(0, 10)
    in_a = day.between(period_a["start"], period_a["end"])
    in_b = day.between(period_b["start"], period_b["end"]) if period_b else pd.Series(False, index=d.index)
    d = d[(in_a | in_b) & d["SR"].notna()].copy()
    d["PERIOD"] = in_a[d.index].map({True: "A", False: "B"})
    rename = {c(n): n for n in ("OUTLET_ID", "BRAND", "SERIES", "VISCOSITY", "SEGMENT", "USAGE") if c(n) != n}
    d = d.rename(columns=rename)
    d["OUTLET_ID"] = d["OUTLET_ID"].astype(str).str.replace(r"\.0$", "", regex=True)
    kimap = c("PAIR_KIMAP")
    d["PAIR_KIMAP"] = (d[kimap].astype(str).str.strip().str.replace(r"\.0$", "", regex=True) if kimap else None)
    d.loc[d["PAIR_KIMAP"].isin(["", "nan", "None", "NAN", "NULL"]), "PAIR_KIMAP"] = None
    for name, src in (("A", "AVAILABILITY_SCORE"), ("V", "VISIBILITY_SCORE")):
        d[name] = pd.to_numeric(d[c(src)], errors="coerce") if c(src) else float("nan")
    d["PAIR_KIMAP"] = d["PAIR_KIMAP"].fillna("")
    out = d.groupby(KEYS, dropna=False).agg(A=("A", "mean"), V=("V", "mean"), AV=("AV", "mean")).reset_index()
    out["PAIR_KIMAP"] = out["PAIR_KIMAP"].replace("", None)
    return out


# ==========================================================================
# Perhitungan
# ==========================================================================
def _r(v: Any, nd: int = 1) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, nd)


def _delta(a: Any, b: Any, nd: int = 1) -> float | None:
    return None if a is None or b is None else round(a - b, nd)


def momentum(delta: float | None, step: float) -> str:
    if delta is None:
        return "n/a"
    if delta >= step - 1e-9:
        return "NAIK"
    if delta <= -step + 1e-9:
        return "TURUN"
    return "STABIL"


def _nd(rows: pd.DataFrame) -> tuple[float | None, int, int]:
    """(ND PTPL %, carry PTPL, total carry) dari baris oli mesin; ND dijumlah per segmen+usage+viskositas."""
    if rows.empty:
        return None, 0, 0
    carry = rows.groupby(["SEGMENT", "USAGE", "VISCOSITY", "BRAND"])["OUTLET_ID"].nunique()
    total = int(carry.sum())
    ptpl = int(carry[carry.index.get_level_values("BRAND") == "PERTAMINA"].sum())
    return (_r(ptpl / total * 100) if total else None), ptpl, total


def _leader(rows: pd.DataFrame) -> tuple[str | None, int]:
    comp = rows[~rows["IS_PTPL"]]
    if comp.empty:
        return None, 0
    s = comp.groupby("BRAND")["OUTLET_ID"].nunique().sort_values(ascending=False)
    return str(s.index[0]), int(s.iloc[0])


def _av(rows: pd.DataFrame) -> dict[str, float | None]:
    """AV/A/V PTPL vs kompetitor hanya di KIMAP yang punya kedua sisi."""
    k = rows[rows["PAIR_KIMAP"].notna()]
    if k.empty:
        return {"av_ptpl": None, "av_komp": None, "av_gap": None, "a_ptpl": None, "a_komp": None,
                "v_ptpl": None, "v_komp": None}
    sides = k.groupby("PAIR_KIMAP")["IS_PTPL"].agg(["any", "all"])
    both = sides[sides["any"] & ~sides["all"]].index
    k = k[k["PAIR_KIMAP"].isin(both)]
    p, q = k[k["IS_PTPL"]], k[~k["IS_PTPL"]]
    out = {"av_ptpl": _r(p["AV"].mean(), 2), "av_komp": _r(q["AV"].mean(), 2), "a_ptpl": _r(p["A"].mean(), 2),
           "a_komp": _r(q["A"].mean(), 2), "v_ptpl": _r(p["V"].mean(), 2), "v_komp": _r(q["V"].mean(), 2)}
    out["av_gap"] = _delta(out["av_ptpl"], out["av_komp"], 2)
    return out


def _whitespace(rows: pd.DataFrame) -> pd.DataFrame:
    """Pasangan outlet × KIMAP: kompetitor ada, PTPL tidak ada."""
    k = rows[rows["PAIR_KIMAP"].notna()]
    if k.empty:
        return pd.DataFrame(columns=["OUTLET_ID", "PAIR_KIMAP", "SR", "SEGMEN_USAGE"])
    g = k.groupby(["OUTLET_ID", "PAIR_KIMAP"]).agg(SR=("SR", "first"), SEGMEN_USAGE=("SEGMEN_USAGE", "first"),
                                                     ptpl=("IS_PTPL", "any"), komp=("IS_PTPL", lambda s: (~s).any()))
    return g[g["komp"] & ~g["ptpl"]].reset_index()


def _kimap_label(rows: pd.DataFrame, kimap: str) -> str:
    r = rows[rows["PAIR_KIMAP"] == kimap]
    p = r[r["IS_PTPL"]]
    src = p if not p.empty else r
    if src.empty:
        return str(kimap)
    top = (src["SERIES"].astype(str) + " " + src["VISCOSITY"].astype(str)).value_counts().index[0]
    return top.title() if not p.empty else f"{top.title()} (tanpa PTPL)"


def build_dataset(rows: pd.DataFrame, period_a: dict, period_b: dict | None, carry_ratio_line: float = 70,
                  min_carry: int = 30, notes: dict | None = None) -> dict[str, Any]:  # noqa: C901
    """Dataset laporan planogram dari baris to_rows()."""
    eng = rows[rows["IS_OLI_MESIN"].fillna(False).astype(bool)] if not rows.empty else rows
    A = eng[eng["PERIOD"] == "A"] if not eng.empty else eng
    B = eng[eng["PERIOD"] == "B"] if not eng.empty else eng
    all_a = rows[rows["PERIOD"] == "A"] if not rows.empty else rows
    all_b = rows[rows["PERIOD"] == "B"] if not rows.empty else rows
    has_b = period_b is not None and not B.empty
    ds: dict[str, Any] = {"period": {"a": period_a["label"], "b": period_b["label"] if period_b else None},
                          "has_data": not A.empty, "has_b": has_b, "source_label": SOURCE_LABEL,
                          "carry_ratio_line": carry_ratio_line, "min_carry": min_carry, "notes": dict(notes or {})}
    if A.empty:
        return ds

    def period_stats(P: pd.DataFrame, P_all: pd.DataFrame) -> dict[str, Any]:
        nd, cp, tot = _nd(P)
        ws = _whitespace(P)
        lb, lc = _leader(P)
        return {"outlets": int(P_all["OUTLET_ID"].nunique()), "carry_ptpl": int(P[P["IS_PTPL"]]["OUTLET_ID"].nunique()),
                "nd": nd, "total_carry": tot, "leader": lb, "leader_carry": lc,
                "ws_outlets": int(ws["OUTLET_ID"].nunique()) if not ws.empty else 0, "ws_pairs": int(len(ws)), **_av(P)}

    na, nb = period_stats(A, all_a), (period_stats(B, all_b) if has_b else {})
    nat = {"a": na, "b": nb, "nd_delta": _delta(na["nd"], nb.get("nd")),
           "av_gap_delta": _delta(na["av_gap"], nb.get("av_gap"), 2)}
    nat["nd_momentum"] = momentum(nat["nd_delta"], 2)
    nat["av_momentum"] = momentum(nat["av_gap_delta"], 0.10)
    ds["national"] = nat

    # --- per SR
    regions = []
    for sr in SR_ORDER:
        pa_, pb_ = A[A["SR"] == sr], B[B["SR"] == sr] if has_b else B.iloc[0:0]
        if pa_.empty and pb_.empty:
            continue
        sa = period_stats(pa_, all_a[all_a["SR"] == sr])
        sb = period_stats(pb_, all_b[all_b["SR"] == sr]) if has_b and not pb_.empty else {}
        ws = _whitespace(pa_)
        top_ws = None
        if not ws.empty:
            kk = ws["PAIR_KIMAP"].value_counts()
            top_ws = {"kimap": kk.index[0], "label": _kimap_label(A, kk.index[0]), "outlets": int(kk.iloc[0])}
        reg = {"sr": sr, "zona": str(pa_["ZONA"].iloc[0]) if not pa_.empty else None, "a": sa, "b": sb,
               "nd_delta": _delta(sa["nd"], sb.get("nd")), "av_gap_delta": _delta(sa["av_gap"], sb.get("av_gap"), 2),
               "top_ws": top_ws, "small": sa["total_carry"] < min_carry,
               "ws_by_segment": ws.groupby("SEGMEN_USAGE")["OUTLET_ID"].count().to_dict() if not ws.empty else {}}
        reg["nd_momentum"] = momentum(reg["nd_delta"], 2)
        reg["av_momentum"] = momentum(reg["av_gap_delta"], 0.10)
        regions.append(reg)
    ds["regions"] = regions

    # --- per segmen + usage
    segs = []
    for su in sorted(A["SEGMEN_USAGE"].dropna().unique()):
        nda, cpa, tota = _nd(A[A["SEGMEN_USAGE"] == su])
        ndb = _nd(B[B["SEGMEN_USAGE"] == su])[0] if has_b else None
        segs.append({"segmen": su, "nd_a": nda, "nd_b": ndb, "carry_ptpl": cpa, "total_carry": tota,
                     "nd_delta": _delta(nda, ndb), "nd_momentum": momentum(_delta(nda, ndb), 2),
                     "small": tota < min_carry})
    ds["segments"] = segs

    # --- per viskositas (di dalam segmen + usage)
    visc = []
    for (su, v), grp in A.groupby(["SEGMEN_USAGE", "VISCOSITY"]):
        nda, cpa, tota = _nd(grp)
        gb = B[(B["SEGMEN_USAGE"] == su) & (B["VISCOSITY"] == v)] if has_b else B.iloc[0:0]
        ndb, cpb, _ = _nd(gb) if not gb.empty else (None, None, 0)
        lb, lc = _leader(grp)
        visc.append({"segmen": su, "viscosity": str(v), "carry_ptpl_a": cpa, "carry_ptpl_b": cpb, "total_carry": tota,
                     "leader": lb, "leader_carry": lc, "nd_a": nda, "nd_b": ndb, "nd_delta": _delta(nda, ndb),
                     "nd_momentum": momentum(_delta(nda, ndb), 2), "small": tota < min_carry})
    visc.sort(key=lambda x: -x["total_carry"])
    ds["viscosities"] = visc
    twot = [x for x in visc if x["viscosity"] in ("2T", "20", "NO VISCOSITY") and x["segmen"].startswith("MCO")]
    if any(x["viscosity"] in ("20", "NO VISCOSITY") for x in twot) or any(x["carry_ptpl_a"] == 0 for x in twot):
        ds["notes"]["2T_perlu_ditarik_ulang"] = True

    # --- per KIMAP
    kim = []
    ka = A[A["PAIR_KIMAP"].notna()]
    ws_a, ws_b = _whitespace(A), (_whitespace(B) if has_b else pd.DataFrame(columns=["PAIR_KIMAP", "OUTLET_ID"]))
    ws_a_k = ws_a["PAIR_KIMAP"].value_counts().to_dict() if not ws_a.empty else {}
    ws_b_k = ws_b["PAIR_KIMAP"].value_counts().to_dict() if not ws_b.empty else {}
    for k, grp in ka.groupby("PAIR_KIMAP"):
        p, q = grp[grp["IS_PTPL"]], grp[~grp["IS_PTPL"]]
        if q.empty:
            continue
        lb, lc = _leader(grp)
        cp = int(p["OUTLET_ID"].nunique())
        av_p, av_q = (_r(p["AV"].mean(), 2) if not p.empty else None), _r(q["AV"].mean(), 2)
        gap_a = _delta(av_p, av_q, 2)
        gb = B[B["PAIR_KIMAP"] == k] if has_b else B.iloc[0:0]
        gap_b = None
        if not gb.empty and gb["IS_PTPL"].any() and (~gb["IS_PTPL"]).any():
            gap_b = _delta(_r(gb[gb["IS_PTPL"]]["AV"].mean(), 2), _r(gb[~gb["IS_PTPL"]]["AV"].mean(), 2), 2)
        ratio = _r(cp / lc * 100) if lc else None
        quad = None
        if ratio is not None and gap_a is not None:
            right, top = ratio >= carry_ratio_line, gap_a >= 0
            quad = QUADRANTS[0] if right and top else QUADRANTS[1] if top else QUADRANTS[2] if not right else QUADRANTS[3]
        outlets = int(grp["OUTLET_ID"].nunique())
        kim.append({"kimap": str(k), "label": _kimap_label(A, k), "segmen": str(grp["SEGMEN_USAGE"].iloc[0]),
                    "viscosity": str(grp["VISCOSITY"].mode().iloc[0]), "outlets": outlets, "carry_ptpl": cp,
                    "leader": lb, "leader_carry": lc, "ratio": ratio, "av_ptpl": av_p, "av_komp": av_q,
                    "gap_a": gap_a, "gap_b": gap_b, "gap_delta": _delta(gap_a, gap_b, 2),
                    "av_momentum": momentum(_delta(gap_a, gap_b, 2), 0.10), "ws_a": int(ws_a_k.get(k, 0)),
                    "ws_b": int(ws_b_k.get(k, 0)) if has_b else None, "quadrant": quad, "small": outlets < min_carry})
    kim.sort(key=lambda x: -x["outlets"])
    ds["kimaps"] = kim
    ds["national"]["kimap_count"] = len([k for k in kim if k["gap_a"] is not None])
    ds["national"]["kimap_unggul"] = len([k for k in kim if (k["gap_a"] or 0) > 0])
    ds["national"]["kimap_kalah"] = len([k for k in kim if k["gap_a"] is not None and k["gap_a"] < 0])
    ds["national"]["kimap_tanpa_ptpl"] = len([k for k in kim if k["carry_ptpl"] == 0])
    return ds


def dataset_numbers(ds: dict[str, Any]) -> list[float]:
    """Semua angka di dataset (dasar verifikasi narasi Gemini)."""
    nums: set[float] = set()

    def walk(node: Any):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)) and not (isinstance(node, float) and math.isnan(node)):
            nums.add(abs(round(float(node), 2)))
    walk(ds)
    return sorted(nums)


# ==========================================================================
# Preset analisis file (dipakai analyze_data): logika sama dengan template
# ==========================================================================
PRESETS = ("planogram_nd", "planogram_av", "planogram_whitespace")


def analysis_rows(prepared: pd.DataFrame) -> pd.DataFrame:
    """Baris unik per KUARTAL × outlet × brand × series × viskositas × KIMAP (satu outlet satu suara)."""
    from .data_engine import PlanError, _col

    c = lambda n: _col(prepared, n)  # noqa: E731
    need = ["OUTLET_ID", "BRAND", "SERIES", "VISCOSITY", "SEGMENT", "USAGE"]
    missing = [n for n in need if not c(n)] + [n for n in ("SR", "AV", "KUARTAL") if n not in prepared.columns]
    if missing:
        raise PlanError(f"Preset planogram butuh kolom: {', '.join(missing)} (file harus berformat VM_PLANOGRAM).")
    d = prepared.rename(columns={c(n): n for n in need if c(n) != n}).copy()
    d["PERIOD"] = d["KUARTAL"].fillna("")
    d["OUTLET_ID"] = d["OUTLET_ID"].astype(str).str.replace(r"\.0$", "", regex=True)
    kimap = c("PAIR_KIMAP")
    d["PAIR_KIMAP"] = d[kimap].astype(str).str.strip().str.replace(r"\.0$", "", regex=True) if kimap else ""
    d.loc[d["PAIR_KIMAP"].isin(["nan", "None", "NAN", "NULL"]), "PAIR_KIMAP"] = ""
    for name, src in (("A", "AVAILABILITY_SCORE"), ("V", "VISIBILITY_SCORE")):
        d[name] = pd.to_numeric(d[c(src)], errors="coerce") if c(src) else float("nan")
    for k in ("ZONA", "SEGMEN_USAGE", "IS_PTPL", "IS_OLI_MESIN"):
        if k not in d.columns:
            d[k] = None
    out = d.groupby(KEYS, dropna=False).agg(A=("A", "mean"), V=("V", "mean"), AV=("AV", "mean")).reset_index()
    out["PAIR_KIMAP"] = out["PAIR_KIMAP"].replace("", None)
    return out


def run_preset(prepared: pd.DataFrame, name: str, group_by: list[str] | None = None,
               engine_oil_only: bool = True) -> pd.DataFrame:
    """ND / AV / whitespace per kelompok (KUARTAL selalu ikut dikelompokkan)."""
    from .data_engine import PlanError

    rows = analysis_rows(prepared)
    if engine_oil_only:
        rows = rows[rows["IS_OLI_MESIN"].fillna(False).astype(bool)]
    allowed = {"SR", "ZONA", "SEGMENT", "USAGE", "SEGMEN_USAGE", "VISCOSITY", "PAIR_KIMAP", "BRAND"}
    group = [g.upper() for g in (group_by or [])]
    bad = [g for g in group if g not in allowed]
    if bad:
        raise PlanError(f"group_by preset planogram hanya boleh: {', '.join(sorted(allowed))}.")
    keys = ["PERIOD"] + group
    out = []
    for vals, grp in rows.groupby(keys, dropna=False):
        vals = vals if isinstance(vals, tuple) else (vals,)
        rec = {("KUARTAL" if k == "PERIOD" else k): v for k, v in zip(keys, vals)}
        if name == "planogram_nd":
            nd, cp, tot = _nd(grp)
            lb, lc = _leader(grp)
            rec.update(OUTLET_CARRY_PTPL=int(grp[grp["IS_PTPL"].fillna(False).astype(bool)]["OUTLET_ID"].nunique()),
                       CARRY_PTPL_PER_VISKOSITAS=cp, TOTAL_CARRY_PER_VISKOSITAS=tot, ND_PTPL_PCT=nd,
                       LEADER_KOMPETITOR=lb, OUTLET_CARRY_LEADER=lc, SAMPEL_KECIL=tot < 30)
        elif name == "planogram_av":
            a = _av(grp)
            rec.update(AV_PTPL=a["av_ptpl"], AV_KOMP=a["av_komp"], GAP_AV=a["av_gap"], A_PTPL=a["a_ptpl"],
                       A_KOMP=a["a_komp"], V_PTPL=a["v_ptpl"], V_KOMP=a["v_komp"])
        elif name == "planogram_whitespace":
            ws = _whitespace(grp)
            rec.update(OUTLET_WHITESPACE=int(ws["OUTLET_ID"].nunique()) if not ws.empty else 0, PELUANG_OUTLET_KIMAP=int(len(ws)))
        else:
            raise PlanError(f"Preset tidak dikenal: {name}. Pilihan: {', '.join(PRESETS)}.")
        out.append(rec)
    return pd.DataFrame(out)
