"""Pengenalan jenis file unggahan dan ekstraksi teks dokumen (semua format diterima).

- File DATA (CSV/Excel) -> dianalisis lewat data_engine (tidak diubah di sini).
- File DOKUMEN (PDF, Word, PowerPoint, teks, Markdown, HTML, JSON, dll.) -> teksnya diekstrak di sini,
  disimpan ke Cloud Storage, lalu "dicerna" agent: diringkas ke user + usulan langkah berikutnya.
- GAMBAR (PNG/JPEG/WEBP/HEIC) -> tidak ada teks; dikirim apa adanya ke Gemini (bisa membaca gambar).
- PDF hasil scan (tanpa teks) -> dikirim apa adanya ke Gemini (bisa membaca PDF) pada giliran unggah.
- Format lain (zip, .doc/.ppt lama, dll.) -> disimpan, tetapi dilaporkan tidak bisa dibaca.
"""
from __future__ import annotations

import html as _html
import io
import re
import zipfile

DATA_EXT = (".csv", ".xlsx", ".xlsm", ".xls", ".tsv")
DATA_MIME = {"text/csv", "application/csv", "text/tab-separated-values", "application/vnd.ms-excel",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "application/vnd.ms-excel.sheet.macroenabled.12"}
TEXT_EXT = (".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".xml", ".log", ".sql", ".py", ".ini", ".cfg", ".prompt")
HTML_EXT = (".html", ".htm")
IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
GEMINI_NATIVE_MIME = IMAGE_MIME | {"application/pdf"}
EXT_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
            ".heic": "image/heic", ".pdf": "application/pdf"}
MAX_TEXT_CHARS = 2_000_000


def _ext(name: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    return m.group(0).lower() if m else ""


def _zip_names(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.namelist()
    except zipfile.BadZipFile:
        return []


def sniff(data: bytes, name: str = "", mime: str = "") -> tuple[str, str, str]:
    """(kategori, nama, mime). kategori: 'data' | 'dokumen'. Nama diberi ekstensi bila tidak ada."""
    mime = (mime or "").lower()
    ext = _ext(name)
    if ext in DATA_EXT or mime in DATA_MIME:
        return "data", name or "data.csv", mime
    head = data[:8]
    if head.startswith(b"PK"):
        names = _zip_names(data)
        if any(n.startswith("xl/") for n in names):
            return "data", name if ext else (name or "data") + ".xlsx", \
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if any(n.startswith("word/") for n in names) and not ext:
            return "dokumen", (name or "dokumen") + ".docx", mime
        if any(n.startswith("ppt/") for n in names) and not ext:
            return "dokumen", (name or "presentasi") + ".pptx", mime
    if head.startswith(b"\xd0\xcf\x11\xe0") and (ext == ".xls" or "excel" in mime):
        return "data", name or "data.xls", mime
    if not ext and not mime.startswith(("application/pdf", "image/")) and not head.startswith(b"%PDF"):
        text = _decode(data[:20000])
        if text is not None and _looks_like_table(text):
            return "data", (name or "data") + ".csv", "text/csv"
    return "dokumen", name or "dokumen", mime


def _looks_like_table(text: str) -> bool:
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if len(lines) < 3:
        return False
    for sep in (",", ";", "\t", "|"):
        counts = [ln.count(sep) for ln in lines]
        if counts[0] >= 2 and all(c == counts[0] for c in counts[1:]):
            return True
    return False


def _decode(data: bytes) -> str | None:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    try:
        text = data.decode("latin-1")
    except UnicodeDecodeError:
        return None
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text[:5000])
    return text if printable > 0.95 * min(len(text), 5000) else None


def _html_text(raw: str) -> str:
    raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"</(p|div|tr|h[1-6]|li|section|br|table)>|<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = _html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = [n for n in z.namelist() if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes)\.xml", n)]
        out = []
        for n in sorted(parts, key=lambda x: (x != "word/document.xml", x)):
            xml = z.read(n).decode("utf-8", "ignore")
            for para in re.split(r"</w:p>", xml):
                cells = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, flags=re.S)
                line = _html.unescape("".join(cells)).strip()
                if line:
                    out.append(line)
    return "\n".join(out)


def _pptx_text(data: bytes) -> tuple[str, int]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    out = []
    for i, slide in enumerate(prs.slides, 1):
        lines = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    lines.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append(" | ".join(c.text.strip() for c in row.cells))
        notes = slide.notes_slide.notes_text_frame.text.strip() if slide.has_notes_slide else ""
        out.append(f"--- Slide {i} ---\n" + "\n".join(lines) + (f"\n[Catatan] {notes}" if notes else ""))
    return "\n".join(out), len(prs.slides)


def _pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    out = []
    for i, page in enumerate(reader.pages[:500], 1):
        try:
            t = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            t = ""
        if t:
            out.append(f"--- Halaman {i} ---\n{t}")
    return "\n".join(out), len(reader.pages)


def extract(data: bytes, name: str, mime: str) -> dict:
    """{'jenis', 'text', 'pages', 'readable', 'native_mime', 'note'} untuk file dokumen."""
    ext = _ext(name)
    mime = (mime or "").lower() or EXT_MIME.get(ext, "")
    res = {"jenis": "lainnya", "text": "", "pages": None, "readable": False, "native_mime": "", "note": ""}
    try:
        if mime == "application/pdf" or ext == ".pdf" or data[:4] == b"%PDF":
            text, pages = _pdf_text(data)
            res.update(jenis="PDF", text=text, pages=pages, native_mime="application/pdf")
            res["readable"] = bool(text.strip())
            if not res["readable"]:
                res["note"] = "PDF tanpa lapisan teks (hasil scan); isi dibaca langsung oleh model pada giliran unggah."
        elif ext == ".docx" or "wordprocessingml" in mime:
            res.update(jenis="Word", text=_docx_text(data))
            res["readable"] = bool(res["text"].strip())
        elif ext == ".pptx" or "presentationml" in mime:
            text, n = _pptx_text(data)
            res.update(jenis="PowerPoint", text=text, pages=n, readable=bool(text.strip()))
        elif mime in IMAGE_MIME or ext in (".png", ".jpg", ".jpeg", ".webp", ".heic"):
            res.update(jenis="Gambar", native_mime=mime or EXT_MIME.get(ext, "image/png"),
                       note="Gambar dibaca langsung oleh model pada giliran unggah.")
        elif ext in HTML_EXT or mime == "text/html":
            raw = _decode(data) or ""
            res.update(jenis="HTML", text=_html_text(raw), readable=bool(raw.strip()))
        elif ext in (".doc", ".ppt", ".rtf", ".odt", ".odp", ".key", ".pages"):
            res.update(jenis=ext.lstrip(".").upper(),
                       note="Format lama/khusus ini belum bisa dibaca. Simpan ulang sebagai PDF, DOCX, atau PPTX.")
        else:
            text = _decode(data) if (ext in TEXT_EXT or mime.startswith("text/") or "json" in mime or not ext) else None
            if text is not None:
                res.update(jenis="Teks", text=text, readable=bool(text.strip()))
            else:
                res["note"] = "Format file ini tidak bisa dibaca sebagai teks."
    except Exception as exc:  # noqa: BLE001
        res["note"] = f"Isi dokumen gagal dibaca: {str(exc)[:150]}"
        res["readable"] = False
    res["text"] = (res["text"] or "")[:MAX_TEXT_CHARS]
    return res
