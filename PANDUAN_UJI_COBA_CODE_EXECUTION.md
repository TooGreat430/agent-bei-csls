# Panduan Uji Coba — Analisis Berbasis Kode (Agent Engine Code Execution) · v2.2

Tujuan: menyalakan analisis berbasis kode **hanya untuk akun Anda**, mencoba kasus nyata, dan memantau biayanya
setiap hari sebelum diputuskan bersama PTPL. Fitur ini **mati secara default**; deploy v2.2 tidak mengubah apa pun
bagi user lain. Perkiraan waktu: 40 menit (termasuk deploy) + waktu uji coba.

## Data yang dipakai (sudah terisi)

| Item | Nilai |
|---|---|
| Project | `ptpl-land-dev` |
| Resource agent (induk sandbox) | `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| Region sandbox | `asia-southeast2` (Jakarta) — sudah diuji berhasil |
| Mesin sandbox | 4 vCPU / 4 GiB, umur 30 menit (diperpanjang tiap eksekusi) |
| settings.json | `gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json` |
| Meteran biaya | `gs://ptpl-ge-bucket/ge-docs-agent/usage/YYYY-MM-DD.json` |
| Batas biaya harian (default) | USD 5 per hari (semua pemakaian model + sandbox yang tercatat). Ubah dengan `--budget` |
| Batas langkah per pesan (default) | 25 eksekusi kode |
| File uji | `SORetail_24-26_DataReadRFM_SR1.xlsx` + `Prompt_Paten_Analisa_RFM_Retail_Outlet_PTPL_v1_3.txt` |

Tidak ada izin IAM baru: sandbox dibuat di bawah agent yang sama, di project yang sama.

---

## Langkah 1 — Deploy v2.2

Sama seperti v2.1 (`PANDUAN_REDEPLOY.md` langkah 1 dan 4): ganti isi repo dengan zip ini di laptop (CMD atau bash),
push, lalu di Cloud Shell:

```bash
cd ~/agent-bei-csls && git status --short && git pull
find . -name __pycache__ -prune -exec rm -rf {} +
bash scripts/update_agent.sh
```

Hasil yang diharapkan: langkah 4 menampilkan `ditambahkan: code_execution_..., price_...` (kunci baru, nilai yang
sudah Anda ubah tidak ditimpa), langkah 5 `OK` (137 uji), lalu `Selesai.` Fitur masih **mati**.

## Langkah 2 — Uji sandbox dengan kode agent yang sebenarnya

```bash
cd ~/agent-bei-csls && source .venv/bin/activate && python scripts/check_code_execution.py
```

Hasil yang diharapkan: tabel kecil di STDOUT, `FILE OUTPUT` berisi `hasil_uji.csv` dan `grafik_uji.png`, lalu
`HASIL: OK`. Jika `PERLU DICEK`, kirim seluruh output ke tim teknis dan berhenti di sini.

## Langkah 3 — Cari ID user Anda di Gemini Enterprise

1. Buka **chat baru** di Gemini Enterprise, kirim `halo`.
2. Di Cloud Shell:

```bash
python scripts/usage_report.py 1
```

Baris paling bawah menampilkan ID user yang tercatat (biasanya email, mis. `jason.kusuma@mii.co.id`). Salin persis.

## Langkah 4 — Nyalakan hanya untuk akun Anda

```bash
python scripts/code_execution_switch.py on jason.kusuma@mii.co.id --budget 5 --steps 25
```

(Ganti ID dengan hasil langkah 3.) Tunggu **5 menit**, lalu cek:

```bash
python scripts/code_execution_switch.py status
```

## Langkah 5 — Uji coba (chat baru untuk tiap kasus)

| No | Kirim | Yang diharapkan |
|---|---|---|
| 1 | Unggah file prompt RFM `.txt` + Excel SR1, ketik: `pelajari datanya dan lakukan analisa sesuai prompt` | Prompt diringkas; agent menyiapkan sandbox, menjalankan Step 1–2 (intake & audit: 5.918 outlet, 21 bulan, baris Grand Total terdeteksi), lalu **berhenti di Step 3** meminta persetujuan metodologi |
| 2 | `Setuju, lanjutkan Step 4 sampai 7` | Agent menghitung R/F/M, threshold baseline 2025, 12 segmen, migrasi; menyerahkan link CSV/PNG/HTML/script. Jika kena batas 25 langkah, agent melapor progres dan bertanya |
| 3 | `Berapa outlet Champions di 2026 dan berapa total volumenya?` | Angka dari output kode (bisa dicek di file CSV hasil langkah 2) |
| 4 | Satu permintaan analisis lain yang sering diminta user (dengan file aslinya) | Hasil sesuai permintaan, tanpa angka karangan |
| 5 | `akhiri analisis` | Sandbox dihapus |

Catat untuk setiap kasus: **berhasil/tidak**, **waktu sampai selesai**, dan **jumlah langkah**.

## Langkah 6 — Pantau biaya setiap hari

```bash
python scripts/usage_report.py 7
```

Kolom yang penting: **Total USD** per hari dan per user. Kurs default Rp16.500; ubah dengan
`KURS_USD_IDR=16300 python scripts/usage_report.py 7`.

Bandingkan dengan tagihan resmi beberapa hari kemudian: Konsol → **Billing** → **Reports** → filter project
`ptpl-land-dev`, kelompokkan per **SKU**. Cari SKU Gemini/Vertex AI dan Agent Engine (Code Execution). Meteran
adalah estimasi dari token & durasi eksekusi; selisih kecil dengan tagihan resmi itu wajar.

Pengaman yang bekerja otomatis:
- Biaya hari ini mencapai batas → eksekusi kode ditolak sampai besok (pertanyaan biasa tetap jalan).
- 25 langkah dalam satu pesan → agent berhenti dan bertanya.
- Sandbox kedaluwarsa sendiri 30 menit setelah eksekusi terakhir.

## Langkah 7 — Matikan bila perlu (kapan saja)

```bash
python scripts/code_execution_switch.py off
```

Berlaku maksimal 5 menit kemudian; tidak perlu deploy.

## Bahan untuk diskusi dengan PTPL

Setelah 3–5 hari uji coba, kumpulkan: hasil `usage_report.py` (biaya per hari & per kasus), daftar kasus yang
berhasil/gagal, contoh file output, dan tagihan resmi dari Billing. Itu menjadi dasar estimasi biaya bulanan yang
nyata, menggantikan estimasi kasar sebelumnya.

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| Agent tidak menulis kode / bilang fitur belum aktif | Belum 5 menit, atau ID user tidak cocok | `code_execution_switch.py status`; cocokkan ID dengan `usage_report.py 1` |
| "Fitur … uji coba terbatas. ID Anda: …" | ID di daftar berbeda | Pakai ID yang disebut agent: `code_execution_switch.py on <ID itu>` |
| "Batas biaya harian … tercapai" | Pengaman bekerja | Tunggu besok, atau naikkan `--budget` secara sadar |
| Error saat membuat sandbox | `LIB_AGENT_RESOURCE` kosong di `.env` | `grep LIB_AGENT_RESOURCE .env`; ulangi `update_agent.sh` (mengisi otomatis) |
| Hasil analisis salah tafsir data | Batas kemampuan model | Beri instruksi lebih spesifik; catat kasusnya untuk evaluasi Gemini vs Claude |
