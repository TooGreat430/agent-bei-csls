"""Uji sungguhan laporan visual otomatis (Claude menyusun storyboard -> PPTX/PDF/HTML) TANPA deploy.

Jalankan di Cloud Shell (butuh akses Vertex AI):
    python scripts/check_visual_report.py                       # pakai data contoh bawaan
    python scripts/check_visual_report.py hasil_analisis.txt    # pakai teks analisis Anda sendiri (mis. isi PDF)

Hasil: folder visual_check/ berisi laporan .pptx/.pdf/.html + storyboard.json, dan ringkasan di layar
(sumber storyboard claude/cadangan, revisi, jumlah halaman & chart, angka hilang/tidak terverifikasi, durasi).
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE = """### Brand Health Study Q3 2026 — Brand Equity Index (BEI) mobil penumpang (4W)
Pertamina Fastron BEI 21.0 (turun 1.7 dari Q2 22.7), TMO 14.3, Shell Helix 13.3, Castrol Magnatec 8.4, Prima XP 6.4.
Effective Equity: Fastron 21.8 (Brand Desire 23.8 + Market Effect -1.98), TMO 22.4 (Market Effect +2.03).
Market Effect Fastron: harga -0.41, stok kosong -0.29, promo -0.19.

| Merek | BEI Q3 | Delta vs Q2 | Aware % | Consider % | P12M % | BUMO % |
|---|---|---|---|---|---|---|
| Fastron | 21.0 | -1.7 | 92 | 36 | 24 | 21 |
| TMO | 14.3 | 0.6 | 61 | 26 | 24 | 23 |
| Shell Helix | 13.3 | -1.1 | 84 | 30 | 18 | 15 |

### Sepeda motor (2W)
Pertamina Enduro BEI 7.4 (+2.9), #2 nasional dan #1 Non-ATPM; AHM MPX 15.8. Awareness Enduro naik 13 poin ke 71%,
hanya 23% yang lanjut consider (AHM MPX 46%). Brand Desire Enduro 5.3 -> 9.6; BUMO 4% -> 10%.

### Komersial diesel
Pertamina Meditran BEI 22.4 (+5.1), Shell Rimula 10.2, Mesran 9.5. BUMO Meditran 37% (+9 poin), CSAT 90%, NPS 90%.
Barrier "tidak cocok kendaraan" naik 22% (Q1) -> 33% -> 51%. Net switching -0.7%.

### Peran mekanik
Pengaruh rekomendasi mekanik Q2 -> Q3: Fastron 30% -> 56%, Enduro 34% -> 57%, Meditran 34% -> 56%; TMO 67%,
AHM MPX 69%, Mesran 74%. NPS: Fastron 84%, Enduro 90%, Meditran 90%.
"""


def main() -> None:
    from library_agent.visual_report.planner import key_numbers, make_report

    data = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else SAMPLE
    keys = key_numbers([data])[:60]
    out = make_report("Buatkan laporan eksekutif dari hasil analisis ini", data, keys, ("pptx", "pdf", "html"),
                      label="Uji check_visual_report")
    folder = os.path.join(os.getcwd(), "visual_check")
    os.makedirs(folder, exist_ok=True)
    for fmt, blob in out["files"].items():
        with open(os.path.join(folder, f"laporan_visual.{fmt}"), "wb") as fh:
            fh.write(blob)
    with open(os.path.join(folder, "storyboard.json"), "w", encoding="utf-8") as fh:
        json.dump(out["storyboard"], fh, ensure_ascii=False, indent=1)
    print(json.dumps({"sumber_storyboard": out["sumber_storyboard"], "revisi": out["revisi"],
                      "halaman": out["stats"]["slide"], "chart": out["stats"]["chart"],
                      "slide_tanpa_visual": out["stats"]["slide_tanpa_visual"],
                      "angka_hilang": out["angka_hilang"], "angka_tidak_terverifikasi": out["angka_tidak_terverifikasi"],
                      "angka_dibulatkan": out["angka_dibulatkan"], "detik": out["detik"],
                      "judul_halaman": [s.title for s in out["deck"].slides]}, ensure_ascii=False, indent=1))
    print(f"\nFile tersimpan di {folder}  (unduh: cloudshell download visual_check/laporan_visual.pptx)")


if __name__ == "__main__":
    main()
