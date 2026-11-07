"""Laporan CUSTOM: prompt Retail Only / Industry Only / Planogram (sama dengan workflow MIR) + Gemini 4 Argon.

Alur:
1. Data dikumpulkan dulu (hasil Data Agent BigQuery yang ditarik sesuai permintaan user, atau hasil analisis
   file unggahan) dan dijadikan teks INPUT.
2. Prompt dari report_assets/custom_prompts/<domain>.txt diisi (permintaan user + data). Bagian FORMAT OUTPUT
   diganti kontrak keluaran agent: model menulis HANYA isi halaman (<section class="page">...). DESIGN SYSTEM PTPL
   (report_assets/ptpl_design_system.html) dibungkus oleh kode, sehingga CSS/JS grafik tidak mungkin rusak dan
   token keluaran jauh lebih hemat.
3. Pemeriksa angka: angka di teks dan grafik dicocokkan dengan data INPUT. Jika ada yang tidak ditemukan, model
   diminta menulis ulang SEKALI; jika masih ada, laporan tetap dibuat dengan catatan pemeriksa di halaman terakhir.
4. Laporan berstatus DRAFT. "approve" menerbitkan ulang sebagai FINAL (body class="final"); "revisi" menulis
   ulang dengan masukan user memakai data yang sama.
"""
from __future__ import annotations

import html as _html
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from .ptpl_design import ASSET_DIR, wrap

logger = logging.getLogger(__name__)
PROMPT_DIR = os.path.join(ASSET_DIR, "custom_prompts")
NO_DATA = "DATA TIDAK DITERIMA DARI DATA AGENT"
FIRST_LINE = {"retail": "LAPORAN RETAIL ONLY", "industri": "LAPORAN INDUSTRY ONLY", "planogram": "LAPORAN PLANOGRAM",
              "retail_planogram": "LAPORAN RETAIL × PLANOGRAM", "umum": "LAPORAN DATA"}
PROMPT_FILES = ("retail", "industri", "planogram", "retail_planogram")
MAX_DATA_CHARS = 120_000

OUTPUT_CONTRACT = """FORMAT OUTPUT (KHUSUS AGENT — MENGGANTIKAN "FORMAT OUTPUT" DAN PERINTAH MENYALIN DESIGN SYSTEM DI ATAS)

Sistem akan membungkus laporanmu dengan DESIGN SYSTEM PTPL secara otomatis (CSS, JS grafik, <html>, <head>,
<body>). JANGAN menulis <!DOCTYPE>, <html>, <head>, <style>, <script>, atau <body>. Semua komponen dan aturan lain di
atas tetap berlaku (struktur halaman, PANDUAN GRAFIK, ATURAN ANGKA, label DRAFT di .hdr-r, footer).

Baris pertama: "{first} — <judul singkat> · <periode>".

Lalu SATU blok kode ```html berisi HANYA rangkaian <section class="page">…</section> (isi ISI_LAPORAN_HTML).

Setelah blok kode (singkat, maksimal 4 baris): data yang dipakai, grafik yang dipilih dan alasannya, data yang tidak
tersedia.

Jika INPUT tidak berisi data angka, tulis HANYA kalimat "DATA TIDAK DITERIMA DARI DATA AGENT." tanpa blok kode.
"""


TEMPLATE_CONTRACT = """FORMAT OUTPUT — TEMPLATE DESAIN DARI USER (MENGGANTIKAN "FORMAT OUTPUT", DESIGN SYSTEM PTPL, DAN DAFTAR
KOMPONEN DI ATAS)

User melampirkan template HTML. Sistem akan membungkus laporanmu dengan <head>, CSS, dan script dari template itu.
Tulis HANYA isi <body> yang memakai struktur, class, dan komponen dari CONTOH BODY TEMPLATE di bawah: pertahankan
susunan bagian, gaya kartu/tabel/judul, dan nama class-nya; ganti teks dan angka contoh dengan isi laporan dari data
INPUT. Jangan menulis <!DOCTYPE>, <html>, <head>, <style>, <script>, atau <body>. Jika template punya komponen grafik
(atribut data/elemen khusus), pakai dengan cara yang sama; jika tidak ada, gunakan tabel dan kartu angka.
Semua ATURAN ANGKA di atas tetap berlaku. Letakkan penanda status di bagian kepala laporan, persis:
<span class="draft">DRAFT - menunggu approval</span>

Baris pertama: "{first} — <judul singkat> · <periode>".
Lalu SATU blok kode ```html berisi isi body.
Setelah blok kode (maksimal 4 baris): data yang dipakai dan data yang tidak tersedia.
Jika INPUT tidak berisi data angka, tulis HANYA kalimat "DATA TIDAK DITERIMA DARI DATA AGENT." tanpa blok kode.

CONTOH BODY TEMPLATE (struktur & class yang harus diikuti; angkanya hanya contoh, JANGAN disalin):
```html
{example}
```
"""
DRAFT_TEXT = "DRAFT - menunggu approval"


def template_parts(template_html: str) -> dict[str, str] | None:
    """Pisahkan template HTML user: kepala (s.d. <body>), contoh isi body, serta style/script yang harus dipertahankan."""
    m = re.search(r"<body\b[^>]*>", template_html or "", re.I)
    if not m:
        return None
    rest = template_html[m.end():]
    end = rest.lower().rfind("</body>")
    inner = rest[:end] if end >= 0 else rest
    scripts = "".join(re.findall(r"<script\b.*?</script>", inner, flags=re.S | re.I))
    styles = "".join(re.findall(r"<style\b.*?</style>", inner, flags=re.S | re.I))
    example = re.sub(r"<(script|style)\b.*?</\1>", "", inner, flags=re.S | re.I)
    example = re.sub(r"\n\s*\n+", "\n", example).strip()
    return {"head": template_html[:m.end()], "styles": styles, "scripts": scripts, "example": example[:25000]}


# ==========================================================================
# Prompt
# ==========================================================================
def load_prompt(domain: str) -> str:
    name = domain if domain in PROMPT_FILES else "retail"
    with open(os.path.join(PROMPT_DIR, f"{name}.txt"), encoding="utf-8") as fh:
        text = fh.read()
    if domain == "umum":   # file format umum: tanpa knowledge retail
        text = re.sub(r"KNOWLEDGE RETAIL.*?(?=ANGGARAN PANJANG)",
                      "KNOWLEDGE DATA\n\nTidak ada aturan bisnis khusus. Pakai nama kolom dan definisi persis seperti di data; "
                      "jangan berasumsi arti istilah yang tidak dijelaskan.\n\n", text, flags=re.S)
        text = text.replace('cabang workflow "Retail Only"', 'cabang "Data Unggahan"')
        text = text.replace("hasil Data Agent", "data/dokumen unggahan").replace("dari Data Agent", "dari data/dokumen unggahan")
    return text


def build_prompt(domain: str, request: str, data_text: str, previous_body: str = "", feedback: str = "",
                 problems: list[str] | None = None, extra_instructions: str = "", template_example: str = "") -> str:
    base = load_prompt(domain)
    base = base.replace("SISIPKAN_VARIABEL_Description", request.strip() or "(tidak ada)")
    base = re.sub(r"SISIPKAN_VARIABEL_\w+_output", lambda _m: data_text.strip() or "(kosong)", base, count=1)
    base = re.sub(r"SISIPKAN_VARIABEL_\w+_output", "(sudah termasuk pada data di atas)", base)
    cut = base.find("FORMAT OUTPUT")
    if cut >= 0:
        base = base[:cut]
    if extra_instructions.strip():
        base += ("\nINSTRUKSI TAMBAHAN DARI DOKUMEN USER (ikuti selama tidak bertentangan dengan LARANGAN SUMBER DATA dan "
                 "ATURAN ANGKA; jika dokumen berupa contoh laporan, tiru struktur dan gaya narasinya, bukan angkanya):\n"
                 + extra_instructions.strip()[:20000] + "\n")
    if template_example:
        base += "\n" + TEMPLATE_CONTRACT.replace("{first}", FIRST_LINE.get(domain, "LAPORAN DATA")).replace(
            "{example}", template_example)
    else:
        base += "\n" + OUTPUT_CONTRACT.format(first=FIRST_LINE.get(domain, "LAPORAN DATA"))
    if previous_body and feedback:
        base += ("\n\nREVISI (WAJIB): Berikut laporan sebelumnya. Tulis ulang SELURUH laporan dengan menerapkan masukan "
                 f"user ini: \"{feedback.strip()}\". Data INPUT tetap sama; jangan menambah angka di luar data.\n\n"
                 "```html\n" + previous_body[:60000] + "\n```")
    if problems:
        base += ("\n\nPERBAIKAN ANGKA (WAJIB): angka berikut di laporan sebelumnya TIDAK ditemukan di data INPUT: "
                 + ", ".join(problems[:15]) + ". Tulis ulang laporan lengkap; pakai HANYA angka yang terlihat di data INPUT, "
                 "jangan menghitung selisih/rata-rata/jumlah sendiri. Jika angka tidak ada, tulis n/a atau hapus kalimatnya.")
    return base


# ==========================================================================
# Data -> teks INPUT
# ==========================================================================
def table_text(columns: list[str], rows: list[list[Any]], total: int | None = None) -> str:
    lines = ["| " + " | ".join(str(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    for r in rows:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    if total and total > len(rows):
        lines.append(f"(menampilkan {len(rows)} dari {total} baris)")
    return "\n".join(lines)


def data_block(title: str, answer: str = "", tables: list[dict] | None = None) -> str:
    parts = [f"### {title}"]
    if answer:
        parts.append(answer.strip())
    for t in tables or []:
        parts.append(table_text(t.get("columns") or [], t.get("rows") or [], t.get("total_rows")))
    return "\n\n".join(parts)


def battlefield_block(ds: dict[str, Any]) -> str:
    """Tabel analisis silang Retail × Planogram (dihitung kode) sebagai bagian data INPUT laporan custom."""
    pa, pb = ds["period"]["a"], ds["period"]["b"] or "-"
    pairs = ds.get("pairs", [])[:20]
    cols = ["KIMAP", "Segmen", "Viskositas", "Produk PTPL", "Head-to-head", "Outlet PTPL", "Outlet komp", "Rasio carry %",
            "AV PTPL", "AV komp", "Gap AV", "HJ/L PTPL", "HJ/L komp", "Keunggulan harga %", "Gap margin/L", "Status",
            f"Δ keunggulan harga pp ({pb}→{pa})", "Δ gap AV", "SR lemah"]
    rows = [[p["kimap"], p["segmen"], p["viscosity"], p["ptpl"], f"{p['h2h']} {p['h2h_series']}", p["out_ptpl"], p["out_comp"],
             p["ratio"], p["av_ptpl"], p["av_comp"], p["av_gap"], p["hj_ptpl"], p["hj_comp"], p["price_adv"], p["eco_gap"],
             p["status"], p["price_adv_delta"], p["av_gap_delta"], ", ".join(p["weak_sr"])] for p in pairs]
    cats = ds.get("categories", [])[:12]
    ccols = ["Kategori", "Exposure", "Δ outlet %", "AV", "Δ AV", "Leader", "Outlet leader", "Outlet PTPL", "White space"]
    crows = [[c["label"], c["exposure"], c["delta_pct"], c["av"], c["delta_av"], c["leader"], c["leader_carry"],
              c["ptpl_carry"], "ya" if c["white_space"] else "tidak"] for c in cats]
    th = ds.get("threats", [])[:10]
    tcols = ["Brand", "Series", "KIMAP", f"Outlet {pb}", f"Outlet {pa}", "Δ outlet", "Growth %", "Δ AV", "Tipe"]
    trows = [[t["brand"], t["series"], t["kimap"], t["out_b"], t["out_a"], t["delta"], t["growth_pct"], t["delta_av"],
              t["type"]] for t in th]
    rcols = ["SR", "Double weakness MCO", "PCO", "Commercial", "Total"]
    rrows = [[r["sr"], r["double_weakness"].get("MCO", 0), r["double_weakness"].get("PCO", 0),
              r["double_weakness"].get("COMMERCIAL", 0), r["dw_total"]] for r in ds.get("regions", [])]
    status = ", ".join(f"{k}: {v}" for k, v in (ds.get("status_counts") or {}).items())
    return data_block(f"Analisis silang Retail × Planogram (dihitung kode) — {pa} vs {pb}",
                      f"Jumlah status head-to-head: {status}.",
                      [{"columns": cols, "rows": rows}, {"columns": ccols, "rows": crows},
                       {"columns": tcols, "rows": trows}, {"columns": rcols, "rows": rrows}])


# ==========================================================================
# Output model -> isi halaman
# ==========================================================================
def parse_output(text: str, template_mode: bool = False) -> dict[str, Any]:
    """{'no_data': bool, 'title': str, 'body': str, 'explanation': str}."""
    raw = (text or "").strip()
    if not raw or (NO_DATA in raw[:300] and "<section" not in raw):
        return {"no_data": True, "title": "", "body": "", "explanation": raw[:500]}
    first = raw.splitlines()[0].strip().strip('"').strip()
    m = re.search(r"```html\s*(.*?)```", raw, re.S | re.I)
    body = m.group(1) if m else raw
    explanation = raw[m.end():].strip() if m else ""
    b = re.search(r"<body[^>]*>(.*)</body>", body, re.S | re.I)   # model tetap menulis dokumen lengkap
    if b:
        body = b.group(1)
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S | re.I)
    body = re.sub(r"<style\b.*?</style>", "", body, flags=re.S | re.I)
    body = body.replace("ISI_LAPORAN_HTML", "")
    if template_mode:
        body = re.sub(r"<!DOCTYPE[^>]*>|</?html[^>]*>|<head\b.*?</head>|</?body[^>]*>", "", body, flags=re.S | re.I)
        title = first if first.upper().startswith("LAPORAN") else ""
        return {"no_data": False, "title": title, "body": body.strip() if "<" in body else "",
                "explanation": explanation[:800]}
    start = body.find("<section")
    end = body.rfind("</section>")
    body = body[start:end + len("</section>")] if start >= 0 and end > start else ""
    title = first if first.upper().startswith("LAPORAN") else ""
    return {"no_data": False, "title": title, "body": body.strip(), "explanation": explanation[:800]}


def visible_text(body: str) -> str:
    text = re.sub(r"<div class=\"chart[^>]*></div>", " ", body)
    text = re.sub(r"<[^>]+>", " ", text)
    return _html.unescape(re.sub(r"\s+", " ", text))


def chart_numbers(body: str) -> list[float]:
    vals: list[float] = []
    for m in re.finditer(r"data-chart='([^']*)'", body):
        try:
            spec = json.loads(_html.unescape(m.group(1)))
        except json.JSONDecodeError:
            continue
        for key in ("from", "to"):
            vals += [v for v in spec.get(key) or [] if isinstance(v, (int, float))]
        for s in spec.get("series") or []:
            vals += [v for v in s.get("data") or [] if isinstance(v, (int, float))]
        for p in spec.get("points") or []:
            vals += [p[k] for k in ("x", "y") if isinstance(p.get(k), (int, float))]
    return vals


def number_pool(data_text: str) -> list[float]:
    from .price_dashboard import _MONEY
    from .report_render import parse_number

    pool: set[float] = set()
    for raw in _MONEY.findall(data_text or ""):
        v = parse_number(raw)
        if v is not None:
            v = abs(v)
            pool.update({round(v, 2), round(v * 100, 2), round(v / 100, 4)})
    for raw in re.findall(r"-?\d+\.\d+(?:[eE][-+]?\d+)?", data_text or ""):
        try:
            v = abs(float(raw))
            pool.update({round(v, 2), round(v * 100, 2)})
        except ValueError:
            pass
    return sorted(pool)


def check_numbers(body: str, pool: list[float]) -> list[str]:
    """Angka di laporan (teks & grafik) yang tidak ditemukan di data INPUT."""
    from .price_dashboard import ungrounded_numbers

    bad = list(dict.fromkeys(ungrounded_numbers(visible_text(body), pool)))
    for v in chart_numbers(body):
        a = abs(float(v))
        if a < 100 and float(a).is_integer():
            continue   # jumlah kecil/label; tidak bisa dibedakan dari hitungan baris
        tol = max(1.0, 0.006 * a) if a >= 100 else 0.051
        if not any(abs(a - n) <= tol for n in pool):
            bad.append(str(v))
    return list(dict.fromkeys(bad))[:20]


def add_checker_note(body: str, bad: list[str]) -> str:
    note = ('<p class="note">Catatan pemeriksa otomatis: angka berikut tidak dapat dicocokkan dengan data sumber dan '
            f'perlu dicek sebelum approval: {_html.escape(", ".join(bad[:10]))}.</p>')
    idx = body.rfind('<div class="footer"')
    return body[:idx] + note + body[idx:] if idx >= 0 else body + note


# ==========================================================================
# Generate / approve
# ==========================================================================
def generate(domain: str, request: str, data_text: str, previous_body: str = "", feedback: str = "",
             extra_instructions: str = "", template_html: str = "") -> dict[str, Any]:
    """Panggil model utama, bungkus design system, dan periksa angka (maks 1 perbaikan)."""
    from .report_engine import generate_text

    data_text = data_text[:MAX_DATA_CHARS]
    pool = number_pool(data_text + "\n" + request)
    parts = template_parts(template_html) if template_html else None
    example = parts["example"] if parts else ""
    tmode = bool(parts)
    out = parse_output(generate_text(build_prompt(domain, request, data_text, previous_body, feedback,
                                                  extra_instructions=extra_instructions, template_example=example)),
                       template_mode=tmode)
    if out["no_data"]:
        return {"status": "no_data", "message": out["explanation"] or NO_DATA}
    if not out["body"]:
        raise RuntimeError("Model tidak menghasilkan isi laporan HTML.")
    bad = check_numbers(out["body"], pool)
    revised = False
    if bad:
        logger.warning("Laporan custom: %d angka tidak terverifikasi, minta tulis ulang: %s", len(bad), bad[:10])
        retry = parse_output(generate_text(build_prompt(domain, request, data_text, previous_body, feedback, bad,
                                                        extra_instructions, example)), template_mode=tmode)
        if retry["body"]:
            revised = True
            out = retry
            bad = check_numbers(out["body"], pool)
    body = add_checker_note(out["body"], bad) if bad else out["body"]
    title = out["title"] or f"{FIRST_LINE.get(domain, 'LAPORAN DATA')} — Laporan custom"
    return {"status": "ok", "title": title, "body": body, "unverified": bad, "revised_for_numbers": revised,
            "explanation": out["explanation"]}


def to_html(title: str, body: str, approved_label: str = "", template_html: str = "") -> bytes:
    parts = template_parts(template_html) if template_html else None
    if not parts:
        return wrap(body, title, approved_label).encode("utf-8")
    head = re.sub(r"<title>.*?</title>", f"<title>{_html.escape(title)}</title>", parts["head"], count=1,
                  flags=re.S | re.I)
    if approved_label:
        body = body.replace(DRAFT_TEXT, _html.escape(approved_label))
    return (head + "\n" + parts["styles"] + body + "\n" + parts["scripts"] + "\n</body>\n</html>\n").encode("utf-8")


def approved_label(user: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%d-%m-%Y")
    who = user.split("@")[0] if user and "@" in user else (user or "")
    return f"FINAL · Disetujui {who} · {stamp}".replace("  ", " ")


FORMAT_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


def parse_formats(value: str) -> list[str]:
    """'pdf dan pptx' / 'html,pdf' / 'PowerPoint' -> ['pdf', 'pptx'] (urutan tetap, tanpa duplikat)."""
    from .report_engine import normalize_format

    out = []
    for token in re.split(r"[,;/+&]|\s+dan\s+|\s+and\s+|\s+", (value or "").lower()):
        f = normalize_format(token.strip())
        if f and f not in out:
            out.append(f)
    return out


def render_format(title: str, body: str, fmt: str, template_html: str = "", approved_label: str = "",
                  source: str = "") -> bytes:
    """Satu isi laporan -> HTML (asli), PDF, atau PowerPoint (lewat model halaman ptpl_design)."""
    if fmt == "html":
        return to_html(title, body, approved_label, template_html)
    from . import html_convert, ptpl_design

    pages = html_convert.to_pages(body, title=title, source=source)
    render = ptpl_design.render_pdf if fmt == "pdf" else ptpl_design.render_pptx
    return render(pages, title, approved_label)
