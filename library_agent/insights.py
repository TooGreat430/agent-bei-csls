"""Insight = catatan temuan penting yang disimpan di DALAM CHAT (session state).

Insight tidak disimpan ke bucket: hidup selama chat itu ada, hanya terlihat di chat itu, dan
dipakai sebagai bahan laporan di chat yang sama. Tidak ada workspace dan tidak ada penumpukan file.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

STATE_KEY = "insights"
MAX_INSIGHTS = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _items(state: Any) -> list[dict[str, Any]]:
    return [dict(i) for i in (state.get(STATE_KEY) or [])]


def _view(item: dict[str, Any], full: bool = False) -> dict[str, Any]:
    view = {
        "insight_id": item["insight_id"],
        "title": item.get("title"),
        "content": item.get("content"),
        "citations": item.get("citations", []),
        "doc_keys": item.get("doc_keys", []),
        "source": item.get("source", "dokumen"),
        "has_data_table": bool(item.get("data")),
        "has_chart": bool(item.get("chart")),
    }
    if full:
        view["data"] = item.get("data")
        view["chart"] = item.get("chart")
    return view


def save(state: Any, owner: str, title: str, content: str, citations: list[str], doc_keys: list[str],
         source: str = "dokumen", data_table: dict[str, Any] | None = None,
         chart: dict[str, Any] | None = None) -> dict[str, Any]:
    items = _items(state)
    item = {"insight_id": f"ins-{uuid.uuid4().hex[:8]}", "owner": owner, "title": title.strip(),
            "content": content.strip(), "citations": list(citations or []), "doc_keys": list(doc_keys or []),
            "source": source, "data": data_table, "chart": chart, "created_at": _now()}
    items.append(item)
    state[STATE_KEY] = items[-MAX_INSIGHTS:]
    return _view(item)


def list_for(state: Any) -> list[dict[str, Any]]:
    return [_view(i) for i in _items(state)]


def list_full(state: Any) -> list[dict[str, Any]]:
    return [_view(i, full=True) for i in _items(state)]


def get_many(state: Any, insight_ids: list[str], full: bool = False) -> list[dict[str, Any]]:
    wanted = set(insight_ids)
    return [_view(i, full) for i in _items(state) if i["insight_id"] in wanted]


def update(state: Any, insight_id: str, title: str | None, content: str | None) -> dict[str, Any]:
    items = _items(state)
    for item in items:
        if item["insight_id"] == insight_id:
            if title:
                item["title"] = title.strip()
            if content:
                item["content"] = content.strip()
            state[STATE_KEY] = items
            return {"status": "ok", "insight": _view(item)}
    return {"status": "not_found", "message": "Insight tidak ditemukan di chat ini."}


def delete(state: Any, insight_id: str) -> dict[str, Any]:
    items = _items(state)
    kept = [i for i in items if i["insight_id"] != insight_id]
    if len(kept) == len(items):
        return {"status": "not_found", "message": "Insight tidak ditemukan di chat ini."}
    state[STATE_KEY] = kept
    return {"status": "ok", "deleted": insight_id}
