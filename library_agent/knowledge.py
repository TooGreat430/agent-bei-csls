"""Pengetahuan bisnis dari Data Agent (retail & industri) untuk dipakai agent ADK.

Instruksi, glossary, dan contoh query resmi dibaca langsung dari definisi Data Agent lewat API,
sehingga aturan bisnis tetap dikelola tim data di satu tempat. Hasil dibaca disimpan sementara di
memori (TTL) dan salinannya disimpan di bucket (config/knowledge_<domain>.json) sebagai cadangan jika
API tidak bisa diakses.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .config import live, settings

logger = logging.getLogger(__name__)
TTL_SECONDS = 1800
_cache: dict[str, tuple[float, dict]] = {}
DOMAINS = ("retail", "industri")


def _agent_for(domain: str) -> str:
    return live("data_agent_industry") if domain == "industri" else live("data_agent")


def _snapshot_path(domain: str) -> str:
    from .config import _internal

    return _internal(f"config/knowledge_{domain}.json")


def _find(node: Any, key: str) -> list:
    """Cari semua nilai dengan nama field `key` di struktur dict/list (rekursif)."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
            out.extend(_find(v, key))
    elif isinstance(node, list):
        for v in node:
            out.extend(_find(v, key))
    return out


CONTEXT_KEYS = ("published_context", "publishedContext", "last_published_context", "lastPublishedContext",
                "staging_context", "stagingContext")


def has_content(k: dict) -> bool:
    return bool(k.get("instruction") or k.get("examples") or k.get("glossary"))


def parse_definition(raw: dict) -> dict[str, Any]:
    """Instruksi, glossary, dan contoh query dari definisi Data Agent: published -> last published -> staging -> semua."""
    candidates = [c for key in CONTEXT_KEYS for c in _find(raw, key) if isinstance(c, dict) and c]
    for ctx in candidates + [raw]:
        parsed = _parse_context(ctx)
        if has_content(parsed):
            return parsed
    return _parse_context(raw)


def _parse_context(published: dict) -> dict[str, Any]:
    instructions = [s for key in ("system_instruction", "system_instructions", "systemInstruction")
                    for s in _find(published, key) if isinstance(s, str) and s.strip()]
    glossary = []
    for g in _find(published, "glossary_terms") + _find(published, "glossaryTerms"):
        for item in g if isinstance(g, list) else [g]:
            if isinstance(item, str):
                glossary.append(item)
            elif isinstance(item, dict):
                term = item.get("display_name") or item.get("displayName") or item.get("term") or ""
                desc = item.get("description") or item.get("definition") or ""
                glossary.append(f"{term}: {desc}".strip(": "))
    examples = []
    for e in _find(published, "example_queries") + _find(published, "exampleQueries"):
        if isinstance(e, dict) and not ({"natural_language_question", "sql_query", "question", "sql"} & set(e)):
            # Format agent card: {"pertanyaan": ["SQL", ...]}
            for q, sqls in e.items():
                sql = sqls[0] if isinstance(sqls, list) and sqls else (sqls if isinstance(sqls, str) else "")
                examples.append({"question": q, "sql": sql})
            continue
        for item in e if isinstance(e, list) else [e]:
            if isinstance(item, dict):
                q = (item.get("natural_language_question") or item.get("naturalLanguageQuestion")
                     or item.get("question") or "")
                sql = item.get("sql_query") or item.get("sqlQuery") or item.get("sql") or ""
                if q or sql:
                    examples.append({"question": q, "sql": sql})
    tables = []
    for t in _find(published, "table_id") + _find(published, "tableId"):
        if isinstance(t, str):
            tables.append(t)
    for t in _find(published, "table_info"):
        tables.extend(x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str))
    return {"instruction": "\n\n".join(instructions), "glossary": glossary, "examples": examples,
            "tables": sorted(set(tables))}


def fetch_raw(agent: str) -> dict:
    """Definisi Data Agent mentah (dict) dari API — untuk diagnosa."""
    from google.cloud import geminidataanalytics as gda

    client_cls = getattr(gda, "DataAgentServiceClient", None)
    if client_cls is None:
        from google.cloud import geminidataanalytics_v1beta as gda_beta

        client_cls = gda_beta.DataAgentServiceClient
    agent_obj = client_cls().get_data_agent(name=agent)
    return type(agent_obj).to_dict(agent_obj)


def _fetch_api(agent: str) -> dict[str, Any]:
    from google.cloud import geminidataanalytics as gda

    client_cls = getattr(gda, "DataAgentServiceClient", None)
    if client_cls is None:
        from google.cloud import geminidataanalytics_v1beta as gda_beta

        client_cls = gda_beta.DataAgentServiceClient
    agent_obj = client_cls().get_data_agent(name=agent)
    raw = type(agent_obj).to_dict(agent_obj)
    return parse_definition(raw)


def _read_snapshot(domain: str) -> dict | None:
    from .store import read_json

    try:
        return read_json(_snapshot_path(domain), dict) or None
    except Exception:  # noqa: BLE001
        return None


def _write_snapshot(domain: str, data: dict) -> None:
    from .clients import storage_client

    try:
        blob = storage_client().bucket(settings.bucket).blob(_snapshot_path(domain))
        blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type="application/json")
    except Exception:  # noqa: BLE001
        logger.warning("Gagal menyimpan salinan pengetahuan %s", domain)


def save_from_card(domain: str, card: dict) -> dict[str, Any]:
    """Buat salinan pengetahuan dari file agent card (cadangan jika API belum bisa diakses)."""
    data = parse_definition(card)
    data.update(source="agent_card", agent=card.get("url", ""), name=card.get("name", ""))
    _write_snapshot(domain, data)
    _cache.pop(domain, None)
    return data


def get(domain: str, force: bool = False) -> dict[str, Any]:
    """Pengetahuan untuk domain 'retail' atau 'industri'. Selalu mengembalikan dict (bisa kosong)."""
    domain = "industri" if domain == "industri" else "retail"
    now = time.time()
    if not force and domain in _cache and now - _cache[domain][0] < TTL_SECONDS:
        return _cache[domain][1]
    agent = _agent_for(domain)
    data: dict[str, Any] = {}
    if agent:
        try:
            data = _fetch_api(agent)
            data.update(source="api", agent=agent, fetched_at=int(now))
            if has_content(data):
                _write_snapshot(domain, data)
            else:
                logger.warning("Definisi Data Agent %s terbaca tetapi kosong; memakai salinan", domain)
                data = {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Definisi Data Agent %s tidak bisa dibaca (%s); memakai salinan", domain, str(exc)[:200])
            data = {}
        if not data:
            data = _read_snapshot(domain) or {}
            if data:
                data["source"] = "snapshot"
    _cache[domain] = (now, data)
    return data


def as_text(domain: str, max_chars: int = 20000) -> str:
    """Pengetahuan dalam bentuk teks untuk instruksi agent."""
    k = get(domain)
    if not k or not (k.get("instruction") or k.get("examples")):
        return f"(Pengetahuan Data Agent {domain} belum tersedia; gunakan aturan bawaan.)"
    parts = [f"### Pengetahuan resmi Data Agent {domain.upper()} (dikelola tim data)"]
    if k.get("instruction"):
        parts.append(k["instruction"].strip())
    if k.get("glossary"):
        parts.append("Glossary:\n" + "\n".join(f"- {g}" for g in k["glossary"][:60]))
    if k.get("examples"):
        lines = ["Contoh pertanyaan & query resmi (terjemahkan logikanya ke rencana analisis file):"]
        for ex in k["examples"][:12]:
            lines.append(f"- T: {ex['question']}\n  SQL: {' '.join(ex['sql'].split())[:900]}")
        parts.append("\n".join(lines))
    text = "\n\n".join(parts)
    return text[:max_chars]
