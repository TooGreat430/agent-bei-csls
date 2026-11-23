"""Beberapa laporan berbeda dalam SATU pesan: dikerjakan paralel dengan batas waktu internal (tanpa DEADLINE_EXCEEDED)."""
from __future__ import annotations

import copy
import inspect
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from google.adk.tools import ToolContext

from .rfm_tools import _num, heavy_turn

logger = logging.getLogger(__name__)


def _safe(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"Paket laporan gagal: {str(exc)[:300]}"}
    return wrapper
MAX_WORKERS = 6
MAX_ITEMS = 10
MIN_WAIT = 10.0

# jenis -> (nama fungsi di modul, parameter yang boleh diisi dari item)
KINDS = {
    "harga": ("report_tools", "generate_price_dashboard", ("period", "compare_period", "title")),
    "industri": ("report_tools", "generate_industry_report", ("period", "competitor", "title")),
    "planogram": ("report_tools", "generate_planogram_report", ("period", "compare_period", "title", "focus")),
    "battlefield": ("report_tools", "generate_battlefield_report", ("period", "compare_period", "title", "focus")),
    "custom": ("report_tools", "generate_custom_report", ("request", "source", "period", "data_questions", "file_id",
                                                          "instruction_doc_id")),
    "rfm": ("rfm_tools", "analisis_rfm", ("region", "cutoff", "fokus")),
    "visual": ("visual_report_tools", "buat_laporan_visual", ("permintaan", "sumber", "file_id", "period", "judul")),
}
ALIASES = {"dashboard": "harga", "dashboard_harga": "harga", "daya_saing_harga": "harga", "price": "harga",
           "retail": "harga", "industry": "industri", "b2b": "industri", "competitive_battlefield": "battlefield",
           "laporan_custom": "custom", "kustom": "custom", "rfm_outlet": "rfm",
           "laporan_visual": "visual", "deck": "visual", "presentasi": "visual"}
NO_FORMAT = {"rfm"}            # RFM selalu HTML + Excel


def parse_item(text: str) -> tuple[str, dict[str, Any]]:
    """'custom | source=retail | request=Analisis harga Fastron' -> ('custom', {...})."""
    parts = [p.strip() for p in (text or "").split("|")]
    kind = parts[0].lower().replace(" ", "_").replace("-", "_") if parts else ""
    kind = ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise ValueError(f"jenis laporan '{parts[0] if parts else ''}' tidak dikenal (pilihan: {', '.join(KINDS)})")
    allowed = set(KINDS[kind][2]) | ({"format"} if kind not in NO_FORMAT else set())
    params: dict[str, Any] = {}
    for p in parts[1:]:
        if not p:
            continue
        if "=" not in p:
            key = {"custom": "request", "visual": "permintaan"}.get(kind, "")
            key = key if key and key not in params else ""
            if not key:
                raise ValueError(f"bagian '{p}' harus berbentuk kunci=nilai")
            params[key] = p
            continue
        k, v = (x.strip() for x in p.split("=", 1))
        k = k.lower()
        if k not in allowed:
            raise ValueError(f"'{k}' tidak berlaku untuk laporan {kind} (boleh: {', '.join(sorted(allowed))})")
        params[k] = [q.strip() for q in v.split(";") if q.strip()] if k == "data_questions" else v
    if kind == "custom" and not (params.get("request") and params.get("source")):
        raise ValueError("laporan custom butuh request=... dan source=...")
    return kind, params


class _State:
    """State per-thread: baca dari state sesi, tulis ke lapisan sendiri (digabung setelah semua selesai)."""

    def __init__(self, base):
        self._base, self.writes = base, {}

    def get(self, key, default=None):
        if key in self.writes:
            return self.writes[key]
        return copy.deepcopy(self._base.get(key, default))

    def __getitem__(self, key):
        val = self.get(key, _MISSING)
        if val is _MISSING:
            raise KeyError(key)
        return val

    def __setitem__(self, key, value):
        self.writes[key] = value

    def __contains__(self, key):
        return key in self.writes or key in self._base

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


_MISSING = object()


class _Ctx:
    """Konteks tool untuk satu laporan di dalam paket (atribut lain diteruskan ke konteks asli)."""

    def __init__(self, real):
        self._real = real
        self.state = _State(real.state)

    def __getattr__(self, name):
        return getattr(self._real, name)


def merge_states(real_state, base_snapshot: dict, layers: list[dict]) -> None:
    """Gabungkan tulisan tiap laporan ke state sesi: list = tambah item baru (tanpa ganda), lainnya = penulis
    terakhir menang, penghitung urut (…_seq) = nilai terbesar; ID tarikan data yang bentrok diberi nomor baru."""
    for layer in layers:
        for key, val in layer.items():
            if key.startswith("temp:") or key == "heavy_report_turn":
                continue
            if isinstance(val, list):
                before = base_snapshot.get(key) or []
                current = list(real_state.get(key) or [])
                for item in val:
                    if item in before or item in current:
                        continue
                    if isinstance(item, dict) and key == "bq_pulls" and any(
                            isinstance(c, dict) and c.get("id") == item.get("id") for c in current):
                        seq = int(real_state.get("bq_pull_seq", 0) or 0) + 1
                        real_state["bq_pull_seq"] = seq
                        item = dict(item, id=f"p{seq}")
                    current.append(item)
                real_state[key] = current[-30:]
            elif key.endswith("_seq"):
                real_state[key] = max(int(real_state.get(key, 0) or 0), int(val or 0))
            else:
                real_state[key] = val


def _raw(kind: str):
    import importlib

    mod_name, fn_name, _ = KINDS[kind]
    mod = importlib.import_module(f"library_agent.tools.{mod_name}")
    return inspect.unwrap(getattr(mod, fn_name))      # lewati pembatas per pesan & pembungkus log


@_safe
@heavy_turn("paket laporan")
def buat_laporan_sekaligus(tool_context: ToolContext, laporan: list[str], output_format: str = "") -> dict[str, Any]:
    """Membuat BEBERAPA LAPORAN BERBEDA SEKALIGUS dalam satu pesan — dikerjakan PARALEL dengan batas waktu internal,
    jadi tidak terkena DEADLINE_EXCEEDED. Pakai ini setiap kali user meminta 2 laporan atau lebih dalam satu pesan
    (mis. "dashboard harga Q3 dan laporan planogram", "laporan custom retail dan industri sekaligus"). JANGAN
    memanggil generate_* berulang kali dalam satu pesan. (RFM banyak region cukup satu item: "rfm | region=semua".)

    Args:
        laporan: Daftar laporan, satu teks per laporan dengan format "jenis | kunci=nilai | kunci=nilai".
            Jenis & kunci:
            - "harga | period=2026-Q3 | compare_period=2026-Q2"   (dashboard daya saing harga retail)
            - "industri | period=Agustus 2026 | competitor=Shell"
            - "planogram | period=2026-Q3 | compare_period=2026-Q2 | focus=..."
            - "battlefield | period=2026-Q3 | compare_period=2026-Q2"
            - "custom | source=retail | request=Analisis harga Fastron di Zona 2 Q3 untuk manajemen"
              (source: retail / industri / planogram / sellout / retail_planogram; opsional data_questions=a; b)
            - "rfm | region=semua"  (atau region=SR1, SR3 / nasional; hasil selalu HTML + Excel)
            - "visual | sumber=retail | permintaan=deck temuan harga Q3"  (laporan visual otomatis)
            Tambahkan "format=pdf" pada satu item bila formatnya beda dari output_format.
        output_format: Format untuk semua laporan non-RFM: "html", "pdf", "pptx" atau gabungan "pdf,pptx". Kosongkan
            bila user belum memilih — alat akan meminta Anda menanyakannya sekali untuk semua laporan.
    """
    from ..config import live

    t0 = time.monotonic()
    items = [x for x in (laporan or []) if str(x).strip()]
    if not items:
        return {"status": "needs_input", "message": "Tanyakan ke user laporan apa saja yang ingin dibuat."}
    if len(items) > MAX_ITEMS:
        return {"status": "invalid", "message": f"Maksimal {MAX_ITEMS} laporan per pesan; bagi permintaannya."}
    parsed, errors = [], []
    for i, text in enumerate(items, 1):
        try:
            parsed.append((text, *parse_item(str(text))))
        except ValueError as exc:
            errors.append(f"laporan {i} ('{str(text)[:60]}'): {exc}")
    if errors:
        return {"status": "invalid", "message": "Perbaiki daftar laporan lalu panggil lagi: " + "; ".join(errors)}
    if any(k not in NO_FORMAT and not (p.get("format") or output_format.strip()) for _, k, p in parsed):
        return {"status": "needs_input", "available_formats": ["html", "pdf", "pptx"],
                "message": ("Tanyakan SEKALI ke user format untuk semua laporan (boleh lebih dari satu): HTML, PDF, "
                            "atau PowerPoint. Laporan RFM selalu HTML + Excel.")}

    budget = _num(live("batch_time_budget"), 300)
    base_snapshot = {}
    for key in ("bq_pulls", "custom_reports", "rfm_reports", "insight_charts", "bq_history", "bq_last",
                "visual_reports"):
        try:
            base_snapshot[key] = copy.deepcopy(tool_context.state.get(key))
        except Exception:  # noqa: BLE001
            pass

    def run(kind: str, params: dict, ctx: _Ctx):
        kwargs = {k: v for k, v in params.items() if k != "format"}
        if kind not in NO_FORMAT:
            kwargs["output_format"] = params.get("format") or output_format
        return _raw(kind)(tool_context=ctx, **kwargs)

    pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(parsed)), thread_name_prefix="paket-laporan")
    jobs = []
    for text, kind, params in parsed:
        ctx = _Ctx(tool_context)
        jobs.append((text, kind, ctx, pool.submit(run, kind, params, ctx)))
    done, _ = wait([j[3] for j in jobs], timeout=max(MIN_WAIT, budget))
    pool.shutdown(wait=False, cancel_futures=True)

    hasil, tertunda, layers = [], [], []
    for text, kind, ctx, fut in jobs:
        if fut not in done:
            tertunda.append(text)
            continue
        try:
            res = fut.result()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Paket laporan: %s gagal", kind)
            res = {"status": "error", "message": f"Laporan gagal dibuat karena kendala teknis: {str(exc)[:200]}"}
        layers.append(ctx.state.writes)
        hasil.append({"permintaan": text, "jenis": kind, **(res if isinstance(res, dict) else {"status": "error"})})
    merge_states(tool_context.state, base_snapshot, layers)

    ok = sum(1 for h in hasil if h.get("status") == "ok")
    msg = (f"{ok} dari {len(parsed)} laporan selesai dalam satu pesan. Sampaikan SEMUA hasil: untuk tiap laporan "
           "judul/jenis, angka kunci dari hasilnya, dan link. ")
    perlu = [h for h in hasil if h.get("status") in ("needs_input", "invalid", "redirect")]
    if perlu:
        msg += "Beberapa laporan butuh info tambahan dari user (lihat 'message' di item tersebut); tanyakan sekaligus. "
    if any(h.get("status") == "error" for h in hasil):
        msg += "Laporan yang error sampaikan apa adanya dan tawarkan dibuat ulang. "
    if tertunda:
        msg += (f"{len(tertunda)} laporan belum selesai dalam batas waktu satu pesan; tawarkan 'ketik lanjut' lalu "
                "panggil alat ini lagi hanya dengan daftar 'tertunda_batas_waktu'. ")
    out = {"status": "ok" if ok else "error", "durasi_detik": round(time.monotonic() - t0, 1), "hasil": hasil,
           "message": msg.strip()}
    if tertunda:
        out["tertunda_batas_waktu"] = tertunda
    return out


BATCH_TOOLS = [buat_laporan_sekaligus]
