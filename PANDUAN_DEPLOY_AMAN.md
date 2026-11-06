# Panduan Deploy Aman — v2.4 (dengan cadangan & rollback)

**Baru di v2.4:** user bisa meminta **file Excel** hasil analisis file ("generate excel"). Agent menjalankan ulang
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
git commit -m "v2.4: ekspor Excel hasil analisis, cadangan kapasitas model (429), Code Execution (mati)"
git push
```

## Langkah 3 — Deploy (Cloud Shell)

```bash
cd ~/agent-bei-csls && git status --short
```

Jika muncul daftar file, jalankan `git reset --hard @{u}` dulu. Lalu:

```bash
git pull && find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```

Hasil yang diharapkan: langkah 5 `OK` (146 uji), langkah 6 berakhir `Selesai.` **Jalankan sekali saja** dan jangan tekan
`Ctrl+C`. Jika uji di langkah 5 gagal, script berhenti sendiri dan agent **tidak berubah** — kirim outputnya ke tim teknis.

## Langkah 4 — Cek cepat di Gemini Enterprise (chat baru, ±10 menit)

| No | Kirim | Lulus jika |
|---|---|---|
| 1 | `Halo, kamu bisa apa saja?` | Menyebut data BigQuery, file unggahan (data & dokumen), laporan template/custom |
| 2 | `Buat dashboard daya saing harga retail Q3 2026 vs Q2 2026, PDF` | Ada link PDF yang bisa dibuka (bug `report_prefix` hilang) |
| 3 | `Berapa gap HTO Product Hero vs kompetitor di Zona 1 Q3 2026?` | Ada tabel dan link grafik yang bisa dibuka |
| 4 | Unggah **1** file Excel + `profil file ini` | Jenis data, jumlah baris, periode disebut; tidak ada error 400 |
| 5 | Unggah 1 PDF + `rangkum` | Ringkasan isi PDF |
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

Setelah 6 uji lulus, coba bertahap: 3 file Excel sekaligus, lalu 7 file sekaligus. Kirim log di atas setelahnya.

---

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
