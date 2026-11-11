"""Insight otomatis: banyak chart per tarikan data + korelasi antar data di chat (Strategist Toolkit).

- daftar_data   : memori data chat ini (tarikan BigQuery p1.., analisis file a1..) beserta kolom & sumbernya.
- buat_insight  : satu panggilan -> beberapa chart (jenis dari katalog insight_charts), angka sorotan dihitung kode.
- korelasi_data : hubungkan dua data lewat kolom kunci yang sama -> korelasi (r Pearson & Spearman, n) + scatter.
                  HANYA untuk data dari sumber yang sama, atau Retail × Planogram. Sumber lain berdiri sendiri.
"""
from __future__ import annotations

import functools
import logging
import re
from datetime import datetime, timezone
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)
CHARTS_KEY = "insight_charts"
MAX_CHARTS = 8
LINKABLE = {"retail", "planogram", "retail_planogram"}


def _safe(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"Gagal karena kendala teknis: {str(exc)[:300]}"}
    return wrapper


# ==========================================================================
# Sumber data
# ==========================================================================
def _file_domain(kind: str | None) -> str:
    return kind if kind in ("retail", "industri", "planogram", "sellout") else "file"


def get_table(state, data_id: str, table_index: int = 0) -> tuple[dict, str, str]:
    """(tabel {'columns','rows'}, domain, label sumber) dari p# (BigQuery) atau a# (analisis file)."""
    from .. import data_agent

    data_id = (data_id or "").strip()
    if data_id.startswith("p"):
        from .data_tools import PULLS_KEY

        pull = next((p for p in state.get(PULLS_KEY, []) or [] if p.get("id") == data_id), None)
        if not pull:
            raise ValueError(f"Data {data_id} tidak ditemukan (mungkin sudah tergeser data yang lebih baru).")
        tables = pull.get("tables") or []
        if not tables:
            raise ValueError(f"Data {data_id} tidak berisi tabel.")
        t = tables[min(max(int(table_index or 0), 0), len(tables) - 1)]
        return t, pull["domain"], data_agent.SOURCE_LABELS.get(pull["domain"], pull["domain"])
    if data_id.startswith("a"):
        from .. import data_engine as de
        from .file_tools import ANALYSES_KEY, _prepared

        a = next((x for x in state.get(ANALYSES_KEY, []) or [] if x.get("id") == data_id), None)
        if not a:
            raise ValueError(f"Analisis {data_id} tidak ditemukan.")
        files = {f["file_id"]: f for f in state.get("data_files", []) or []}
        plan = dict(a["plan"])
        frames, kind = {}, None
        for fid in {plan.get("file"), (plan.get("join") or {}).get("file")} - {None}:
            if fid not in files:
                raise ValueError(f"File {fid} sudah tidak ada di chat.")
            frame, _, k = _prepared(files[fid])
            frames[fid] = frame
            kind = kind or files[fid].get("kind") or k
        res = de.run_plan(frames, plan, max_rows=5000)
        return {"columns": res["columns"], "rows": res["rows"]}, _file_domain(kind), f"File unggahan {a.get('file', '')}"
    raise ValueError("data_id harus berawalan p (tarikan BigQuery) atau a (analisis file).")


def _upload(tool_context: ToolContext, png: bytes, title: str) -> str:
    from ..clients import get_user_id, storage_client
    from ..config import settings

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%f")[:-3]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:40].lower() or "chart"
    path = f"{settings.report_prefix}/{get_user_id(tool_context)}/charts/{stamp}-{slug}.png"
    storage_client().bucket(settings.report_bucket).blob(path).upload_from_string(png, content_type="image/png")
    pending = list(tool_context.state.get("insight_pending_charts") or [])
    pending.append({"bucket": settings.report_bucket, "path": path, "title": title})
    tool_context.state["insight_pending_charts"] = pending[-MAX_CHARTS:]
    return f"https://storage.cloud.google.com/{settings.report_bucket}/{path}"


def _remember(tool_context: ToolContext, item: dict) -> None:
    charts = list(tool_context.state.get(CHARTS_KEY, []) or [])
    charts.append(item)
    tool_context.state[CHARTS_KEY] = charts[-20:]


# ==========================================================================
# Tools
# ==========================================================================
@_safe
def daftar_data(tool_context: ToolContext) -> dict[str, Any]:
    """Daftar semua data di chat ini (tarikan BigQuery p#, analisis file a#) beserta sumber dan kolomnya.

    Pakai untuk memilih data_id bagi buat_insight, dan untuk mencari data lain yang bisa dihubungkan (korelasi_data)
    dengan data baru.
    """
    from .data_tools import PULLS_KEY
    from .file_tools import ANALYSES_KEY

    out = []
    for p in tool_context.state.get(PULLS_KEY, []) or []:
        t = (p.get("tables") or [{}])[0]
        out.append({"data_id": p.get("id"), "sumber": p.get("domain"), "pertanyaan": p.get("question"),
                    "kolom": t.get("columns"), "baris": len(t.get("rows") or [])})
    files = {f["file_id"]: f for f in tool_context.state.get("data_files", []) or []}
    for a in tool_context.state.get(ANALYSES_KEY, []) or []:
        f = files.get((a.get("plan") or {}).get("file"), {})
        out.append({"data_id": a.get("id"), "sumber": _file_domain(f.get("kind")), "pertanyaan": a.get("question"),
                    "kolom": a.get("columns"), "baris": a.get("rows_total")})
    return {"status": "ok", "data": out,
            "aturan_korelasi": "Hanya data dari sumber yang sama, atau Retail × Planogram."}


@_safe
def buat_insight(charts: list[dict], tool_context: ToolContext) -> dict[str, Any]:
    """Membuat BEBERAPA chart insight sekaligus dari data di chat ini; angka sorotan dihitung otomatis.

    Pilih jenis chart sesuai pertanyaan analisis (katalog Strategist Toolkit): trend, comparison, mix, distribution,
    candlestick, scatter, positioning, cumulative (Pareto), rank, waterfall, actual_target, heatmap, profit_margin,
    unit_economics, cashflow, roic, marginal_return, bull_bear (skenario, hanya bila diminta).

    Args:
        charts: daftar chart (maks. 8). Tiap chart: {"jenis", "data_id" (p#/a#), "tabel" (indeks, default 0),
            "judul" (HEADLINE berupa kesimpulan, bukan topik), "satuan", dan kolom sesuai jenis:
            trend/cashflow/marginal_return: x=periode, y=[kolom...] (trend: "stack": true untuk stacked);
            comparison: x=kategori, y=[nilai] atau [nilai_A, nilai_B]; mix: x=komponen, y=[periode_A, periode_B];
            distribution: nilai; candlestick: kategori, nilai; scatter/positioning: x, y=[kolom], label, ukuran,
            garis_x, garis_y, kuadran=[kanan atas, kiri atas, kiri bawah, kanan bawah]; cumulative: x, y=[nilai];
            rank: x=periode, kategori=item, nilai; waterfall: x, y=[awal, akhir]; actual_target: x, y=[aktual, target];
            heatmap: x=kolom, kategori=baris, nilai, kecil_lebih_baik; profit_margin: x, y=[pendapatan, biaya];
            unit_economics: x, y=[LTV, CAC]; roic: x, y=[NOPAT, modal]; bull_bear: x, y=[aktual], horizon,
            skenario_pct}.
    """
    from .. import insight_charts as ic

    if not charts:
        return {"status": "invalid", "message": "Isi minimal satu chart."}
    results = []
    for c in charts[:MAX_CHARTS]:
        c = dict(c or {})
        kind = str(c.get("jenis", "")).strip().lower()
        title = str(c.get("judul") or kind).strip()
        try:
            table, domain, source = get_table(tool_context.state, c.get("data_id", ""), int(c.get("tabel") or 0))
            spec, facts = ic.build(kind, table, c)
            png = ic.render(spec, title, facts[0] if facts else "", source, c.get("satuan", ""))
            link = _upload(tool_context, png, title)
            _remember(tool_context, {"judul": title, "jenis": kind, "data_id": c.get("data_id"), "sumber": domain,
                                     "fakta": facts, "link": link})
            results.append({"status": "ok", "judul": title, "jenis": kind, "fakta": facts, "link": link})
        except (ic.ChartError, ValueError) as exc:
            results.append({"status": "error", "judul": title, "jenis": kind, "message": str(exc)})
    ok = [r for r in results if r["status"] == "ok"]
    return {"status": "ok" if ok else "error", "chart": results,
            "panduan": ("Mulai jawaban dengan kesimpulan utama (jawaban dulu). Lalu untuk tiap chart: headline, angka "
                        "sorotan dari 'fakta' (persis), takeaway 'so what' untuk user, dan link chart. Perbaiki chart "
                        "yang error bila perlu (cek nama kolom).")}


@_safe
def korelasi_data(data_a: str, data_b: str, kunci_a: str, kunci_b: str, nilai_a: str, nilai_b: str,
                  tool_context: ToolContext, judul: str = "", tabel_a: int = 0, tabel_b: int = 0) -> dict[str, Any]:
    """Menghubungkan dua data di chat ini lewat kolom kunci yang sama (mis. SR, periode, KIMAP, brand) dan menghitung
    korelasinya (r Pearson & Spearman, jumlah pasangan n) beserta scatter.

    HANYA boleh untuk data dari sumber yang sama (mis. dua tarikan Retail, atau file retail + tarikan Retail), atau
    Retail × Planogram. Hasilnya asosiasi, BUKAN sebab-akibat.

    Args:
        data_a: data_id pertama (p#/a#).
        data_b: data_id kedua (p#/a#).
        kunci_a: Kolom kunci di data_a (mis. "SR").
        kunci_b: Kolom kunci di data_b yang isinya setara (mis. "SALES_REGION").
        nilai_a: Kolom angka di data_a (sumbu X).
        nilai_b: Kolom angka di data_b (sumbu Y).
        judul: Headline berupa kesimpulan (opsional).
        tabel_a: Indeks tabel di data_a (default 0).
        tabel_b: Indeks tabel di data_b (default 0).
    """
    from .. import insight_charts as ic

    ta, da, sa = get_table(tool_context.state, data_a, tabel_a)
    tb, db, sb = get_table(tool_context.state, data_b, tabel_b)
    if not (da == db or {da, db} <= LINKABLE):
        return {"status": "not_allowed",
                "message": (f"Data {data_a} ({da}) dan {data_b} ({db}) tidak dihubungkan: korelasi hanya untuk sumber "
                            "yang sama atau Retail × Planogram. Sajikan masing-masing secara terpisah.")}
    norm = lambda v: re.sub(r"\s+", "", str(v)).upper().replace("SR0", "SR")  # noqa: E731
    ka, va = ic.column(ta, kunci_a), ic.column(ta, nilai_a, True)
    kb, vb = ic.column(tb, kunci_b), ic.column(tb, nilai_b, True)
    left = {norm(k): (k, v) for k, v in zip(ka, va) if v is not None}
    pairs = [(left[norm(k)][0], left[norm(k)][1], v) for k, v in zip(kb, vb) if v is not None and norm(k) in left]
    if len(pairs) < 3:
        return {"status": "insufficient", "message": f"Hanya {len(pairs)} kunci yang cocok antara {kunci_a} dan "
                                                     f"{kunci_b}; minimal 3 untuk korelasi. Cek kesamaan isi kolom kunci."}
    xs, ys = [p[1] for p in pairs], [p[2] for p in pairs]
    r, rho = ic.pearson(xs, ys), ic.spearman(xs, ys)
    facts = [f"{nilai_a} ({data_a}) vs {nilai_b} ({data_b}) per {kunci_a}: r Pearson = "
             f"{ic.fmt(r, 2) if r is not None else 'n/a'} ({ic.strength(r)}), Spearman = "
             f"{ic.fmt(rho, 2) if rho is not None else 'n/a'}, n = {len(pairs)}",
             "Asosiasi, bukan sebab-akibat" + (" — n kecil, tafsirkan hati-hati" if len(pairs) < 8 else "")]
    spec = {"kind": "scatter", "points": [(x, y, k, None) for k, x, y in pairs], "lines": (None, None),
            "xlab": f"{nilai_a} ({sa})", "ylab": f"{nilai_b} ({sb})"}
    title = judul.strip() or f"Hubungan {nilai_a} dan {nilai_b} per {kunci_a}"
    link = _upload(tool_context, ic.render(spec, title, facts[0], f"{sa} × {sb}"), title)
    _remember(tool_context, {"judul": title, "jenis": "korelasi", "data_id": f"{data_a}×{data_b}",
                             "sumber": f"{da}×{db}", "fakta": facts, "link": link})
    return {"status": "ok", "judul": title, "fakta": facts, "pasangan": len(pairs), "link": link,
            "panduan": "Jelaskan arah & kekuatan hubungan dengan angka di fakta, beri takeaway, dan ingatkan asosiasi."}


CHART_INSIGHT_TOOLS = [daftar_data, buat_insight, korelasi_data]
