"""Tahap B: perencana storyboard otomatis (Claude) + pemeriksa angka + cadangan deterministik.

Alur `make_report` (TIDAK PERNAH melempar error, SELALU menghasilkan file):
1. Claude menyusun storyboard (JSON komponen) dari seluruh hasil analisis di chat — user tidak perlu menyebut isi.
2. Kode memeriksa: angka di storyboard harus ada di data (tidak mengarang / tidak membulatkan), angka kunci hasil
   analitik harus muncul, setiap halaman punya visual, judul berupa kesimpulan.
3. Bila ada masalah dan waktu cukup: SATU putaran revisi oleh Claude.
4. Jaring terakhir (kode): angka kunci yang masih belum ada -> halaman lampiran "angka kunci"; angka yang tidak
   ditemukan di data -> halaman catatan pemeriksa. Planner gagal / melewati batas waktu -> storyboard cadangan
   dibangun kode dari tabel data (tetap ber-chart).
"""
from __future__ import annotations

import bisect
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import theme as T
from .build import build_deck
from .quality import coverage, review

logger = logging.getLogger(__name__)

MAX_DATA_CHARS = 110_000
RENDER_RESERVE = 30.0       # detik yang disisihkan untuk render 3 format + simpan
MIN_REVISE = 45.0           # revisi hanya bila sisa waktu minimal sebesar ini
MAX_KEY = 120               # angka kunci maksimal yang diwajibkan
DIFF_BASE = 300             # banyak angka data yang dipakai untuk menghitung selisih/perubahan yang sah
_TOKEN = re.compile(r"(?<![\w.,/−–-])[-−–+]?\d[\d.,]*")      # bukan bagian kode (10W-40, SR7, 2/4)

COMPONENT_GUIDE = r"""
KOMPONEN YANG TERSEDIA (pilih yang paling cocok dengan isi; setiap halaman isi WAJIB punya visual):
- "ringkasan": ringkasan eksekutif per segmen/merek. {"kolom":[{"nama","sub","baris":[{"label":"Posisi","teks"},
  {"label":"Penyebab","teks"},{"label":"Keputusan","teks"}]}], "benang_merah":"kalimat temuan lintas segmen"}
- "kartu": 2–4 angka besar. {"kartu":[{"angka":"21,0","label","delta":"−1,7","tone":"pos|neg|warn","teks"}]}
- "papan_skor": peringkat (bar horizontal), 1–3 panel. {"panel":[{"judul_panel","kategori":[...],"nilai":[...],
  "sorot":["merek PTPL"],"sorot2":["merek Pertamina lain"],"satuan":"%","insight":{"judul":"#1","teks"},"tone"}]}
- "perbandingan": kolom berkelompok (mis. Q2 vs Q3), 1–3 panel. {"panel":[{"judul_panel","kategori":[...],
  "seri":[{"nama":"Q2","nilai":[...],"warna":"A3ADBA"},{"nama":"Q3","nilai":[...]}],"satuan","insight"}]}
- "tren": garis waktu, 1–3 panel. {"panel":[{"judul_panel","kategori":["Jan","Feb",...],"seri":[{"nama","nilai"}],"insight"}]}
- "waterfall": dekomposisi (awal -> faktor -> akhir). {"panel":[{"judul_panel","langkah":[{"label","nilai","total":true},
  {"label","nilai"},{"label","nilai","total":true}],"insight","tone"}]}
- "funnel": corong tahap, 1 atau 2 seri per panel. {"panel":[{"judul_panel","tahap":[...],"seri":[{"nama","nilai":[...],
  "delta":[...],"konversi":["66%",...]}],"satuan":"%","insight"}]}  ("konversi" = % konversi antar tahap DARI SUMBER
  bila sumber menyebutnya; kosongkan bila tidak ada — kode menghitungnya)
- "heatmap": matriks nilai berwarna. {"kolom":[...],"label_baris","baris":[{"label","nilai":[...]}],"satuan",
  "poin":[{"judul","teks"}]}
- "tabel": tabel data (otomatis berlanjut ke halaman berikut bila panjang). {"kolom":[...],"baris":[[...]],
  "sorot_baris":[0],"poin":[...]}
- "poin": butir insight + chart di samping (opsional). {"poin":[{"judul","teks"}],"chart":{"jenis":"barh|column|line",
  "kategori":[...],"nilai":[...]}}
- "benang_merah": satu pernyataan besar + bukti. {"teks","poin":[{"angka","judul","teks"}]}
- "swot": {"sorotan":[{"label","angka"}],"kuadran":{"S":[...],"W":[...],"O":[...],"T":[...]}}
- "smart": {"kolom":["Merek A","Merek B"],"baris":{"S":[...],"M":[...],"A":[...],"R":[...],"T":[...]}}
- "target_kpi": {"kolom":["KPI","Q2","Q3","Target"],"baris":[[...]],"poin":[{"judul","teks"}]}
- "aksi": rencana aksi. {"baris":[{"aksi","pemilik","waktu","kpi"}]}
- "roadmap": {"tahap":[{"waktu","judul","item":[...]}]}
- "pemisah": pembatas bab. {"nomor":"02","judul","teks"}
Setiap halaman juga boleh punya "bagian" (label kecil di atas judul), "catatan" (definisi/legenda) dan "sumber".
"""

PROMPT = """Anda adalah konsultan strategi senior yang menyusun DECK LAPORAN EKSEKUTIF untuk tim Marketing Intelligence
PT Pertamina Lubricants (PTPL). User TIDAK menyebut isi laporan: Anda yang menentukan alur cerita, halaman, dan visual
terbaik dari SELURUH hasil analisis di bawah — selengkap dan sevisual mungkin, setara deck konsultan kelas atas.

PERMINTAAN USER: {request}
SUMBER: {label}

ATURAN ALUR CERITA
- Piramida Minto / SCQA: kesimpulan utama dulu (ringkasan eksekutif + angka kunci), lalu bukti per tema, lalu
  implikasi & rencana aksi. Umumnya 9–16 halaman isi; jangan memotong temuan penting demi ringkas.
- Satu pesan per halaman. JUDUL HALAMAN = KALIMAT KESIMPULAN yang memuat angka (mis. "Fastron memimpin BEI 4W (21,0)
  tetapi turun 1,7 poin"), BUKAN nama topik ("Analisis BEI").
- Pakai variasi komponen: chart (papan_skor/perbandingan/tren/waterfall/funnel/heatmap) untuk data; swot/smart/
  target_kpi/aksi/roadmap untuk strategi bila relevan. Minimal sepertiga halaman isi berupa chart.
- Hipotesis/asumsi WAJIB ditandai "(hipotesis)". Rekomendasi harus berpijak pada temuan data.
- Aturan bisnis: harga Retail dibandingkan PER LITER; gap harga Retail negatif = PTPL lebih murah (baik). Industri:
  gap % positif = kompetitif.

ATURAN ANGKA (PALING PENTING — diperiksa kode)
- Semua angka HARUS berasal dari DATA di bawah. DILARANG mengarang angka, DILARANG mengambil angka dari gambar.
- Tulis angka PERSIS seperti di data, TANPA PEMBULATAN (jumlah desimal sama). Di teks pakai format Indonesia
  (koma desimal, titik ribuan: 1.234,56); di "nilai"/"langkah" chart tulis sebagai angka JSON (1234.56).
- Selisih dua angka data boleh ditulis (hitung dengan teliti). Jangan menghitung rasio/proyeksi baru.
- ANGKA KUNCI WAJIB berikut adalah hasil analitik yang sudah dilihat user — SEMUANYA harus muncul di deck (di kartu,
  chart, tabel, atau teks): {key}
{feedback}
{guide}
FORMAT OUTPUT: HANYA satu objek JSON (tanpa teks lain, tanpa ```), bentuknya:
{{"judul":"judul deck berupa kesimpulan","subjudul":"...","periode":"...","sumber":"...","format_angka":"id",
 "kartu":[{{"nama","sub"}}],  (opsional: segmen/merek di sampul)
 "slides":[{{"komponen":"ringkasan", "bagian":"Ringkasan eksekutif", "judul":"...", ...}}, ...]}}
(halaman sampul dibuat otomatis — jangan masukkan ke "slides")

DATA HASIL ANALISIS:
{data}
"""

REVISE = """
REVISI — deck sebelumnya (JSON di bawah) diperiksa kode dan perlu diperbaiki. Kembalikan deck LENGKAP yang sudah
diperbaiki (JSON utuh, bukan potongan). Masalah yang harus diperbaiki:
{issues}
DECK SEBELUMNYA:
{previous}
"""

FEEDBACK = """
MASUKAN USER UNTUK REVISI (prioritaskan): {feedback}
DECK SEBELUMNYA (ubah sesuai masukan, pertahankan bagian lain yang baik):
{previous}
"""


# ---------------------------------------------------------------------------------------------- angka
def readings(raw: str) -> list[float]:
    """Semua tafsiran wajar sebuah token angka ('1.234' = 1234 [ID] atau 1,234 [EN])."""
    raw = raw.rstrip(".,")
    out = []
    v = T.to_num(raw)
    if v is not None:
        out.append(v)
    s = raw.replace("−", "-").replace("–", "-")
    if re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", s):
        out.append(float(s.replace(".", "")))
        if s.count(".") == 1:
            out.append(float(s))
    elif re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+", s):
        out.append(float(s.replace(",", "")))
        if s.count(",") == 1:
            out.append(float(s.replace(",", ".")))
    return list(dict.fromkeys(out))


def _tokens(text: str):
    """(token mentah, tafsiran, persen?) untuk setiap angka di teks."""
    for m in _TOKEN.finditer(text or ""):
        raw = m.group(0).rstrip(".,")
        tail = text[m.end():m.end() + 2]
        if re.match(r"[A-Za-z]", tail[:1]) and not tail.lower().startswith("rb"):
            continue                                            # 10W-40, 3D, 2W/4W: bukan angka bisnis
        vals = readings(raw)
        if vals:
            yield raw, vals, tail.strip().startswith("%")


def _significant(raw: str, vals: list[float], pct: bool) -> bool:
    v = abs(vals[0])
    has_dec = bool(re.search(r"[.,]\d{1,2}$", raw)) and not re.fullmatch(r"[-−–+]?\d{1,3}([.,]\d{3})+", raw)
    if pct or has_dec:
        return True
    if float(v).is_integer() and 1900 <= v <= 2100:
        return False                                            # tahun
    return v >= 10


def key_numbers(texts: list[str], limit: int = MAX_KEY) -> list[dict[str, Any]]:
    """Angka kunci hasil analitik (dari jawaban analisis di chat & fakta chart) beserta konteks kalimatnya."""
    out: list[dict[str, Any]] = []
    seen: set[float] = set()
    for text in texts:
        for line in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
            line = re.sub(r"[*_`#>|]+", " ", line).strip()
            if not line or "http" in line:
                continue
            for raw, vals, pct in _tokens(line):
                if not _significant(raw, vals, pct):
                    continue
                v = vals[0]
                key = round(abs(v), 6)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"angka": raw + ("%" if pct else ""), "nilai": v, "konteks": line[:220]})
                if len(out) >= limit:
                    return out
    return out


class Pool:
    """Kumpulan angka sah: angka data (semua tafsiran, ×100, ÷100) + selisih & perubahan % antar angka data."""

    def __init__(self, texts: list[str], extra: list[float] | None = None):
        base: list[float] = []
        for t in texts:
            for _, vals, _ in _tokens(t):
                base += vals
        base += [float(x) for x in extra or []]
        vals = {abs(v) for v in base}
        # selisih & perubahan hanya dari angka "penting" (desimal / ≥ 10) agar tidak meledak
        imp = []
        for v in base:
            if abs(v) >= 10 or not float(v).is_integer():
                imp.append(v)
        imp = list(dict.fromkeys(imp))[:DIFF_BASE]
        derived = set()
        for i, a in enumerate(imp):
            for b in imp[i + 1:]:
                derived.add(round(abs(a - b), 6))
                if b:
                    derived.add(round(abs((a - b) / b * 100), 1))
                if a:
                    derived.add(round(abs((b - a) / a * 100), 1))
        self.exact = sorted(vals | {round(v * 100, 6) for v in vals} | {round(v / 100, 8) for v in vals})
        self.derived = sorted(derived)

    @staticmethod
    def _near(arr: list[float], v: float, tol: float) -> bool:
        i = bisect.bisect_left(arr, v - tol)
        return i < len(arr) and arr[i] <= v + tol

    def status(self, v: float, raw: str = "") -> str:
        """'ok' (persis ada), 'bulat' (hanya cocok bila dibulatkan), 'tidak' (tidak ada di data)."""
        a = abs(v)
        if self._near(self.exact, a, 1e-9 * max(1.0, a)) or self._near(self.derived, a, 1e-6 * max(1.0, a)):
            return "ok"
        dec = T.decimals_of([a])
        tol = 0.5 * 10 ** (-dec) + 1e-9
        if self._near(self.exact, a, tol) or self._near(self.derived, a, tol):
            return "bulat"
        if a >= 1000 and self._near(self.exact, a, 50):
            return "bulat"
        return "tidak"


def _strings(v: Any, path: str = ""):
    if isinstance(v, dict):
        for k, x in v.items():
            if k in ("warna", "color", "tone", "nada", "komponen", "nomor", "format_angka", "png_b64", "_png"):
                continue
            yield from _strings(x, k)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _strings(x, path)
    elif T.is_num(v):
        yield path, v
    elif isinstance(v, str):
        yield path, v


def check_storyboard(sb: dict, pool: Pool) -> tuple[list[str], list[str]]:
    """(angka tidak ada di data, angka yang dibulatkan) dari seluruh storyboard (teks & nilai chart)."""
    bad, rounded = [], []
    for path, v in _strings(sb):
        if T.is_num(v):
            items = [(T.fmt(v, None, "", "id"), [float(v)], False)]
        else:
            items = list(_tokens(v))
        for raw, vals, pct in items:
            if not _significant(raw, vals, pct) or path in ("periode", "waktu"):
                continue
            st = [pool.status(x, raw) for x in vals]
            if "ok" in st:
                continue
            (rounded if "bulat" in st else bad).append(raw + ("%" if pct else ""))
    return list(dict.fromkeys(bad))[:30], list(dict.fromkeys(rounded))[:30]


# ---------------------------------------------------------------------------------------------- model
def parse_storyboard(text: str) -> dict | None:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        sb = json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(sb, dict):
        return None
    slides = sb.get("slides") or sb.get("halaman")
    if not isinstance(slides, list) or not [x for x in slides if isinstance(x, dict)]:
        return None
    return sb


def build_prompt(request: str, label: str, data_text: str, keys: list[dict], issues: list[str] | None = None,
                 previous: dict | None = None, feedback: str = "") -> str:
    key = "; ".join(f"{k['angka']} ({k['konteks'][:90]})" for k in keys) or "(tidak ada daftar khusus)"
    extra = ""
    if feedback and previous:
        extra = FEEDBACK.format(feedback=feedback, previous=json.dumps(previous, ensure_ascii=False)[:60000])
    elif issues and previous:
        extra = REVISE.format(issues="\n".join(f"- {x}" for x in issues),
                              previous=json.dumps(previous, ensure_ascii=False)[:60000])
    return PROMPT.format(request=request or "laporan lengkap dari hasil analisis", label=label or "-", key=key,
                         feedback=extra, guide=COMPONENT_GUIDE, data=(data_text or "")[:MAX_DATA_CHARS])


def _call_model(prompt: str, timeout: float, images=None) -> str | None:
    """Panggil Claude (cadangan Argon) dengan batas waktu keras; None bila gagal/terlambat (tidak melempar)."""
    if timeout < 5:
        return None
    from ..report_engine import generate_text

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="storyboard")
    fut = pool.submit(generate_text, prompt, "", 0.3, images)
    try:
        return fut.result(timeout=timeout)
    except Exception as exc:  # noqa: BLE001  (termasuk TimeoutError)
        logger.warning("Perencana storyboard tidak selesai (%s): %s", type(exc).__name__, str(exc)[:200])
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------------------------- cadangan
def parse_blocks(data_text: str) -> list[dict[str, Any]]:
    """Teks data (### judul, paragraf, tabel markdown) -> [{'judul','teks':[...],'tabel':[{'kolom','baris'}]}]."""
    blocks: list[dict[str, Any]] = []
    cur = None
    table = None
    for line in (data_text or "").splitlines():
        st = line.strip()
        if st.startswith("### "):
            cur = {"judul": st[4:].strip(), "teks": [], "tabel": []}
            blocks.append(cur)
            table = None
            continue
        if cur is None:
            cur = {"judul": "Hasil analisis", "teks": [], "tabel": []}
            blocks.append(cur)
        if st.startswith("|") and st.endswith("|"):
            cells = [c.strip() for c in st.strip("|").split("|")]
            if all(re.fullmatch(r"-{2,}|-*", c) for c in cells):
                continue
            if table is None:
                table = {"kolom": cells, "baris": []}
                cur["tabel"].append(table)
            else:
                table["baris"].append(cells)
            continue
        table = None
        if st and not st.startswith("(menampilkan"):
            cur["teks"].append(st)
    return blocks


def _numeric_cols(tab: dict) -> tuple[int | None, list[int]]:
    cols, rows = tab["kolom"], tab["baris"]
    if not rows:
        return None, []
    num = []
    for j in range(len(cols)):
        vals = [r[j] for r in rows if j < len(r) and str(r[j]).strip() not in ("", "None", "-", "—")]
        if vals and sum(T.to_num(v) is not None for v in vals) >= 0.8 * len(vals):
            num.append(j)
    label = next((j for j in range(len(cols)) if j not in num), None)
    return label, num


def fallback_storyboard(title: str, request: str, data_text: str, keys: list[dict], label: str = "") -> dict:
    """Storyboard yang dibangun KODE (tanpa model): angka kunci + chart & tabel dari setiap tabel data."""
    slides: list[dict] = []
    if keys:
        slides.append({"komponen": "poin", "bagian": "Ringkasan", "judul": "Angka kunci dari hasil analisis",
                       "poin": [k["konteks"] for k in keys[:10]]})
    for b in parse_blocks(data_text)[:12]:
        for tab in b["tabel"][:2]:
            lab, num = _numeric_cols(tab)
            rows = [r for r in tab["baris"] if len(r) == len(tab["kolom"])]
            if lab is not None and num and 2 <= len(rows) <= 40:
                j = num[0]
                pairs = [(str(r[lab]), T.to_num(r[j]), r[j]) for r in rows if T.to_num(r[j]) is not None]
                if pairs:
                    top = max(pairs, key=lambda p: p[1])
                    slides.append({"komponen": "papan_skor", "bagian": b["judul"][:60],
                                   "judul": f"{top[0]} tertinggi untuk {tab['kolom'][j]}: {top[2]}",
                                   "panel": [{"judul_panel": tab["kolom"][j], "kategori": [p[0] for p in pairs],
                                              "nilai": [p[1] for p in pairs], "sorot": [top[0]]}]})
            if rows:
                slides.append({"komponen": "tabel", "bagian": b["judul"][:60], "judul": b["judul"][:140],
                               "kolom": tab["kolom"], "baris": rows})
        text = [t for t in b["teks"] if len(t) > 3]
        if text:
            slides.append({"komponen": "poin", "bagian": "Temuan", "judul": b["judul"][:140], "poin": text[:16]})
        if len(slides) >= 30:
            break
    return {"judul": title or "Laporan hasil analisis", "subjudul": request[:160], "sumber": label,
            "format_angka": "id", "slides": slides or [{"komponen": "poin", "judul": "Ringkasan hasil analisis",
                                                       "poin": [request or "-"]}]}


# ---------------------------------------------------------------------------------------------- evaluasi
def evaluate(sb: dict, pool: Pool, keys: list[dict]) -> dict[str, Any]:
    deck = build_deck(sb)
    rev = review(deck)
    missing = coverage(deck, [k["nilai"] for k in keys])
    bad, rounded = check_storyboard(sb, pool)
    issues = list(rev["masalah"])
    issues += [m for m in deck.issues if "dipotong" not in m]
    if missing:
        issues.append("angka kunci WAJIB belum muncul di deck: " + ", ".join(missing[:25]))
    if bad:
        issues.append("angka TIDAK ADA di data (hapus atau ganti dengan angka data yang persis): " + ", ".join(bad[:20]))
    if rounded:
        issues.append("angka DIBULATKAN — tulis persis seperti di data, tanpa pembulatan: " + ", ".join(rounded[:20]))
    score = len(bad) * 4 + len(missing) * 3 + len(rounded) * 2 + len(rev["masalah"])
    return {"issues": issues, "missing": missing, "bad": bad, "rounded": rounded, "score": score,
            "slides": len(deck.slides), "chart": rev["chart"]}


def finalize(sb: dict, keys: list[dict], ev: dict) -> dict:
    """Jaring terakhir: angka kunci yang hilang -> lampiran; angka di luar data -> halaman catatan pemeriksa."""
    sb = dict(sb)
    slides = list(sb.get("slides") or sb.get("halaman") or [])
    sb.pop("halaman", None)
    if ev["missing"]:
        want = set()
        for m in ev["missing"]:
            v = T.to_num(m)
            if v is not None:
                want.add(round(abs(v), 6))
        rows = [[k["angka"], k["konteks"]] for k in keys if round(abs(k["nilai"]), 6) in want]
        if rows:
            slides.append({"komponen": "tabel", "bagian": "Lampiran", "kolom": ["Angka", "Konteks dari hasil analisis"],
                           "judul": f"{len(rows)} angka kunci hasil analisis yang juga menjadi dasar laporan ini",
                           "baris": rows})
    if ev["bad"]:
        slides.append({"komponen": "poin", "bagian": "Catatan pemeriksa angka",
                       "judul": "Beberapa angka perlu dicek ulang terhadap data sumber sebelum dibagikan",
                       "poin": ["Pemeriksa otomatis tidak menemukan angka berikut di data sumber: "
                                + ", ".join(ev["bad"][:20]) + ".",
                                "Angka lain di laporan ini sudah dicocokkan dengan hasil analisis."]})
    sb["slides"] = slides
    return sb


# ---------------------------------------------------------------------------------------------- utama
def make_report(request: str, data_text: str, keys: list[dict], formats=("pptx", "pdf", "html"), title: str = "",
                label: str = "", budget: float = 240.0, previous: dict | None = None, feedback: str = "",
                images=None, use_model: bool = True) -> dict[str, Any]:
    from . import render_report

    t0 = time.monotonic()
    left = lambda: budget - (time.monotonic() - t0)  # noqa: E731
    pool = Pool([data_text, request] + [k["konteks"] for k in keys] + ([json.dumps(previous, ensure_ascii=False)]
                                                                         if previous and feedback else []))
    source, revised = "claude", False
    t1 = time.monotonic()
    text = _call_model(build_prompt(request, label, data_text, keys, previous=previous, feedback=feedback),
                       left() - RENDER_RESERVE, images) if use_model else None
    first_dur = time.monotonic() - t1
    sb = parse_storyboard(text) if text else None
    if sb is None:
        logger.warning("Storyboard model tidak tersedia/valid (%.0f dtk); memakai storyboard cadangan kode", first_dur)
        sb, source = fallback_storyboard(title, request, data_text, keys, label), "cadangan"
    try:
        ev = evaluate(sb, pool, keys)
    except Exception:  # noqa: BLE001
        logger.exception("Evaluasi storyboard gagal; memakai storyboard cadangan")
        sb, source = fallback_storyboard(title, request, data_text, keys, label), "cadangan"
        ev = evaluate(sb, pool, keys)
    if source == "claude" and ev["issues"] and left() - RENDER_RESERVE > max(MIN_REVISE, first_dur * 1.1):
        logger.info("Storyboard: %d masalah, revisi sekali: %s", len(ev["issues"]), ev["issues"][:6])
        text2 = _call_model(build_prompt(request, label, data_text, keys, ev["issues"], sb), left() - RENDER_RESERVE,
                            images)
        sb2 = parse_storyboard(text2) if text2 else None
        if sb2 is not None:
            try:
                ev2 = evaluate(sb2, pool, keys)
                if ev2["score"] <= ev["score"]:
                    sb, ev, revised = sb2, ev2, True
            except Exception:  # noqa: BLE001
                logger.exception("Evaluasi revisi storyboard gagal; memakai versi pertama")
    if title and not sb.get("judul"):
        sb["judul"] = title
    final = finalize(sb, keys, ev)
    out = render_report(final, formats, angka_wajib=[k["nilai"] for k in keys])
    logger.info("Laporan visual: sumber=%s revisi=%s slide=%s chart=%s hilang=%s luar_data=%s dibulatkan=%s %.0f dtk",
                source, revised, out["stats"]["slide"], out["stats"]["chart"], len(out["angka_hilang"]),
                len(ev["bad"]), len(ev["rounded"]), time.monotonic() - t0)
    return {**out, "storyboard": sb, "sumber_storyboard": source, "revisi": revised,
            "angka_tidak_terverifikasi": ev["bad"], "angka_dibulatkan": ev["rounded"],
            "detik": round(time.monotonic() - t0, 1)}
