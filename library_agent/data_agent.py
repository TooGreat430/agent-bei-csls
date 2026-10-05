"""Memanggil Data Agent BigQuery (Conversational Analytics API) dari Marketing Insight Assistant.

Data Agent "Marketing Intelligence" sudah berisi aturan bisnis, glossary, Product Hero, dan
verified queries. Agent ini TIDAK menduplikasi aturan itu: setiap pertanyaan data diteruskan
ke Data Agent (stateless chat dengan referensi data agent), lalu jawaban teks dan tabel hasil
query dikembalikan untuk ditampilkan, disimpan sebagai insight, dan dipakai di laporan.

Identitas pemanggil (data_auth_mode):
- "service_account" (default): identitas service account agent; butuh role Data Agent & BigQuery untuk SA.
- "user": token OAuth user dari Gemini Enterprise (Authorization pada pendaftaran agent).
  Query berjalan dengan akses user sendiri, sama seperti Data Agent di GE.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

SOURCE_LABEL = "Survey Response Report Retail"
MAX_TABLE_ROWS = 200
MAX_HISTORY = 3


# ==========================================================================
# Logika murni (bisa diuji tanpa GCP)
# ==========================================================================
def _cell(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 4)
    if isinstance(value, (dict, list)):
        return str(value)
    return value


def parse_stream(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Ubah aliran Message (sudah dalam bentuk dict) menjadi jawaban teks, tabel, SQL, dan error."""
    texts: list[str] = []
    tables: list[dict[str, Any]] = []
    sqls: list[str] = []
    errors: list[str] = []
    for message in messages:
        sm = message.get("system_message") or {}
        text = sm.get("text") or {}
        if text:
            kind = str(text.get("text_type", "")).upper()
            if kind in ("", "0", "TEXT_TYPE_UNSPECIFIED", "FINAL_RESPONSE", "1"):
                texts.extend(p for p in text.get("parts") or [] if p and p.strip())
        data = sm.get("data") or {}
        if data.get("generated_sql"):
            sqls.append(data["generated_sql"])
        result = data.get("result") or {}
        rows = result.get("data") or []
        if rows:
            fields = [f.get("name") for f in ((result.get("schema") or {}).get("fields") or []) if f.get("name")]
            columns = fields or list(rows[0].keys())
            tables.append({
                "columns": columns,
                "rows": [[_cell(r.get(c)) for c in columns] for r in rows[:MAX_TABLE_ROWS]],
                "total_rows": len(rows),
            })
        error = sm.get("error") or {}
        if error.get("text"):
            errors.append(error["text"])
    return {"answer": "\n".join(texts).strip(), "tables": tables, "sql": sqls, "errors": errors}


def table_to_markdown(table: dict[str, Any], max_rows: int = 15) -> str:
    cols = table["columns"]
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for row in table["rows"][:max_rows]:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    if table.get("total_rows", 0) > max_rows:
        lines.append(f"_(menampilkan {max_rows} dari {table['total_rows']} baris)_")
    return "\n".join(lines)


def trim_for_state(result: dict[str, Any], max_rows: int = 60) -> dict[str, Any]:
    """Versi ringkas hasil untuk disimpan di session state / insight."""
    return {
        "answer": result.get("answer", ""),
        "tables": [{"columns": t["columns"], "rows": t["rows"][:max_rows], "total_rows": t.get("total_rows", 0)}
                   for t in result.get("tables", [])[:3]],
    }


# ==========================================================================
# Panggilan API
# ==========================================================================
def _to_dict(message: Any) -> dict[str, Any]:
    try:
        return type(message).to_dict(message, use_integers_for_enums=False)
    except TypeError:
        return type(message).to_dict(message)


def find_user_token(state: Any, auth_id: str) -> str | None:
    """Token OAuth user dari Gemini Enterprise di session state (kunci = ID Authorization)."""
    for key in (auth_id, f"temp:{auth_id}"):
        try:
            value = state.get(key)
        except Exception:  # noqa: BLE001
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def classify_error(text: str) -> str:
    low = text.lower()
    if "401" in text or "unauthenticated" in low or "invalid_grant" in low or "expired" in low:
        return "token"
    if "403" in text or "permission" in low or "denied" in low:
        return "permission"
    return "other"


def ask(question: str, history: list[dict[str, str]] | None = None,
        access_token: str | None = None) -> dict[str, Any]:
    """Kirim pertanyaan ke Data Agent. `history`: [{"question", "answer"}] untuk konteks lanjutan.

    `access_token`: token OAuth user; jika diisi, Data Agent dipanggil atas nama user tersebut.
    """
    from google.cloud import geminidataanalytics as gda

    if not settings.data_agent:
        raise RuntimeError("Data Agent belum dikonfigurasi (LIB_DATA_AGENT).")
    messages = []
    for item in (history or [])[-MAX_HISTORY:]:
        messages.append(gda.Message(user_message=gda.UserMessage(text=item["question"])))
        if item.get("answer"):
            messages.append(gda.Message(system_message=gda.SystemMessage(
                text=gda.TextMessage(parts=[item["answer"]]))))
    messages.append(gda.Message(user_message=gda.UserMessage(text=question)))

    request = gda.ChatRequest(
        parent=f"projects/{settings.data_agent_billing_project}/locations/{settings.data_agent_location}",
        messages=messages,
        data_agent_context=gda.DataAgentContext(data_agent=settings.data_agent),
    )
    if access_token:
        from google.oauth2.credentials import Credentials

        client = gda.DataChatServiceClient(credentials=Credentials(token=access_token))
    else:
        client = gda.DataChatServiceClient()
    stream = client.chat(request=request, timeout=240)
    return parse_stream([_to_dict(m) for m in stream])
