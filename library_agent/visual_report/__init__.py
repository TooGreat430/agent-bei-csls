"""Mesin laporan visual otomatis PTPL: storyboard -> PPTX (chart native) / PDF / HTML dengan tampilan identik.

Pemakaian:
    from library_agent.visual_report import render_report
    out = render_report(storyboard, ("pptx", "pdf", "html"), angka_wajib=[21.0, -1.98, ...])
    out["files"]["pptx"]  -> bytes
    out["masalah"]        -> daftar catatan mutu (untuk revisi otomatis), tidak pernah ditampilkan mentah ke user
    out["angka_hilang"]   -> angka hasil analitik yang belum muncul di laporan

render_report TIDAK PERNAH melempar error: storyboard rusak -> deck darurat; satu format gagal -> format lain tetap
dibuat; elemen gagal -> versi sederhana (chart -> tabel datanya).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .build import Deck, build_deck, emergency_deck, flatten
from .quality import coverage, review

logger = logging.getLogger(__name__)
FORMATS = ("pptx", "pdf", "html")

__all__ = ["render_report", "build_deck", "review", "coverage", "FORMATS"]


def _renderer(fmt: str):
    if fmt == "pptx":
        from .render_pptx import render
    elif fmt == "pdf":
        from .render_pdf import render
    else:
        from .render_html import render
    return render


def render_report(spec: dict, formats=FORMATS, angka_wajib: list | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    formats = [f for f in (formats or FORMATS) if f in FORMATS] or list(FORMATS)
    try:
        deck = build_deck(spec)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Storyboard tidak bisa dibangun; memakai deck darurat")
        title = str((spec or {}).get("judul") or "Laporan Analisis") if isinstance(spec, dict) else "Laporan Analisis"
        deck = emergency_deck(title, flatten(spec) if isinstance(spec, (dict, list)) else [str(spec)])
        deck.issues.append(f"storyboard tidak valid ({str(exc)[:120]}); dibuat versi sederhana")
    files: dict[str, bytes] = {}
    for fmt in formats:
        try:
            files[fmt] = _renderer(fmt)(deck)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Render %s gagal; mencoba deck darurat", fmt)
            deck.issues.append(f"format {fmt}: render utama gagal ({str(exc)[:100]}); dibuat versi sederhana")
            try:
                simple = emergency_deck(deck.title, [s.title + ": " + s.all_text()[:600] for s in deck.slides])
                files[fmt] = _renderer(fmt)(simple)
            except Exception:  # noqa: BLE001
                logger.exception("Deck darurat %s juga gagal", fmt)
    missing = coverage(deck, angka_wajib or [])
    report = review(deck)
    return {"files": files, "deck": deck, "stats": deck.stats(), "masalah": deck.issues + report["masalah"],
            "angka_hilang": missing, "detik": round(time.monotonic() - t0, 1)}
