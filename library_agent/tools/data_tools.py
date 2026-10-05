"""Tool ADK untuk data BigQuery lewat Data Agent "Marketing Intelligence"."""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import data_agent, insights
from ..clients import get_user_id
from ..config import live
from .library_tools import ACTIVE_KEY, DEFAULT_WORKSPACE, WORKSPACE_KEY

logger = logging.getLogger(__name__)

HISTORY_KEY = "bq_history"
LAST_KEY = "bq_last"


def ask_marketing_intelligence(question: str, tool_context: ToolContext) -> dict[str, Any]:
    """Menjawab pertanyaan data pasar dari BigQuery lewat Data Agent Marketing Intelligence.

    Gunakan untuk SEMUA pertanyaan data survei retail: harga jual/tebus, HET, HTO, gap harga,
    margin, TOV, Product Hero, kompetitor, zona/region, segmen MCO/PCO/Commercial, tren per periode.

    Args:
        question: Pertanyaan user dalam bahasa alami, lengkap dengan konteks yang relevan dari
            percakapan (mis. periode, zona, produk yang sedang dibahas).

    Returns:
        answer (teks dari Data Agent), tables (tabel markdown hasil query), source.
    """
    history = list(tool_context.state.get(HISTORY_KEY, []))
    mode = (live("data_auth_mode") or "user").strip().lower()
    token = None
    if mode == "user":
        token = data_agent.find_user_token(tool_context.state, live("data_auth_id") or "mia-bigquery")
        if not token:
            return {"status": "needs_authorization",
                    "message": ("Untuk mengambil data BigQuery, akun Anda perlu diotorisasi terlebih dahulu. "
                                "Klik tombol Authorize/Otorisasi yang muncul di Gemini Enterprise untuk agent ini, "
                                "lalu kirim ulang pertanyaan. Jika tombol tidak muncul, buka chat baru.")}
    try:
        result = data_agent.ask(question, history, access_token=token)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Data Agent gagal")
        text = str(exc)
        kind = data_agent.classify_error(text)
        if kind == "token" and mode == "user":
            return {"status": "needs_authorization",
                    "message": "Otorisasi akun Anda sudah kedaluwarsa. Buka chat baru dan klik Authorize/Otorisasi lagi."}
        hint = ""
        if kind == "permission":
            hint = (" Akun Anda belum memiliki akses ke Data Agent atau tabel BigQuery-nya." if mode == "user"
                    else " Service account agent belum memiliki izin ke Data Agent atau tabel BigQuery-nya.")
        return {"status": "error", "message": f"Data tidak bisa diambil saat ini.{hint}", "detail": text[:300]}

    if result["errors"] and not result["answer"]:
        return {"status": "error", "message": "Data Agent tidak bisa menjawab pertanyaan ini.",
                "detail": "; ".join(result["errors"])[:500]}

    history.append({"question": question, "answer": result["answer"][:2000]})
    tool_context.state[HISTORY_KEY] = history[-data_agent.MAX_HISTORY:]
    tool_context.state[LAST_KEY] = dict(data_agent.trim_for_state(result), question=question)
    return {
        "status": "ok",
        "answer": result["answer"],
        "tables": [data_agent.table_to_markdown(t) for t in result["tables"][:2]],
        "source": data_agent.SOURCE_LABEL,
        "note": "Grafik dari Data Agent tidak tampil di chat ini; grafik tersedia di laporan.",
    }


def save_data_insight(title: str, content: str, citations: list[str], tool_context: ToolContext) -> dict[str, Any]:
    """Menyimpan jawaban data BigQuery TERAKHIR sebagai insight, BESERTA tabel datanya.

    Tabel data ikut tersimpan agar grafik dan angka di laporan berasal dari data asli.

    Args:
        title: Judul singkat insight.
        content: Ringkasan temuan, memakai angka persis dari jawaban Data Agent.
        citations: Sumber, mis. ["[Survey Response Report Retail, Mei 2026]"].
    """
    last = tool_context.state.get(LAST_KEY)
    if not last:
        return {"status": "error", "message": "Belum ada jawaban data BigQuery di chat ini untuk disimpan."}
    table = (last.get("tables") or [None])[0]
    item = insights.save(
        owner=get_user_id(tool_context),
        workspace=tool_context.state.get(WORKSPACE_KEY, DEFAULT_WORKSPACE),
        title=title, content=content, citations=citations or [f"[{data_agent.SOURCE_LABEL}]"],
        doc_keys=[], source="bigquery",
        data_table=dict(table, question=last.get("question", "")) if table else None,
    )
    return {"status": "ok", "workspace": tool_context.state.get(WORKSPACE_KEY, DEFAULT_WORKSPACE), "insight": item}


DATA_TOOLS = [ask_marketing_intelligence, save_data_insight]
