"""Laporan meteran biaya harian agent (estimasi dari token & durasi sandbox).

    python scripts/usage_report.py            # 7 hari terakhir
    python scripts/usage_report.py 30         # 30 hari terakhir

Tagihan resmi tetap di Cloud Billing; laporan ini untuk memantau tren dan memastikan batas harian bekerja.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent import usage  # noqa: E402
from library_agent.config import live  # noqa: E402

days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
kurs = float(os.getenv("KURS_USD_IDR", "16500"))
print(f"Batas harian: USD {float(live('code_execution_daily_budget_usd')):g} · fitur aktif: {bool(live('code_execution_enabled'))}"
      f" · user uji coba: {', '.join(live('code_execution_users') or ()) or '(semua)'}\n")
print(f"{'Tanggal':<11}{'Panggilan':>10}{'Token in':>12}{'Cache':>10}{'Token out':>11}{'Model USD':>11}"
      f"{'Eksekusi':>10}{'Sandbox USD':>13}{'Total USD':>11}{'Total Rp':>13}")
tot = 0.0
users: dict = {}
for i in range(days - 1, -1, -1):
    day = (datetime.now(usage.WIB) - timedelta(days=i)).strftime("%Y-%m-%d")
    d = usage.read_day(day)
    m, s = d["model"], d["sandbox"]
    tot += d["total_usd"]
    for u, v in d.get("by_user", {}).items():
        users[u] = users.get(u, 0) + v
    print(f"{day:<11}{m['calls']:>10}{m['input']:>12,}{m['cached']:>10,}{m['output']:>11,}{m['usd']:>11.3f}"
          f"{s['executions']:>10}{s['usd']:>13.3f}{d['total_usd']:>11.3f}{d['total_usd'] * kurs:>13,.0f}")
print(f"\nTotal {days} hari: USD {tot:.3f} (± Rp{tot * kurs:,.0f}, kurs {kurs:,.0f})")
for u, v in sorted(users.items(), key=lambda x: -x[1]):
    print(f"  {u:<40} USD {v:.3f}")
