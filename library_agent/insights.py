"""Penyimpanan insight di Cloud Storage (satu file JSON per user).

Lokasi: gs://<LIB_BUCKET>/<LIB_INSIGHT_PREFIX>/<user>.json   (default prefix: insights)

Format:
    {"insights": {"<insight_id>": {title, content, citations, doc_keys,
                                    workspace, created_at, updated_at}}}

Insight adalah temuan penting dari diskusi yang disimpan user, lengkap dengan
sitasi. Insight menjadi landasan penyusunan laporan, sehingga user tidak perlu
mengetik ulang hasil analisisnya. Insight tetap ada walaupun user membuka chat baru.

Karena file dipisah per user, user hanya bisa membaca dan mengubah insight miliknya.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from . import store
from .config import settings


def _path(owner: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._@-]+", "_", owner)
    return f"{settings.insight_prefix}/{slug}.json"


def _empty() -> dict[str, Any]:
    return {"insights": {}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _view(insight_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "insight_id": insight_id,
        "title": data.get("title"),
        "content": data.get("content"),
        "citations": data.get("citations", []),
        "doc_keys": data.get("doc_keys", []),
        "workspace": data.get("workspace"),
    }


def _load(owner: str) -> dict[str, dict[str, Any]]:
    return store.read_json(_path(owner), _empty).get("insights", {})


def save(owner: str, workspace: str, title: str, content: str,
         citations: list[str], doc_keys: list[str]) -> dict[str, Any]:
    insight_id = f"ins-{uuid.uuid4().hex[:10]}"
    data = {
        "workspace": workspace,
        "title": title.strip(),
        "content": content.strip(),
        "citations": citations,
        "doc_keys": doc_keys,
        "created_at": _now(),
        "updated_at": _now(),
    }

    def mutate(doc: dict[str, Any]) -> None:
        doc.setdefault("insights", {})[insight_id] = data

    store.update_json(_path(owner), _empty, mutate)
    return _view(insight_id, data)


def list_for(owner: str, workspace: str) -> list[dict[str, Any]]:
    items = [(i, d) for i, d in _load(owner).items() if d.get("workspace") == workspace]
    items.sort(key=lambda it: it[1].get("created_at", ""))
    return [_view(i, d) for i, d in items]


def get_many(owner: str, insight_ids: list[str]) -> list[dict[str, Any]]:
    all_items = _load(owner)
    return [_view(i, all_items[i]) for i in insight_ids if i in all_items]


def update(owner: str, insight_id: str, title: str | None, content: str | None) -> dict[str, Any] | None:
    def mutate(doc: dict[str, Any]) -> dict[str, Any] | None:
        item = doc.get("insights", {}).get(insight_id)
        if not item:
            return None
        if title:
            item["title"] = title.strip()
        if content:
            item["content"] = content.strip()
        item["updated_at"] = _now()
        return _view(insight_id, item)

    return store.update_json(_path(owner), _empty, mutate)


def delete(owner: str, insight_id: str) -> bool:
    def mutate(doc: dict[str, Any]) -> bool:
        return doc.get("insights", {}).pop(insight_id, None) is not None

    return store.update_json(_path(owner), _empty, mutate)
