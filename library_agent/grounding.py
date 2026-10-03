"""Pengaman angka laporan: setiap nilai di KPI, matriks, dan grafik harus berasal dari sumber.

Sumber = isi insight, tabel data BigQuery yang tersimpan bersama insight, dan kutipan dokumen.
Hanya field bernama "nilai" yang diperiksa (dipakai oleh kpi_zona.metrik, matriks.baris, grafik.seri).
Perbandingan memakai nilai absolut dengan toleransi pembulatan, karena tanda gap bisa ditulis berbeda.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .report_render import parse_number

_ANY_NUM = re.compile(r"[-−–+]?\d[\d.,]*")
SKIP_TEXT = {"", "NA", "N/A", "-", "–", "—", "NULL"}


def numbers_in_text(text: str) -> list[float]:
    out = []
    for raw in _ANY_NUM.findall(text or ""):
        value = parse_number(raw)
        if value is not None:
            out.append(abs(value))
    return out


def source_numbers(insight_items: list[dict[str, Any]], excerpts: list[dict[str, Any]] | None = None) -> list[float]:
    nums: list[float] = []
    for item in insight_items:
        nums += numbers_in_text(item.get("content", ""))
        nums += numbers_in_text(" ".join(item.get("citations") or []))
        table = item.get("data") or {}
        for row in table.get("rows") or []:
            for cell in row:
                if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                    nums.append(abs(float(cell)))
                elif isinstance(cell, str):
                    nums += numbers_in_text(cell)
    for ex in excerpts or []:
        nums += numbers_in_text(ex.get("content", ""))
    return sorted(set(round(n, 4) for n in nums))


def is_grounded(value: float, nums: list[float], rel_tol: float = 0.006, abs_tol: float = 1.0) -> bool:
    target = abs(value)
    return any(abs(target - n) <= max(abs_tol, rel_tol * n) for n in nums)


def _walk(node: Any, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}" if path else key
            if key == "nilai":
                yield sub, value
            else:
                yield from _walk(value, sub)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def check(content: dict[str, Any], nums: list[float]) -> list[str]:
    """Daftar nilai yang tidak ditemukan di sumber, mis. ['grafik[0].seri[1].nilai: 12345']."""
    issues = []
    for path, value in _walk(content):
        for v in _values(value):
            if v is None or (isinstance(v, str) and v.strip().upper() in SKIP_TEXT):
                continue
            number = parse_number(v)
            if number is not None and not is_grounded(number, nums):
                issues.append(f"{path}: {v}")
    return issues


def strip_ungrounded(content: dict[str, Any], nums: list[float]) -> tuple[dict[str, Any], int]:
    """Hapus nilai yang tidak terverifikasi: angka grafik -> null, sel matriks -> 'NA', metrik KPI dibuang."""
    fixed = copy.deepcopy(content)
    removed = 0

    def bad(v: Any) -> bool:
        number = parse_number(v)
        return number is not None and not is_grounded(number, nums)

    for chart in fixed.get("grafik") or []:
        for series in chart.get("seri") or []:
            new = []
            for v in series.get("nilai") or []:
                if v is not None and bad(v):
                    removed += 1
                    new.append(None)
                else:
                    new.append(v)
            series["nilai"] = new
    matrix = fixed.get("matriks")
    if isinstance(matrix, dict):
        for row in matrix.get("baris") or []:
            new = []
            for v in row.get("nilai") or []:
                if isinstance(v, str) and v.strip().upper() not in SKIP_TEXT and bad(v):
                    removed += 1
                    new.append("NA")
                else:
                    new.append(v)
            row["nilai"] = new
    for card in fixed.get("kpi_zona") or []:
        kept = []
        for metric in card.get("metrik") or []:
            if bad(metric.get("nilai")):
                removed += 1
            else:
                kept.append(metric)
        card["metrik"] = kept
    if "kpi_zona" in fixed:
        fixed["kpi_zona"] = [c for c in fixed["kpi_zona"] if c.get("metrik")]
    return fixed, removed
