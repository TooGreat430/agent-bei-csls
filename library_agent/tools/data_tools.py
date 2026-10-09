"""Tool ADK untuk data BigQuery lewat Data Agent "Marketing Intelligence"."""
from __future__ import annotations

import logging
from typing import Any

from google.adk.tools import ToolContext

from .. import data_agent, insights
from ..clients import get_user_id
from ..config import live

logger = logging.getLogger(__name__)

HISTORY_KEY = "bq_history"
LAST_KEY = "bq_last"
CHART_KEY = "bq_last_chart"
PENDING_CHART_KEY = "bq_pending_chart"


def ask_marketing_intelligence(question: str, tool_context: ToolContext, domain: str = "retail") -> dict[str, Any]:
    """Menjawab pertanyaan data survei BigQuery lewat Data Agent PTPL (retail atau industri).

    domain "retail": survei outlet/bengkel — harga jual/tebus, HET, HTO, gap Rp/L, margin, TOV,
        Product Hero, KIMAP, segmen MCO/PCO/Commercial/Gear.
    domain "industri": survei industri/B2B — channel (Agro, Construction, Fleet, Manufacturing, Marine,
        Mining), main stage EARLY/NEXT, HTD (Harga Tebus Distributor), gap % vs HTD+3%, produk fokus
        B2B (Meditran, Turalik, Rored HDA, Masri, Medripal, Grease).

    Args:
        question: Pertanyaan user dalam bahasa alami, lengkap dengan konteks yang relevan dari
            percakapan (mis. periode, zona, produk yang sedang dibahas).
        domain: "retail" atau "industri". Jika tidak jelas dari pertanyaan, TANYAKAN ke user dulu.

    Returns:
        answer (teks dari Data Agent), tables (tabel markdown hasil query), source.
    """
    domain = "industri" if str(domain).strip().lower() in ("industri", "industry", "b2b") else "retail"
    agent = live("data_agent_industry") if domain == "industri" else live("data_agent")
    if not agent:
        return {"status": "error", "message": f"Data Agent {domain} belum dikonfigurasi."}
    hist_key = HISTORY_KEY if domain == "retail" else HISTORY_KEY + "_industri"
    history = list(tool_context.state.get(hist_key, []))
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
        result = data_agent.ask(question, history, access_token=token, agent=agent)
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
    tool_context.state[hist_key] = history[-data_agent.MAX_HISTORY:]
    tool_context.state[LAST_KEY] = dict(data_agent.trim_for_state(result), question=question, domain=domain)
    return {
        "status": "ok",
        "answer": result["answer"],
        "tables": [data_agent.table_to_markdown(t) for t in result["tables"][:2]],
        "table_columns": [t["columns"] for t in result["tables"][:2]],
        "source": data_agent.SOURCE_LABELS[domain],
        "domain": domain,
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
        return {"status": "error", "message": "Belum ada jawaban data (BigQuery atau file) di chat ini untuk disimpan."}
    table = (last.get("tables") or [None])[0]
    domain = last.get("domain", "retail")
    if domain == "file":
        label, source = last.get("citation", "File unggahan"), last.get("insight_source", "file")
    else:
        label = data_agent.SOURCE_LABELS[domain]
        source = "bigquery" if domain == "retail" else "bigquery_industri"
    item = insights.save(
        tool_context.state, get_user_id(tool_context),
        title=title, content=content, citations=citations or [f"[{label}]"],
        doc_keys=[], source=source,
        data_table=dict(table, question=last.get("question", "")) if table else None,
        chart=(tool_context.state.get(CHART_KEY) if include_chart else None),
    )
    return {"status": "ok", "insight": item, "total_insight_di_chat": len(insights.list_for(tool_context.state))}


def _safe(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s gagal", func.__name__)
            return {"status": "error", "message": f"Kendala teknis: {str(exc)[:200]}"}
    return wrapper


def ask_retail_intelligence(question: str, tool_context: ToolContext) -> dict[str, Any]:
    """Data survei RETAIL (outlet/bengkel) lewat Data Agent "Retail Marketing Intelligence".

    Untuk: harga jual, harga tebus, HET, HTO, gap harga Rp/L (negatif = PTPL lebih murah), margin bengkel, TOV,
    Product Hero, KIMAP, segmen MCO/PCO/Commercial/Gear, tipe outlet, lokasi outlet.

    Args:
        question: Pertanyaan user dalam bahasa alami, lengkap dengan konteks dari percakapan
            (periode, zona, produk yang sedang dibahas).
    """
    return ask_marketing_intelligence(question, tool_context, domain="retail")


def ask_industry_intelligence(question: str, tool_context: ToolContext) -> dict[str, Any]:
    """Data survei INDUSTRI/B2B lewat Data Agent "Industry Marketing Intelligence".

    Untuk: channel (Agro, Construction, Fleet, Manufacturing, Marine, Mining, dll.), main stage EARLY/NEXT,
    HTD (Harga Tebus Distributor), gap % terhadap HTD+3% (positif = PTPL kompetitif), produk fokus B2B
    (Meditran, Turalik, Rored HDA, Masri, Medripal, Grease), harga kompetitor per liter.

    Args:
        question: Pertanyaan user dalam bahasa alami, lengkap dengan konteks dari percakapan
            (periode, channel, zona, main stage, produk).
    """
    return ask_marketing_intelligence(question, tool_context, domain="industri")


ask_marketing_intelligence = _safe(ask_marketing_intelligence)
ask_retail_intelligence = _safe(ask_retail_intelligence)
ask_industry_intelligence = _safe(ask_industry_intelligence)
create_chart = _safe(create_chart)
save_data_insight = _safe(save_data_insight)
DATA_TOOLS = [ask_retail_intelligence, ask_industry_intelligence, create_chart, save_data_insight]
