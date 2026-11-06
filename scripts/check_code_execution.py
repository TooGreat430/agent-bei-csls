"""Uji end-to-end Code Execution dengan kode agent yang sebenarnya (sebelum fitur dinyalakan untuk user).

    python scripts/check_code_execution.py

Membuat sandbox di bawah agent (LIB_AGENT_RESOURCE), mengirim satu file CSV, menjalankan pandas, membuat file output
CSV + PNG, membaca hasilnya, lalu menghapus sandbox. Biaya: beberapa detik pemakaian sandbox.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent import code_exec  # noqa: E402

csv = b"Customer Code,date,Grand Total\n1,2025-01-31,1.5\n1,2025-02-28,2.0\n2,2025-01-31,0.7\n"
code = """
import pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
df = pd.read_csv('f1_uji.csv')
rfm = df.groupby('Customer Code').agg(bulan_aktif=('date', 'nunique'), volume=('Grand Total', 'sum')).reset_index()
print(rfm.to_string(index=False))
rfm.to_csv('hasil_uji.csv', index=False)
rfm.plot.bar(x='Customer Code', y='volume'); plt.savefig('grafik_uji.png', dpi=100)
"""
client = code_exec._client()
print("Region sandbox  :", code_exec.region())
t0 = time.time()
sb = code_exec._create_sandbox(client)
print("Sandbox dibuat  :", sb, f"({time.time() - t0:.1f} dtk)")
try:
    t0 = time.time()
    resp = code_exec._execute(client, sb, code, [{"name": "f1_uji.csv", "content": csv, "file_id": "f1"}])
    print(f"Eksekusi        : {time.time() - t0:.1f} dtk · field file = '{code_exec._FILES_FIELD['value']}'")
    out = code_exec.parse_response(resp, {"f1_uji.csv"})
    print("STDOUT:\n" + out["stdout"])
    print("STDERR:", out["stderr"] or "-")
    print("FILE OUTPUT     :", [(f["name"], f["mime_type"], len(f["content"])) for f in out["files"]])
    ok = "hasil_uji.csv" in [f["name"] for f in out["files"]] and not out["stderr"].strip()
    print("\nHASIL:", "OK — sandbox menerima file, menjalankan pandas, dan mengembalikan file output." if ok else
          "PERLU DICEK — kirim seluruh output ini ke tim teknis.")
    if not ok:
        print("Mentah:", [(getattr(c, 'mime_type', ''), getattr(getattr(c, 'metadata', None), 'attributes', None),
                           (getattr(c, 'data', b'') or b'')[:200]) for c in resp.outputs])
finally:
    client.agent_engines.sandboxes.delete(name=sb)
    print("Sandbox dihapus.")
