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
    _update(mutate)


def _update(mutate) -> None:
    """Baca–ubah–tulis dengan if_generation_match agar aman dari tulis bersamaan."""
    from .clients import storage_client

    day = today()
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
