"""Meteran biaya: mencatat pemakaian model & sandbox per hari, dan menegakkan batas anggaran harian.

Dicatat di gs://<bucket>/<folder>/usage/YYYY-MM-DD.json (tanggal WIB). Angkanya ESTIMASI dari jumlah token yang
dilaporkan model × tarif di settings.json (price_*), plus durasi eksekusi sandbox × tarif vCPU/GiB. Tagihan resmi
tetap di Cloud Billing; meteran ini untuk pengaman dan pemantauan harian.

- record_model_usage: after_model_callback (dipasang di semua agent) — token input, cache, output, thinking.
- record_sandbox: dipanggil tool eksekusi kode setelah setiap eksekusi.
- budget_status: dipakai tool eksekusi kode sebelum berjalan; jika biaya hari ini ≥ batas, eksekusi ditolak.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import live, settings

logger = logging.getLogger(__name__)
WIB = timezone(timedelta(hours=7))
PRO_AGENTS = {"file_agent", "report_agent"}


def today() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d")


def _path(day: str) -> str:
    from .config import _internal

    return _internal(f"usage/{day}.json")


def this_month() -> str:
    return datetime.now(WIB).strftime("%Y-%m")


def _empty(day: str) -> dict[str, Any]:
    return {"date": day, "total_usd": 0.0,
            "model": {"calls": 0, "input": 0, "cached": 0, "output": 0, "usd": 0.0, "by_model": {}},
            "sandbox": {"executions": 0, "seconds": 0.0, "usd": 0.0}, "by_user": {}}


def read_day(day: str | None = None) -> dict[str, Any]:
    from .clients import storage_client

    day = day or today()
    try:
        raw = storage_client().bucket(settings.bucket).blob(_path(day)).download_as_bytes()
        return json.loads(raw)
    except Exception:  # noqa: BLE001  (belum ada pemakaian hari itu)
        return _empty(day)


_BUFFER: dict[str, Any] = {"ops": [], "usd": 0.0, "last_flush": 0.0}
FLUSH_SECONDS = 20


def _queue(op, usd: float) -> None:
    """Catat di buffer memori; tulis ke bucket paling sering tiap FLUSH_SECONDS (hindari batas tulis per objek)."""
    _BUFFER["ops"].append(op)
    _BUFFER["usd"] += usd
    if time.time() - _BUFFER["last_flush"] >= FLUSH_SECONDS:
        flush()


def flush() -> None:
    ops, _BUFFER["ops"] = _BUFFER["ops"], []
    _BUFFER["usd"] = 0.0
    _BUFFER["last_flush"] = time.time()
    if not ops:
        return

    def mutate(d):
        for op in ops:
            op(d)
    _update(mutate)                                   # file harian
    _update(mutate, this_month())                     # file bulanan (untuk batas bulanan)
    _CACHE["at"] = 0.0


def _update(mutate, key: str | None = None) -> None:
    """Baca–ubah–tulis dengan if_generation_match agar aman dari tulis bersamaan."""
    from .clients import storage_client

    day = key or today()
    blob = storage_client().bucket(settings.bucket).blob(_path(day))
    for _ in range(5):
        gen = 0
        try:
            blob.reload()
            gen = blob.generation or 0
            data = json.loads(blob.download_as_bytes(if_generation_match=gen))
        except Exception:  # noqa: BLE001
            gen, data = 0, _empty(day)
        mutate(data)
        try:
            blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=1), content_type="application/json",
                                    if_generation_match=gen)
            return
        except Exception as exc:  # noqa: BLE001  (conflict -> ulang)
            if "412" not in str(exc) and "Precondition" not in str(exc):
                logger.warning("Meteran biaya gagal disimpan: %s", str(exc)[:200])
                return
            time.sleep(0.2)
    logger.warning("Meteran biaya: konflik tulis berulang, satu catatan dilewati")


def model_cost(agent_name: str, prompt: int, cached: int, output: int) -> tuple[str, float]:
    pro = agent_name in PRO_AGENTS
    model = settings.model_pro if pro else settings.model_fast
    p_in, p_out, p_cache = (("price_pro_input", "price_pro_output", "price_pro_cached") if pro
                            else ("price_fast_input", "price_fast_output", "price_fast_cached"))
    usd = ((max(prompt - cached, 0) * float(live(p_in)) + cached * float(live(p_cache))
            + output * float(live(p_out))) / 1_000_000)
    return model, usd


def sandbox_cost(seconds: float) -> float:
    per_hour = (float(live("price_sandbox_vcpu_hour")) * settings.sandbox_vcpu
                + float(live("price_sandbox_gib_hour")) * settings.sandbox_gib)
    return seconds / 3600 * per_hour


def _add_user(data: dict, user: str, usd: float) -> None:
    data["by_user"][user] = round(data["by_user"].get(user, 0.0) + usd, 6)
    data["total_usd"] = round(data.get("total_usd", 0.0) + usd, 6)


def record_model_usage(callback_context, llm_response) -> None:
    """after_model_callback: catat token & biaya model. Tidak pernah mengubah jawaban."""
    meta = getattr(llm_response, "usage_metadata", None)
    if not meta:
        return None
    try:
        from .clients import get_user_id

        prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
        cached = int(getattr(meta, "cached_content_token_count", 0) or 0)
        output = int(getattr(meta, "candidates_token_count", 0) or 0) + int(getattr(meta, "thoughts_token_count", 0) or 0)
        agent = getattr(callback_context, "agent_name", "") or ""
        model, usd = model_cost(agent, prompt, cached, output)
        user = get_user_id(callback_context)

        def mutate(d):
            m = d["model"]
            m["calls"] += 1
            m["input"] += prompt
            m["cached"] += cached
            m["output"] += output
            m["usd"] = round(m["usd"] + usd, 6)
            bm = m["by_model"].setdefault(model, {"calls": 0, "usd": 0.0})
            bm["calls"] += 1
            bm["usd"] = round(bm["usd"] + usd, 6)
            _add_user(d, user, usd)
        _queue(mutate, usd)
    except Exception:  # noqa: BLE001  (meteran tidak boleh mengganggu agent)
        logger.warning("Meteran biaya model gagal", exc_info=True)
    return None


def record_sandbox(user: str, seconds: float) -> float:
    usd = sandbox_cost(seconds)

    def mutate(d):
        s = d["sandbox"]
        s["executions"] += 1
        s["seconds"] = round(s["seconds"] + seconds, 2)
        s["usd"] = round(s["usd"] + usd, 6)
        _add_user(d, user, usd)
    try:
        _queue(mutate, usd)
    except Exception:  # noqa: BLE001
        logger.warning("Meteran biaya sandbox gagal", exc_info=True)
    return usd


def budget_status() -> dict[str, Any]:
    d = read_day()
    spent = d.get("total_usd", 0.0) + _BUFFER["usd"]          # termasuk catatan yang belum ditulis
    cap = float(live("code_execution_daily_budget_usd") or 0)
    return {"date": d["date"], "spent_usd": round(spent, 4), "budget_usd": cap, "exceeded": cap > 0 and spent >= cap}


def chain(*callbacks):
    """Gabungkan beberapa after_model_callback: jalankan berurutan, kembalikan hasil pertama yang bukan None."""
    def combined(callback_context, llm_response):
        result = None
        for cb in callbacks:
            out = cb(callback_context, llm_response)
            if out is not None and result is None:
                result = out
        return result
    return combined


# ==========================================================================
# Batas pemakaian harian / bulanan + notifikasi ke user
# ==========================================================================
_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
CACHE_SECONDS = 60


def budget_overview(force: bool = False) -> dict[str, Any]:
    """Pemakaian hari ini & bulan ini vs batas. level: ok | warn | exceeded."""
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["at"] < CACHE_SECONDS:
        base = _CACHE["data"]
    else:
        base = {"day": read_day().get("total_usd", 0.0), "month": read_day(this_month()).get("total_usd", 0.0)}
        _CACHE.update(at=now, data=base)
    day_spent, month_spent = base["day"] + _BUFFER["usd"], base["month"] + _BUFFER["usd"]
    caps = {"harian": float(live("budget_daily_usd") or 0), "bulanan": float(live("budget_monthly_usd") or 0)}
    warn_pct = float(live("budget_warn_pct") or 80)
    out = {"harian": {"terpakai_usd": round(day_spent, 4), "batas_usd": caps["harian"]},
           "bulanan": {"terpakai_usd": round(month_spent, 4), "batas_usd": caps["bulanan"]},
           "level": "ok", "periode": None, "persen": 0.0}
    for name, spent in (("harian", day_spent), ("bulanan", month_spent)):
        cap = caps[name]
        if cap <= 0:
            continue
        pct = spent / cap * 100
        out[name]["persen"] = round(pct, 1)
        level = "exceeded" if pct >= 100 else "warn" if pct >= warn_pct else "ok"
        rank = {"ok": 0, "warn": 1, "exceeded": 2}
        if rank[level] > rank[out["level"]] or (level == out["level"] and pct > out["persen"]):
            out.update(level=level, periode=name, persen=round(pct, 1))
    return out


def heavy_allowed() -> tuple[bool, str]:
    """Laporan & analisis berbasis kode boleh berjalan? (False + pesan untuk user bila batas tercapai)."""
    try:
        ov = budget_overview()
    except Exception:  # noqa: BLE001  (meteran tidak boleh menghentikan agent)
        return True, ""
    if ov["level"] != "exceeded":
        return True, ""
    return False, block_text(ov)


def _reset_text(periode: str) -> str:
    return "besok pukul 00.00 WIB" if periode == "harian" else "awal bulan depan"


def block_text(ov: dict[str, Any]) -> str:
    p = ov["periode"]
    scope = str(live("budget_block_scope") or "berat").lower()
    what = ("Agent tidak dapat memproses permintaan" if scope == "semua"
            else "Pembuatan laporan dan analisis berbasis kode dihentikan sementara")
    rest = "" if scope == "semua" else " Pertanyaan data dan analisis biasa tetap bisa dijawab."
    return (f"⚠️ Batas pemakaian {p} agent (USD {ov[p]['batas_usd']:g}) sudah tercapai. {what} sampai "
            f"{_reset_text(p)}.{rest} Hubungi admin bila perlu dinaikkan.")


def warn_text(ov: dict[str, Any]) -> str:
    p = ov["periode"]
    return (f"ℹ️ Info: pemakaian {p} agent sudah {ov['persen']:.0f}% dari batas (USD {ov[p]['terpakai_usd']:.2f} dari "
            f"USD {ov[p]['batas_usd']:g}). Saat batas tercapai, pembuatan laporan dihentikan sementara sampai "
            f"{_reset_text(p)}.")


def budget_guard(callback_context, llm_request):
    """before_model_callback: bila cakupan 'semua' dan batas tercapai, jawab langsung tanpa memanggil model."""
    if str(live("budget_block_scope") or "berat").lower() != "semua":
        return None
    try:
        ov = budget_overview()
    except Exception:  # noqa: BLE001
        return None
    if ov["level"] != "exceeded":
        return None
    from google.adk.models import LlmResponse
    from google.genai import types

    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=block_text(ov))]))


def budget_notice(callback_context, llm_response) -> None:
    """after_model_callback: tempel pemberitahuan kuota pada jawaban akhir — sekali per chat per hari per level."""
    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) or []
    if not parts or any(getattr(p, "function_call", None) for p in parts) or not any(getattr(p, "text", None) for p in parts):
        return None
    try:
        ov = budget_overview()
    except Exception:  # noqa: BLE001
        return None
    if ov["level"] == "ok":
        return None
    flag = f"budget_notice_{today()}_{ov['level']}_{ov['periode']}"
    state = callback_context.state
    if state.get(flag):
        return None
    from google.genai import types

    text = block_text(ov) if ov["level"] == "exceeded" else warn_text(ov)
    parts.append(types.Part(text="\n\n" + text))
    state[flag] = True
    return None


def chain_before(*callbacks):
    """Gabungkan before_model_callback: hasil pertama yang bukan None menghentikan rantai."""
    def combined(callback_context, llm_request):
        for cb in callbacks:
            out = cb(callback_context, llm_request)
            if out is not None:
                return out
        return None
    return combined
