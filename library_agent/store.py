"""Penyimpanan JSON di Cloud Storage (pengganti Firestore).

Dipakai untuk katalog perpustakaan dan insight. Tidak butuh API tambahan selain
Cloud Storage, yang memang sudah dipakai untuk dokumen dan template.

Keamanan penulisan bersamaan (dua user menulis di waktu yang sama) dijaga dengan
*optimistic concurrency*: setiap tulis memakai `if_generation_match`. Jika file
sudah diubah orang lain sejak dibaca, tulis ditolak lalu diulang dengan data terbaru.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable, TypeVar

from .clients import storage_client
from .config import settings

logger = logging.getLogger(__name__)
T = TypeVar("T")

MAX_RETRIES = 6


def _blob(path: str):
    return storage_client().bucket(settings.bucket).blob(path)


def read_json(path: str, default: Callable[[], Any]) -> Any:
    """Baca file JSON. Jika belum ada, kembalikan default()."""
    from google.api_core.exceptions import NotFound

    try:
        return json.loads(_blob(path).download_as_bytes())
    except NotFound:
        return default()


def update_json(path: str, default: Callable[[], Any], mutate: Callable[[Any], T]) -> T:
    """Baca, ubah dengan `mutate(data)`, lalu tulis secara atomik.

    `mutate` mengubah `data` secara langsung (in-place) dan boleh mengembalikan
    nilai apa pun sebagai hasil fungsi ini. Dijalankan ulang jika terjadi konflik.
    """
    from google.api_core.exceptions import NotFound, PreconditionFailed

    for attempt in range(MAX_RETRIES):
        blob = _blob(path)
        try:
            blob.reload()
            generation = blob.generation
            data = json.loads(blob.download_as_bytes(if_generation_match=generation))
        except NotFound:
            generation = 0  # 0 = hanya boleh dibuat jika file belum ada
            data = default()
        except PreconditionFailed:
            continue

        result = mutate(data)
        try:
            blob.upload_from_string(
                json.dumps(data, ensure_ascii=False, default=str),
                content_type="application/json",
                if_generation_match=generation,
            )
            return result
        except PreconditionFailed:
            wait = (2 ** attempt) * 0.1 + random.random() * 0.1
            logger.info("Konflik tulis %s, ulang dalam %.2fs", path, wait)
            time.sleep(wait)
    raise RuntimeError(f"Gagal menyimpan {path}: terlalu banyak penulisan bersamaan.")


def write_json(path: str, data: Any) -> None:
    """Tulis file JSON baru (tanpa pengecekan konflik). Untuk file yang ditulis sekali."""
    _blob(path).upload_from_string(
        json.dumps(data, ensure_ascii=False, default=str), content_type="application/json"
    )
