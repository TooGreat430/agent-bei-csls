"""Atur batas pemakaian agent tanpa deploy (settings.json di bucket). Berlaku maks. 5 menit kemudian.

    python scripts/set_budget.py status
    python scripts/set_budget.py set --harian 10 --bulanan 150 [--peringatan 80] [--cakupan berat|semua]
    python scripts/set_budget.py off                      # hapus batas (0 = tidak dibatasi)

Batas dihitung dari meteran biaya (estimasi token model + sandbox, USD). Saat pemakaian mencapai --peringatan %,
user mendapat info sekali per chat per hari. Saat batas tercapai: cakupan "berat" menghentikan laporan & analisis
berbasis kode (tanya-jawab tetap jalan); cakupan "semua" menghentikan seluruh agent sampai periode berikutnya.
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
p.add_argument("aksi", choices=["status", "set", "off"])
p.add_argument("--harian", type=float)
p.add_argument("--bulanan", type=float)
p.add_argument("--peringatan", type=float)
p.add_argument("--cakupan", choices=["berat", "semua"])
a = p.parse_args()
blob = storage_client().bucket(settings.bucket).blob(runtime_config_path())
cfg = json.loads(blob.download_as_bytes()) if blob.exists() else {}
if a.aksi == "off":
    cfg.update(budget_daily_usd=0, budget_monthly_usd=0)
elif a.aksi == "set":
    for key, val in (("budget_daily_usd", a.harian), ("budget_monthly_usd", a.bulanan),
                     ("budget_warn_pct", a.peringatan), ("budget_block_scope", a.cakupan)):
        if val is not None:
            cfg[key] = val
if a.aksi != "status":
    blob.upload_from_string(json.dumps(cfg, ensure_ascii=False, indent=2), content_type="application/json")
for k in ("budget_daily_usd", "budget_monthly_usd", "budget_warn_pct", "budget_block_scope"):
    print(f"  {k:<22} = {cfg.get(k, '(default)')}")
print("Tersimpan. Berlaku di agent maksimal 5 menit lagi." if a.aksi != "status" else "")
