"""Pratinjau template secara lokal tanpa Google Cloud.

Pemakaian:
    python scripts/preview_template.py <template_id> <contoh_isi.json> [html|pdf|pptx|all]

Contoh:
    python scripts/preview_template.py studi_bei_nps tests/fixtures/sample_bei_nps.json all
Hasil: preview_<template>.<format> di root repo.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("LIB_TEMPLATE_SOURCE", "local")

from library_agent import report_engine  # noqa: E402


def main(template_id: str, content_path: str, fmt: str) -> None:
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
    meta = report_engine.build_meta(template, "penguji@klien.co.id", "Pratinjau Template")
    formats = template.outputs if fmt == "all" else [fmt]
    for f in formats:
        data, ext, _ = report_engine.render(template, content, meta, f)
        out = os.path.join(ROOT, f"preview_{template_id}.{ext}")
        with open(out, "wb") as fh:
            fh.write(data)
        print(f"{f.upper():5s}: {out}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "all")
