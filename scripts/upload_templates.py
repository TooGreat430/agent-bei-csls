"""Mengunggah folder ./templates ke gs://<LIB_BUCKET>/<LIB_TEMPLATE_PREFIX>/.

Pemakaian:
    python scripts/upload_templates.py                 # semua template
    python scripts/upload_templates.py laporan_studi   # satu template
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library_agent.clients import storage_client  # noqa: E402
from library_agent.config import settings  # noqa: E402

REQUIRED = ("manifest.json", "schema.json", "template.html")


def upload(template_id: str) -> None:
    folder = os.path.join(settings.local_template_dir, template_id)
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(folder, f))]
    if missing:
        print(f"Lewati {template_id}: file wajib tidak ada {missing}")
        return
    bucket = storage_client().bucket(settings.bucket)
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            blob = bucket.blob(f"{settings.template_prefix}/{template_id}/{name}")
            blob.upload_from_filename(path)
            print("  ->", f"gs://{settings.bucket}/{blob.name}")


if __name__ == "__main__":
    ids = sys.argv[1:] or sorted(os.listdir(settings.local_template_dir))
    for tid in ids:
        if os.path.isdir(os.path.join(settings.local_template_dir, tid)):
            print("Template:", tid)
            upload(tid)
