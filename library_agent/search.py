"""Pencarian ke data store perpustakaan yang SELALU dibatasi ke dokumen aktif.

Pembatasan ditegakkan lewat filter di level API (bukan hanya instruksi prompt),
sehingga dokumen di luar daftar aktif tidak mungkin ikut terambil.
"""
from __future__ import annotations

import logging
from typing import Any

from . import catalog
from .clients import search_client, serving_config_path
from .config import settings

logger = logging.getLogger(__name__)


def build_doc_filter(doc_keys: list[str]) -> str:
    """Filter Discovery Engine: doc_key: ANY("k1", "k2").

    Field `doc_key` harus ditandai indexable di skema data store
    (lihat setup/datastore_schema.json).
    """
    if not doc_keys:
        raise ValueError("Daftar dokumen aktif kosong.")
    safe = []
    for key in doc_keys:
        if not key or '"' in key or "\\" in key:
            raise ValueError(f"doc_key tidak valid: {key!r}")
        safe.append(f'"{key}"')
    return f"doc_key: ANY({', '.join(safe)})"


def citation_label(title: str, version: str | None, page: Any = None) -> str:
    parts = [title or "Tanpa judul"]
    if version:
        parts.append(f"v{version}" if not str(version).lower().startswith("v") else str(version))
    if page not in (None, "", 0):
        parts.append(f"hal. {page}")
    return "[" + ", ".join(parts) + "]"


def _doc_id_from_chunk_name(name: str) -> str | None:
    # .../branches/default_branch/documents/{doc_id}/chunks/{chunk_id}
    marker = "/documents/"
    if marker not in name:
        return None
    rest = name.split(marker, 1)[1]
    return rest.split("/", 1)[0]


def search_documents(query: str, doc_keys: list[str], max_results: int = 8) -> list[dict[str, Any]]:
    from google.cloud import discoveryengine_v1 as de

    spec_cls = de.SearchRequest.ContentSearchSpec
    use_chunks = settings.search_result_mode.upper() == "CHUNKS"

    if use_chunks:
        content_spec = spec_cls(
            search_result_mode=spec_cls.SearchResultMode.CHUNKS,
            chunk_spec=spec_cls.ChunkSpec(num_previous_chunks=1, num_next_chunks=1),
        )
    else:
        content_spec = spec_cls(
            search_result_mode=spec_cls.SearchResultMode.DOCUMENTS,
            extractive_content_spec=spec_cls.ExtractiveContentSpec(max_extractive_segment_count=3),
        )

    request = de.SearchRequest(
        serving_config=serving_config_path(),
        query=query,
        page_size=max_results,
        filter=build_doc_filter(doc_keys),
        content_search_spec=content_spec,
    )
    logger.info("search filter=%s query=%s", request.filter, query)
    response = search_client().search(request=request)

    meta = catalog.get_many(doc_keys)
    results: list[dict[str, Any]] = []

    for item in response.results:
        if use_chunks and item.chunk and item.chunk.content:
            chunk = item.chunk
            doc_key = _doc_id_from_chunk_name(chunk.name) or ""
            info = meta.get(doc_key, {})
            page = chunk.page_span.page_start if chunk.page_span else None
            title = info.get("title") or (chunk.document_metadata.title if chunk.document_metadata else "")
            results.append({
                "doc_key": doc_key,
                "title": title,
                "version": info.get("version"),
                "page": page,
                "content": chunk.content,
                "citation": citation_label(title, info.get("version"), page),
            })
        elif item.document:
            doc = item.document
            doc_key = doc.id
            info = meta.get(doc_key, {})
            derived = de.Document.to_dict(doc).get("derived_struct_data") or {}
            title = info.get("title") or derived.get("title", "")
            for seg in derived.get("extractive_segments", []) or derived.get("extractiveSegments", []):
                page = seg.get("pageNumber") or seg.get("page_number")
                results.append({
                    "doc_key": doc_key,
                    "title": title,
                    "version": info.get("version"),
                    "page": page,
                    "content": seg.get("content", ""),
                    "citation": citation_label(title, info.get("version"), page),
                })

    # Pengaman lapis kedua: buang apa pun yang (seharusnya tidak mungkin) di luar daftar aktif.
    allowed = set(doc_keys)
    filtered = [r for r in results if r["doc_key"] in allowed]
    if len(filtered) != len(results):
        logger.warning("Hasil di luar dokumen aktif dibuang: %d", len(results) - len(filtered))
    return filtered[:max_results]
