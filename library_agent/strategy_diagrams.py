"""Diagram kerangka strategi (Strategist Toolkit) bergaya PTPL + perhitungan keputusan oleh kode.

jenis            isi (dict)
panel            {"bagian": [{"judul", "teks"}]}                       SCQ, HTDQ, Outcome, 5W+H, Venn, Hub n' Spoke
driver_tree      {"akar", "cabang": [{"label", "nilai"?, "catatan"?, "anak": [...]}]}      Driver Tree, Bucketing
hypothesis_tree  {"akar", "cabang": [{"label", "status": terbukti|tidak|belum, "catatan"?}]}
five_whys        {"masalah", "langkah": [{"mengapa", "alasan", "bukti"?}], "akar_masalah"}
decision_flow    {"masalah", "langkah": [{"pertanyaan", "ya"}], "akhir"}                    Yes/No flowchart
table            {"kolom": [...], "baris": [[...]]}                     Tabular, Bezos, Decision Grid, Continuum
heat_table       sama dengan table; sel TINGGI/SEDANG/RENDAH/BAIK/BURUK/HIGH/MED/LOW diwarnai  Heat map, Capability
one_pager        {"lapisan": [{"judul", "item": [...]}]}                One Pager, Canvas, GTM Stack
columns          {"kolom": [{"judul", "poin": [...]}]}                  Tri-Column
chevron          {"tahap": [{"nama", "poin": [...]}]}                   Chevron, Horizon, Timeline, Journey, SPADE, Zero-to-One
gantt            {"periode": [...], "baris": [{"stream", "aktivitas", "mulai", "selesai", "pemimpin"?}]}
matrix_2x2       {"sumbu_x", "sumbu_y", "kuadran": [kanan atas, kiri atas, kiri bawah, kanan bawah],
                  "item": [{"label", "kuadran": 1-4}]}                  2x2, Eisenhower, ABCD
matrix_3x3       {"sumbu_x", "sumbu_y", "item": [{"label", "x": 1-3, "y": 1-3}]}
from_to          {"dari": [...], "ke": [...], "langkah": [...]}
pyramid          {"puncak", "argumen": [{"judul", "bukti": [...]}]}     Minto, Pyramid
decision_tree    {"keputusan", "satuan"?, "opsi": [{"nama", "hasil": [{"label", "peluang", "nilai"}]}]}  -> nilai harapan
pros_cons        {"opsi": [{"nama", "pro": [...], "kontra": [...]}], "rekomendasi"?}
evaluation       {"kriteria": [{"nama", "bobot"}], "opsi": [{"nama", "skor": [...]}], "skala"?}  -> skor berbobot
"""
from __future__ import annotations

import io
import textwrap
from typing import Any

from .insight_charts import BORDER, GOLD, GRAY, GREEN, NAVY, RED, fmt

KINDS = ("panel", "driver_tree", "hypothesis_tree", "five_whys", "decision_flow", "table", "heat_table", "one_pager",
         "columns", "chevron", "gantt", "matrix_2x2", "matrix_3x3", "from_to", "pyramid", "decision_tree", "pros_cons",
         "evaluation")
ALIASES = {"scq": "panel", "htdq": "panel", "outcome": "panel", "five_w_h": "panel", "venn": "panel",
           "hub_spoke": "panel", "bucketing": "driver_tree", "hypothesis": "hypothesis_tree", "yes_no": "decision_flow",
           "tabular": "table", "bezos": "table", "decision_grid": "table", "continuum": "table",
           "heat_map": "heat_table", "capability_map": "heat_table", "canvas": "one_pager", "gtm_stack": "one_pager",
           "tri_column": "columns", "horizon": "chevron", "timeline": "chevron", "journey": "chevron",
           "spade": "chevron", "zero_to_one": "chevron", "circular": "chevron", "execution_plan": "gantt",
           "comms_deploy": "gantt", "capability_drop": "gantt", "matrix": "matrix_2x2", "eisenhower": "matrix_2x2",
           "abcd": "matrix_2x2", "three_by_three": "matrix_3x3", "minto": "pyramid", "evaluation_matrix": "evaluation"}
LIGHT, LIGHT_GOLD = "#EEF2F7", "#FBF3E2"
RATING = {"tinggi": GREEN, "high": GREEN, "baik": GREEN, "kuat": GREEN, "sedang": GOLD, "med": GOLD, "medium": GOLD,
          "cukup": GOLD, "rendah": RED, "low": RED, "buruk": RED, "lemah": RED}


class DiagramError(ValueError):
    pass


def _wrap(text: Any, width: int) -> str:
    return "\n".join(textwrap.wrap(str(text or ""), width)) or ""


def _box(ax, x, y, w, h, text, fc=LIGHT, tc=NAVY, size=8, bold=False, wrap=24, ec=BORDER):
    from matplotlib.patches import FancyBboxPatch

    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.01", fc=fc, ec=ec, lw=0.8))
    ax.text(x + w / 2, y + h / 2, _wrap(text, wrap), ha="center", va="center", fontsize=size, color=tc,
            fontweight="bold" if bold else "normal")


def _line(ax, x0, y0, x1, y1, color=GRAY, arrow=False):
    if arrow:
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->", color=color, lw=1))
    else:
        ax.plot([x0, x1], [y0, y1], color=color, lw=1)


def _need(isi: dict, *keys) -> None:
    missing = [k for k in keys if not isi.get(k)]
    if missing:
        raise DiagramError(f"Isi diagram kurang: {', '.join(missing)}.")


def _num(v) -> float:
    from .insight_charts import num

    n = num(v)
    if n is None:
        raise DiagramError(f"Nilai '{v}' bukan angka.")
    return n


# ==========================================================================
# Perhitungan keputusan (kode, bukan model)
# ==========================================================================
def decision_values(isi: dict) -> tuple[list[tuple[str, float]], list[str]]:
    _need(isi, "opsi")
    out, notes = [], []
    for o in isi["opsi"]:
        hasil = o.get("hasil") or []
        if not hasil:
            raise DiagramError(f"Opsi '{o.get('nama')}' belum punya hasil (peluang & nilai).")
        ps = [_num(h.get("peluang")) for h in hasil]
        if sum(ps) > 1.5:                                       # ditulis dalam persen
            ps = [p / 100 for p in ps]
        if abs(sum(ps) - 1) > 0.02:
            notes.append(f"Peluang opsi '{o.get('nama')}' berjumlah {fmt(sum(ps) * 100, 0)}% (seharusnya 100%)")
        ev = sum(p * _num(h.get("nilai")) for p, h in zip(ps, hasil))
        out.append((str(o.get("nama")), ev))
    return out, notes


def weighted_scores(isi: dict) -> list[tuple[str, float, list[float]]]:
    _need(isi, "kriteria", "opsi")
    w = [_num(k.get("bobot", 1)) for k in isi["kriteria"]]
    tw = sum(w) or 1
    out = []
    for o in isi["opsi"]:
        s = [_num(v) for v in o.get("skor") or []]
        if len(s) != len(w):
            raise DiagramError(f"Opsi '{o.get('nama')}' punya {len(s)} skor; kriteria ada {len(w)}.")
        out.append((str(o.get("nama")), sum(a * b for a, b in zip(s, w)) / tw, s))
    return sorted(out, key=lambda t: -t[1])


# ==========================================================================
# Gambar
# ==========================================================================
def render(kind: str, title: str, isi: dict, subtitle: str = "") -> tuple[bytes, list[str]]:  # noqa: C901
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    isi = dict(isi or {})
    if kind == "eisenhower":
        isi.setdefault("kuadran", ["DO — kerjakan sekarang", "DELEGATE — serahkan", "DELETE — hapus",
                                   "SCHEDULE — jadwalkan"])
        isi.setdefault("sumbu_x", "Penting")
        isi.setdefault("sumbu_y", "Mendesak")
    elif kind == "abcd":
        isi.setdefault("kuadran", ["CROSS-CUTTING — sering, lintas fungsi", "BIG-BET — jarang, dampak besar",
                                   "AD HOC — jarang, lingkup sempit", "DELEGATED — sering, lingkup sempit"])
        isi.setdefault("sumbu_x", "Frekuensi keputusan")
        isi.setdefault("sumbu_y", "Cakupan dampak")
    kind = ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise DiagramError(f"Jenis diagram '{kind}' tidak dikenal. Pilihan: {', '.join(KINDS)}")
    facts: list[str] = []
    fig = plt.figure(figsize=(11, 6.2), dpi=150)
    ax = fig.add_axes([0.02, 0.06, 0.96, 0.78])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    if kind == "panel":
        _need(isi, "bagian")
        parts = isi["bagian"][:8]
        cols = 2 if len(parts) > 3 else len(parts)
        rows = -(-len(parts) // cols)
        w, h = 0.96 / cols, 0.96 / rows
        for i, p in enumerate(parts):
            r, c = divmod(i, cols)
            x, y = 0.02 + c * w, 0.98 - (r + 1) * h
            _box(ax, x, y + h - 0.09, w - 0.02, 0.08, p.get("judul", ""), fc=NAVY, tc="white", bold=True, wrap=40)
            _box(ax, x, y + 0.01, w - 0.02, h - 0.11, p.get("teks", ""), fc=LIGHT, size=8.5, wrap=int(70 * w))

    elif kind in ("driver_tree", "hypothesis_tree"):
        _need(isi, "akar", "cabang")
        leaves = []

        def collect(nodes, depth):
            for n in nodes:
                if n.get("anak"):
                    collect(n["anak"], depth + 1)
                else:
                    leaves.append(n)
        collect(isi["cabang"], 1)

        def depth_of(nodes):
            return 1 + max((depth_of(n["anak"]) for n in nodes if n.get("anak")), default=0)
        levels = depth_of(isi["cabang"]) + 1
        colw = 0.98 / (levels + (1 if kind == "hypothesis_tree" else 0))   # kolom ekstra untuk catatan/bukti
        bh = min(0.11, 0.9 / max(len(leaves), 1))
        counter = [0]
        status_col = {"terbukti": GREEN, "tidak": RED, "tidak terbukti": RED, "belum": GOLD}

        def place(nodes, depth):
            ys = []
            for n in nodes:
                if n.get("anak"):
                    y = sum(place(n["anak"], depth + 1)) / len(n["anak"])
                else:
                    y = 0.95 - (counter[0] + 0.5) * (0.9 / max(len(leaves), 1))
                    counter[0] += 1
                n["_y"] = y
                ys.append(y)
                label = n.get("label", "")
                if n.get("nilai") not in (None, ""):
                    label += f"\n{n['nilai']}"
                st = str(n.get("status", "")).lower()
                fc = status_col.get(st, LIGHT)
                tc = "white" if st in status_col else NAVY
                if st:
                    label += f"\n[{st.upper()}]"
                _box(ax, 0.01 + depth * colw, y - bh / 2, colw - 0.03, bh, label, fc=fc, tc=tc, size=7.5,
                     wrap=int(110 * colw))
                if n.get("anak"):
                    for ch in n["anak"]:
                        _line(ax, 0.01 + depth * colw + colw - 0.03, y, 0.01 + (depth + 1) * colw, ch["_y"])
                if kind == "hypothesis_tree" and n.get("catatan"):
                    _box(ax, 0.01 + levels * colw, y - bh / 2, colw - 0.01, bh, n["catatan"], fc="white", tc=GRAY,
                         size=7, wrap=int(110 * colw))
                    _line(ax, 0.01 + depth * colw + colw - 0.03, y, 0.01 + levels * colw, y, color=BORDER)
                    facts.append(f"{n.get('label')}: {st.upper() or '-'} — {n['catatan']}")
            return ys
        ys = place(isi["cabang"], 1)
        ry = sum(ys) / len(ys)
        _box(ax, 0.01, ry - 0.07, colw - 0.03, 0.14, isi["akar"], fc=NAVY, tc="white", bold=True, wrap=int(110 * colw))
        for n in isi["cabang"]:
            _line(ax, 0.01 + colw - 0.03, ry, 0.01 + colw, n["_y"])

    elif kind == "five_whys":
        _need(isi, "masalah", "langkah")
        steps = isi["langkah"][:6]
        n = len(steps) + 2
        h = 0.9 / n
        _box(ax, 0.02, 0.95 - h, 0.96, h - 0.02, "MASALAH: " + str(isi["masalah"]), fc=NAVY, tc="white", bold=True, wrap=120)
        for i, s in enumerate(steps, 1):
            y = 0.95 - (i + 1) * h
            _box(ax, 0.02, y, 0.08, h - 0.02, f"MENGAPA {i}", fc=GOLD, tc="white", bold=True, size=7, wrap=10)
            _box(ax, 0.11, y, 0.40, h - 0.02, s.get("mengapa", ""), size=7.5, wrap=60)
            _box(ax, 0.52, y, 0.46, h - 0.02, (s.get("alasan", "") + (f"  [bukti: {s['bukti']}]" if s.get("bukti") else
                                                                       "  [hipotesis]")), size=7.5, wrap=70)
        _box(ax, 0.02, 0.95 - (len(steps) + 2) * h, 0.96, h - 0.02, "AKAR MASALAH: " + str(isi.get("akar_masalah", "")),
             fc=RED, tc="white", bold=True, wrap=120)
        facts.append(f"Akar masalah: {isi.get('akar_masalah', '')}")

    elif kind == "decision_flow":
        _need(isi, "masalah", "langkah")
        steps = isi["langkah"][:6]
        h = 0.9 / (len(steps) + 2)
        _box(ax, 0.30, 0.95 - h, 0.40, h - 0.02, isi["masalah"], fc=NAVY, tc="white", bold=True, wrap=50)
        for i, s in enumerate(steps, 1):
            y = 0.95 - (i + 1) * h
            _box(ax, 0.30, y, 0.40, h - 0.02, s.get("pertanyaan", "") + " ?", size=7.5, wrap=55)
            _box(ax, 0.76, y, 0.22, h - 0.02, s.get("ya", ""), fc=LIGHT_GOLD, size=7.5, wrap=30)
            ax.text(0.715, y + h / 2, "YA →", fontsize=7, color=GREEN, va="center")
            _line(ax, 0.5, y + h, 0.5, y + h - 0.02, arrow=True)
            ax.text(0.505, y - 0.012, "tidak", fontsize=6.5, color=RED)
        if isi.get("akhir"):
            _box(ax, 0.30, 0.95 - (len(steps) + 2) * h, 0.40, h - 0.02, isi["akhir"], fc=LIGHT_GOLD, size=7.5, wrap=55)

    elif kind in ("table", "heat_table", "evaluation", "pros_cons"):
        if kind == "evaluation":
            ranked = weighted_scores(isi)
            crit = isi["kriteria"]
            cols = ["Opsi"] + [f"{k.get('nama')} (bobot {fmt(_num(k.get('bobot', 1)), 0)})" for k in crit] + ["Skor berbobot"]
            rows = [[name] + [fmt(v, 1) for v in s] + [fmt(score, 2)] for name, score, s in ranked]
            facts.append(f"Rekomendasi: {ranked[0][0]} (skor berbobot {fmt(ranked[0][1], 2)} dari skala "
                         f"{fmt(_num(isi.get('skala', 5)), 0)})")
            facts += [f"Peringkat {i}: {n} {fmt(s, 2)}" for i, (n, s, _) in enumerate(ranked, 1)]
        elif kind == "pros_cons":
            _need(isi, "opsi")
            cols = ["Opsi", "Kelebihan", "Kekurangan"]
            rows = [[o.get("nama"), "\n".join("+ " + p for p in o.get("pro", [])), "\n".join("− " + c for c in o.get("kontra", []))]
                    for o in isi["opsi"]]
            if isi.get("rekomendasi"):
                facts.append(f"Rekomendasi: {isi['rekomendasi']}")
        else:
            _need(isi, "kolom", "baris")
            cols, rows = isi["kolom"], isi["baris"]
        rows = rows[:14]
        nc = len(cols)
        cw = 0.96 / nc
        rh = min(0.09, 0.88 / (len(rows) + 1))
        if kind == "pros_cons":
            rh = min(0.2, 0.88 / (len(rows) + 1))
        for j, c in enumerate(cols):
            _box(ax, 0.02 + j * cw, 0.97 - rh, cw - 0.005, rh - 0.005, c, fc=NAVY, tc="white", bold=True, size=7.5,
                 wrap=int(130 * cw))
        for i, r in enumerate(rows, 1):
            for j in range(nc):
                v = r[j] if j < len(r) else ""
                fc, tc = (LIGHT if i % 2 else "white"), NAVY
                if kind == "heat_table" and str(v).strip().lower() in RATING:
                    fc, tc = RATING[str(v).strip().lower()], "white"
                if kind == "evaluation" and i == 1:
                    fc = LIGHT_GOLD
                _box(ax, 0.02 + j * cw, 0.97 - (i + 1) * rh, cw - 0.005, rh - 0.005, v, fc=fc, tc=tc, size=7,
                     wrap=int(140 * cw))

    elif kind == "one_pager":
        _need(isi, "lapisan")
        layers = isi["lapisan"][:4]
        h = 0.96 / len(layers)
        for i, lay in enumerate(layers):
            y = 0.98 - (i + 1) * h
            _box(ax, 0.01, y + 0.01, 0.16, h - 0.02, lay.get("judul", ""), fc=NAVY, tc="white", bold=True, wrap=18)
            items = lay.get("item") or []
            w = 0.81 / max(len(items), 1)
            for j, it in enumerate(items[:6]):
                _box(ax, 0.18 + j * w, y + 0.01, w - 0.01, h - 0.02, it, fc=LIGHT if i % 2 == 0 else LIGHT_GOLD,
                     size=7.5, wrap=int(120 * w))

    elif kind == "columns":
        _need(isi, "kolom")
        cols = isi["kolom"][:4]
        w = 0.96 / len(cols)
        for j, c in enumerate(cols):
            _box(ax, 0.02 + j * w, 0.86, w - 0.02, 0.12, c.get("judul", ""), fc=NAVY, tc="white", bold=True,
                 wrap=int(110 * w))
            _box(ax, 0.02 + j * w, 0.02, w - 0.02, 0.82, "\n\n".join("• " + p for p in c.get("poin", [])), fc=LIGHT,
                 size=8, wrap=int(120 * w))

    elif kind == "chevron":
        _need(isi, "tahap")
        steps = isi["tahap"][:6]
        w = 0.98 / len(steps)
        from matplotlib.patches import Polygon

        for j, s in enumerate(steps):
            x = 0.01 + j * w
            ax.add_patch(Polygon([(x, 0.80), (x + w - 0.03, 0.80), (x + w, 0.89), (x + w - 0.03, 0.98), (x, 0.98),
                                  (x + (0.03 if j else 0), 0.89)], closed=True, fc=NAVY if j % 2 == 0 else GOLD, ec="white"))
            ax.text(x + w / 2, 0.89, _wrap(s.get("nama", ""), int(90 * w)), ha="center", va="center", color="white",
                    fontsize=8, fontweight="bold")
            _box(ax, x + 0.005, 0.02, w - 0.02, 0.75, "\n\n".join("• " + p for p in s.get("poin", [])), size=7.5,
                 wrap=int(120 * w))

    elif kind == "gantt":
        _need(isi, "periode", "baris")
        per = [str(p) for p in isi["periode"]]
        rows = isi["baris"][:12]
        lw = 0.26
        cw = (0.98 - lw) / len(per)
        rh = min(0.09, 0.85 / (len(rows) + 1))
        for j, p in enumerate(per):
            _box(ax, 0.01 + lw + j * cw, 0.98 - rh, cw - 0.004, rh - 0.005, p, fc=NAVY, tc="white", bold=True, size=7.5)
        for i, r in enumerate(rows, 1):
            y = 0.98 - (i + 1) * rh
            lab = f"{r.get('stream', '')}" + (f" · {r['pemimpin']}" if r.get("pemimpin") else "")
            _box(ax, 0.01, y, lw - 0.01, rh - 0.005, lab, size=7, wrap=40)
            try:
                a, b = per.index(str(r.get("mulai"))), per.index(str(r.get("selesai", r.get("mulai"))))
            except ValueError as exc:
                raise DiagramError(f"Periode '{r.get('mulai')}'/'{r.get('selesai')}' tidak ada di daftar periode.") from exc
            _box(ax, 0.01 + lw + a * cw, y + rh * 0.12, (b - a + 1) * cw - 0.006, rh * 0.76, r.get("aktivitas", ""),
                 fc=GOLD if i % 2 else NAVY, tc="white", size=7, wrap=int(140 * (b - a + 1) * cw))

    elif kind in ("matrix_2x2", "matrix_3x3"):
        n = 2 if kind == "matrix_2x2" else 3
        quads = isi.get("kuadran") or [""] * 4
        cell = 0.84 / n
        x0, y0 = 0.12, 0.08
        for i in range(n):
            for j in range(n):
                ax.add_patch(matplotlib.patches.Rectangle((x0 + i * cell, y0 + j * cell), cell, cell, fc=LIGHT if (i + j) % 2 else
                                                          "white", ec=BORDER))
        if n == 2:
            pos = {1: (1, 1), 2: (0, 1), 3: (0, 0), 4: (1, 0)}
            for q, (i, j) in pos.items():
                ax.text(x0 + i * cell + cell / 2, y0 + j * cell + cell - 0.03, quads[q - 1] if q - 1 < len(quads) else "",
                        ha="center", va="top", fontsize=9, color=GOLD, fontweight="bold")
            groups: dict[tuple, list] = {}
            for it in isi.get("item", []):
                groups.setdefault(pos.get(int(it.get("kuadran", 1)), (1, 1)), []).append(it.get("label", ""))
        else:
            groups = {}
            for it in isi.get("item", []):
                groups.setdefault((int(it.get("x", 1)) - 1, int(it.get("y", 1)) - 1), []).append(it.get("label", ""))
        for (i, j), labels in groups.items():
            ax.text(x0 + i * cell + cell / 2, y0 + j * cell + cell / 2 - 0.02, _wrap(" · ".join(labels), 38),
                    ha="center", va="center", fontsize=8, color=NAVY)
            facts.append(f"{(quads[[(1, 1), (0, 1), (0, 0), (1, 0)].index((i, j))] if n == 2 and len(quads) == 4 else f'sel {i + 1},{j + 1}')}: {', '.join(labels)}")
        ax.text(x0 + 0.42, 0.02, f"{isi.get('sumbu_x', '')}  →", ha="center", fontsize=8.5, color=GRAY)
        ax.text(0.05, y0 + 0.42, f"{isi.get('sumbu_y', '')}  →", rotation=90, va="center", fontsize=8.5, color=GRAY)

    elif kind == "from_to":
        _need(isi, "dari", "ke")
        _box(ax, 0.02, 0.88, 0.38, 0.09, "SAAT INI", fc=GRAY, tc="white", bold=True)
        _box(ax, 0.60, 0.88, 0.38, 0.09, "TARGET", fc=NAVY, tc="white", bold=True)
        _box(ax, 0.02, 0.05, 0.38, 0.81, "\n\n".join("• " + x for x in isi["dari"]), size=8.5, wrap=48)
        _box(ax, 0.60, 0.05, 0.38, 0.81, "\n\n".join("• " + x for x in isi["ke"]), fc=LIGHT_GOLD, size=8.5, wrap=48)
        steps = isi.get("langkah") or []
        for i, s in enumerate(steps[:5]):
            y = 0.80 - i * 0.16
            _line(ax, 0.41, y, 0.59, y, color=GOLD, arrow=True)
            ax.text(0.5, y + 0.015, _wrap(s, 26), ha="center", va="bottom", fontsize=7, color=NAVY)

    elif kind == "pyramid":
        _need(isi, "puncak")
        args = isi.get("argumen") or []
        _box(ax, 0.30, 0.80, 0.40, 0.16, isi["puncak"], fc=NAVY, tc="white", bold=True, size=9, wrap=55)
        if args:
            w = 0.96 / len(args)
            for j, a in enumerate(args[:4]):
                x = 0.02 + j * w
                _line(ax, 0.5, 0.80, x + w / 2, 0.70)
                _box(ax, x, 0.56, w - 0.02, 0.14, a.get("judul", ""), fc=GOLD, tc="white", bold=True, wrap=int(110 * w))
                _box(ax, x, 0.02, w - 0.02, 0.52, "\n\n".join("• " + b for b in a.get("bukti", [])), size=7.5,
                     wrap=int(120 * w))

    elif kind == "decision_tree":
        evs, notes = decision_values(isi)
        unit = isi.get("satuan", "")
        best = max(evs, key=lambda t: t[1])
        facts.append(f"Nilai harapan tertinggi: {best[0]} = {fmt(best[1])} {unit}".strip())
        facts += [f"{n}: nilai harapan {fmt(v)} {unit}".strip() for n, v in evs]
        facts += notes
        opts = isi["opsi"][:4]
        _box(ax, 0.01, 0.42, 0.16, 0.16, isi.get("keputusan", "Keputusan"), fc=NAVY, tc="white", bold=True, wrap=18)
        oh = 0.96 / len(opts)
        for i, (o, (_, ev)) in enumerate(zip(opts, evs)):
            oy = 0.98 - (i + 1) * oh + oh / 2
            _line(ax, 0.17, 0.5, 0.24, oy)
            _box(ax, 0.24, oy - 0.05, 0.20, 0.10, f"{o.get('nama')}\nEV {fmt(ev)} {unit}".strip(),
                 fc=LIGHT_GOLD if o.get("nama") == best[0] else LIGHT, size=7.5, wrap=26)
            hs = o.get("hasil", [])[:4]
            hh = oh / max(len(hs), 1)
            for k, h in enumerate(hs):
                hy = oy + oh / 2 - (k + 0.5) * hh
                _line(ax, 0.44, oy, 0.50, hy)
                p = _num(h.get("peluang"))
                ptxt = fmt(p if p > 1.5 else p * 100, 0) + "%"
                _box(ax, 0.50, hy - hh * 0.4, 0.48, hh * 0.8, f"{h.get('label')} · peluang {ptxt} · nilai {fmt(_num(h.get('nilai')))}",
                     size=7, wrap=70)
    else:
        raise DiagramError(f"Jenis {kind} belum didukung.")

    fig.text(0.02, 0.965, str(title)[:110], fontsize=13, fontweight="bold", color=NAVY, va="top")
    sub = subtitle or (facts[0] if facts else "")
    if sub:
        fig.text(0.02, 0.905, str(sub)[:160], fontsize=9, color=GOLD, va="top")
    fig.text(0.02, 0.015, "Kerangka: Strategist Toolkit · PT Pertamina Lubricants", fontsize=7, color=GRAY)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue(), facts
