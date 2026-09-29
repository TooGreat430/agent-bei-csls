"""Pratinjau template secara lokal tanpa Google Cloud.

Pemakaian:
    python scripts/preview_template.py laporan_studi tests/fixtures/sample_content.json
Hasil: preview_<template>.html (dan .pdf jika WeasyPrint terpasang).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("LIB_TEMPLATE_SOURCE", "local")

from library_agent import report_engine  # noqa: E402


def main(template_id: str, content_path: str) -> None:
    template = report_engine.load_template(template_id)
    with open(content_path, encoding="utf-8") as fh:
        content = json.load(fh)
    try:
        errors = report_engine.validate_content(content, template.schema)
        if errors:
            print("Konten tidak sesuai skema:\n- " + "\n- ".join(errors))
            sys.exit(1)
    except ImportError:
        print("(jsonschema belum terpasang, validasi dilewati)")
    meta = report_engine.build_meta(template, "analis@klien.co.id", "Laporan Studi CSLS Q3 2026")
    html = report_engine.render_html(template, content, meta)
    out = os.path.join(ROOT, f"preview_{template_id}.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("HTML:", out)
    pdf = report_engine.html_to_pdf(html)
    if pdf:
        with open(out.replace(".html", ".pdf"), "wb") as fh:
            fh.write(pdf)
        print("PDF :", out.replace(".html", ".pdf"))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
