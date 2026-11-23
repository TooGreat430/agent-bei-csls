"""Kunci requirements ke versi yang TERPASANG di .venv saat deploy.

Kenapa: Agent Engine menerima objek agent yang di-pickle dari .venv Cloud Shell, lalu container-nya memasang
requirements sendiri. Dengan `google-adk>=1.10.0` container memasang ADK TERBARU, sedangkan objek agent dibuat dengan
ADK lama di .venv (`pip install -r` tidak meng-upgrade paket yang sudah memenuhi syarat). Beda versi ->
`'LlmAgent' object has no attribute 'max_parallel_workers'` dan setiap pesan gagal tanpa event (insiden 22 Nov).
"""
from __future__ import annotations

import re
from importlib import metadata

_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def pin_requirements(lines: list[str], version_of=metadata.version) -> tuple[list[str], list[str]]:
    """(requirements terkunci `nama[extras]==versi`, paket yang tidak terpasang sehingga dibiarkan apa adanya)."""
    pinned, missing = [], []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _REQ.match(line)
        if not m or line.startswith(("-", "git+", "http")) or "@" in line:
            pinned.append(line)
            continue
        name, extras = m.group(1), m.group(2) or ""
        try:
            pinned.append(f"{name}{extras}=={version_of(name)}")
        except metadata.PackageNotFoundError:
            missing.append(name)
            pinned.append(line)
    return pinned, missing


def read_pinned(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        pinned, missing = pin_requirements(fh.read().splitlines())
    print("    Versi dikunci sesuai .venv:")
    for p in pinned:
        print("      ", p)
    if missing:
        print("    PERINGATAN: belum terpasang di .venv (tidak dikunci):", ", ".join(missing))
    return pinned
