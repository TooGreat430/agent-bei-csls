"""Alat analisis RFM outlet sell-out (Bengkel & Toko Oli) + pembatas satu laporan berat per pesan."""
from __future__ import annotations

import functools
import logging
import re
import threading
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)
HEAVY_KEY = "heavy_report_turn"   # {"inv": invocation_id, "label": ...}
_HEAVY: dict[str, str] = {}
_LOCK = threading.Lock()
NARR_WORKERS = 4   # narasi Claude paralel (4 agar tidak memicu 429 kuota); sisanya menunggu giliran
RFM_KEY = "rfm_reports"
RFM_WORDS = re.compile(r"\bRFM\b|recency|frequency.{0,20}monetary|champions|can'?t lose|hibernating", re.I)


def _safe(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            msg = str(exc)
            if "403" in msg or "Access Denied" in msg:
                msg = "service account belum punya akses baca ke tabel sell-out"
            return {"status": "error", "message": f"Analisis RFM gagal: {msg[:300]}"}
    return wrapper


def _invocation_id(tool_context: Any) -> str:
    inv = getattr(tool_context, "invocation_id", None)
    if not inv:
        ic = getattr(tool_context, "_invocation_context", None)
        inv = getattr(ic, "invocation_id", None) if ic else None
    return inv if isinstance(inv, str) and inv else ""


def heavy_turn_guard(tool_context: ToolContext, label: str) -> dict | None:
    """Batas SATU laporan berat per pesan user (satu invocation ADK) agar tidak kena DEADLINE_EXCEEDED.

    None = boleh lanjut (dan giliran ini ditandai); dict 'deferred' = sudah ada laporan berat di pesan ini.
    Penanda disimpan di registry proses (aman untuk panggilan paralel dalam satu respons model) DAN di state sesi
    (kunci biasa berisi invocation_id; state 'temp:' tidak dipakai karena tidak terlihat antar-panggilan tool).
    """
    inv = _invocation_id(tool_context)
    if not inv:
        return None
    with _LOCK:
        done = _HEAVY.get(inv)
        if not done:
            prev = tool_context.state.get(HEAVY_KEY) or {}
            done = prev.get("label") if isinstance(prev, dict) and prev.get("inv") == inv else None
        if done:
            return {"status": "deferred",
                    "message": (f"Di pesan ini sudah dibuat satu laporan berat ({done}). Agar tidak melewati batas "
                                f"waktu, '{label}' dibuat di pesan berikutnya. JANGAN memanggil alat laporan lagi di "
                                "pesan ini. Sampaikan hasil laporan yang sudah jadi, lalu tawarkan: ketik 'lanjut' "
                                "untuk membuat laporan berikutnya. (Lain kali: beberapa laporan berbeda = SATU "
                                "panggilan buat_laporan_sekaligus; RFM beberapa region = analisis_rfm(region='semua').)")}
        _HEAVY[inv] = label
        while len(_HEAVY) > 500:
            _HEAVY.pop(next(iter(_HEAVY)))
    tool_context.state[HEAVY_KEY] = {"inv": inv, "label": label}
    return None


def release_heavy_turn(tool_context: ToolContext) -> None:
    """Lepas penanda bila alat ternyata tidak mengerjakan laporan (mis. masih menanyakan format)."""
    inv = _invocation_id(tool_context)
    if not inv:
        return
    with _LOCK:
        _HEAVY.pop(inv, None)
    prev = tool_context.state.get(HEAVY_KEY) or {}
    if isinstance(prev, dict) and prev.get("inv") == inv:
        tool_context.state[HEAVY_KEY] = {}


NOT_HEAVY = {"needs_input", "invalid", "deferred", "budget_limit", "redirect"}  # tidak memakai jatah pesan


def heavy_turn(label: str):
    """Dekorator alat laporan berat: maksimal satu per pesan user."""
    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ctx = kwargs.get("tool_context") or next((a for a in args if hasattr(a, "state")), None)
            if ctx is None:
                return func(*args, **kwargs)
            blocked = heavy_turn_guard(ctx, label)
            if blocked:
                return blocked
            result = None
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                if not isinstance(result, dict) or result.get("status") in NOT_HEAVY or result.pop("_ringan", False):
                    release_heavy_turn(ctx)
        return wrapper
    return deco


def is_rfm_request(text: str) -> bool:
    return bool(RFM_WORDS.search(text or ""))


ALL_WORDS = ("semua", "all", "semua region", "nasional dan semua region", "nasional + region", "lengkap", "paket")
REGION_ONLY_WORDS = ("semua_region", "region saja", "semua region saja", "seluruh region", "sr1-sr7", "region i-vii")
NATIONAL_WORDS = ("", "nasional", "national", "nas")


def parse_scopes(region: str, available: list[str]) -> list[str]:
    """'' -> [NASIONAL]; 'semua' -> NASIONAL + semua region; 'semua_region' -> semua region; 'SR1, SR3' -> daftar."""
    from .. import rfm_engine as eng

    low = " ".join((region or "").lower().split())
    if low in REGION_ONLY_WORDS:
        return list(available)
    if low in ALL_WORDS:
        return ["NASIONAL"] + list(available)
    if low in NATIONAL_WORDS:
        return ["NASIONAL"]
    out = []
    for tok in re.split(r"\s*(?:,|;|/|\+|&|\bdan\b)\s*", low):
        tok = tok.strip()
        if not tok:
            continue
        key = "NASIONAL" if tok in NATIONAL_WORDS else eng.region_key(tok)
        if key != "NASIONAL" and key not in available:
            raise ValueError(f"Region '{tok}' tidak ada di data. Region tersedia: {', '.join(available)}")
        if key not in out:
            out.append(key)
    return out or ["NASIONAL"]


def _narratives(results: list[dict], fokus: str, timeout: float) -> list[dict]:
    """Narasi semua cakupan DITULIS PARALEL (Claude); yang melewati batas waktu memakai narasi aturan."""
    from concurrent.futures import ThreadPoolExecutor, wait

    from .. import rfm_report as rep

    pool = ThreadPoolExecutor(max_workers=max(1, min(NARR_WORKERS, len(results))), thread_name_prefix="rfm-narasi")
    futs = [pool.submit(rep.generate_narrative, r, fokus) for r in results]
    done, _ = wait(futs, timeout=timeout)
    pool.shutdown(wait=False, cancel_futures=True)
    out = []
    for r, f in zip(results, futs):
        narr = None
        if f in done:
            try:
                narr = f.result()
            except Exception:  # noqa: BLE001
                logger.warning("Narasi RFM %s gagal; memakai narasi aturan", r["scope"])
        if narr is None:
            if f not in done:
                logger.warning("Narasi RFM %s melewati %ss; memakai narasi aturan", r["scope"], int(timeout))
            narr = dict(rep.fallback_narrative(r), _timeout=f not in done)
        out.append(narr)
    return out


def _period_tag(w: dict) -> str:
    return f"Jan{w['y0']}_{w['label_ytd'].split('–')[1].replace(' ', '')}"


def _summary(res: dict) -> dict:
    k, w = res["kpi"], res["window"]
    seg = {s["segment"]: s for s in res["segments"]}
    return {"cakupan": res["scope_label"],
            "periode": f"{w['label_ytd']} vs {w['label_ytd_prev']} (baseline {w['label_base']})",
            "volume_ytd_kl": round(k["vol_ytd"], 2), "yoy_total_pct": _r(k["yoy_total_pct"]),
            "yoy_baseline_cohort_pct": _r(k["yoy_cohort_pct"]), "outlet_valid": k["outlets_valid"],
            "outlet_baseline": k["outlets_baseline"], "dataset_entrants": k["outlets_entrants"],
            "champions": {"outlet": seg["Champions"]["outlets"], "porsi_volume_pct": _r(seg["Champions"]["vol_share"])},
            "momentum": {m["status"]: m["outlets"] for m in res["momentum"]},
            "threshold": {"F": [round(x, 4) for x in res["thresholds"]["F"]],
                          "M": [round(x, 4) for x in res["thresholds"]["M"]], "basis": res["thresholds"]["basis"]},
            "pemeriksaan": res["checks"]}


@_safe
@heavy_turn("laporan RFM")
def analisis_rfm(tool_context: ToolContext, region: str = "", cutoff: str = "", fokus: str = "",
                 refresh: bool = False) -> dict[str, Any]:
    """Analisis & laporan RFM outlet Retail (Bengkel + Toko Oli) dari datamart sell-out, DIHITUNG KODE langsung dari
    BigQuery (SALES_OUT_DAILY) sesuai metodologi PTPL RFM SR7 v5: skor R/F/M, threshold P20–P80 baseline region,
    12 segmen first-match (uji 125 kombinasi), momentum, matriks perpindahan 12×12, produk (top, pertumbuhan,
    penetrasi per segmen, adopsi/berhenti), Top 20 outlet, kuartal, audit. Tiap cakupan menghasilkan laporan HTML
    8 section (struktur SR7 v5) + Excel register outlet.

    BEBERAPA LAPORAN SEKALIGUS DALAM SATU PANGGILAN: untuk "semua region + nasional" pakai region="semua"; untuk
    beberapa region pakai daftar, mis. region="SR2, SR3, SR4". Data ditarik sekali dan narasi ditulis paralel,
    lalu dibuat halaman paket berisi perbandingan + semua tautan. JANGAN memanggil alat ini berulang-ulang dalam satu
    pesan (panggilan kedua akan ditolak); gabungkan semua cakupan dalam SATU panggilan.

    Pakai alat ini untuk SEMUA permintaan RFM / segmentasi outlet sell-out — JANGAN memakai ask_sellout_intelligence
    atau generate_custom_report untuk RFM (datanya tidak cukup rinci).

    Args:
        region: "" / "nasional" = nasional; "SR1".."SR7" / "Region III" = satu Sales Region; "semua" = nasional +
            SR1–SR7; "semua_region" = SR1–SR7 saja; daftar dipisah koma, mis. "nasional, SR1, SR2";
            "daftar" = lihat region tersedia tanpa membuat laporan.
        cutoff: Bulan cut-off YTD format YYYY-MM (default dari pengaturan, mis. 2026-09). Baseline = Jan–Des tahun sebelumnya.
        fokus: Penekanan narasi dari user (opsional).
        refresh: True untuk menarik ulang data dari BigQuery (default memakai cache ≤ 12 jam).
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    from .. import rfm_engine as eng
    from .. import rfm_report as rep
    from ..clients import get_user_id
    from ..config import live
    from ..report_engine import FORMATS, save_output

    t0 = time.monotonic()
    budget = _num(live("rfm_time_budget"), 300)
    cfg = eng.config()
    if cutoff.strip():
        eng.parse_cutoff(cutoff)
        cfg["cutoff"] = cutoff.strip()
    data = eng.fetch(cfg, refresh=refresh)
    if data["outlets"].empty:
        return {"status": "error", "message": "Tidak ada data outlet Bengkel/Toko Oli pada periode ini di datamart."}
    regions = sorted({eng.region_key(r) for r in data["outlets"]["region"]} - {""})
    if (region or "").strip().lower() in ("daftar", "list", "?"):
        return {"status": "ok", "_ringan": True, "region_tersedia": regions, "jumlah_outlet": int(len(data["outlets"])),
                "message": "Untuk semua laporan sekaligus panggil analisis_rfm(region='semua')."}
    scopes = parse_scopes(region, regions)
    results = [eng.compute(data["outlets"], data["series"], data["audit"], cfg["cutoff"],
                           scope="" if sc == "NASIONAL" else sc) for sc in scopes]
    narr_timeout = _num(live("rfm_narrative_timeout"), 120)
    narrs = _narratives(results, fokus, max(1.0, min(narr_timeout, budget - (time.monotonic() - t0) - 60)))
    credit = live("rfm_footer_credit") or "Prepared with Marketing Insight Assistant"
    source = f"Selling Out Intelligence — {cfg['table']}"
    uid = get_user_id(tool_context)
    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    uploads = ThreadPoolExecutor(max_workers=6, thread_name_prefix="rfm-upload")
    built, pending = [], []
    for res, narr in zip(results, narrs):
        if built and time.monotonic() - t0 > budget:
            pending.append(res["scope"])
            continue
        w = res["window"]
        tag, period = res["scope"], _period_tag(res["window"])
        record = {"source": "sellout_rfm", "scope": tag, "cutoff": cfg["cutoff"]}
        html_doc = rep.render_html(res, narr, credit=credit, source=source, fetched_at=data.get("fetched_at", ""))
        f_html = uploads.submit(save_output, uid, "rfm_outlet", f"PTPL_RFM_{tag}_Executive_Intelligence_Report_{period}",
                                html_doc.encode("utf-8"), "html", FORMATS["html"][1], record)
        f_xlsx = uploads.submit(save_output, uid, "rfm_outlet", f"PTPL_RFM_{tag}_Outlet_RFM_Register_{period}",
                                eng.register_excel(res), "xlsx", xlsx_type, record)
        built.append({"res": res, "narr": narr, "f_html": f_html, "f_xlsx": f_xlsx, "w": w})
    for b in built:
        b["html"], b["xlsx"] = b.pop("f_html").result()["url"], b.pop("f_xlsx").result()["url"]
    uploads.shutdown(wait=True)

    paket = None
    if len(built) > 1:
        idx = rep.render_index(built, credit=credit, source=source, fetched_at=data.get("fetched_at", ""),
                               pending=pending)
        paket = save_output(uid, "rfm_outlet", f"PTPL_RFM_Paket_Laporan_{_period_tag(built[0]['w'])}",
                            idx.encode("utf-8"), "html", FORMATS["html"][1],
                            {"source": "sellout_rfm", "scope": "PAKET", "cutoff": cfg["cutoff"]})["url"]

    reports = list(tool_context.state.get(RFM_KEY) or [])
    reports += [{"scope": b["res"]["scope"], "cutoff": cfg["cutoff"], "html": b["html"], "xlsx": b["xlsx"]} for b in built]
    tool_context.state[RFM_KEY] = reports[-20:]
    done = sorted({r["scope"] for r in reports})
    remaining = [r for r in ["NASIONAL"] + regions if r not in done]
    timeouts = sum(1 for b in built if b["narr"].get("_timeout"))
    dropped = sum(int(b["narr"].get("_dropped") or 0) for b in built)
    out = {"status": "ok", "durasi_detik": round(time.monotonic() - t0, 1),
           "laporan": [{"cakupan": b["res"]["scope_label"], "laporan_html": b["html"], "register_excel": b["xlsx"],
                        "headline": b["narr"]["headline"], "ringkasan": _summary(b["res"])} for b in built],
           "sudah_dibuat_di_chat_ini": done, "belum_dibuat": remaining}
    if paket:
        out["halaman_paket"] = paket
    if pending:
        out["tertunda_batas_waktu"] = pending
    msg = ("Laporan RFM selesai. " + ("Tampilkan DULU link 'halaman_paket' (perbandingan semua cakupan + semua link), "
                                     "lalu tabel ringkas per cakupan (outlet valid, volume YTD, YoY, Champions) dan "
                                     "link HTML/Excel tiap laporan. " if paket else
                                     "Sampaikan headline, 4–6 angka kunci dari 'ringkasan', dan kedua link. "))
    if pending:
        msg += (f"{len(pending)} laporan ({', '.join(pending)}) belum sempat dibuat agar tidak melewati batas waktu; "
                "tawarkan 'ketik lanjut' untuk melengkapinya (panggil lagi dengan region berisi daftar itu). ")
    elif remaining and not paket:
        msg += "Tawarkan juga membuat sisanya sekaligus (region='semua' atau daftar dari 'belum_dibuat'). "
    if timeouts:
        msg += f"Catatan: {timeouts} laporan memakai narasi standar karena penulisan narasi melewati batas waktu. "
    if dropped:
        msg += f"Catatan: {dropped} kalimat narasi dibuang pemeriksa angka. "
    out["message"] = msg.strip()
    return out


def _num(v, default: float) -> float:
    try:
        return float(default if v is None or v == "" else v)
    except (TypeError, ValueError):
        return float(default)


def _r(v):
    return None if v is None else round(float(v), 2)


RFM_TOOLS = [analisis_rfm]
