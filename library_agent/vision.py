"""Gambar unggahan (JPG/PNG/WEBP, termasuk WhatsApp Image) untuk dilihat model (Claude / Gemini).

Gemini Enterprise tidak mengirim gambar di dalam pesan — hanya penanda teks; file aslinya disimpan sebagai dokumen
chat (jenis "Gambar"). Modul ini memuat gambar itu, mengecilkannya (sisi terpanjang 1568 px, JPEG) agar hemat token,
lalu menyerahkannya ke model:
- otomatis pada giliran gambar diunggah;
- pada giliran lain bila agent memanggil lihat_gambar (gambar dari pesan sebelumnya);
- ke penulis laporan custom sebagai gambar referensi (tata letak, pengelompokan, simbol).
"""
from __future__ import annotations

import io
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)
MAX_SIDE = 1568
SHOW_KEY = "temp:show_images"
MAX_IMAGES = 6


def is_image(doc: dict) -> bool:
    return doc.get("jenis") == "Gambar" or str(doc.get("native_mime", "")).startswith("image/")


@lru_cache(maxsize=32)
def _load(uri: str) -> tuple[bytes, str] | None:
    from PIL import Image

    from .clients import parse_gcs_uri, storage_client

    bucket, path = parse_gcs_uri(uri)
    raw = storage_client().bucket(bucket).blob(path).download_as_bytes()
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:  # noqa: BLE001  (mis. HEIC tanpa plugin)
        logger.warning("Gambar %s tidak bisa dibuka", uri)
        return None
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg"


def load(doc: dict) -> tuple[bytes, str] | None:
    try:
        return _load(doc["uri"])
    except Exception:  # noqa: BLE001
        logger.warning("Gambar %s gagal dimuat", doc.get("doc_id"), exc_info=True)
        return None


def images_for(state, doc_ids: list[str] | None = None, invocation_id: str = "") -> list[dict]:
    """Dokumen gambar: yang diminta (doc_ids) atau yang diunggah pada giliran ini (invocation_id)."""
    docs = [d for d in (state.get("documents") or []) if is_image(d)]
    if doc_ids:
        wanted = {d.strip() for d in doc_ids}
        return [d for d in docs if d["doc_id"] in wanted][:MAX_IMAGES]
    return [d for d in docs if invocation_id and d.get("invocation_id") == invocation_id][:MAX_IMAGES]


def payloads(docs: list[dict]) -> list[tuple[str, bytes, str]]:
    """[(doc_id, bytes, mime)] untuk gambar yang berhasil dimuat."""
    out = []
    for d in docs:
        loaded = load(d)
        if loaded:
            out.append((d["doc_id"], loaded[0], loaded[1]))
    return out
