"""(Opsional, untuk tim teknis) Samakan katalog dengan folder dokumen dari Cloud Shell.

Biasanya TIDAK perlu: agent sudah menyamakan katalog otomatis setiap kali user membuka
katalog atau memilih dokumen. Script ini berguna untuk pemuatan awal file dalam jumlah
sangat banyak, karena memproses semua file tanpa batas per putaran.

    python scripts/sync_folder.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

os.environ.setdefault("LIB_FOLDER_BATCH_SIZE", "100000")

from library_agent import sync  # noqa: E402

result = sync.sync_folder()
print(f"Ditambahkan: {len(result['added'])} | diperbarui: {len(result['updated'])} | "
      f"dihapus: {len(result['removed'])} | dilewati: {len(result['skipped'])}")
for doc in result["added"] + result["updated"]:
    flag = f"  (perlu dicek: {', '.join(doc['needs_review'])})" if doc.get("needs_review") else ""
    print(f"  + {doc['file_name']} -> {doc['title']} ({doc['doc_type'] or '?'}, v{doc['version']}){flag}")
for doc in result["removed"]:
    print(f"  - {doc['file_name']} ({doc['title']})")
for item in result["skipped"]:
    print(f"  ! {item['file_name']}: {item['reason']}")
