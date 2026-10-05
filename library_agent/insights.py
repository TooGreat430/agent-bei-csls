"""Penyimpanan insight di Cloud Storage (satu file JSON per workspace).

Lokasi: gs://<LIB_BUCKET>/<LIB_INSIGHT_PREFIX>/<workspace>.json

Format:
    {"insights": {"<insight_id>": {owner, title, content, citations, doc_keys,
                                    created_at, updated_at}}}

Aturan akses:
- Semua user di workspace yang sama bisa MELIHAT dan MEMAKAI insight untuk laporan.
- Hanya pembuat insight yang bisa MENGUBAH atau MENGHAPUS insight miliknya.

Insight tetap ada walaupun user membuka chat baru.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from . import store
from .config import settings


def workspace_slug(workspace: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", workspace.strip().lower()).strip("-")
    return slug or "umum"


def _path(workspace: str) -> str:
    return f"{settings.insight_prefix}/{workspace_slug(workspace)}.json"


def _empty() -> dict[str, Any]:
    return {"insights": {}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _view(insight_id: str, data: dict[str, Any], full: bool = False) -> dict[str, Any]:
    view = {
        "insight_id": insight_id,
        "owner": data.get("owner"),
        "title": data.get("title"),
        "content": data.get("content"),
        "citations": data.get("citations", []),
        "doc_keys": data.get("doc_keys", []),
        "source": data.get("source", "dokumen"),
        "has_data_table": bool(data.get("data")),
        "has_chart": bool(data.get("chart")),
    }
    if full:
        view["data"] = data.get("data")
        view["chart"] = data.get("chart")
    return view


def _load(workspace: str) -> dict[str, dict[str, Any]]:
    return store.read_json(_path(workspace), _empty).get("insights", {})


def save(owner: str, workspace: str, title: str, content: str,
         citations: list[str], doc_keys: list[str], source: str = "dokumen",
         data_table: dict[str, Any] | None = None, chart: dict[str, Any] | None = None) -> dict[str, Any]:
    """Simpan insight. `source`: "dokumen" atau "bigquery". `data_table`: hasil query BQ pendukung."""
    insight_id = f"ins-{uuid.uuid4().hex[:10]}"
    data = {
        "owner": owner,
        "title": title.strip(),
        "content": content.strip(),
        "citations": citations,
        "doc_keys": doc_keys,
        "source": source,
        "data": data_table,
        "chart": chart,
        "created_at": _now(),
        "updated_at": _now(),
    }

    def mutate(doc: dict[str, Any]) -> None:
        doc.setdefault("insights", {})[insight_id] = data

    store.update_json(_path(workspace), _empty, mutate)
    return _view(insight_id, data)


def list_for(workspace: str) -> list[dict[str, Any]]:
    items = sorted(_load(workspace).items(), key=lambda it: it[1].get("created_at", ""))
    return [_view(i, d) for i, d in items]


def get_many(workspace: str, insight_ids: list[str], full: bool = False) -> list[dict[str, Any]]:
    all_items = _load(workspace)
    return [_view(i, all_items[i], full) for i in insight_ids if i in all_items]


def list_full(workspace: str) -> list[dict[str, Any]]:
    """Semua insight beserta tabel datanya (untuk penyusunan laporan)."""
    items = sorted(_load(workspace).items(), key=lambda it: it[1].get("created_at", ""))
    return [_view(i, d, full=True) for i, d in items]


def update(user: str, workspace: str, insight_id: str,
           title: str | None, content: str | None) -> dict[str, Any]:
    """Hasil: {"status": "ok"|"not_found"|"forbidden", "insight": ...}."""
    def mutate(doc: dict[str, Any]) -> dict[str, Any]:
        item = doc.get("insights", {}).get(insight_id)
        if not item:
            return {"status": "not_found"}
        if item.get("owner") != user:
            return {"status": "forbidden", "owner": item.get("owner")}
        if title:
            item["title"] = title.strip()
        if content:
            item["content"] = content.strip()
        item["updated_at"] = _now()
        return {"status": "ok", "insight": _view(insight_id, item)}

    return store.update_json(_path(workspace), _empty, mutate)


def delete(user: str, workspace: str, insight_id: str) -> dict[str, Any]:
    """Hasil: {"status": "ok"|"not_found"|"forbidden"}."""
    def mutate(doc: dict[str, Any]) -> dict[str, Any]:
        items = doc.get("insights", {})
        item = items.get(insight_id)
        if not item:
            return {"status": "not_found"}
        if item.get("owner") != user:
            return {"status": "forbidden", "owner": item.get("owner")}
        del items[insight_id]
        return {"status": "ok"}

    return store.update_json(_path(workspace), _empty, mutate)
