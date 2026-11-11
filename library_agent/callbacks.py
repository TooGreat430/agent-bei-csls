"""Callback agent: tangkap lampiran (semua format), bersihkan request ke model, jawaban tidak kosong, cek angka.

UNGGAHAN (capture_uploads, before_agent_callback di root DAN sub-agent; duplikasi dicegah dengan hash):
- Semua format diterima. CSV/Excel -> state `data_files` (dianalisis pandas). Format lain -> state `documents`:
  file asli + teks hasil ekstraksi disimpan di ge-docs-agent/doc-files/<chat>/.
- Lampiran bisa datang sebagai inline_data, file_data (gs:// atau https://), atau artifact ADK
  (placeholder teks "[Uploaded Artifact: ...]"); semuanya ditangani dan dicatat di log "user_content parts".

REQUEST KE MODEL (sanitize_request, before_model_callback):
- Gemini menolak lampiran berformat Excel/Word/PowerPoint mentah (penyebab error 400 "Reasoning Engine
  Execution failed"). Sebelum request dikirim, setiap lampiran diganti teks: file data -> rujukan file_id;
  dokumen yang baru diunggah -> isi teksnya (dicerna model); dokumen lama -> rujukan doc_id. Gambar dan PDF
  scan yang baru diunggah tetap dikirim apa adanya karena Gemini bisa membacanya.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from .clients import get_session_id, storage_client

logger = logging.getLogger(__name__)

DOCS_KEY = "documents"
FILES_KEY = "data_files"
ARTIFACTS_KEY = "artifacts_seen"
PROMPT_DOC_CHARS = 30000
NATIVE_MAX_BYTES = 15 * 1024 * 1024
_ARTIFACT_RE = re.compile(r'\[Uploaded Artifact:\s*"?([^"\]]+)"?\]')


def _describe_parts(content: types.Content) -> list[dict]:
    summary = []
    for part in content.parts or []:
        if part.text:
            summary.append({"kind": "text", "chars": len(part.text), "preview": part.text[:120]})
        elif part.inline_data:
            summary.append({"kind": "inline_data", "mime_type": part.inline_data.mime_type,
                            "display_name": getattr(part.inline_data, "display_name", None),
                            "bytes": len(part.inline_data.data or b"")})
        elif part.file_data:
            summary.append({"kind": "file_data", "mime_type": part.file_data.mime_type,
                            "display_name": getattr(part.file_data, "display_name", None),
                            "file_uri": part.file_data.file_uri})
        else:
            summary.append({"kind": "other"})
    return summary


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _download_uri(uri: str) -> bytes:
    """Unduh lampiran file_data: gs://, https://storage.googleapis.com/..., atau URL https lain (kredensial agent)."""
    from .clients import parse_gcs_uri

    m = re.match(r"https://storage\.(?:googleapis|cloud\.google)\.com/(?:download/storage/v1/b/([^/]+)/o/([^?]+)|([^/]+)/([^?]+))", uri)
    if uri.startswith("gs://") or m:
        if uri.startswith("gs://"):
            bucket, path = parse_gcs_uri(uri)
        else:
            from urllib.parse import unquote

            bucket, path = (m.group(1), unquote(m.group(2))) if m.group(1) else (m.group(3), unquote(m.group(4)))
        return storage_client().bucket(bucket).blob(path).download_as_bytes()
    if uri.startswith("https://"):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        resp = AuthorizedSession(creds).get(uri, timeout=60)
        resp.raise_for_status()
        return resp.content
    raise ValueError(f"Alamat lampiran tidak didukung: {uri[:80]}")


def _part_payload(part) -> tuple[bytes, str, str] | None:
    """(bytes, nama, mime) dari part lampiran; None jika bukan lampiran."""
    if part.inline_data and part.inline_data.data:
        return (part.inline_data.data, getattr(part.inline_data, "display_name", None) or "",
                part.inline_data.mime_type or "")
    if part.file_data and part.file_data.file_uri:
        uri = part.file_data.file_uri
        name = getattr(part.file_data, "display_name", None) or uri.split("?")[0].rsplit("/", 1)[-1]
        return _download_uri(uri), name, part.file_data.mime_type or ""
    return None


def _store_data_file(data: bytes, name: str, mime: str, callback_context: CallbackContext,
                     session_id: str) -> dict:
    from .clients import safe_filename
    from .config import live, settings

    files = list(callback_context.state.get(FILES_KEY, []))
    digest = _digest(data)
    found = next((f for f in files if f.get("hash") == digest), None)
    if found:
        return {"status": "duplikat", **found}
    max_mb = float(live("max_file_mb") or 100)
    if len(data) > max_mb * 1024 * 1024:
        return {"status": "terlalu_besar", "filename": name, "message": f"lebih dari {max_mb:g} MB"}
    fname = safe_filename(name)
    path = f"{settings.data_file_prefix}/{session_id}/{digest}_{fname}"
    storage_client().bucket(settings.bucket).blob(path).upload_from_string(data, content_type=mime or "text/csv")
    entry = {"file_id": f"f{len(files) + 1}", "filename": fname, "uri": f"gs://{settings.bucket}/{path}",
             "mime_type": mime, "size_bytes": len(data), "hash": digest}
    files.append(entry)
    callback_context.state[FILES_KEY] = files
    logger.info("File data disimpan: %s (%d byte)", fname, len(data))
    return {"status": "baru", **entry}


def _store_document(data: bytes, name: str, mime: str, callback_context: CallbackContext,
                    session_id: str) -> dict:
    from . import documents
    from .clients import safe_filename
    from .config import settings

    docs = list(callback_context.state.get(DOCS_KEY, []))
    digest = _digest(data)
    found = next((d for d in docs if d.get("hash") == digest), None)
    if found:
        return {"status": "duplikat", **found}
    info = documents.extract(data, name, mime)
    fname = safe_filename(name)
    base = f"{settings.doc_file_prefix}/{session_id}/{digest}_{fname}"
    bucket = storage_client().bucket(settings.bucket)
    bucket.blob(base).upload_from_string(data, content_type=mime or "application/octet-stream")
    text_uri = ""
    if info["text"]:
        bucket.blob(base + ".txt").upload_from_string(info["text"], content_type="text/plain; charset=utf-8")
        text_uri = f"gs://{settings.bucket}/{base}.txt"
    entry = {"doc_id": f"d{len(docs) + 1}", "filename": fname, "mime_type": mime, "jenis": info["jenis"],
             "uri": f"gs://{settings.bucket}/{base}", "text_uri": text_uri, "chars": len(info["text"]),
             "pages": info["pages"], "readable": info["readable"], "native_mime": info["native_mime"],
             "note": info["note"], "hash": digest, "size_bytes": len(data),
             "invocation_id": getattr(callback_context, "invocation_id", "")}
    docs.append(entry)
    callback_context.state[DOCS_KEY] = docs
    logger.info("Dokumen disimpan: %s (%s, %d karakter teks)", fname, info["jenis"], len(info["text"]))
    return {"status": "baru", **entry}


def _ingest(data: bytes, name: str, mime: str, callback_context: CallbackContext, session_id: str) -> dict:
    from . import documents

    kind, name, mime = documents.sniff(data, name, mime)
    if kind == "data":
        return _store_data_file(data, name, mime, callback_context, session_id)
    return _store_document(data, name, mime, callback_context, session_id)


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


async def _artifact_uploads(callback_context: CallbackContext, session_id: str, wanted: set[str]) -> list[dict]:
    """Lampiran yang disimpan sebagai artifact ADK (mis. plugin SaveFilesAsArtifacts)."""
    out = []
    lister = getattr(callback_context, "list_artifacts", None)
    loader = getattr(callback_context, "load_artifact", None)
    if not lister or not loader:
        return out
    try:
        names = list(await _maybe(lister()) or [])
    except Exception:  # noqa: BLE001
        logger.debug("list_artifacts tidak tersedia", exc_info=True)
        return out
    seen = set(callback_context.state.get(ARTIFACTS_KEY, []))
    for name in names:
        if name in seen and name not in wanted:
            continue
        try:
            part = await _maybe(loader(name))
        except Exception:  # noqa: BLE001
            logger.warning("Artifact %s gagal dimuat", name, exc_info=True)
            continue
        if part is not None and part.inline_data and part.inline_data.data:
            out.append(_ingest(part.inline_data.data, getattr(part.inline_data, "display_name", None) or name,
                               part.inline_data.mime_type or "", callback_context, session_id))
        seen.add(name)
    callback_context.state[ARTIFACTS_KEY] = sorted(seen)
    return out


async def capture_uploads(callback_context: CallbackContext) -> Optional[types.Content]:
    """Simpan semua lampiran (data & dokumen). Tidak ada lagi format yang ditolak."""
    content = callback_context.user_content
    if not content or not content.parts:
        return None
    logger.info("user_content parts: %s", json.dumps(_describe_parts(content), ensure_ascii=False))
    session_id = get_session_id(callback_context)
    results, failed, wanted = [], [], set()
    for part in content.parts:
        if part.text:
            wanted.update(m.strip() for m in _ARTIFACT_RE.findall(part.text))
        try:
            payload = _part_payload(part)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Lampiran gagal diunduh")
            failed.append(f"{getattr(part.file_data, 'display_name', None) or 'lampiran'} ({str(exc)[:80]})")
            continue
        if payload:
            try:
                results.append(_ingest(*payload, callback_context, session_id))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Lampiran gagal disimpan")
                failed.append(f"{payload[1] or 'lampiran'} ({str(exc)[:80]})")
    results += await _artifact_uploads(callback_context, session_id, wanted)
    problems = failed + [f"{r.get('filename')} ({r.get('message')})" for r in results if r.get("status") == "terlalu_besar"]
    if problems:
        callback_context.state["temp:upload_problems"] = problems
    if results:
        callback_context.state["temp:new_uploads"] = [
            {k: r.get(k) for k in ("status", "file_id", "doc_id", "filename", "jenis", "readable", "note")} for r in results]
    return None


# ==========================================================================
# Bersihkan request ke model: lampiran mentah -> teks
# ==========================================================================
@functools.lru_cache(maxsize=32)
def _doc_text(text_uri: str) -> str:
    from .clients import parse_gcs_uri

    bucket, path = parse_gcs_uri(text_uri)
    return storage_client().bucket(bucket).blob(path).download_as_text()


def _match(state, part) -> tuple[str, dict | None]:
    """('data'|'dokumen'|'', entri) untuk part lampiran berdasarkan hash/URI/nama."""
    files, docs = state.get(FILES_KEY, []) or [], state.get(DOCS_KEY, []) or []
    digest, name = None, ""
    if part.inline_data and part.inline_data.data:
        digest = _digest(part.inline_data.data)
        name = getattr(part.inline_data, "display_name", None) or ""
    elif part.file_data:
        name = getattr(part.file_data, "display_name", None) or (part.file_data.file_uri or "").rsplit("/", 1)[-1]
    for kind, entries in (("data", files), ("dokumen", docs)):
        for e in entries:
            if (digest and e.get("hash") == digest) or (not digest and name and e.get("filename", "").endswith(
                    re.sub(r"[^A-Za-z0-9._-]+", "_", name))):
                return kind, e
    return "", None


def document_prompt_text(entry: dict, limit: int = PROMPT_DOC_CHARS) -> str:
    head = (f"[DOKUMEN UNGGAHAN · {entry['doc_id']} · {entry['filename']} · {entry.get('jenis')}"
            + (f" · {entry['pages']} halaman" if entry.get("pages") else "") + f" · {entry.get('chars', 0)} karakter]")
    if not entry.get("text_uri"):
        return head + "\n" + (entry.get("note") or "Isi dokumen tidak bisa dibaca sebagai teks.")
    text = _doc_text(entry["text_uri"])
    cut = len(text) > limit
    return head + "\n" + text[:limit] + (
        f"\n[... terpotong; baca lanjutan dengan read_document('{entry['doc_id']}', offset={limit})]" if cut else "")


def sanitize_request(callback_context: CallbackContext, llm_request) -> None:
    """before_model_callback: ganti lampiran mentah di SEMUA content request (termasuk riwayat) dengan teks."""
    contents = getattr(llm_request, "contents", None) or []
    state = callback_context.state
    current = getattr(callback_context, "invocation_id", "")
    for content in contents:
        if not content.parts:
            continue
        new_parts, changed = [], False
        for part in content.parts:
            if not (getattr(part, "inline_data", None) or getattr(part, "file_data", None)):
                new_parts.append(part)
                continue
            changed = True
            kind, entry = _match(state, part)
            if kind == "data":
                new_parts.append(types.Part(text=f"[File data {entry['file_id']} · {entry['filename']} — "
                                                 "dianalisis dengan tool file (profile_data_file / analyze_data).]"))
            elif kind == "dokumen":
                fresh = entry.get("invocation_id") == current
                native = entry.get("native_mime") in ("application/pdf", "image/png", "image/jpeg", "image/webp",
                                                      "image/heic", "image/heif")
                small = (entry.get("size_bytes") or 0) <= NATIVE_MAX_BYTES
                if fresh and native and small and part.inline_data and not entry.get("readable"):
                    new_parts.append(part)   # gambar / PDF scan: Gemini membaca langsung
                elif fresh:
                    try:
                        new_parts.append(types.Part(text=document_prompt_text(entry)))
                    except Exception:  # noqa: BLE001
                        logger.exception("Teks dokumen gagal dimuat")
                        new_parts.append(types.Part(text=f"[Dokumen {entry['doc_id']} · {entry['filename']} — "
                                                         "teks gagal dimuat; coba read_document.]"))
                else:
                    new_parts.append(types.Part(text=f"[Dokumen {entry['doc_id']} · {entry['filename']} · "
                                                     f"{entry.get('jenis')} — isi bisa dibaca dengan read_document.]"))
            else:
                new_parts.append(types.Part(text="[Lampiran tidak dapat dibaca agent.]"))
        if changed:
            content.parts = new_parts
    _attach_images(callback_context, llm_request, contents)
    return None


def _attach_images(callback_context: CallbackContext, llm_request, contents) -> None:
    """Gemini Enterprise tidak mengirim gambar di pesan: lampirkan gambar giliran ini (dan yang diminta lewat
    lihat_gambar) sebagai inline_data agar model (Claude/Gemini) benar-benar melihatnya."""
    from . import vision

    if getattr(callback_context, "agent_name", "") == "marketing_insight_assistant":
        return                                   # router hanya meneruskan pesan; tidak perlu melihat gambar
    state = callback_context.state
    requested = list(state.get(vision.SHOW_KEY) or [])
    docs = vision.images_for(state, requested) if requested else []
    docs += [d for d in vision.images_for(state, invocation_id=getattr(callback_context, "invocation_id", ""))
             if d not in docs]
    if not docs:
        return
    loaded = vision.payloads(docs[:vision.MAX_IMAGES])
    if not loaded:
        return
    parts = [types.Part(text="[Gambar unggahan user dilampirkan untuk dilihat: "
                             + ", ".join(f"{i} ({next(d['filename'] for d in docs if d['doc_id'] == i)})"
                                         for i, _, _ in loaded) + "]")]
    parts += [types.Part(inline_data=types.Blob(data=data, mime_type=mime)) for _, data, mime in loaded]
    last = contents[-1] if contents else None
    if last is not None and getattr(last, "role", "") == "user" and not any(
            getattr(p, "function_response", None) for p in (last.parts or [])):
        last.parts = list(last.parts or []) + parts
    else:
        contents.append(types.Content(role="user", parts=parts))
        try:
            llm_request.contents = contents
        except Exception:  # noqa: BLE001
            pass


# ==========================================================================
# Setelah sub-agent selesai: jawaban tidak boleh kosong + grafik di chat
# ==========================================================================
def summarize_result(resp: dict) -> str:
    """Teks pengganti dari hasil tool terakhir jika model tidak menulis jawaban."""
    if not isinstance(resp, dict):
        return ""
    if resp.get("status") == "ok" and resp.get("url"):
        title = resp.get("report_title") or "Laporan"
        return f"{title} sudah siap: {resp['url']}"
    if resp.get("message"):
        return str(resp["message"])
    if resp.get("status") == "ok":
        return "Permintaan sudah diproses."
    return ""


def _invocation_events(callback_context: CallbackContext) -> list:
    ctx = getattr(callback_context, "_invocation_context", None)
    if ctx is None or getattr(ctx, "session", None) is None:
        return []
    return [e for e in ctx.session.events if getattr(e, "invocation_id", None) == ctx.invocation_id]


def fallback_reply(events: list, agent_name: str) -> str:
    """Jika TIDAK ADA agent yang menulis teks di giliran ini, ambil pesan dari hasil tool terakhir."""
    last_response = None
    for event in events:
        content = getattr(event, "content", None)
        for part in (getattr(content, "parts", None) or []):
            if getattr(event, "author", "") not in ("", "user") and getattr(part, "text", None) \
                    and not getattr(part, "thought", False) and part.text.strip():
                return ""
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "response", None):
                last_response = fr.response
    return summarize_result(last_response) if last_response else ""


def ensure_reply(callback_context: CallbackContext) -> Optional[types.Content]:
    """after_agent_callback: pastikan user selalu menerima jawaban."""
    try:
        text = fallback_reply(_invocation_events(callback_context), callback_context.agent_name)
    except Exception:  # noqa: BLE001
        logger.exception("Pemeriksaan jawaban kosong gagal")
        return None
    return types.Content(role="model", parts=[types.Part(text=text)]) if text else None


def data_after_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    """after_agent_callback agent data: jawaban tidak kosong + tampilkan grafik PNG di chat."""
    parts: list = []
    reply = ensure_reply(callback_context)
    if reply:
        parts.extend(reply.parts)
    pending = callback_context.state.get("bq_pending_chart")
    if pending:
        callback_context.state["bq_pending_chart"] = None
    from .config import live

    if pending and live("chat_inline_chart"):
        # Gemini Enterprise belum menampilkan gambar dari agent ADK (muncul sebagai asc_slot://),
        # jadi lampiran gambar hanya dikirim jika diaktifkan di settings.json.
        try:
            png = storage_client().bucket(pending["bucket"]).blob(pending["path"]).download_as_bytes()
            parts.append(types.Part.from_bytes(data=png, mime_type="image/png"))
        except Exception:  # noqa: BLE001
            logger.exception("Grafik tidak bisa ditampilkan di chat")
    return types.Content(role="model", parts=parts) if parts else None


# ==========================================================================
# Pengecekan angka otomatis (Tahap 0)
# ==========================================================================
def _number_pool(callback_context: CallbackContext) -> list[float]:
    """Angka dari hasil tool di sesi ini + pesan user (dasar verifikasi jawaban)."""
    from .price_dashboard import _MONEY
    from .report_render import parse_number

    ctx = getattr(callback_context, "_invocation_context", None)
    events = list(getattr(getattr(ctx, "session", None), "events", []) or [])[-60:]
    texts = []
    for e in events:
        content = getattr(e, "content", None)
        for part in (getattr(content, "parts", None) or []):
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", "") != "periksa_angka":
                try:
                    texts.append(json.dumps(fr.response, ensure_ascii=False, default=str))
                except Exception:  # noqa: BLE001
                    texts.append(str(fr.response))
            elif getattr(e, "author", "") == "user" and getattr(part, "text", None):
                texts.append(part.text)
    if callback_context.user_content and callback_context.user_content.parts:
        texts += [p.text for p in callback_context.user_content.parts if getattr(p, "text", None)]
    texts += [t for t in (callback_context.state.get("temp:code_outputs") or []) if t]   # stdout eksekusi kode
    for doc in callback_context.state.get(DOCS_KEY, []) or []:   # angka yang dikutip dari dokumen unggahan
        if doc.get("text_uri"):
            try:
                texts.append(_doc_text(doc["text_uri"])[:300000])
            except Exception:  # noqa: BLE001
                logger.warning("Teks dokumen %s tidak bisa dimuat untuk verifikasi", doc.get("doc_id"))
    pool = set()
    for t in texts:
        for raw in _MONEY.findall(t):
            v = parse_number(raw)
            if v is not None:
                v = abs(v)
                pool.update({round(v, 2), round(v * 100, 2), round(v / 100, 4)})
        for raw in re.findall(r"-?\d+\.\d+(?:[eE][-+]?\d+)?", t):
            try:
                v = abs(float(raw))
                pool.update({round(v, 2), round(v * 100, 2)})
            except ValueError:
                pass
    return sorted(pool)


def verify_numbers(callback_context: CallbackContext, llm_response):
    """Jawaban akhir yang memuat angka di luar hasil tool -> minta model menulis ulang sekali; jika masih,
    tambahkan catatan transparan."""
    from google.adk.models import LlmResponse

    from .price_dashboard import ungrounded_numbers

    content = getattr(llm_response, "content", None)
    parts = list(getattr(content, "parts", None) or [])
    if not parts or any(getattr(p, "function_call", None) for p in parts):
        return None
    text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
    if not text.strip():
        return None
    pool = _number_pool(callback_context)
    if not pool:
        return None
    bad = sorted(set(ungrounded_numbers(text, pool)))
    if not bad:
        return None
    ctx = getattr(callback_context, "_invocation_context", None)
    key = f"temp:numcheck_{getattr(ctx, 'invocation_id', '')}"
    tries = callback_context.state.get(key, 0)
    logger.warning("Angka tidak terverifikasi (percobaan %d): %s", tries, bad[:10])
    if tries == 0:
        callback_context.state[key] = 1
        call = types.FunctionCall(name="periksa_angka", args={"angka_tidak_terverifikasi": bad[:10]})
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
    note = ("\n\n_Catatan: angka berikut tidak dapat diverifikasi otomatis terhadap data: "
            + ", ".join(bad[:8]) + ". Mohon cek ulang sebelum dipakai._")
    new_parts = [types.Part(text=text + note)]
    return LlmResponse(content=types.Content(role="model", parts=new_parts))
