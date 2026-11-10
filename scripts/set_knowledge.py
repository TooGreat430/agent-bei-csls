"""Tambah/ganti pengetahuan bisnis dari tim MIR untuk satu domain, tanpa deploy.

    python scripts/set_knowledge.py status
    python scripts/set_knowledge.py upload sellout panduan_sellout.md
    python scripts/set_knowledge.py show sellout
    python scripts/set_knowledge.py hapus sellout

File Markdown/teks berisi definisi metrik, aturan, struktur laporan yang diinginkan, dll. Dipakai bersama pengetahuan
resmi Data Agent: di instruksi agent analisis file dan di prompt laporan custom domain tersebut. Berlaku untuk chat baru.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent import knowledge  # noqa: E402
from library_agent.clients import storage_client  # noqa: E402
from library_agent.config import settings  # noqa: E402

args = sys.argv[1:] or ["status"]
bucket = storage_client().bucket(settings.bucket)
if args[0] == "status":
    for d in knowledge.DOMAINS:
        b = bucket.blob(knowledge.extra_path(d))
        print(f"  {d:<10} {'ada (' + str(b.reload() or b.size) + ' byte)' if b.exists() else '-'}")
elif args[0] == "upload" and len(args) == 3:
    domain, path = args[1], args[2]
    if domain not in knowledge.DOMAINS:
        sys.exit(f"Domain harus salah satu: {', '.join(knowledge.DOMAINS)}")
    text = open(path, encoding="utf-8").read()
    bucket.blob(knowledge.extra_path(domain)).upload_from_string(text, content_type="text/markdown; charset=utf-8")
    print(f"Tersimpan: gs://{settings.bucket}/{knowledge.extra_path(domain)} ({len(text)} karakter). Berlaku di chat baru.")
elif args[0] == "show" and len(args) == 2:
    b = bucket.blob(knowledge.extra_path(args[1]))
    print(b.download_as_text() if b.exists() else "(belum ada)")
elif args[0] == "hapus" and len(args) == 2:
    b = bucket.blob(knowledge.extra_path(args[1]))
    if b.exists():
        b.delete()
    print("Dihapus.")
else:
    sys.exit(__doc__)
