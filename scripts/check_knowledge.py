"""Cek & siapkan pengetahuan Data Agent (retail & industri) untuk ADK.

1) Cek baca lewat API (default):
       python scripts/check_knowledge.py
2) Buat salinan cadangan dari file agent card (JSON yang diberikan tim data):
       python scripts/check_knowledge.py --from-card retail card_retail.json
       python scripts/check_knowledge.py --from-card industri card_industri.json
Salinan disimpan di bucket (config/knowledge_<domain>.json) dan dipakai jika API tidak bisa diakses.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent import knowledge  # noqa: E402


def show(domain, data):
    print(f"[{domain}] sumber={data.get('source', '-')} agent={data.get('agent', '-')}")
    print(f"   instruksi={len(data.get('instruction', ''))} karakter · glossary={len(data.get('glossary', []))} · "
          f"contoh query={len(data.get('examples', []))} · tabel={', '.join(data.get('tables', [])) or '-'}")


if len(sys.argv) == 4 and sys.argv[1] == "--from-card":
    domain, path = sys.argv[2], sys.argv[3]
    with open(path, encoding="utf-8") as fh:
        card = json.load(fh)
    show(domain, knowledge.save_from_card(domain, card))
    print("Salinan pengetahuan dari agent card tersimpan di bucket.")
    sys.exit(0)

ok = True
for domain in knowledge.DOMAINS:
    data = knowledge.get(domain, force=True)
    show(domain, data)
    ok = ok and data.get("source") == "api"
print("\nHASIL:", "OK — definisi Data Agent terbaca langsung lewat API." if ok else
      "Sebagian belum terbaca lewat API. Tambahkan role Data Agent Viewer, atau buat salinan dengan --from-card.")
