# Panduan Deploy Aman — v3.0 (dengan cadangan & rollback)

**Baru di v3.0:** Claude (`claude-opus-5-5`) untuk tugas berat dengan cadangan Gemini 4 Argon, dan skill pembuatan
file (Excel/PowerPoint/Word/PDF/edit file user). **Untuk deploy v3.0 ikuti `PANDUAN_CLAUDE_DAN_SKILL.md`** — panduan
ini tetap berlaku untuk rollback dan uji cepat umum.

**Dari v2.10:** (1) penulisan laporan mencoba ulang lalu pindah ke **Argon global** saat kuota/kapasitas Argon
regional habis (penyebab laporan gagal → user meminta TXT pada 7 Nov); `update_agent.sh` tidak lagi memaksa region
Argon. (2) **Batas pemakaian harian/bulanan** dengan notifikasi ke user (peringatan di 80%, laporan dihentikan
sementara saat batas tercapai) — default mati, diatur dengan `scripts/set_budget.py`.

**Dari v2.9:** laporan dari **data BigQuery** yang sudah ditarik kini dibuat langsung oleh agent data (HTML/PDF/
PowerPoint, Gemini 4 Argon + template PTPL) — sebelumnya bisa berakhir sebagai TXT. Agent menawarkan laporan (ya/tidak)
setelah jawaban data selesai, dan laporan memakai data yang sudah ditarik di chat tanpa menarik ulang.

**Dari v2.8:** setelah analisis selesai, agent **menawarkan** (ya/tidak) untuk membuat laporan — tidak memotong
analisis; format (HTML/PDF/PowerPoint) ditanyakan setelah user setuju bila belum disebut; semua laporan lewat Argon + template PTPL — **tidak ada lagi hasil berbentuk TXT** (diblokir di level
kode); user yang membawa dokumen hasil analisis (TXT/PDF/Word) bisa langsung dibuatkan laporan di agent ini.

**Dari v2.7:** laporan dari hasil analisis unggahan manual kini dibuat langsung oleh agent analisis file dengan
**Gemini 4 Argon + base template PTPL** dalam HTML/PDF/PowerPoint (sebelumnya agent bisa berimprovisasi menjadi .txt).
Penulisan laporan mendapat cadangan **Argon global** bila Argon `asia-southeast1` penuh, dan hasil eksekusi kode
(sandbox) ikut masuk ke laporan.

**Dari v2.6:** laporan custom kini tersedia dalam **HTML, PDF, dan PowerPoint** (sebelumnya hanya HTML). Agent
selalu menanyakan format bila user belum menyebutnya, user bisa memilih beberapa sekaligus, dan laporan yang sudah
jadi bisa dikonversi ke format lain tanpa ditulis ulang. Dependensi baru: `beautifulsoup4` (terpasang otomatis).

**Dari v2.5:** file Excel hasil **PivotTable** (header bertingkat, seperti data Mesrania 2T) dibaca dengan
benar; harga otomatis dibandingkan **per liter** bila kemasan berbeda ukuran; laporan custom bisa langsung dibuat dari
file format umum; dan laporan custom bisa dibangun **di dalam template HTML milik user** (mis.
`MIR_Master_HTML_Report_Template.html`).

**Dari v2.4:** user bisa meminta **file Excel** hasil analisis file ("generate excel"). Agent menjalankan ulang
analisis dengan seluruh baris (mis. 5.918 outlet, bukan Top 50) dan memberi link unduhan .xlsx multi-sheet — tanpa
Code Execution dan tanpa biaya tambahan. Agent tidak lagi menyuruh user menjalankan Python sendiri, dan tidak lagi
menyebut fitur sandbox kepada user yang belum diaktifkan.

**Dari v2.3:** cadangan otomatis saat kapasitas model penuh (error 429 `RESOURCE_EXHAUSTED` yang membuat analisis
RFM gagal): Argon `asia-southeast1` → Argon `global` → model cepat `global`, dan bila semua penuh agent membalas pesan
"layanan padat" alih-alih error 400. Tracing dimatikan (menghilangkan log `Failed to export span … 403`).

Versi ini juga mencakup semua perbaikan sejak v2: bug `report_prefix` (laporan & grafik gagal disimpan), Excel tidak
terdeteksi / error 400, semua format file, Retail × Planogram, dan fitur Code Execution. **Code Execution ikut
ter-deploy dalam keadaan MATI** — tidak ada biaya baru dan tidak ada perubahan perilaku sampai Anda menyalakannya
sendiri (lihat `PANDUAN_UJI_COBA_CODE_EXECUTION.md`).

## Data yang dipakai (sudah terisi)

| Item | Nilai |
|---|---|
| Repo | laptop: folder `agent-bei-csls` · Cloud Shell: `~/agent-bei-csls` |
| Zip | `%USERPROFILE%\Downloads\ge-library-agent.zip` (Windows) |
| Resource agent | `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| settings.json | `gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json` |
| Nama tag cadangan | `cadangan-v2` |

Perkiraan waktu: 30 menit (deploy 5–10 menit di dalamnya).

---

## Langkah 0 — Buat titik cadangan (laptop, CMD)

```bat
cd agent-bei-csls
git pull
git tag cadangan-v2
git push origin cadangan-v2
```

Hasil yang diharapkan: `* [new tag] cadangan-v2 -> cadangan-v2`. Ini menandai kode yang sedang berjalan sekarang.
Jika tag sudah ada dari deploy sebelumnya, pakai nama baru, mis. `cadangan-v22` (sesuaikan juga di bagian Rollback).

## Langkah 1 — Cadangkan settings.json (Cloud Shell)

```bash
gcloud storage cp gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json \
  gs://ptpl-ge-bucket/ge-docs-agent/config/settings.cadangan-v2.json
```

## Langkah 2 — Ganti isi repo dengan versi baru (laptop, CMD)

Jalankan baris per baris:

```bat
cd agent-bei-csls
for /d %d in (*) do @rmdir /s /q "%d"
for %f in (*) do @del /q "%f"
if exist %TEMP%\gla rmdir /s /q %TEMP%\gla
mkdir %TEMP%\gla
tar -xf %USERPROFILE%\Downloads\ge-library-agent.zip -C %TEMP%\gla
xcopy /e /h /y /q %TEMP%\gla\ge-library-agent\* .
git add -A
git commit -m "v2.10: coba ulang + Argon global untuk laporan, batas pemakaian harian/bulanan dengan notifikasi"
git push
```

## Langkah 2b — (Disarankan) Argon global sebagai endpoint utama

Sesuai sizing (Argon *Standard, Global*) dan untuk menghindari kuota regional yang sering habis. Lewati jika PTPL
mensyaratkan region tetap. Caranya: pada langkah 3, ganti perintah terakhir menjadi
`NEW_GEMINI_LOCATION_PRO=global bash scripts/update_agent.sh`. Script akan menampilkan
`Model utama: gemini-4-argon @ global`.

## Langkah 3 — Deploy (Cloud Shell)

```bash
cd ~/agent-bei-csls && git status --short
```

Jika muncul daftar file, jalankan `git reset --hard @{u}` dulu. Lalu:

```bash
git pull && find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```

Hasil yang diharapkan: langkah 5 `OK` (196 uji), langkah 6 berakhir `Selesai.` **Jalankan sekali saja** dan jangan tekan
`Ctrl+C`. Jika uji di langkah 5 gagal, script berhenti sendiri dan agent **tidak berubah** — kirim outputnya ke tim teknis.

## Langkah 4 — Cek cepat di Gemini Enterprise (chat baru, ±10 menit)

| No | Kirim | Lulus jika |
|---|---|---|
| 1 | `Halo, kamu bisa apa saja?` | Menyebut data BigQuery, file unggahan (data & dokumen), laporan template/custom |
| 2 | `Buat dashboard daya saing harga retail Q3 2026 vs Q2 2026, PDF` | Ada link PDF yang bisa dibuka (bug `report_prefix` hilang) |
| 3 | `Berapa gap HTO Product Hero vs kompetitor di Zona 1 Q3 2026?` | Ada tabel dan link grafik yang bisa dibuka |
| 4 | Unggah **1** file Excel + `profil file ini` | Jenis data, jumlah baris, periode disebut; tidak ada error 400 |
| 5 | Unggah 1 PDF + `rangkum` | Ringkasan isi PDF |
| 7 | Chat baru: unggah `MIR_Mesrania2T_PriceCompetitiveness_Q1-Q32026.xlsx` + `MIR_Master_HTML_Report_Template.html`, kirim prompt yang sama seperti sebelumnya | Agent langsung membuat laporan custom (tanpa meminta analisis dulu); link HTML memakai desain template Anda; harga dibandingkan **per liter** (Mesrania Q3 Rp65.129/L vs Castrol Rp91.571/L), bukan per kemasan |
| 8 | Chat baru: `Buatkan laporan custom planogram: ND per SR Q3 vs Q2 2026` (tanpa menyebut format) | Agent menanyakan format (HTML/PDF/PowerPoint). Jawab `PDF dan PowerPoint` → dua link; lalu `buat juga versi HTML` → link HTML tanpa laporan ditulis ulang; `approve` → FINAL dalam ketiga format |
| 11 | Chat baru: `Berapa gap HTO Product Hero vs kompetitor di Zona 1 Q3 2026?` → setelah dijawab, agent bertanya apakah ingin dibuatkan laporan → jawab `ya` → agent menanyakan format → jawab `HTML dan PDF` | Dua link (HTML & PDF) bergaya PTPL berisi angka yang sama dengan jawaban tadi; **tidak ada TXT** atau laporan berupa teks di chat |
| 10 | Chat baru: unggah file TXT hasil analisis (mis. TXT yang dulu dihasilkan agent) + `Buatkan laporan PowerPoint dari hasil analisa ini` | Link PPTX bergaya PTPL berisi angka dari TXT; tidak menyuruh pindah chat |
| 9 | Chat baru: unggah Excel SR1 → `Hitung volume dan jumlah bulan aktif per outlet per tahun` → `Buatkan one pager untuk management dari hasil analisa ini` | Setelah analisis selesai, agent **bertanya** "Apakah Anda ingin saya buatkan laporan…?" (tanpa langsung membuat). Jawab `ya` → agent menanyakan format; jawab `PDF` → link PDF satu halaman bergaya PTPL dengan angka dari analisis tadi. **Tidak boleh** berupa file .txt atau teks di chat |
| 6 | Lanjut di chat no. 4: `Hitung volume dan jumlah bulan aktif per outlet`, lalu `Generate excel dari hasil analisa ini` | Link .xlsx; sheet berisi **seluruh** outlet (bukan hanya yang tampil di chat) + sheet Keterangan; agent tidak menyuruh menjalankan Python |

Lalu ambil log untuk memastikan cara Gemini Enterprise mengirim lampiran:

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"
  AND resource.labels.reasoning_engine_id="5516874359156768768"
  AND (severity>=WARNING OR textPayload:"user_content parts" OR textPayload:"disimpan")' \
  --project=ptpl-land-dev --freshness=1h --limit=40 \
  --format="value(timestamp,severity,textPayload)" | cut -c1-1200
```

Lulus jika ada baris `File data disimpan: …xlsx` untuk uji no. 4 dan tidak ada `ERROR`.

Setelah 11 uji lulus, coba bertahap: 3 file Excel sekaligus, lalu 7 file sekaligus. Kirim log di atas setelahnya.

---

## Langkah 5 — (Opsional) Batas pemakaian dengan notifikasi ke user

```bash
cd ~/agent-bei-csls && source .venv/bin/activate
python scripts/set_budget.py set --harian 10 --bulanan 150 --peringatan 80 --cakupan berat
python scripts/usage_report.py 7          # pemakaian & status batas
```

Angka di atas contoh; sesuaikan dengan anggaran yang disepakati PTPL. `--cakupan berat` hanya menghentikan laporan
dan analisis berbasis kode saat batas tercapai; tanya-jawab tetap jalan. Matikan: `python scripts/set_budget.py off`.

## Rollback (jika ada masalah serius)

Mengembalikan agent persis ke kode sebelum langkah 2.

**Laptop (CMD):**

```bat
cd agent-bei-csls
git pull
git rm -r -q .
git checkout cadangan-v2 -- .
git commit -m "rollback ke cadangan-v2"
git push
```

**Cloud Shell:**

```bash
cd ~/agent-bei-csls && git reset --hard @{u} && git pull
gcloud storage cp gs://ptpl-ge-bucket/ge-docs-agent/config/settings.cadangan-v2.json \
  gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json
find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```

Catatan: kode v2 memiliki bug `report_prefix`, jadi setelah rollback laporan & grafik kembali gagal disimpan seperti
sebelumnya. Rollback hanya untuk keadaan darurat; kirim log errornya agar diperbaiki di versi berikutnya.
