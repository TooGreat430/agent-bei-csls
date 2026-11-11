"""Katalog chart insight (mengikuti "Overnight Strategist – Strategist Toolkit", bagian ANALYSE).

Setiap jenis chart menjawab satu PERTANYAAN ANALISIS. Data diambil dari tabel hasil tarikan (BigQuery / analisis file),
diolah kode (urut, kumulatif, persentil, korelasi, dll.), lalu digambar PNG bergaya PTPL. Angka sorotan ("fakta")
dihitung di sini — model hanya menulis headline & takeaway dari fakta itu.

jenis              pertanyaan                                   input (nama kolom tabel)
trend              berubah bagaimana dari waktu ke waktu?       x=periode, y=[nilai...] (stack=True -> stacked bar)
comparison         siapa lebih tinggi/rendah? (peringkat)       x=kategori, y=[nilai] (2 nilai -> perbandingan periode)
mix                komposisi bergeser bagaimana? (from->to)     x=komponen, y=[nilai_periode_A, nilai_periode_B, ...]
distribution       seberapa tersebar?                           nilai=kolom angka (baris mentah)
candlestick        rentang min–P25–median–P75–max per grup      kategori=grup, nilai=kolom angka (baris mentah)
scatter            dua ukuran saling berhubungan?               x, y, (ukuran -> bubble), label
positioning        posisi vs kompetitor di 2 dimensi (2x2)      x, y, label, (garis_x, garis_y)
cumulative         siapa penyumbang terbesar? (Pareto 80/20)    x=kategori, y=[nilai]
rank               siapa naik/turun peringkat?                  x=periode, kategori=item, nilai=angka
waterfall          apa yang menjelaskan perubahan total?        x=kategori, y=[nilai_awal, nilai_akhir]
actual_target      seberapa jauh dari target?                   x=kategori, y=[aktual, target]
heatmap            pola baris × kolom (traffic light)           x=kolom_kategori, kategori=baris, nilai=angka
profit_margin      pendapatan, biaya, margin %                  x=periode, y=[pendapatan, biaya]
unit_economics     LTV vs CAC                                   x=kategori, y=[LTV, CAC]
cashflow           arus kas positif/negatif & kumulatif         x=periode, y=[arus_kas]
roic               imbal hasil modal                            x=periode, y=[laba_operasi_setelah_pajak, modal]
marginal_return    hasil tambahan per tambahan input            x=input, y=[output]
bull_bear          skenario bull/base/bear dari tren aktual     x=periode, y=[aktual]; skenario_pct (default 10)
"""
from __future__ import annotations

import io
import math
import re
from typing import Any

NAVY, NAVY2, GOLD = "#0C1E3C", "#1A3260", "#B58012"
GREEN, RED, BLUE, GRAY, BORDER = "#15803D", "#DC2626", "#1D4ED8", "#475569", "#CBD5E1"
PALETTE = ["#0C1E3C", "#B58012", "#15803D", "#DC2626", "#1D4ED8", "#7C3AED", "#0891B2", "#94A3B8"]
KINDS = ("trend", "comparison", "mix", "distribution", "candlestick", "scatter", "positioning", "cumulative", "rank",
         "waterfall", "actual_target", "heatmap", "profit_margin", "unit_economics", "cashflow", "roic",
         "marginal_return", "bull_bear")
ALIASES = {"line": "trend", "bar": "comparison", "hbar": "comparison", "pareto": "cumulative", "boxplot": "candlestick",
           "histogram": "distribution", "bubble": "scatter", "matrix": "positioning", "2x2": "positioning",
           "target": "actual_target", "actual_v_target": "actual_target", "football": "candlestick"}


class ChartError(ValueError):
    pass


# ==========================================================================
# Utilitas data
# ==========================================================================
def num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip().replace("Rp", "").replace("%", "").replace(" ", "")
    if not s:
        return None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):          # 1.234.567,8 (format Indonesia)
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d+,\d+", s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def col_index(columns: list[str], name: str | None) -> int:
    if name is None:
        raise ChartError("Nama kolom wajib diisi.")
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())  # noqa: E731
    for i, c in enumerate(columns):
        if str(c) == name or norm(c) == norm(name):
            return i
    raise ChartError(f"Kolom '{name}' tidak ada. Kolom tersedia: {', '.join(map(str, columns))[:400]}")


def column(table: dict, name: str, numeric: bool = False) -> list:
    i = col_index(table["columns"], name)
    vals = [r[i] if i < len(r) else None for r in table["rows"]]
    return [num(v) for v in vals] if numeric else ["" if v is None else str(v) for v in vals]


def fmt(v: float | None, dec: int | None = None) -> str:
    """Format Indonesia: 1.234,5."""
    if v is None:
        return "n/a"
    if dec is None:
        dec = 0 if abs(v) >= 100 else 1 if abs(v) >= 10 else 2
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float | None, dec: int = 1) -> str:
    return "n/a" if v is None else fmt(v, dec) + "%"


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def _ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(_ranks(xs), _ranks(ys)) if len(xs) >= 3 else None


def strength(r: float | None) -> str:
    if r is None:
        return "tidak dapat dihitung"
    a = abs(r)
    word = "sangat lemah" if a < 0.2 else "lemah" if a < 0.4 else "sedang" if a < 0.6 else "kuat" if a < 0.8 else "sangat kuat"
    return f"{word} {'positif' if r > 0 else 'negatif'}"


def percentile(vals: list[float], p: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def _pairs(xs: list, ys: list) -> list[tuple]:
    return [(x, y) for x, y in zip(xs, ys) if y is not None]


# ==========================================================================
# Transformasi + fakta per jenis (hasil: dict gambar + daftar fakta berangka)
# ==========================================================================
def build(kind: str, table: dict, a: dict) -> tuple[dict, list[str]]:  # noqa: C901
    kind = ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise ChartError(f"Jenis chart '{kind}' tidak dikenal. Pilihan: {', '.join(KINDS)}")
    y = list(a.get("y") or [])
    facts: list[str] = []
    unit = a.get("satuan", "")
    u = "" if not unit else (unit if unit in ("%", "pp", "x") else f" {unit}")

    if kind in ("trend", "bull_bear", "cashflow", "marginal_return", "profit_margin", "roic"):
        xs = column(table, a.get("x"))
        series = [(c, column(table, c, True)) for c in (y or [])]
        if not series:
            raise ChartError("Isi y dengan minimal satu kolom angka.")
    if kind == "trend":
        for name, vals in series:
            pts = [v for v in vals if v is not None]
            if len(pts) >= 2 and pts[0]:
                facts.append(f"{name}: {fmt(pts[0])} → {fmt(pts[-1])}{u} ({pct((pts[-1] - pts[0]) / abs(pts[0]) * 100)})")
            if pts:
                hi = max(range(len(vals)), key=lambda i: vals[i] if vals[i] is not None else -1e18)
                facts.append(f"{name} tertinggi di {xs[hi]}: {fmt(vals[hi])}{u}")
        return {"kind": "stack" if a.get("stack") else "line", "x": xs, "series": series}, facts

    if kind == "comparison":
        xs = column(table, a.get("x"))
        if len(y) >= 2:
            s = [(c, column(table, c, True)) for c in y[:2]]
            ch = [(xs[i], s[0][1][i], s[1][1][i]) for i in range(len(xs)) if s[0][1][i] is not None and s[1][1][i] is not None]
            for lab, v0, v1 in sorted(ch, key=lambda t: -(abs(t[2] - t[1])))[:3]:
                facts.append(f"{lab}: {fmt(v0)} → {fmt(v1)}{u} ({'+' if v1 >= v0 else ''}{fmt(v1 - v0)})")
            return {"kind": "group", "x": xs, "series": s}, facts
        vals = column(table, y[0], True)
        pts = sorted(_pairs(xs, vals), key=lambda t: -t[1])
        if not pts:
            raise ChartError("Kolom nilai kosong.")
        facts.append(f"Tertinggi {pts[0][0]}: {fmt(pts[0][1])}{u}; terendah {pts[-1][0]}: {fmt(pts[-1][1])}{u}")
        if len(pts) > 1 and pts[-1][1]:
            facts.append(f"Selisih tertinggi–terendah: {fmt(pts[0][1] - pts[-1][1])}{u}")
        return {"kind": "hbar", "x": [p[0] for p in pts][:20], "series": [(y[0], [p[1] for p in pts][:20])]}, facts

    if kind == "mix":
        xs = column(table, a.get("x"))
        periods = [(c, column(table, c, True)) for c in y]
        if len(periods) < 1:
            raise ChartError("Isi y dengan kolom nilai per periode (mis. [Q2, Q3]).")
        shares = []
        for name, vals in periods:
            tot = sum(v for v in vals if v)
            shares.append((name, [(v or 0) / tot * 100 if tot else 0 for v in vals]))
        if len(shares) >= 2:
            d = [(xs[i], shares[-1][1][i] - shares[0][1][i]) for i in range(len(xs))]
            up, dn = max(d, key=lambda t: t[1]), min(d, key=lambda t: t[1])
            facts.append(f"Porsi naik terbesar: {up[0]} {'+' if up[1] >= 0 else ''}{fmt(up[1], 1)} pp")
            facts.append(f"Porsi turun terbesar: {dn[0]} {fmt(dn[1], 1)} pp")
        top = max(range(len(xs)), key=lambda i: shares[-1][1][i])
        facts.append(f"Porsi terbesar {shares[-1][0]}: {xs[top]} {pct(shares[-1][1][top])}")
        return {"kind": "mix", "components": xs, "periods": shares}, facts

    if kind == "distribution":
        vals = [v for v in column(table, a.get("nilai") or (y[0] if y else None), True) if v is not None]
        if len(vals) < 5:
            raise ChartError("Distribusi butuh minimal 5 nilai (pakai baris mentah, bukan agregat).")
        q1, med, q3 = percentile(vals, 25), percentile(vals, 50), percentile(vals, 75)
        facts += [f"Median {fmt(med)}{u}; rentang tengah (P25–P75) {fmt(q1)}–{fmt(q3)}{u}",
                  f"Min {fmt(min(vals))}{u}, maks {fmt(max(vals))}{u}, n = {len(vals)}"]
        return {"kind": "hist", "values": vals, "q": (q1, med, q3)}, facts

    if kind == "candlestick":
        cats = column(table, a.get("kategori") or a.get("x"))
        vals = column(table, a.get("nilai") or (y[0] if y else None), True)
        groups: dict[str, list[float]] = {}
        for c, v in zip(cats, vals):
            if v is not None:
                groups.setdefault(c, []).append(v)
        stats = {c: (min(v), percentile(v, 25), percentile(v, 50), percentile(v, 75), max(v), len(v))
                 for c, v in groups.items() if len(v) >= 3}
        if not stats:
            raise ChartError("Candlestick butuh minimal 3 nilai per grup (pakai baris mentah).")
        order = sorted(stats, key=lambda c: -stats[c][2])[:15]
        widest = max(order, key=lambda c: stats[c][3] - stats[c][1])
        facts.append(f"Median tertinggi {order[0]}: {fmt(stats[order[0]][2])}{u}; terendah {order[-1]}: "
                     f"{fmt(stats[order[-1]][2])}{u}")
        facts.append(f"Sebaran terlebar {widest}: P25–P75 {fmt(stats[widest][1])}–{fmt(stats[widest][3])}{u}")
        return {"kind": "box", "cats": order, "stats": [stats[c] for c in order]}, facts

    if kind in ("scatter", "positioning"):
        xs, ys = column(table, a.get("x"), True), column(table, (y[0] if y else a.get("nilai")), True)
        labels = column(table, a["label"]) if a.get("label") else [""] * len(xs)
        sizes = column(table, a["ukuran"], True) if a.get("ukuran") else None
        pts = [(xs[i], ys[i], labels[i], (sizes[i] if sizes else None)) for i in range(len(xs))
               if xs[i] is not None and ys[i] is not None]
        if len(pts) < 3:
            raise ChartError("Scatter butuh minimal 3 titik dengan x dan y terisi.")
        r = pearson([p[0] for p in pts], [p[1] for p in pts])
        facts.append(f"Korelasi {a.get('x')} vs {y[0] if y else a.get('nilai')}: r = {fmt(r, 2) if r is not None else 'n/a'} "
                     f"({strength(r)}), n = {len(pts)} — asosiasi, bukan sebab-akibat")
        gx = a.get("garis_x")
        gy = a.get("garis_y")
        if kind == "positioning":
            gx = sum(p[0] for p in pts) / len(pts) if gx is None else float(gx)
            gy = sum(p[1] for p in pts) / len(pts) if gy is None else float(gy)
            quad = {"kanan atas": 0, "kiri atas": 0, "kiri bawah": 0, "kanan bawah": 0}
            for p in pts:
                quad[("kanan" if p[0] >= gx else "kiri") + (" atas" if p[1] >= gy else " bawah")] += 1
            facts.append("Sebaran kuadran: " + ", ".join(f"{k} {v}" for k, v in quad.items()))
        return {"kind": "scatter", "points": pts, "lines": (gx, gy), "xlab": a.get("x"),
                "ylab": y[0] if y else a.get("nilai"), "quadrants": a.get("kuadran")}, facts

    if kind == "cumulative":
        xs = column(table, a.get("x"))
        vals = column(table, y[0] if y else None, True)
        pts = sorted([p for p in _pairs(xs, vals) if p[1] > 0], key=lambda t: -t[1])
        tot = sum(p[1] for p in pts)
        if not pts or not tot:
            raise ChartError("Pareto butuh nilai positif.")
        cum, k80 = 0.0, None
        cums = []
        for i, p in enumerate(pts):
            cum += p[1]
            cums.append(cum / tot * 100)
            if k80 is None and cum / tot >= 0.8:
                k80 = i + 1
        facts.append(f"{k80} dari {len(pts)} {a.get('x')} ({pct(k80 / len(pts) * 100)}) menyumbang ≥80% "
                     f"{y[0]} (tepatnya {pct(cums[k80 - 1])})")
        facts.append(f"Penyumbang terbesar {pts[0][0]}: {pct(pts[0][1] / tot * 100)} dari total")
        return {"kind": "pareto", "x": [p[0] for p in pts][:25], "vals": [p[1] for p in pts][:25],
                "cum": cums[:25]}, facts

    if kind == "rank":
        per, items, vals = column(table, a.get("x")), column(table, a.get("kategori")), column(table, a.get("nilai"), True)
        periods = list(dict.fromkeys(per))
        ranks: dict[str, list] = {}
        for pname in periods:
            rows = sorted([(items[i], vals[i]) for i in range(len(per)) if per[i] == pname and vals[i] is not None],
                          key=lambda t: -t[1])
            for rk, (it, _) in enumerate(rows, 1):
                ranks.setdefault(it, [None] * len(periods))[periods.index(pname)] = rk
        moves = [(it, r[0] - r[-1]) for it, r in ranks.items() if r[0] and r[-1]]
        if moves:
            up = max(moves, key=lambda t: t[1])
            dn = min(moves, key=lambda t: t[1])
            facts.append(f"Naik peringkat terbanyak: {up[0]} ({'+' if up[1] >= 0 else ''}{up[1]} posisi)")
            facts.append(f"Turun peringkat terbanyak: {dn[0]} ({dn[1]} posisi)")
        leader = next((it for it, r in ranks.items() if r[-1] == 1), None)
        if leader:
            facts.append(f"Peringkat 1 di {periods[-1]}: {leader}")
        top = sorted(ranks, key=lambda it: ranks[it][-1] or 99)[:10]
        return {"kind": "rank", "periods": periods, "ranks": {it: ranks[it] for it in top}}, facts

    if kind == "waterfall":
        xs = column(table, a.get("x"))
        if len(y) < 2:
            raise ChartError("Waterfall butuh y = [nilai_awal, nilai_akhir].")
        s0, s1 = column(table, y[0], True), column(table, y[1], True)
        deltas = [(xs[i], (s1[i] or 0) - (s0[i] or 0)) for i in range(len(xs))]
        start, end = sum(v or 0 for v in s0), sum(v or 0 for v in s1)
        deltas.sort(key=lambda t: -abs(t[1]))
        pos = max(deltas, key=lambda t: t[1])
        neg = min(deltas, key=lambda t: t[1])
        facts.append(f"Total {y[0]} {fmt(start)} → {y[1]} {fmt(end)}{u} ({'+' if end >= start else ''}{fmt(end - start)})")
        facts.append(f"Pendorong naik terbesar {pos[0]}: +{fmt(pos[1])}{u}; penekan terbesar {neg[0]}: {fmt(neg[1])}{u}")
        return {"kind": "waterfall", "start": (y[0], start), "end": (y[1], end), "deltas": deltas[:12]}, facts

    if kind == "actual_target":
        xs = column(table, a.get("x"))
        if len(y) < 2:
            raise ChartError("Actual v Target butuh y = [aktual, target].")
        act, tgt = column(table, y[0], True), column(table, y[1], True)
        ach = [(xs[i], act[i] / tgt[i] * 100) for i in range(len(xs)) if act[i] is not None and tgt[i]]
        ta, tt = sum(v or 0 for v in act), sum(v or 0 for v in tgt)
        if tt:
            facts.append(f"Pencapaian total {pct(ta / tt * 100)} ({fmt(ta)} dari target {fmt(tt)}{u})")
        if ach:
            below = [c for c, p in ach if p < 100]
            worst = min(ach, key=lambda t: t[1])
            facts.append(f"{len(below)} dari {len(ach)} di bawah target; terendah {worst[0]} {pct(worst[1])}")
        return {"kind": "target", "x": xs, "act": act, "tgt": tgt}, facts

    if kind == "heatmap":
        cols_, rows_, vals = column(table, a.get("x")), column(table, a.get("kategori")), column(table, a.get("nilai"), True)
        cx, ry = list(dict.fromkeys(cols_)), list(dict.fromkeys(rows_))[:20]
        grid = [[None] * len(cx) for _ in ry]
        for c, r, v in zip(cols_, rows_, vals):
            if r in ry and v is not None:
                grid[ry.index(r)][cx.index(c)] = v
        flat = [(ry[i], cx[j], grid[i][j]) for i in range(len(ry)) for j in range(len(cx)) if grid[i][j] is not None]
        if not flat:
            raise ChartError("Heat map kosong.")
        hi, lo = max(flat, key=lambda t: t[2]), min(flat, key=lambda t: t[2])
        facts.append(f"Tertinggi {hi[0]} × {hi[1]}: {fmt(hi[2])}{u}; terendah {lo[0]} × {lo[1]}: {fmt(lo[2])}{u}")
        return {"kind": "heat", "cols": cx, "rows": ry, "grid": grid, "invert": bool(a.get("kecil_lebih_baik"))}, facts

    if kind == "profit_margin":
        rev, cost = series[0][1], (series[1][1] if len(series) > 1 else None)
        if cost is None:
            raise ChartError("Profit margin butuh y = [pendapatan, biaya].")
        margin = [((r - c) / r * 100) if r and c is not None else None for r, c in zip(rev, cost)]
        pts = [(xs[i], margin[i]) for i in range(len(xs)) if margin[i] is not None]
        if pts:
            facts.append(f"Margin {pts[0][0]} {pct(pts[0][1])} → {pts[-1][0]} {pct(pts[-1][1])}")
        return {"kind": "margin", "x": xs, "rev": rev, "cost": cost, "margin": margin}, facts

    if kind == "unit_economics":
        xs = column(table, a.get("x"))
        ltv, cac = column(table, y[0], True), column(table, y[1] if len(y) > 1 else None, True)
        ratio = [(xs[i], ltv[i] / cac[i]) for i in range(len(xs)) if ltv[i] is not None and cac[i]]
        for c, rr in sorted(ratio, key=lambda t: -t[1])[:3]:
            facts.append(f"{c}: LTV:CAC = {fmt(rr, 1)}x")
        return {"kind": "group", "x": xs, "series": [(y[0], ltv), (y[1], cac)]}, facts

    if kind == "cashflow":
        vals = series[0][1]
        cum, run = [], 0.0
        for v in vals:
            run += v or 0
            cum.append(run)
        neg = sum(1 for v in vals if v is not None and v < 0)
        facts.append(f"Arus kas kumulatif akhir {fmt(cum[-1])}{u}; {neg} periode negatif")
        return {"kind": "cash", "x": xs, "vals": vals, "cum": cum}, facts

    if kind == "roic":
        nopat, cap = series[0][1], (series[1][1] if len(series) > 1 else None)
        if cap is None:
            raise ChartError("ROIC butuh y = [laba_operasi_setelah_pajak, modal_diinvestasikan].")
        roic = [(n / c * 100) if n is not None and c else None for n, c in zip(nopat, cap)]
        pts = [(xs[i], roic[i]) for i in range(len(xs)) if roic[i] is not None]
        if pts:
            facts.append(f"ROIC {pts[0][0]} {pct(pts[0][1])} → {pts[-1][0]} {pct(pts[-1][1])}")
        return {"kind": "line", "x": xs, "series": [("ROIC %", roic)]}, facts

    if kind == "marginal_return":
        out = series[0][1]
        marg = [None] + [(out[i] - out[i - 1]) if out[i] is not None and out[i - 1] is not None else None
                         for i in range(1, len(out))]
        valid = [(xs[i], marg[i]) for i in range(1, len(xs)) if marg[i] is not None]
        if valid:
            peak = max(valid, key=lambda t: t[1])
            facts.append(f"Tambahan hasil terbesar di {peak[0]} (+{fmt(peak[1])}{u}); sesudahnya tambahan hasil mengecil")
        return {"kind": "marginal", "x": xs, "out": out, "marg": marg}, facts

    if kind == "bull_bear":
        act = series[0][1]
        pts = [(i, v) for i, v in enumerate(act) if v is not None]
        if len(pts) < 3:
            raise ChartError("Bull/bear butuh minimal 3 titik aktual.")
        n = len(pts)
        mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx else 0
        horizon = int(a.get("horizon") or 3)
        p_ = float(a.get("skenario_pct") or 10) / 100
        last_i = len(act) - 1
        base = [my + slope * (last_i + k - mx) for k in range(1, horizon + 1)]
        facts.append(f"SKENARIO (bukan data): tren linear {fmt(slope)}{u} per periode; base periode +{horizon}: "
                     f"{fmt(base[-1])}{u}; bull/bear ±{fmt(p_ * 100, 0)}%")
        return {"kind": "bullbear", "x": xs, "act": act, "base": base, "p": p_}, facts

    raise ChartError(f"Jenis {kind} belum didukung.")


# ==========================================================================
# Gambar (PNG bergaya PTPL)
# ==========================================================================
def render(spec: dict, title: str, subtitle: str = "", source: str = "", unit: str = "") -> bytes:  # noqa: C901
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    k = spec["kind"]
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    fig.subplots_adjust(top=0.80, bottom=0.16, left=0.12, right=0.95)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(BORDER)
    ax.tick_params(colors=GRAY, labelsize=8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
    short = lambda s, n=18: (s if len(str(s)) <= n else str(s)[:n - 1] + "…")  # noqa: E731

    if k in ("line", "stack"):
        xs = spec["x"]
        if k == "line":
            for i, (name, vals) in enumerate(spec["series"]):
                ax.plot(range(len(xs)), [v if v is not None else float("nan") for v in vals], marker="o",
                        color=PALETTE[i % 8], lw=2, label=name)
        else:
            bottom = [0.0] * len(xs)
            for i, (name, vals) in enumerate(spec["series"]):
                v = [x or 0 for x in vals]
                ax.bar(range(len(xs)), v, bottom=bottom, color=PALETTE[i % 8], label=name)
                bottom = [b + c for b, c in zip(bottom, v)]
        ax.set_xticks(range(len(xs)), [short(x, 12) for x in xs], rotation=30 if len(xs) > 8 else 0, ha="right" if len(xs) > 8 else "center")
    elif k == "hbar":
        xs, vals = spec["x"][::-1], spec["series"][0][1][::-1]
        ax.barh(range(len(xs)), vals, color=[GOLD if i == len(xs) - 1 else NAVY for i in range(len(xs))])
        ax.set_yticks(range(len(xs)), [short(x, 26) for x in xs])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
        for i, v in enumerate(vals):
            ax.text(v, i, " " + fmt(v), va="center", fontsize=7, color=GRAY)
    elif k == "group":
        xs = spec["x"]
        w = 0.8 / len(spec["series"])
        for i, (name, vals) in enumerate(spec["series"]):
            ax.bar([j + i * w for j in range(len(xs))], [v or 0 for v in vals], w, color=PALETTE[i % 8], label=name)
        ax.set_xticks([j + w / 2 for j in range(len(xs))], [short(x, 12) for x in xs], rotation=30 if len(xs) > 6 else 0,
                      ha="right" if len(xs) > 6 else "center")
    elif k == "mix":
        comps, periods = spec["components"], spec["periods"]
        bottom = [0.0] * len(periods)
        for i, c in enumerate(comps[:8]):
            vals = [p[1][i] for p in periods]
            ax.bar(range(len(periods)), vals, bottom=bottom, color=PALETTE[i % 8], label=short(c, 20), width=0.55)
            for j, v in enumerate(vals):
                if v >= 6:
                    ax.text(j, bottom[j] + v / 2, pct(v, 0), ha="center", va="center", fontsize=7, color="white")
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_xticks(range(len(periods)), [p[0] for p in periods])
        ax.set_ylim(0, 118)
        ax.set_yticks([0, 20, 40, 60, 80, 100])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v, 0)))
    elif k == "hist":
        ax.hist(spec["values"], bins=min(20, max(5, int(len(spec["values"]) ** 0.5))), color=NAVY, edgecolor="white")
        for q, lab in zip(spec["q"], ("P25", "Median", "P75")):
            ax.axvline(q, color=GOLD if lab == "Median" else GRAY, ls="--", lw=1)
            ax.text(q, ax.get_ylim()[1] * 0.95, " " + lab, color=GRAY, fontsize=7)
        ax.set_ylabel("Frekuensi", color=GRAY, fontsize=8)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v, 0)))
    elif k == "box":
        for i, (mn, q1, med, q3, mx, _) in enumerate(spec["stats"]):
            ax.vlines(i, mn, mx, color=GRAY, lw=1)
            ax.add_patch(matplotlib.patches.Rectangle((i - 0.3, q1), 0.6, q3 - q1, color=NAVY, alpha=0.85))
            ax.hlines(med, i - 0.3, i + 0.3, color=GOLD, lw=2)
        ax.set_xticks(range(len(spec["cats"])), [short(c, 14) for c in spec["cats"]], rotation=30, ha="right")
        ax.set_xlim(-0.7, len(spec["cats"]) - 0.3)
    elif k == "scatter":
        pts = spec["points"]
        sizes = [p[3] for p in pts]
        if any(s is not None for s in sizes):
            mx = max(s for s in sizes if s is not None) or 1
            s_ = [30 + 900 * ((s or 0) / mx) for s in sizes]
        else:
            s_ = [45] * len(pts)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=s_, color=NAVY, alpha=0.7, edgecolor="white")
        for p in pts[:25]:
            if p[2]:
                ax.annotate(short(p[2], 16), (p[0], p[1]), fontsize=6.5, color=GRAY, xytext=(4, 3), textcoords="offset points")
        gx, gy = spec["lines"]
        if gx is not None:
            ax.axvline(gx, color=GOLD, ls="--", lw=1)
        if gy is not None:
            ax.axhline(gy, color=GOLD, ls="--", lw=1)
        q = spec.get("quadrants")
        if q and len(q) == 4 and gx is not None and gy is not None:
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            for (tx, ty, ha, va), lab in zip(((x1, y1, "right", "top"), (x0, y1, "left", "top"),
                                               (x0, y0, "left", "bottom"), (x1, y0, "right", "bottom")), q):
                ax.text(tx, ty, lab, ha=ha, va=va, fontsize=8, color=GOLD, fontweight="bold")
        ax.set_xlabel(spec.get("xlab") or "", color=GRAY, fontsize=8)
        ax.set_ylabel(spec.get("ylab") or "", color=GRAY, fontsize=8)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
    elif k == "pareto":
        xs = spec["x"]
        ax.bar(range(len(xs)), spec["vals"], color=NAVY)
        ax2 = ax.twinx()
        ax2.plot(range(len(xs)), spec["cum"], color=GOLD, marker="o", lw=2)
        ax2.axhline(80, color=RED, ls="--", lw=1)
        ax2.set_ylim(0, 105)
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v, 0)))
        ax2.tick_params(colors=GRAY, labelsize=8)
        for s in ("top",):
            ax2.spines[s].set_visible(False)
        ax.set_xticks(range(len(xs)), [short(x, 12) for x in xs], rotation=40, ha="right")
    elif k == "rank":
        periods = spec["periods"]
        for i, (it, r) in enumerate(spec["ranks"].items()):
            ax.plot(range(len(periods)), [v if v else float("nan") for v in r], marker="o", lw=2, color=PALETTE[i % 8])
            last = next((v for v in reversed(r) if v), None)
            if last:
                ax.text(len(periods) - 1 + 0.08, last, short(it, 20), va="center", fontsize=7, color=PALETTE[i % 8])
        ax.invert_yaxis()
        ax.set_xticks(range(len(periods)), periods)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"#{int(v)}" if v >= 1 else ""))
        ax.set_xlim(-0.2, len(periods) - 0.2 + 1)
    elif k == "waterfall":
        labels = [spec["start"][0]] + [d[0] for d in spec["deltas"]] + [spec["end"][0]]
        run = spec["start"][1]
        levels = [run]
        ax.bar(0, run, color=NAVY)
        ax.text(0, run, fmt(run), ha="center", va="bottom", fontsize=7, color=GRAY)
        for i, (_, d) in enumerate(spec["deltas"], 1):
            ax.bar(i, d, bottom=run if d >= 0 else run + d, color=GREEN if d >= 0 else RED)
            ax.text(i, max(run, run + d), ("+" if d >= 0 else "") + fmt(d), ha="center", va="bottom", fontsize=7,
                    color=GREEN if d >= 0 else RED)
            run += d
            levels.append(run)
        end = spec["end"][1]
        ax.bar(len(labels) - 1, end, color=NAVY)
        ax.text(len(labels) - 1, end, fmt(end), ha="center", va="bottom", fontsize=7, color=GRAY)
        lo, hi = min(levels + [end]), max(levels + [end])
        pad = max((hi - lo) * 0.35, abs(hi) * 0.01, 1e-9)
        if lo - pad > 0:
            ax.set_ylim(lo - pad, hi + pad)          # fokus ke perubahan (sumbu tidak dari 0)
        ax.set_xticks(range(len(labels)), [short(l, 12) for l in labels], rotation=35, ha="right")
    elif k == "target":
        xs = spec["x"]
        ax.bar(range(len(xs)), [v or 0 for v in spec["act"]], color=NAVY, label="Aktual")
        ax.scatter(range(len(xs)), [v if v is not None else float("nan") for v in spec["tgt"]], marker="_", s=600,
                   color=GOLD, lw=3, label="Target", zorder=3)
        ax.set_xticks(range(len(xs)), [short(x, 12) for x in xs], rotation=30 if len(xs) > 6 else 0,
                      ha="right" if len(xs) > 6 else "center")
    elif k == "heat":
        import numpy as np

        g = np.array([[float("nan") if v is None else v for v in row] for row in spec["grid"]])
        cmap = matplotlib.colormaps["RdYlGn_r" if spec.get("invert") else "RdYlGn"]
        ax.imshow(g, cmap=cmap, aspect="auto")
        for i in range(g.shape[0]):
            for j in range(g.shape[1]):
                if not math.isnan(g[i, j]):
                    ax.text(j, i, fmt(g[i, j]), ha="center", va="center", fontsize=7)
        ax.set_xticks(range(len(spec["cols"])), [short(c, 12) for c in spec["cols"]], rotation=30, ha="right")
        ax.set_yticks(range(len(spec["rows"])), [short(r, 22) for r in spec["rows"]])
    elif k == "margin":
        xs = spec["x"]
        cost = [c or 0 for c in spec["cost"]]
        prof = [max((r or 0) - c, 0) for r, c in zip(spec["rev"], cost)]
        ax.bar(range(len(xs)), cost, color=NAVY, label="Biaya")
        ax.bar(range(len(xs)), prof, bottom=cost, color=GOLD, label="Laba")
        for i, m in enumerate(spec["margin"]):
            if m is not None:
                ax.text(i, (spec["rev"][i] or 0), pct(m), ha="center", va="bottom", fontsize=8, color=RED)
        ax.set_xticks(range(len(xs)), xs)
    elif k == "cash":
        xs = spec["x"]
        ax.bar(range(len(xs)), [v or 0 for v in spec["vals"]], color=[GREEN if (v or 0) >= 0 else RED for v in spec["vals"]])
        ax.plot(range(len(xs)), spec["cum"], color=GOLD, marker="o", lw=2, label="Kumulatif")
        ax.set_xticks(range(len(xs)), xs)
    elif k == "marginal":
        xs = spec["x"]
        ax.plot(range(len(xs)), [v if v is not None else float("nan") for v in spec["out"]], color=NAVY, marker="o",
                lw=2, label="Output")
        ax2 = ax.twinx()
        ax2.bar(range(len(xs)), [v or 0 for v in spec["marg"]], color=GOLD, alpha=0.5, label="Tambahan output")
        ax2.tick_params(colors=GRAY, labelsize=8)
        ax.set_xticks(range(len(xs)), xs)
    elif k == "bullbear":
        xs, act = list(spec["x"]), spec["act"]
        n = len(act)
        fut = [f"+{i}" for i in range(1, len(spec["base"]) + 1)]
        ax.plot(range(n), [v if v is not None else float("nan") for v in act], color=NAVY, lw=2.5, label="Aktual")
        rng = range(n - 1, n + len(fut))
        last = next(v for v in reversed(act) if v is not None)
        base = [last] + spec["base"]
        for lab, f, col in (("Bull", 1 + spec["p"], GREEN), ("Base", 1, GRAY), ("Bear", 1 - spec["p"], RED)):
            ax.plot(rng, [base[0]] + [b * f for b in base[1:]], ls="--", color=col, lw=1.8, label=lab)
        ax.set_xticks(range(n + len(fut)), [short(x, 10) for x in xs] + fut, rotation=30, ha="right")
    if k in ("line", "stack", "group", "mix", "target", "margin", "cash") or (k == "marginal"):
        ax.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.02), ncol=4)

    fig.text(0.02, 0.955, title[:110], fontsize=12.5, fontweight="bold", color=NAVY, va="top")
    if subtitle:
        fig.text(0.02, 0.885, subtitle[:150], fontsize=9, color=GOLD, va="top")
    foot = " · ".join(x for x in ((f"Satuan: {unit}" if unit else ""), (f"Sumber: {source}" if source else ""),
                                  "PT Pertamina Lubricants") if x)
    fig.text(0.02, 0.02, foot[:180], fontsize=7, color=GRAY)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
