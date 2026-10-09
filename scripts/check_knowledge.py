"""Cek & siapkan pengetahuan Data Agent (retail & industri) untuk ADK.

1) Cek baca lewat API:            python scripts/check_knowledge.py
2) Diagnosa struktur definisi:     python scripts/check_knowledge.py --dump retail
3) Salinan dari file agent card:   python scripts/check_knowledge.py --from-card retail card_retail.json
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


def outline(node, path="", depth=0, out=None):
    out = [] if out is None else out
    if depth > 6:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            outline(v, f"{path}.{k}" if path else k, depth + 1, out)
    elif isinstance(node, list):
        out.append(f"{path}  [list, {len(node)} item]")
        if node:
            outline(node[0], f"{path}[0]", depth + 1, out)
    else:
        text = str(node)
        out.append(f"{path}  = {text[:60]!r}{'…' if len(text) > 60 else ''} ({len(text)} karakter)")
    return out


args = sys.argv[1:]
if len(args) == 2 and args[0] == "--dump":
    domain = args[1]
    raw = knowledge.fetch_raw(knowledge._agent_for(domain))
    print("\n".join(outline(raw)))
    sys.exit(0)
if len(args) == 3 and args[0] == "--from-card":
    domain, path = args[1], args[2]
    with open(path, encoding="utf-8") as fh:
        card = json.load(fh)
    data = knowledge.save_from_card(domain, card)
    show(domain, data)
    print("Salinan pengetahuan dari agent card tersimpan di bucket." if knowledge.has_content(data)
          else "PERINGATAN: isi agent card kosong — periksa file JSON-nya.")
    sys.exit(0)

ok = True
for domain in knowledge.DOMAINS:
    data = knowledge.get(domain, force=True)
    show(domain, data)
    ok = ok and data.get("source") == "api" and knowledge.has_content(data)
print("\nHASIL:", "OK — pengetahuan Data Agent terbaca lewat API." if ok else
      "BELUM OK — isi belum terbaca lewat API. Jalankan '--dump retail' dan kirim hasilnya, "
      "atau buat salinan dengan '--from-card'.")
