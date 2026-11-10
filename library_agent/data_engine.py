"""Mesin analisis file CSV/Excel unggahan user.

Gemini menyusun RENCANA analisis (JSON); kode ini yang membaca file dan MENGHITUNG dengan pandas.
Aturan bisnis survei retail, industri, dan planogram (filter wajib, harga per liter, zona, KIMAP, gap,
skor AV) diterapkan otomatis sesuai jenis file yang dikenali dari kolomnya (skema SURVEY_PRODUCTS /
survey_industry / VM_PLANOGRAM).
Tidak ada tabel yang dibuat di BigQuery.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import OrderedDict
from typing import Any

import logging

import pandas as pd

RETAIL_KEYS = {"HARGA_JUAL", "HARGA_TEBUS", "HET", "HTO", "CONTENT", "KIMAP", "BRAND", "QNR", "SALES_REGION_CUSTOMER"}
INDUSTRY_KEYS = {"harga_kompetitor_per_liter", "htd_ptpl", "htd_ptpl_plus", "main_stage", "channel", "produk_ptpl"}
PLANOGRAM_KEYS = {"OUTLET_ID", "PAIR_KIMAP", "BRAND", "SERIES", "VISCOSITY", "SEGMENT", "USAGE", "REGION",
                  "AVAILABILITY_SCORE", "VISIBILITY_SCORE", "AV_SCORE"}
ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7"}
ENGINE_SEGMENTS = {"MCO", "PCO", "COMMERCIAL"}
NON_ENGINE_VISC = {"90", "140", "GEAR", "OTHER"}
ZONE_OF_REGION = {"3": "Zona 1", "4": "Zona 1", "5": "Zona 1", "2": "Zona 2", "6": "Zona 2", "1": "Zona 3", "7": "Zona 3"}
AGGS = {"mean", "sum", "count", "min", "max", "median", "nunique"}
OPS = {"==", "!=", ">", ">=", "<", "<=", "in", "not in", "contains", "between", "isnull", "notnull"}
MAX_RESULT_ROWS = 200
_EXPR_OK = re.compile(r"^[A-Za-z0-9_ .+\-*/()`]+$")
PACKAGE_SIZE = r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:LITER|L)\b"   # sama dengan verified query Data Agent retail
_frames: "OrderedDict[str, pd.DataFrame]" = OrderedDict()

logger = logging.getLogger(__name__)


class PlanError(ValueError):
    """Rencana analisis tidak valid; pesannya ditampilkan ke model untuk diperbaiki."""


# ==========================================================================
# Membaca file
# ==========================================================================
def _looks_pivot(df: pd.DataFrame) -> bool:
    """Header pandas banyak 'Unnamed' -> kemungkinan ekspor PivotTable / header bertingkat."""
    cols = [str(c) for c in df.columns]
    return len(cols) >= 3 and sum(c.startswith("Unnamed") for c in cols) >= max(2, 0.3 * len(cols))


def _clean_label(v: Any) -> str:
    t = re.sub(r"\s+", " ", str(v)).strip()
    m = re.match(r"(?i)^(average|sum|count|max|min) of (.+)$", t)
    if m:
        t = f"{m.group(2)} ({ {'average': 'rata-rata', 'sum': 'jumlah', 'count': 'jumlah data'}.get(m.group(1).lower(), m.group(1).lower())})"
    return t


def fix_layout(raw: pd.DataFrame) -> pd.DataFrame:
    """Rapikan tabel hasil PivotTable: header bertingkat -> satu baris nama kolom, kelompok kosong diisi ke bawah.

    raw dibaca dengan header=None. Baris header = baris pertama (dalam 15 baris) yang hampir penuh; baris di atasnya
    yang berisi label berselang (mis. Qtr1 ... Qtr2 ... Qtr3) menjadi awalan nama kolom.
    """
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    raw.columns = range(raw.shape[1])
    ncol = raw.shape[1]
    h = next((i for i in range(min(15, len(raw)))
              if raw.iloc[i].notna().sum() >= 0.8 * ncol
              and sum(isinstance(v, str) for v in raw.iloc[i].dropna()) >= 0.6 * raw.iloc[i].notna().sum()), 0)
    header = [_clean_label(v) if pd.notna(v) else "" for v in raw.iloc[h]]
    prefixes = [""] * ncol
    group_start = ncol
    for b in range(h):
        row = raw.iloc[b]
        idx = [j for j in range(ncol) if pd.notna(row[j])]
        spaced = len(idx) >= 2 and all(idx[k + 1] - idx[k] > 1 for k in range(len(idx) - 1))
        if not spaced:
            continue                                   # baris meta pivot (mis. "Quarters | SURVEY_WAVE | Values")
        group_start = min(group_start, idx[0])
        cur = ""
        for j in range(idx[0], ncol):
            if pd.notna(row[j]):
                cur = _clean_label(row[j])
            prefixes[j] = f"{prefixes[j]} · {cur}".strip(" ·") if cur else prefixes[j]
    names, seen = [], {}
    for j in range(ncol):
        name = " · ".join(p for p in (prefixes[j], header[j]) if p) or f"Kolom {j + 1}"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    data = raw.iloc[h + 1:].reset_index(drop=True)
    data.columns = names
    filled = []
    for col in names[:min(group_start, ncol - 1)]:     # kolom pengelompokan pivot: sel kosong = sama dengan di atas
        nums = pd.to_numeric(data[col], errors="coerce")
        if data[col].isna().any() and data[col].notna().any() and nums.notna().sum() < 0.5 * data[col].notna().sum():
            data[col] = data[col].ffill()
            filled.append(col)
    for col in names:
        conv = pd.to_numeric(data[col], errors="coerce")
        if data[col].notna().sum() and conv.notna().sum() >= 0.8 * data[col].notna().sum():
            data[col] = conv
    data.attrs["tata_letak"] = {"jenis": "pivot / header bertingkat", "baris_header": h + 1,
                                "baris_label_kelompok": h, "kolom_diisi_ke_bawah": filled}
    return data


def read_bytes(data: bytes, filename: str, sheet: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Baca CSV/XLSX/XLS menjadi DataFrame. Mengembalikan (frame, daftar sheet)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        book = pd.read_excel(io.BytesIO(data), sheet_name=None)
        sheets = list(book)
        if not sheets:
            raise PlanError("File Excel tidak memiliki sheet.")
        pick = sheet if sheet in book else next((s for s in sheets if not book[s].empty), sheets[0])
        df = book[pick]
        if _looks_pivot(df):
            df = fix_layout(pd.read_excel(io.BytesIO(data), sheet_name=pick, header=None))
        return df, sheets
    text = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:20000]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delim = ","
    df = pd.read_csv(io.StringIO(text), sep=delim, low_memory=False)
    if _looks_pivot(df):
        df = fix_layout(pd.read_csv(io.StringIO(text), sep=delim, low_memory=False, header=None))
    return df, []


def load_frame(uri: str, filename: str, sheet: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Unduh dari GCS lalu baca (disimpan di memori untuk pemakaian berikutnya)."""
    key = f"{uri}#{sheet or ''}"
    if key in _frames:
        _frames.move_to_end(key)
        return _frames[key], []
    from .clients import parse_gcs_uri, storage_client

    bucket, path = parse_gcs_uri(uri)
    data = storage_client().bucket(bucket).blob(path).download_as_bytes()
    df, sheets = read_bytes(data, filename, sheet)
    _frames[key] = df
    while len(_frames) > 6:
        _frames.popitem(last=False)
    return df, sheets


# ==========================================================================
# Mengenali jenis data & aturan bisnis
# ==========================================================================
def _colmap(df: pd.DataFrame) -> dict[str, str]:
    return {c.strip().lower(): c for c in df.columns}


def detect_kind(df: pd.DataFrame) -> str:
    cols = {c.strip().lower() for c in df.columns}
    if len({k.lower() for k in RETAIL_KEYS} & cols) >= 6:
        return "retail"
    if len({k.lower() for k in INDUSTRY_KEYS} & cols) >= 4:
        return "industri"
    if len({k.lower() for k in PLANOGRAM_KEYS} & cols) >= 7:
        return "planogram"
    return "lainnya"


def _is_date(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_numeric_dtype(series):
        return False
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce")
    return parsed.notna().mean() >= 0.9


_PACK = re.compile(r"(\d+(?:[.,]\d+)?)\s*(LITER|LITRE|LTR|LT|L|ML)\b", re.I)
_PRICE_COL = re.compile(r"HTO|HET|HARGA|MARGIN|PROMO|LOYALTY|PRICE|\bHT\b|\bHJ\b", re.I)


def pack_liters(text: Any) -> float | None:
    """'MESRANIA 2T SUPER 1 LITER' -> 1.0 · 'ACTIV 2T 0.7 LITER' -> 0.7 · '800 ML' -> 0.8."""
    if not isinstance(text, str):
        return None
    hits = _PACK.findall(text)
    if not hits:
        return None
    num, unit = hits[-1]
    v = float(num.replace(",", "."))
    return v / 1000 if unit.upper() == "ML" else v


def add_per_liter(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Tambah kolom harga per liter bila ada kolom nama produk berisi ukuran kemasan (aturan Retail PTPL)."""
    text_cols = [c for c in df.columns
                 if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c])]
    best, share = None, 0.0
    for c in text_cols:
        vals = df[c].dropna()
        if len(vals):
            frac = vals.map(lambda x: pack_liters(x) is not None).mean()
            if frac > share:
                best, share = c, frac
    if best is None or share < 0.8:
        return df, []
    out = df.copy()
    out["ISI_KEMASAN_L"] = out[best].map(pack_liters)
    added = ["ISI_KEMASAN_L"]
    for c in df.columns:
        if c != best and _PRICE_COL.search(str(c)) and pd.api.types.is_numeric_dtype(df[c]) and not str(c).endswith("/L"):
            out[f"{c} /L"] = (df[c] / out["ISI_KEMASAN_L"]).round(2)
            added.append(f"{c} /L")
    return (out, added) if len(added) > 1 else (df, [])


def total_rows(df: pd.DataFrame) -> pd.Series:
    """Baris total/subtotal di file umum: kolom kunci kosong DAN nilai numerik terbesar ≈ jumlah baris lain."""
    keyish = [c for c in df.columns
              if re.search(r"(^|[\s_])(code|kode|id|outlet|customer|pelanggan|nama|name)([\s_]|$)", str(c), re.I)]
    keys = keyish or [df.columns[0]]
    blank = df[keys].isna().all(axis=1) | df[keys].astype(str).apply(lambda s: s.str.strip().isin(["", "nan", "None"])).all(axis=1)
    flag = pd.Series(False, index=df.index)
    if not blank.any():
        return flag
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in keys]
    if not nums:
        return flag
    main = max(nums, key=lambda c: df[c].abs().sum())
    for i in df.index[blank]:
        v = df.at[i, main]
        rest = df.loc[df.index != i, main].sum()
        if pd.notna(v) and rest and abs(v - rest) <= max(0.005 * abs(rest), 1e-6):
            flag.at[i] = True
        elif pd.notna(v) and re.search(r"total|jumlah|grand", " ".join(map(str, df.loc[i].values)), re.I):
            flag.at[i] = True
    return flag


def region_number(series: pd.Series) -> pd.Series:
    """'REGION V' / 'SR5' / '5' / 5.0 -> '5' (kosong jika tidak dikenali)."""
    s = series.astype(str).str.upper().str.strip().str.replace(r"\.0$", "", regex=True)
    s = s.str.replace(r"^(REGION|SR|SALES REGION)\s*", "", regex=True).str.strip()
    return s.map(lambda v: ROMAN.get(v, v if v in ROMAN.values() else ""))


def _col(df: pd.DataFrame, name: str) -> str | None:
    return _colmap(df).get(name.lower())


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _txt(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def _region(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def prepare(df: pd.DataFrame, kind: str, heroes: list[str] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Terapkan filter wajib + kolom turunan standar. Mengembalikan (frame, catatan)."""
    out = df.copy()
    notes: dict[str, Any] = {"rows_input": int(len(out)), "excluded": {}, "added_columns": []}

    def drop(mask: pd.Series, reason: str):
        nonlocal out
        n = int((~mask).sum())
        if n:
            notes["excluded"][reason] = notes["excluded"].get(reason, 0) + n
        out = out[mask]

    if kind == "retail":
        c = lambda n: _col(out, n)  # noqa: E731
        if c("AVAILABILITY"):
            drop(_txt(out[c("AVAILABILITY")]).str.replace(r"\.0$", "", regex=True) == "1", "AVAILABILITY bukan 1")
        for f in ("OUTLIER_HTO", "OUTLIER_HET"):
            if c(f):
                drop(_txt(out[c(f)]).str.upper() == "DATA USE", f"{f} bukan DATA USE")
        if c("CONTENT"):
            raw_content = _num(out[c("CONTENT")])
            from_name = (pd.to_numeric(out[c("QNR")].astype(str).str.upper().str.extract(PACKAGE_SIZE)[0], errors="coerce")
                         if c("QNR") else pd.Series(float("nan"), index=out.index))
            valid = from_name.where(from_name.notna(), raw_content)
            fixed = int(((from_name.notna()) & ((from_name - raw_content).abs() > 0.0001)).sum())
            if fixed:
                notes["content_dikoreksi_dari_nama_produk"] = fixed
            out["CONTENT_VALID"] = valid
            notes["added_columns"].append("CONTENT_VALID")
            drop(out["CONTENT_VALID"] > 0, "ukuran kemasan kosong/0")
            content = out["CONTENT_VALID"]
            for src, dst in (("HET", "HET_L"), ("HTO", "HTO_L"), ("HARGA_JUAL", "HJ_L"), ("HARGA_TEBUS", "HT_L"),
                             ("MARGIN_SURVEY", "MARG_L")):
                if c(src):
                    out[dst] = _num(out[c(src)]) / content
                    notes["added_columns"].append(dst)
        if c("MARGIN_SURVEY"):
            out["TOV"] = (_num(out[c("MARGIN_SURVEY")]).fillna(0) + _num(out[c("TRADE_PROMO")]).fillna(0)
                          if c("TRADE_PROMO") else _num(out[c("MARGIN_SURVEY")]))
            if c("LOYALTY"):
                out["TOV"] = out["TOV"] + _num(out[c("LOYALTY")]).fillna(0)
            notes["added_columns"].append("TOV")
        if c("BRAND"):
            out["IS_PTPL"] = _txt(out[c("BRAND")]).str.upper() == "PERTAMINA"
            notes["added_columns"].append("IS_PTPL")
        if c("QNR") and heroes:
            hs = {h.upper() for h in heroes}
            out["IS_HERO"] = _txt(out[c("QNR")]).str.upper().isin(hs)
            notes["added_columns"].append("IS_HERO")
    elif kind == "industri":
        c = lambda n: _col(out, n)  # noqa: E731
        if c("data_status"):
            drop(_txt(out[c("data_status")]).str.upper() == "OK", "data_status bukan OK")
        if c("htd_ptpl"):
            drop(_num(out[c("htd_ptpl")]).notna(), "htd_ptpl kosong")
        if c("harga_kompetitor_per_liter"):
            drop(_num(out[c("harga_kompetitor_per_liter")]) > 0, "tanpa harga kompetitor")
        if c("produk_kompetitor"):
            drop(~_txt(out[c("produk_kompetitor")]).str.lower().isin(["", "tidak ada", "nan", "none"]), "tanpa produk kompetitor")
        if c("harga_kompetitor_per_liter") and c("htd_ptpl_plus"):
            htd = _num(out[c("htd_ptpl_plus")])
            out["GAP_PCT"] = (_num(out[c("harga_kompetitor_per_liter")]) - htd) / htd * 100
            notes["added_columns"].append("GAP_PCT")
    elif kind == "planogram":
        c = lambda n: _col(out, n)  # noqa: E731
        out = out.copy()
        for name in ("BRAND", "SERIES", "VISCOSITY", "SEGMENT", "USAGE"):
            if c(name):
                col = out[c(name)]
                out[c(name)] = col.where(col.isna(), col.astype(str).str.strip().str.upper())
        if c("SEGMENT") and c("USAGE"):
            empty = {"", "NAN", "NULL", "NONE"}
            drop(out[c("SEGMENT")].notna() & out[c("USAGE")].notna() & ~out[c("SEGMENT")].isin(empty)
                 & ~out[c("USAGE")].isin(empty), "SEGMENT/USAGE kosong")
        if c("SERIES") and c("VISCOSITY"):
            out = out.copy()
            is2t = out[c("SERIES")].astype(str).str.contains(r"\b2T\b", regex=True, na=False) & \
                (out[c("VISCOSITY")].isna() | out[c("VISCOSITY")].astype(str).isin(["20", "NO VISCOSITY", ""]))
            if int(is2t.sum()):
                out.loc[is2t, c("VISCOSITY")] = "2T"
                notes["viskositas_2T_dinormalisasi"] = int(is2t.sum())
        if c("SEGMENT") and c("VISCOSITY"):
            drop(~(out[c("SEGMENT")].isin(["PCO", "COMMERCIAL"]) & (out[c("VISCOSITY")].astype(str) == "NO VISCOSITY")),
                 "NO VISCOSITY di PCO/Commercial (bukan oli mesin)")
        out = out.copy()
        if c("BRAND"):
            out["IS_PTPL"] = out[c("BRAND")].astype(str) == "PERTAMINA"
            notes["added_columns"].append("IS_PTPL")
        if c("REGION"):
            num = region_number(out[c("REGION")])
            out["SR"] = ("SR" + num).where(num != "", None)
            out["ZONA"] = num.map(ZONE_OF_REGION)
            notes["added_columns"] += ["SR", "ZONA"]
        if c("AV_SCORE"):
            out["AV"] = _num(out[c("AV_SCORE")])
        elif c("AVAILABILITY_SCORE") and c("VISIBILITY_SCORE"):
            out["AV"] = (_num(out[c("AVAILABILITY_SCORE")]) + _num(out[c("VISIBILITY_SCORE")])) / 2
        if "AV" in out.columns:
            notes["added_columns"].append("AV")
        if c("SEGMENT") and c("USAGE"):
            out["SEGMEN_USAGE"] = out[c("SEGMENT")].astype(str) + " " + out[c("USAGE")].astype(str)
            out["IS_OLI_MESIN"] = out[c("SEGMENT")].isin(ENGINE_SEGMENTS) & \
                ~out[c("VISCOSITY")].astype(str).isin(NON_ENGINE_VISC) if c("VISCOSITY") else out[c("SEGMENT")].isin(ENGINE_SEGMENTS)
            notes["added_columns"] += ["SEGMEN_USAGE", "IS_OLI_MESIN"]
        if c("DT_PR"):
            d = pd.to_datetime(out[c("DT_PR")], errors="coerce")
            out["KUARTAL"] = [f"{x.year}-Q{x.quarter}" if pd.notna(x) else None for x in d]
            notes["added_columns"].append("KUARTAL")
    if kind in ("lainnya", "sellout") and len(out) > 1:
        try:
            drop(~total_rows(out), "baris total/subtotal (kolom kunci kosong, nilai = jumlah baris lain)")
        except Exception:  # noqa: BLE001
            logger.warning("Deteksi baris total gagal", exc_info=True)
    if kind in ("lainnya", "sellout"):
        if df.attrs.get("tata_letak"):
            notes["tata_letak"] = df.attrs["tata_letak"]
        try:
            out, per_l = add_per_liter(out)
            if per_l:
                notes["added_columns"] += per_l
                notes["harga_per_liter"] = ("Kolom harga /L ditambahkan (harga ÷ isi kemasan dari nama produk). "
                                            "Bandingkan antar produk dengan kolom /L, bukan harga per kemasan.")
        except Exception:  # noqa: BLE001
            logger.warning("Kolom per liter gagal ditambahkan", exc_info=True)
    region = _col(out, "SALES_REGION_CUSTOMER")
    if region:
        out["ZONA"] = _region(out[region]).map(ZONE_OF_REGION)
        notes["added_columns"].append("ZONA")
    period = _col(out, "DT_PR")
    if period:
        out["PERIODE"] = out[period].astype(str).str.slice(0, 7)
        notes["added_columns"].append("PERIODE")
    notes["rows_used"] = int(len(out))
    return out, notes


# ==========================================================================
# Profil & kolom penghubung
# ==========================================================================
def profile(df: pd.DataFrame, max_unique: int = 15) -> dict[str, Any]:
    cols = []
    for c in df.columns:
        s = df[c]
        info: dict[str, Any] = {"name": str(c), "dtype": str(s.dtype), "null": int(s.isna().sum())}
        nun = int(s.nunique(dropna=True))
        info["unique"] = nun
        if nun <= max_unique:
            info["values"] = [str(v) for v in s.dropna().unique()[:max_unique]]
        elif pd.api.types.is_numeric_dtype(s):
            info["min"], info["max"] = _clean(s.min()), _clean(s.max())
        cols.append(info)
    sample = json.loads(df.head(5).to_json(orient="records", date_format="iso", default_handler=str))
    return {"rows": int(len(df)), "columns": cols, "sample": sample}


def find_join_keys(a: pd.DataFrame, b: pd.DataFrame, top: int = 5) -> list[dict[str, Any]]:
    """Kandidat pasangan kolom penghubung berdasarkan kecocokan nilai (persentase nilai A yang ada di B)."""
    def norm_vals(s: pd.Series) -> set:
        v = s.dropna().astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
        return set(v[v != ""].unique()[:50000])

    def key(n: str) -> str:
        return re.sub(r"[^a-z0-9]", "", n.lower())

    cand = []
    a_vals = {c: norm_vals(a[c]) for c in a.columns if a[c].nunique(dropna=True) > 1}
    b_vals = {c: norm_vals(b[c]) for c in b.columns if b[c].nunique(dropna=True) > 1}
    for ca, va in a_vals.items():
        for cb, vb in b_vals.items():
            if not va or not vb:
                continue
            inter = va & vb
            if not inter:
                continue
            cover_a, cover_b = len(inter) / len(va), len(inter) / len(vb)
            name_bonus = 0.15 if key(ca) == key(cb) or key(ca) in key(cb) or key(cb) in key(ca) else 0
            score = max(cover_a, cover_b) + name_bonus
            if max(cover_a, cover_b) >= 0.05:
                cand.append({"kolom_file_a": str(ca), "kolom_file_b": str(cb), "nilai_cocok": len(inter),
                             "cocok_pct_a": round(cover_a * 100, 1), "cocok_pct_b": round(cover_b * 100, 1),
                             "contoh": sorted(inter)[:3], "_score": score})
    cand.sort(key=lambda x: -x["_score"])
    for c in cand:
        c.pop("_score", None)
    return cand[:top]


# ==========================================================================
# Menjalankan rencana analisis
# ==========================================================================
def _clean(v: Any) -> Any:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v


def _require(df: pd.DataFrame, cols: list[str]) -> list[str]:
    cmap = _colmap(df)
    out = []
    for c in cols:
        real = c if c in df.columns else cmap.get(str(c).lower())
        if real is None:
            raise PlanError(f"Kolom '{c}' tidak ada. Kolom tersedia: {', '.join(map(str, df.columns))[:1500]}")
        out.append(real)
    return out


def _apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    for f in filters or []:
        col, op, val = f.get("column"), f.get("op", "=="), f.get("value")
        if op not in OPS:
            raise PlanError(f"Operator filter tidak dikenal: {op}")
        (col,) = _require(df, [col])
        s = df[col]
        num = pd.to_numeric(s, errors="coerce")
        use_num = isinstance(val, (int, float)) or (isinstance(val, list) and val and all(isinstance(x, (int, float)) for x in val))
        cmp = num if use_num else s.astype(str).str.strip()
        if op in ("in", "not in"):
            vals = val if isinstance(val, list) else [val]
            mask = cmp.isin(vals) if use_num else cmp.str.upper().isin([str(v).strip().upper() for v in vals])
            mask = ~mask if op == "not in" else mask
        elif op == "contains":
            mask = s.astype(str).str.contains(str(val), case=False, regex=False, na=False)
        elif op == "between":
            if not isinstance(val, list) or len(val) != 2:
                raise PlanError("Filter 'between' butuh value [awal, akhir].")
            lo, hi = val
            mask = cmp.between(lo, hi) if use_num else cmp.between(str(lo), str(hi))
        elif op == "isnull":
            mask = s.isna()
        elif op == "notnull":
            mask = s.notna()
        else:
            if not use_num and isinstance(val, str):
                cmp, val = cmp.str.upper(), val.strip().upper()
            mask = {"==": cmp == val, "!=": cmp != val, ">": cmp > val, ">=": cmp >= val,
                    "<": cmp < val, "<=": cmp <= val}[op]
        df = df[mask.fillna(False) if hasattr(mask, "fillna") else mask]
    return df


def _derive(df: pd.DataFrame, derive: list[dict]) -> pd.DataFrame:
    for d in derive or []:
        name, expr = d.get("name"), d.get("expr", "")
        if not name or not _EXPR_OK.match(expr or ""):
            raise PlanError(f"Ekspresi turunan tidak valid: {expr!r} (hanya kolom, angka, dan + - * / ( )).")
        tmp = df.copy()
        for c in tmp.columns:
            if not pd.api.types.is_numeric_dtype(tmp[c]) and not pd.api.types.is_datetime64_any_dtype(tmp[c]):
                conv = pd.to_numeric(tmp[c], errors="coerce")
                if conv.notna().sum() >= max(1, int(0.5 * tmp[c].notna().sum())):
                    tmp[c] = conv
        try:
            df = df.assign(**{name: tmp.eval(expr, engine="python")})
        except Exception as exc:  # noqa: BLE001
            raise PlanError(f"Ekspresi '{expr}' gagal dihitung: {exc}") from exc
    return df


def _gap_kimap(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """PTPL vs rata-rata kompetitor dalam KIMAP yang sama (aturan Data Agent retail)."""
    metrics = spec.get("metrics") or ["HJ_L"]
    group = spec.get("group_by") or []
    kimap, qnr = _require(df, ["KIMAP", "QNR"])
    metrics = _require(df, metrics)
    group = _require(df, group) if group else []
    if "IS_PTPL" not in df.columns:
        raise PlanError("Preset gap_kimap butuh data retail (kolom BRAND).")
    comp = df[~df["IS_PTPL"]]
    brands = spec.get("competitor_brands")
    if brands:
        bcol = _require(df, ["BRAND"])[0]
        comp = comp[comp[bcol].astype(str).str.upper().isin([b.upper() for b in brands])]
    ptpl = df[df["IS_PTPL"]]
    if spec.get("hero_only") and "IS_HERO" in df.columns:
        ptpl = ptpl[ptpl["IS_HERO"]]
    p = ptpl.groupby(group + [kimap, qnr], dropna=False)[metrics].mean().reset_index().rename(columns={qnr: "PRODUK_PTPL"})
    k = comp.groupby(group + [kimap], dropna=False)[metrics].mean().reset_index()
    m = p.merge(k, on=group + [kimap], suffixes=("_PTPL", "_KOMP"))
    for met in metrics:
        m[f"GAP_{met}"] = m[f"{met}_PTPL"] - m[f"{met}_KOMP"]
    return m


def run_plan(frames: dict[str, pd.DataFrame], plan: dict[str, Any], max_rows: int | None = None) -> dict[str, Any]:
    """Jalankan rencana: {file, join?, filters?, derive?, preset?, group_by?, metrics?, pivot?, sort?, limit?}."""
    fid = plan.get("file")
    if fid not in frames:
        raise PlanError(f"File '{fid}' tidak ada. File tersedia: {', '.join(frames)}")
    df = frames[fid]
    j = plan.get("join")
    if j:
        other = frames.get(j.get("file"))
        if other is None:
            raise PlanError(f"File join '{j.get('file')}' tidak ada.")
        left, right = _require(df, j.get("left_on") or []), _require(other, j.get("right_on") or [])
        if not left or len(left) != len(right):
            raise PlanError("Join butuh left_on dan right_on dengan jumlah kolom yang sama.")
        lhs, rhs = df.copy(), other.copy()
        for a, b in zip(left, right):
            lhs[a] = lhs[a].astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
            rhs[b] = rhs[b].astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
        df = lhs.merge(rhs, left_on=left, right_on=right, how=j.get("how", "inner"), suffixes=("", "_B"))
    rows_input = len(df)
    df = _apply_filters(df, plan.get("filters"))
    rows_filtered = len(df)
    df = _derive(df, plan.get("derive"))
    if plan.get("preset") == "gap_kimap":
        df = _gap_kimap(df, plan.get("preset_args") or {})
    elif str(plan.get("preset", "")).startswith("planogram_"):
        from .planogram_data import run_preset

        args = plan.get("preset_args") or {}
        df = run_preset(df, plan["preset"], args.get("group_by"), args.get("engine_oil_only", True))
    gb = plan.get("group_by") or []
    metrics = plan.get("metrics") or []
    if plan.get("pivot"):
        pv = plan["pivot"]
        idx, colk, val = _require(df, pv.get("index") or []), _require(df, [pv.get("columns")])[0], _require(df, [pv.get("values")])[0]
        agg = pv.get("agg", "mean")
        if agg not in AGGS:
            raise PlanError(f"Agregasi tidak dikenal: {agg}")
        df = pd.pivot_table(df, index=idx, columns=colk, values=val, aggfunc=agg).reset_index()
        df.columns = [str(c) for c in df.columns]
    elif metrics:
        gb = _require(df, gb) if gb else []
        named = {}
        for m in metrics:
            agg = m.get("agg", "mean")
            if agg not in AGGS:
                raise PlanError(f"Agregasi tidak dikenal: {agg}")
            col = _require(df, [m.get("column")])[0]
            name = m.get("name") or f"{agg}_{col}"
            if agg in ("count", "nunique"):
                series = df[col]
            elif agg in ("min", "max") and _is_date(df[col]):
                series = pd.to_datetime(df[col], errors="coerce")       # tanggal tetap tanggal, bukan angka
            else:
                series = pd.to_numeric(df[col], errors="coerce")
            named[name] = (series, agg)
        work = df[gb].copy() if gb else pd.DataFrame(index=df.index)
        for name, (series, _) in named.items():
            work[name] = series
        if gb:
            df = work.groupby(gb, dropna=False).agg({n: a for n, (_, a) in named.items()}).reset_index()
        else:
            df = pd.DataFrame([{n: work[n].agg(a) for n, (_, a) in named.items()}])
        df["JUMLAH_BARIS"] = (work.groupby(gb, dropna=False).size().values if gb else [len(work)])
    elif plan.get("columns"):
        df = df[_require(df, plan["columns"])]
    for s in reversed(plan.get("sort") or []):
        (col,) = _require(df, [s.get("column")])
        df = df.sort_values(col, ascending=not s.get("desc", False), kind="stable")
    total = len(df)
    if max_rows is None:
        limit = min(int(plan.get("limit") or 50), MAX_RESULT_ROWS)
    else:                                                    # ekspor: semua baris (batas Excel), abaikan limit tampilan
        limit = max_rows
    df = df.head(limit)
    rows = [[_clean(v) for v in r] for r in df.itertuples(index=False, name=None)]
    return {"columns": [str(c) for c in df.columns], "rows": rows, "rows_total": int(total),
            "rows_input": int(rows_input), "rows_after_filter": int(rows_filtered)}


# ==========================================================================
# Baris laporan dari file (mesin yang sama dengan laporan BigQuery)
# ==========================================================================
def retail_report_rows(df: pd.DataFrame, period_a: dict, period_b: dict | None, heroes: list[str]):
    """Baris agregat & bulanan setara AGG_SQL/MONTHLY_SQL di price_data, dari frame retail yang sudah di-prepare."""
    c = lambda n: _col(df, n)  # noqa: E731
    need = ["DT_PR", "SEGMENT", "VISCOSITY", "KIMAP", "BRAND", "QNR"]
    missing = [n for n in need if not c(n)]
    if missing or "HJ_L" not in df.columns:
        raise PlanError(f"File retail tidak lengkap untuk laporan (kolom hilang: {', '.join(missing) or 'harga per liter'}).")
    d = df.copy()
    d["_D"] = d[c("DT_PR")].astype(str).str.slice(0, 10)
    in_a = d["_D"].between(period_a["start"], period_a["end"])
    in_b = d["_D"].between(period_b["start"], period_b["end"]) if period_b else pd.Series(False, index=d.index)
    d = d[(in_a | in_b) & d["ZONA"].notna()].copy()
    d["PERIOD"] = in_a[d.index].map({True: "A", False: "B"})
    d["SIDE"] = d["IS_PTPL"].map({True: "PTPL", False: "KOMP"})
    d["PRODUCT"] = d[c("QNR")].astype(str).str.upper().where(d["IS_PTPL"], "")
    d["SEGMENT_U"] = d[c("SEGMENT")].astype(str).str.upper()
    mets = {"HET": "HET_L", "HJ": "HJ_L", "HTO": "HTO_L", "HT": "HT_L", "MARG": "MARG_L"}
    for k, v in mets.items():
        if v not in d.columns:
            d[v] = float("nan")
    agg, monthly = [], []
    both = pd.concat([d.assign(ZONE=d["ZONA"]), d.assign(ZONE="Nasional")])
    keys = ["PERIOD", "ZONE", "SEGMENT_U", c("VISCOSITY"), c("KIMAP"), "SIDE", "PRODUCT"]
    g = both.groupby(keys, dropna=False)
    means = g[[v for v in mets.values()]].mean().reset_index()
    counts = g.size().reset_index(name="N")
    means = means.merge(counts, on=keys)
    for r in means.itertuples(index=False):
        row = dict(zip(means.columns, r))
        agg.append({"PERIOD": row["PERIOD"], "ZONE": row["ZONE"], "SEGMENT": row["SEGMENT_U"],
                    "VISCOSITY": row[c("VISCOSITY")], "KIMAP": row[c("KIMAP")], "SIDE": row["SIDE"],
                    "PRODUCT": row["PRODUCT"], **{k: _clean(row[v]) for k, v in mets.items()}, "N": int(row["N"])})
    hero_set = {h.upper() for h in heroes}
    hero_kimaps = set(d[d["IS_PTPL"] & d[c("QNR")].astype(str).str.upper().isin(hero_set)][c("KIMAP")])
    hb = both[both[c("KIMAP")].isin(hero_kimaps)].copy()
    hb["MONTH"] = hb["_D"].str.slice(0, 7)
    mk = ["MONTH", "ZONE", "SEGMENT_U", c("KIMAP"), "SIDE", c("QNR")]
    mm = hb.groupby(mk, dropna=False).agg(HJ=("HJ_L", "mean"), HTO=("HTO_L", "mean"), BRAND=(c("BRAND"), "first")).reset_index()
    for r in mm.itertuples(index=False):
        row = dict(zip(mm.columns, r))
        monthly.append({"MONTH": row["MONTH"], "ZONE": row["ZONE"], "SEGMENT": row["SEGMENT_U"], "KIMAP": row[c("KIMAP")],
                        "SIDE": row["SIDE"], "PRODUCT": str(row[c("QNR")]).upper(), "BRAND": str(row["BRAND"]).upper(),
                        "HJ": _clean(row["HJ"]), "HTO": _clean(row["HTO"])})
    return agg, monthly


def industry_report_rows(df: pd.DataFrame, period_a: dict, period_b: dict | None, htd_column: str,
                         segment_column: str) -> list[dict]:
    c = lambda n: _col(df, n)  # noqa: E731
    need = ["dt_pr", "main_stage", "produk_ptpl", "brand", "harga_kompetitor_per_liter", htd_column, segment_column]
    missing = [n for n in need if not c(n)]
    if missing:
        raise PlanError(f"File industri tidak lengkap untuk laporan (kolom hilang: {', '.join(missing)}).")
    d = df.copy()
    d["_D"] = d[c("dt_pr")].astype(str).str.slice(0, 10)
    in_a = d["_D"].between(period_a["start"], period_a["end"])
    in_b = d["_D"].between(period_b["start"], period_b["end"]) if period_b else pd.Series(False, index=d.index)
    d = d[(in_a | in_b) & d["ZONA"].notna()]
    rows = []
    for idx, r in d.iterrows():
        rows.append({"PERIOD": "A" if in_a[idx] else "B", "STAGE": str(r[c("main_stage")]).upper(), "ZONE": r["ZONA"],
                     "CHANNEL": r[c(segment_column)], "PRODUCT": r[c("produk_ptpl")], "BRAND": str(r[c("brand")]).upper(),
                     "PRICE": _clean(pd.to_numeric(r[c("harga_kompetitor_per_liter")], errors="coerce")),
                     "HTD_PLUS": _clean(pd.to_numeric(r[c(htd_column)], errors="coerce"))})
    return rows
