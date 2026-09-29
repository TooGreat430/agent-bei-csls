"""Impor dokumen dari folder bucket ke perpustakaan agent.

Pemakaian (dari root repo, setelah memuat .env):

  1) Pindai folder dan buat CSV untuk dicek:
     python scripts/import_folder.py scan gs://ptpl-ge-bucket/ge-docs-datastore/

  2) Cek/koreksi import_review.csv (kolom title, doc_type, version, doc_date, action),
     lalu impor:
     python scripts/import_folder.py run --wait

  Tanpa pemeriksaan CSV (langsung impor):
     python scripts/import_folder.py auto gs://ptpl-ge-bucket/ge-docs-datastore/ --wait

  Hapus dari perpustakaan dokumen yang file sumbernya sudah dihapus dari folder:
     python scripts/import_folder.py prune gs://ptpl-ge-bucket/ge-docs-datastore/

Opsi:
  --csv PATH     Lokasi CSV (default: import_review.csv)
  --max-mb N     Lewati file lebih besar dari N MB (default: 100)
  --in-place     Rujuk file di lokasi asli, tanpa menyalin (default: disalin ke folder perpustakaan)
  --wait         Tunggu indexing selesai dan tampilkan hasilnya

Impor ulang berkala aman: file yang sudah ada dilewati, file yang isinya berubah menjadi
versi baru, dan dokumen yang pernah dihapus user tidak dimasukkan lagi.
"""
import argparse
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from library_agent import folder_import  # noqa: E402


def _print_scan_summary(rows, csv_path):
    counts = Counter(r["action"] for r in rows)
    check = [r for r in rows if r["action"] == "IMPORT" and "MOHON DICEK" in r["note"]]
    print(f"\nTotal file: {len(rows)} | akan diimpor: {counts.get('IMPORT', 0)} | dilewati: {counts.get('SKIP', 0)}")
    if check:
        print(f"Perlu dicek manual: {len(check)} file (lihat kolom 'note' berisi 'MOHON DICEK')")
    skipped = [r for r in rows if r["action"] == "SKIP"]
    for r in skipped[:15]:
        print(f"  - dilewati: {r['file_name']} -> {r['note']}")
    if len(skipped) > 15:
        print(f"  ... dan {len(skipped) - 15} lainnya (lihat CSV)")
    print(f"\nCSV: {csv_path}")


def _print_run_summary(result, wait):
    print(f"\nBerhasil didaftarkan: {len(result['imported'])} dokumen")
    for rec in result["imported"]:
        print(f"  + {rec['title']} ({rec['doc_type']}, v{rec['version']}, {rec['doc_date']})")
    if result["errors"]:
        print(f"\nTidak diimpor: {len(result['errors'])} baris")
        for err in result["errors"]:
            print(f"  ! {err['file']}: {err['problem']}")
    if wait and result["imported"]:
        print("\nMenunggu indexing selesai (bisa beberapa menit)...")
        counts = folder_import.wait_for_indexing(result["imported"])
        print(f"Indexing: siap={counts['ready']} gagal={counts['failed']} masih proses={counts['indexing']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["scan", "run", "auto", "prune"])
    parser.add_argument("source", nargs="?", help="Folder sumber, mis. gs://ptpl-ge-bucket/ge-docs-datastore/")
    parser.add_argument("--csv", default=os.path.join(ROOT, "import_review.csv"))
    parser.add_argument("--max-mb", type=float, default=100)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()

    if args.command in ("scan", "auto", "prune") and not (args.source or "").startswith("gs://"):
        parser.error("Folder sumber wajib diisi, contoh: gs://ptpl-ge-bucket/ge-docs-datastore/")

    if args.command in ("scan", "auto"):
        print(f"Memindai {args.source} ...")
        rows = folder_import.scan(args.source, args.max_mb)
        folder_import.write_csv(rows, args.csv)
        _print_scan_summary(rows, args.csv)
        if args.command == "scan":
            print("Langkah berikutnya: cek CSV, lalu jalankan: python scripts/import_folder.py run --wait")
            return
        rows = folder_import.read_csv(args.csv)
        _print_run_summary(folder_import.run(rows, args.in_place), args.wait)

    elif args.command == "run":
        if not os.path.exists(args.csv):
            parser.error(f"CSV tidak ditemukan: {args.csv}. Jalankan 'scan' terlebih dahulu.")
        rows = folder_import.read_csv(args.csv)
        _print_run_summary(folder_import.run(rows, args.in_place), args.wait)

    elif args.command == "prune":
        removed = folder_import.prune(args.source)
        print(f"Dihapus dari perpustakaan: {len(removed)} dokumen")
        for item in removed:
            if item.get("deleted"):
                print(f"  - {item['deleted']['title']} v{item['deleted']['version']}")


if __name__ == "__main__":
    main()
