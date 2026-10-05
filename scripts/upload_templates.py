"""Mengunggah folder ./templates ke gs://<LIB_BUCKET>/<folder kerja>/templates/.

Pemakaian:
    python scripts/upload_templates.py                  # semua template (menimpa)
    python scripts/upload_templates.py laporan_studi    # satu template (menimpa)
    python scripts/upload_templates.py --missing-only   # hanya FILE yang belum ada di bucket (tidak menimpa),
                                                        # kecuali manifest.json dengan "version" lebih tinggi
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library_agent.clients import storage_client  # noqa: E402
from library_agent.config import settings  # noqa: E402

REQUIRED = ("manifest.json", "schema.json")


def upload(template_id: str, missing_only: bool = False) -> None:
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
            if missing_only and blob.exists():
                if name != "manifest.json" or not _newer_manifest(path, blob):
                    continue
            blob.upload_from_filename(path)
            print(f"  {template_id}/{name} diunggah")


def _version(value) -> tuple:
    try:
        return tuple(int(x) for x in str(value).split("."))
    except ValueError:
        return (0,)


def _newer_manifest(local_path: str, blob) -> bool:
    """True jika manifest di repo punya 'version' lebih tinggi daripada di bucket."""
    import json

    try:
        remote = json.loads(blob.download_as_text())
    except Exception:  # noqa: BLE001
        return False
    with open(local_path, encoding="utf-8") as fh:
        local = json.load(fh)
    return _version(local.get("version", "0")) > _version(remote.get("version", "0"))


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
        if not missing_only:
            print("Template:", tid)
        upload(tid, missing_only=missing_only)
