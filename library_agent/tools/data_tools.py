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
CHART_KEY = "bq_last_chart"
PENDING_CHART_KEY = "bq_pending_chart"


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
    mode = (live("data_auth_mode") or "service_account").strip().lower()
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

    tool_context.state[CHART_KEY] = None
    history.append({"question": question, "answer": result["answer"][:2000]})
    tool_context.state[HISTORY_KEY] = history[-data_agent.MAX_HISTORY:]
    tool_context.state[LAST_KEY] = dict(data_agent.trim_for_state(result), question=question)
    return {
        "status": "ok",
        "answer": result["answer"],
        "tables": [data_agent.table_to_markdown(t) for t in result["tables"][:2]],
        "table_columns": [t["columns"] for t in result["tables"][:2]],
        "source": data_agent.SOURCE_LABEL,
    }


def create_chart(x_column: str, y_columns: list[str], tool_context: ToolContext, chart_type: str = "bar",
                 title: str = "", unit: str = "IDR/L", table_index: int = 0) -> dict[str, Any]:
    """Membuat grafik dari tabel hasil query BigQuery TERAKHIR dan menampilkannya di chat.

    Angka diambil langsung dari tabel hasil query, bukan ditulis ulang.

    Args:
        x_column: Nama kolom untuk sumbu X (kategori), mis. zona, produk, brand, atau periode.
        y_columns: 1-4 nama kolom angka untuk sumbu Y, mis. ["GAP_HET_PER_LITER", "GAP_HTO_PER_LITER"].
        chart_type: "bar" untuk perbandingan, "line" untuk tren antar periode.
        title: Judul grafik singkat dalam Bahasa Indonesia.
        unit: Satuan, mis. "IDR/L" atau "IDR".
        table_index: Urutan tabel jika jawaban berisi lebih dari satu tabel (mulai 0).
    """
    from .. import chart_image
    from ..clients import storage_client
    from ..config import settings

    last = tool_context.state.get(LAST_KEY) or {}
    tables = last.get("tables") or []
    if not tables:
        return {"status": "error", "message": "Belum ada tabel data BigQuery di chat ini untuk dibuat grafik."}
    table = tables[min(max(table_index, 0), len(tables) - 1)]
    chart, problem = chart_image.build_chart(table, x_column, y_columns, chart_type, title, unit)
    if not chart:
        return {"status": "error", "message": problem}
    try:
        png = chart_image.render_png(chart)
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = f"{settings.report_prefix}/{get_user_id(tool_context)}/charts/{stamp}.png"
        blob = storage_client().bucket(settings.report_bucket).blob(path)
        blob.upload_from_string(png, content_type="image/png")
        link = f"https://storage.cloud.google.com/{settings.report_bucket}/{path}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Grafik gagal dibuat")
        return {"status": "error", "message": f"Grafik gagal dibuat: {exc}"}
    tool_context.state[CHART_KEY] = dict(chart, question=last.get("question", ""))
    tool_context.state[PENDING_CHART_KEY] = {"bucket": settings.report_bucket, "path": path, "title": chart["judul"]}
    return {"status": "ok", "chart_title": chart["judul"], "link": link,
            "message": "Grafik ditampilkan di bawah jawaban. Sertakan juga link grafik di jawaban."}


def save_data_insight(title: str, content: str, citations: list[str], tool_context: ToolContext,
                      include_chart: bool = True) -> dict[str, Any]:
    """Menyimpan jawaban data BigQuery TERAKHIR sebagai insight, BESERTA tabel datanya.

    Tabel data (dan grafik, jika sudah dibuat) ikut tersimpan agar grafik dan angka di laporan
    berasal dari data asli.

    Args:
        title: Judul singkat insight.
        content: Ringkasan temuan, memakai angka persis dari jawaban Data Agent.
        citations: Sumber, mis. ["[Survey Response Report Retail, Mei 2026]"].
        include_chart: False jika user tidak ingin grafik ini dipakai di laporan.
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
        chart=(tool_context.state.get(CHART_KEY) if include_chart else None),
    )
    return {"status": "ok", "workspace": tool_context.state.get(WORKSPACE_KEY, DEFAULT_WORKSPACE), "insight": item}


DATA_TOOLS = [ask_marketing_intelligence, create_chart, save_data_insight]
