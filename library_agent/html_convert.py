"""Ubah isi laporan custom (HTML) menjadi model halaman ptpl_design, agar bisa dirender ke PDF dan PowerPoint.

- Laporan custom design system PTPL: komponen dikenali satu per satu (<section class="page">, .hdr, .kpi, table.gt,
  .ins, .card, .chart[data-chart], h2.sec, h3.sub, p.note, .grid) sehingga PDF/PPTX tampil sama gaya dengan HTML-nya.
- Laporan dengan template HTML milik user (class bebas): dibaca secara umum — judul (h1–h4), tabel, paragraf, daftar,
  dan grafik data-chart — lalu disusun ulang bergaya PTPL. Tampilan PDF/PPTX tidak identik dengan template, isinya sama.
"""
from __future__ import annotations

import json
import re
from typing import Any

GRID_CLASSES = {"g2", "g3", "g4", "g5", "g-6040", "g-4060"}
KPI_TONES = {"kg", "kw", "kr", "kb"}
INS_TONES = {"ig", "ir", "iw", "ib"}
CELL_CLASSES = {"nm", "up", "dn", "fl", "pos", "neg", "h1c", "h2c", "h3c", "h4c", "h5c"}
MAX_BLOCKS_PER_PAGE = 7


def _cls(el) -> set[str]:
    return set(el.get("class") or []) if hasattr(el, "get") else set()


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el is not None else ""


def _kpi(el) -> dict[str, Any]:
    c = _cls(el)
    badge = el.select_one(".badge")
    return {"label": _text(el.select_one(".kpi-lbl")), "value": _text(el.select_one(".kpi-val")),
            "mono": _text(el.select_one(".kpi-mono")), "desc": _text(el.select_one(".kpi-desc")),
            "tone": next(iter(c & KPI_TONES), ""),
            "badge": {"text": _text(badge), "tone": next((x for x in _cls(badge) if x.startswith("b-")), "b-n")}
            if badge else {}}


def _table(el) -> dict[str, Any]:
    rows = el.find_all("tr")
    if not rows:
        return {}
    head = el.select_one("thead tr") or rows[0]
    columns = [_text(c) for c in head.find_all(["th", "td"])]
    body = []
    for tr in rows:
        if tr is head:
            continue
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        rcls = _cls(tr)
        if "seg" in rcls:
            body.append({"cls": "seg", "cells": [_text(tr)]})
            continue
        out = []
        for td in cells:
            item: dict[str, Any] = {"t": _text(td)}
            cc = _cls(td) & CELL_CLASSES
            if cc:
                item["cls"] = next(iter(cc))
            dot = td.select_one(".dot")
            if dot:
                item["dot"] = next((x for x in _cls(dot) if x.startswith("d-")), "d-n")
            out.append(item)
        body.append({"cls": next(iter(rcls & {"ptpl", "hl"}), ""), "cells": out})
    width = max([len(columns)] + [len(r["cells"]) for r in body if r.get("cls") != "seg"] or [0])
    columns += [""] * (width - len(columns))
    return {"type": "table", "columns": columns, "rows": body[:60]}


def _chart(el) -> dict[str, Any] | None:
    try:
        spec = json.loads(el.get("data-chart") or "")
    except (ValueError, TypeError):
        return None
    size = next((s for s in ("xl", "lg", "sm") if s in _cls(el)), "")
    return {"type": "chart", "size": size, "spec": spec}


def _blocks(parent, generic: bool) -> list[dict[str, Any]]:  # noqa: C901
    out: list[dict[str, Any]] = []

    def add_item(kind: str, item: dict) -> None:
        if out and out[-1]["type"] == kind:
            out[-1]["items"].append(item)
        else:
            out.append({"type": kind, "items": [item]})

    for el in getattr(parent, "children", []):
        name = getattr(el, "name", None)
        if name is None:
            t = str(el).strip()
            if t and generic:
                out.append({"type": "text", "text": re.sub(r"\s+", " ", t)})
            continue
        c = _cls(el)
        if name in ("script", "style", "br", "hr"):
            continue
        if c & {"hdr", "footer", "draft", "final-badge"}:
            continue
        if el.get("data-chart"):
            ch = _chart(el)
            if ch:
                out.append(ch)
            continue
        if "kpi" in c:
            add_item("kpis", _kpi(el))
            continue
        if "grid" in c or c & GRID_CLASSES:
            kids = [k for k in el.children if getattr(k, "name", None)]
            if kids and all("kpi" in _cls(k) for k in kids):
                out.append({"type": "kpis", "items": [_kpi(k) for k in kids]})
            else:
                cols = [b for b in (_blocks(k, generic) for k in kids) if b]
                if len(cols) == 1:
                    out += cols[0]
                elif cols:
                    out.append({"type": "grid", "cols": next(iter(c & GRID_CLASSES), "g2"), "children": cols})
            continue
        if "ins" in c:
            add_item("insights", {"tone": next(iter(c & INS_TONES), ""), "label": _text(el.select_one(".ins-lbl")),
                                  "title": _text(el.select_one(".ins-title")), "body": _text(el.select_one(".ins-body"))
                                  or _text(el)})
            continue
        if "card" in c:
            h = el.find(["h4", "h3", "h5"])
            body = _text(el).replace(_text(h), "", 1).strip() if h else _text(el)
            add_item("cards", {"title": _text(h), "body": body})
            continue
        if name == "table":
            tb = _table(el)
            if tb:
                out.append(tb)
            continue
        if name == "h2" or ("sec" in c and name in ("h1", "h2", "h3")):
            acc = el.select_one(".acc")
            title = _text(el).replace(_text(acc), "").strip() if acc else _text(el)
            out.append({"type": "sec", "title": title, "acc": _text(acc).lstrip("· ").strip() if acc else ""})
            continue
        if name in ("h1", "h3", "h4", "h5") or "sub" in c:
            out.append({"type": "sec" if name == "h1" else "sub", "title": _text(el)})
            continue
        if name == "p" or "txt" in c:
            t = _text(el)
            if t:
                out.append({"type": "note" if "note" in c else "text", "text": t})
            continue
        if name in ("ul", "ol"):
            for li in el.find_all("li", recursive=False):
                out.append({"type": "text", "text": "• " + _text(li)})
            continue
        inner = _blocks(el, generic)
        if inner:
            out += inner
        elif generic and _text(el):
            out.append({"type": "text", "text": _text(el)})
    return out


def _page_meta(section) -> dict[str, Any]:
    hdr = section.select_one(".hdr")
    title_el = hdr.select_one(".hdr-title") if hdr else None
    tag = title_el.select_one(".tag") if title_el else None
    title = _text(title_el).replace(_text(tag), "").strip() if title_el else ""
    right = hdr.select_one(".hdr-r") if hdr else None
    draft = right.select_one(".draft, .final-badge") if right else None
    right_txt = _text(right).replace(_text(draft), "").strip() if right else ""
    foot = section.select_one(".footer span")
    return {"kicker": _text(hdr.select_one(".kicker")) if hdr else "", "title": title, "tag": _text(tag),
            "sub": _text(hdr.select_one(".hdr-sub")) if hdr else "", "right": right_txt, "draft": bool(draft),
            "source": re.sub(r"^Sumber:\s*", "", _text(foot))}


def to_pages(body_html: str, title: str = "", source: str = "") -> list[dict[str, Any]]:
    """Isi body laporan custom -> list halaman ptpl_design (siap render_pdf / render_pptx)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body_html or "", "html.parser")
    sections = soup.select("section.page")
    if sections:
        pages = []
        for s in sections:
            meta = _page_meta(s)
            pages.append({**meta, "source": meta["source"] or source, "blocks": _blocks(s, generic=False)})
        return pages
    blocks = _blocks(soup, generic=True)                     # template HTML milik user / struktur bebas
    first = next((b for b in blocks if b["type"] == "sec"), None)
    has_draft = "DRAFT" in soup.get_text()
    pages, cur = [], []
    for b in blocks:
        if b["type"] == "sec" and len(cur) >= MAX_BLOCKS_PER_PAGE:
            pages.append(cur)
            cur = []
        cur.append(b)
        if len(cur) >= MAX_BLOCKS_PER_PAGE * 2:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    if pages and first and pages[0] and pages[0][0] is first:
        pages[0] = pages[0][1:] or [{"type": "text", "text": ""}]       # judul sudah di kepala halaman
    return [{"kicker": f"LAPORAN · {i + 1:02d}", "title": (first["title"] if first and i == 0 else title) or title,
             "tag": "", "sub": "", "right": "", "draft": has_draft, "source": source, "blocks": blk}
            for i, blk in enumerate(pages or [[{"type": "text", "text": "(laporan kosong)"}]])]
