"""Nyalakan / matikan analisis berbasis kode tanpa deploy (mengubah settings.json di bucket).

    python scripts/code_execution_switch.py status
    python scripts/code_execution_switch.py on  <ID_USER> [<ID_USER_2> ...] [--budget 5] [--steps 25]
    python scripts/code_execution_switch.py off

Perubahan berlaku di agent maksimal 5 menit kemudian.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent.clients import storage_client  # noqa: E402
from library_agent.config import runtime_config_path, settings  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("aksi", choices=["status", "on", "off"])
p.add_argument("users", nargs="*")
p.add_argument("--budget", type=float)
p.add_argument("--steps", type=int)
a = p.parse_args()
blob = storage_client().bucket(settings.bucket).blob(runtime_config_path())
cfg = json.loads(blob.download_as_bytes()) if blob.exists() else {}
if a.aksi == "on":
    if not a.users:
        sys.exit("Sebutkan minimal satu ID user (lihat: python scripts/usage_report.py 1).")
    cfg["code_execution_enabled"] = True
    cfg["code_execution_users"] = a.users
elif a.aksi == "off":
    cfg["code_execution_enabled"] = False
if a.budget is not None:
    cfg["code_execution_daily_budget_usd"] = a.budget
if a.steps is not None:
    cfg["code_execution_max_steps"] = a.steps
if a.aksi != "status":
    blob.upload_from_string(json.dumps(cfg, ensure_ascii=False, indent=2), content_type="application/json")
print(f"settings.json: gs://{settings.bucket}/{runtime_config_path()}")
for k in ("code_execution_enabled", "code_execution_users", "code_execution_daily_budget_usd", "code_execution_max_steps",
          "code_execution_ttl_seconds"):
    print(f"  {k:<34} = {cfg.get(k, '(default)')}")
if a.aksi != "status":
    print("Tersimpan. Berlaku di agent maksimal 5 menit lagi.")
