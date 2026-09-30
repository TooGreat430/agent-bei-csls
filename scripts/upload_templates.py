"""Mengunggah folder ./templates ke gs://<LIB_BUCKET>/<folder kerja>/templates/.

Pemakaian:
    python scripts/upload_templates.py                  # semua template (menimpa)
    python scripts/upload_templates.py laporan_studi    # satu template (menimpa)
    python scripts/upload_templates.py --missing-only   # hanya template yang belum ada di bucket
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library_agent.clients import storage_client  # noqa: E402
from library_agent.config import settings  # noqa: E402

REQUIRED = ("manifest.json", "schema.json")


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


def exists_in_bucket(template_id: str) -> bool:
    blob = storage_client().bucket(settings.bucket).blob(f"{settings.template_prefix}/{template_id}/manifest.json")
    return blob.exists()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    missing_only = "--missing-only" in sys.argv
    ids = args or sorted(os.listdir(settings.local_template_dir))
    for tid in ids:
        if not os.path.isdir(os.path.join(settings.local_template_dir, tid)):
            continue
        if missing_only and exists_in_bucket(tid):
            continue
        print("Template:", tid)
        upload(tid)
