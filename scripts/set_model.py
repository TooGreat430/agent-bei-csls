"""Saklar model tugas berat tanpa deploy (berlaku maks. 5 menit kemudian).

    python scripts/set_model.py status
    python scripts/set_model.py claude      # default: Claude, cadangan Gemini 4 Argon
    python scripts/set_model.py gemini      # semua tugas berat memakai Gemini 4 Argon
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent.clients import storage_client  # noqa: E402
from library_agent.config import runtime_config_path, settings  # noqa: E402

aksi = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
if aksi not in ("status", "claude", "gemini"):
    sys.exit("Pakai: status | claude | gemini")
blob = storage_client().bucket(settings.bucket).blob(runtime_config_path())
cfg = json.loads(blob.download_as_bytes()) if blob.exists() else {}
if aksi != "status":
    cfg["heavy_model"] = aksi
    blob.upload_from_string(json.dumps(cfg, ensure_ascii=False, indent=2), content_type="application/json")
print(f"heavy_model = {cfg.get('heavy_model', 'claude (default)')} · Claude: {settings.model_claude} @ {settings.claude_region}"
      f" · cadangan: {settings.model_pro}")
if aksi != "status":
    print("Tersimpan. Berlaku di agent maksimal 5 menit lagi.")
