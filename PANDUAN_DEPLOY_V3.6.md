# Panduan Deploy v3.6 — Analisis RFM Outlet Sell-out + Batas 1 Laporan Berat per Pesan

Perbaikan untuk error `DEADLINE_EXCEEDED` (400 FAILED_PRECONDITION) yang dialami user klien di chat
"RFM Outlet Analysis review" (20 Nov 2026). Dibangun di atas v3.5.2. Perkiraan waktu: 30–40 menit.

| Isi v3.6 | Ringkas |
|---|---|
| `analisis_rfm` | RFM outlet Bengkel + Toko Oli dihitung **kode** langsung dari `SALES_OUT_DAILY` (metodologi Master Prompt v1.0 / SR7 v5): skor R/F/M, threshold P20–P80 per region, 12 segmen, matriks 12×12, momentum, produk, Top 20 outlet, audit. Hasil per cakupan: laporan HTML 8 section + Excel register |
| Semua sekaligus | "RFM nasional + semua Sales Region" = **satu pesan, satu panggilan**: data ditarik sekali, narasi ditulis paralel, 8 laporan + **halaman paket** (perbandingan + semua link). Ada batas waktu internal 5 menit: bila terlampaui, sisa laporan ditawarkan "ketik lanjut" (tidak pernah error) |
| Laporan berbeda sekaligus | Alat baru `buat_laporan_sekaligus`: mis. "dashboard harga Q3 + laporan planogram + RFM semua region" dalam **satu pesan** → semua dikerjakan paralel, hasil keluar di jawaban yang sama (batas waktu internal 5 menit; sisa → "ketik lanjut") |
| Batas waktu | Maksimal **satu panggilan alat laporan berat per pesan** (template/custom, revisi, RFM). Mencegah agent memanggil laporan custom 6× seperti insiden 20 Nov siang |
| Pengalihan | Permintaan RFM sell-out tidak lagi lewat laporan custom / tanya-jawab Data Agent (penyebab bagian "n/a") |

Izin: **tidak ada izin baru.** SA sudah punya Data Viewer di tabel `SALES_OUT_DAILY` + `bigquery.jobUser`.
`settings.json` **tidak perlu diubah** (nilai default ada di kode; kunci `rfm_*` opsional).

## Data yang dipakai (sudah terisi)

| Item | Nilai |
|---|---|
| Repo laptop / Cloud Shell | `agent-bei-csls` / `~/agent-bei-csls` |
| Zip | `%USERPROFILE%\Downloads\ge-library-agent.zip` |
| Tabel | `ptpl-curated-prd.DATAMART.SALES_OUT_DAILY` |
| Cut-off default | `2026-09` (baseline Jan–Des 2025, YTD Jan–Sep 2026) |
| Tag cadangan | `cadangan-v352` |

---

## Langkah 1 — Cadangan (laptop CMD)

```bat
cd agent-bei-csls
git pull
git tag cadangan-v352
git push origin cadangan-v352
```

## Langkah 2 — Masukkan kode v3.6 (laptop)

Zip berisi seluruh repo v3.6. **Jika sejak v3.5.2 Anda belum mengubah kode di Claude Code**, ganti seluruh isi:
```bat
cd agent-bei-csls
for /d %d in (*) do @if /i not "%d"=="riwayat-chat" rmdir /s /q "%d"
for %f in (*) do @del /q "%f"
if exist %TEMP%\gla rmdir /s /q %TEMP%\gla
mkdir %TEMP%\gla
tar -xf %USERPROFILE%\Downloads\ge-library-agent.zip -C %TEMP%\gla
xcopy /e /h /y /q %TEMP%\gla\ge-library-agent\* .
```
**Jika Anda sudah mengubah kode**, salin hanya file berikut dari zip (atau minta Claude Code menggabungkannya):

| File | Status |
|---|---|
| `library_agent/rfm_engine.py`, `library_agent/rfm_report.py`, `library_agent/tools/rfm_tools.py` | baru |
| `tests/test_rfm.py`, `tests/_rfm_synth.py`, `scripts/check_rfm.py`, `PANDUAN_DEPLOY_V3.6.md` | baru |
| `library_agent/tools/batch_tools.py`, `tests/test_batch.py` | baru |
| `library_agent/tools/report_tools.py`, `library_agent/tools/data_tools.py`, `library_agent/subagents/data.py`, `library_agent/subagents/files.py`, `library_agent/prompts.py`, `library_agent/config.py` | diubah |
| `setup/settings.json`, `tests/test_industry.py`, `README.md`, `CLAUDE.md`, `docs/knowledge/keputusan.md`, `docs/knowledge/insiden.md` | diubah |

Lalu uji & push:
```bat
python -m unittest discover tests
git add -A
git commit -m "v3.6: analisis_rfm (RFM sell-out dihitung kode) + batas 1 laporan berat per pesan"
git push
```
Uji harus `OK` (278 uji). Pastikan `riwayat-chat/` tidak ikut ter-commit (`git status` tidak menampilkannya).

## Langkah 3 — Ambil kode & cek data RFM (Cloud Shell)

```bash
cd ~/agent-bei-csls && git pull && git log --oneline -1
source .venv/bin/activate && pip install -q -r requirements.txt
python scripts/check_rfm.py --report SR7 2>&1 | tee cek_rfm.txt
```
Butuh ±1–3 menit. **Kirim isi `cek_rfm.txt` ke tim teknis** — dipakai untuk mengonfirmasi asumsi:

| Bagian output | Yang dicek |
|---|---|
| 1. DT_PR | Kolom `hari` per bulan harus > 1 (mis. 20–31). Jika hanya 1, DT_PR adalah tanggal proses, bukan tanggal transaksi |
| 2. REGION_NAME | Tiap region terpetakan ke `SR1`..`SR7` |
| 3. Tipe outlet | OTO-5/6/7/8/9/10/13 bertanda `✓ dipakai` |
| 4. Seri produk | Nama seri (Fastron, Enduro, dst.) dan baris "dikecualikan" muncul di MEDITRAN SX BIO |
| 6. Pemeriksaan | `migration_reconciled: True`, `segments_reconciled: True`, `rules_125: 'PASS'`, `unassigned_outlets: 0` |

Laporan uji tersimpan di `rfm_uji/RFM_SR7_2026-09.html` dan `.xlsx` (Cloud Shell Editor → klik kanan → Download).
Bandingkan angkanya dengan laporan SR7 v5 yang sudah ada.

## Langkah 4 — Deploy (Cloud Shell)

```bash
find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```
Harus berakhir `Uji: OK` (278 uji) dan `Selesai.` Jalankan **sekali** dan jangan `Ctrl+C`.

## Langkah 5 — Uji (chat baru, tunggu 5 menit setelah deploy)

| No | Kirim | Lulus jika |
|---|---|---|
| 1 | `Buatkan analisis RFM outlet SR7` | Satu jawaban berisi ringkasan angka + 2 link (HTML 8 section, Excel register) |
| 2 | `Buatkan laporan RFM untuk setiap Sales Region dan 1 nasional` | **Satu pesan** → link halaman paket + 8 laporan HTML + 8 Excel, ±2–4 menit, **tanpa DEADLINE_EXCEEDED**. Catat `durasi_detik` di log |
| 3 | `RFM SR2 dan SR5 saja` | Dua laporan + halaman paket dalam satu jawaban (data dari cache, lebih cepat) |
| 3b | `Buatkan dashboard daya saing harga Q3 2026 dan laporan planogram Q3 2026, format PDF` | Satu jawaban berisi kedua laporan (bukan "ketik lanjut") |
| 4 | Unggah master prompt RFM + `Kerjakan sesuai prompt ini untuk SR3` | Agent memakai analisis_rfm (bukan laporan custom); bagian laporan tidak ada "n/a" |
| 5 | `Laporan custom sell-out per distributor Q3 PDF` | Laporan custom tetap jalan seperti biasa (regresi) |
| 6 | `Buatkan laporan custom retail harga Fastron dan laporan custom industri Mining, HTML` | Kedua laporan custom jadi dalam satu jawaban |

Buka laporan HTML: 8 section (Executive Overview … Methodology & Data Governance), footer
"Marketing Intelligence & Research — PTPL 2026 | RFM Retail Outlet Intelligence • Sales Region 7".

## Saran untuk user klien

- Boleh langsung minta semuanya ("RFM setiap Sales Region + nasional"); hasilnya satu halaman paket berisi semua link.
- Mulai dari **chat baru** (chat lama yang panjang memperlambat setiap jawaban).
- Data ditarik sekali lalu disimpan 12 jam; minta "tarik ulang data RFM" bila data BigQuery baru saja diperbarui.
- Cut-off lain: "RFM SR2 cut-off Oktober 2026" (format bulan apa pun yang jelas).

## Pengaturan opsional (tanpa deploy, berlaku ≤ 5 menit)

Tambahkan kunci ke `settings.json` di bucket **hanya bila perlu** (konfirmasi dulu):

| Kunci | Default | Contoh perubahan |
|---|---|---|
| `rfm_cutoff` | `2026-09` | `2026-10` setelah data Oktober lengkap |
| `rfm_series_column` | `PRODUCT_SEGMENT` | `PRODUCT_SEG_GRP` bila seri ada di kolom itu |
| `rfm_store_types` | OTO-5,6,7,8,9,10,13 | daftar lain |
| `rfm_exclude_pattern` | `MEDITRAN SX BIO` | beberapa pola dipisah `|` |
| `rfm_footer_credit` | `Prepared with Marketing Insight Assistant` | teks footer kanan |
| `rfm_time_budget` | `300` (detik) | batas waktu internal satu panggilan RFM; turunkan bila GE masih timeout |
| `batch_time_budget` | `300` (detik) | batas waktu internal `buat_laporan_sekaligus` |
| `rfm_narrative_timeout` | `120` (detik) | batas tunggu narasi Claude per laporan; lewat batas → narasi standar (angka tetap sama) |

## Rollback

```bat
cd agent-bei-csls
git pull
git rm -r -q .
git checkout cadangan-v352 -- .
git commit -m "rollback ke v3.5.2"
git push
```
Cloud Shell: `cd ~/agent-bei-csls && git pull && find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh`

## Troubleshooting

| Gejala | Solusi |
|---|---|
| `Analisis RFM gagal: service account belum punya akses…` | Akses tabel berubah; cek ulang Data Viewer SA di `SALES_OUT_DAILY` |
| Bulan terakhir kosong / angka YTD terlalu kecil | Data bulan cut-off belum lengkap → turunkan `rfm_cutoff` atau sebut cut-off di pesan |
| Region tidak dikenali | Kirim output bagian 2 `check_rfm.py` (format REGION_NAME) |
| Masih DEADLINE_EXCEEDED | Kirim log (perintah di README); sertakan jam kejadian |
