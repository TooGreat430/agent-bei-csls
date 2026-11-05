# Panduan Redeploy — Marketing Insight Assistant v2.1

Update **di tempat**: resource Agent Engine dan pendaftaran di Gemini Enterprise tetap sama; hanya kode, `.env`,
`settings.json`, dan deskripsi agent yang berubah. Perkiraan waktu: 30 menit.

## Yang baru di v2.1 (dibanding v2)

| Perubahan | Dampak |
|---|---|
| **Perbaikan bug `report_prefix`** | Di v2 semua laporan dan grafik chat gagal tersimpan ("'Settings' object has no attribute 'report_prefix'"). Sudah diperbaiki + uji regresi |
| **Perbaikan crash 400 saat unggah Excel** | Lampiran mentah tidak lagi diteruskan ke Gemini; diganti rujukan/teks sebelum dikirim |
| **Perbaikan file Excel "tidak terdeteksi"** | Lampiran dari artifact ADK, alamat https://, atau tanpa nama/tipe kini tertangkap |
| **Semua format file diterima** | PDF, Word, PowerPoint, teks, HTML, gambar dicerna: diringkas + usulan langkah berikutnya |
| **Analisis silang Retail × Planogram** | Di chat (insight per KIMAP), template baru **Competitive Battlefield**, dan laporan custom gabungan |
| **Dokumen sebagai prompt/template laporan custom** | Laporan custom dapat mengikuti struktur dokumen unggahan |

Tidak ada izin IAM baru. Dependensi baru: `pypdf` (terpasang otomatis). Jika Anda sudah pernah menjalankan v2,
langkah 3 (cek pengetahuan) dan 5 (deskripsi GE) boleh dilewati — kecuali Anda ingin memakai deskripsi baru.

## Data yang dipakai panduan ini (sudah terisi)

| Item | Nilai |
|---|---|
| Project | `ptpl-land-dev` (nomor `37078813825`) |
| Resource agent | `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| Repo | `https://github.com/TooGreat430/agent-bei-csls` — laptop: folder `agent-bei-csls`, Cloud Shell: `~/agent-bei-csls` |
| File zip | `~/Downloads/ge-library-agent.zip` (di laptop) |
| Bucket | `gs://ptpl-ge-bucket` (folder kerja `ge-docs-agent/`) |
| Service account agent | `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com` |
| Data Agent planogram | `agent_5f69a707-a240-49ea-9c96-dd12493f659c` |
| Tabel planogram | `ptpl-curated-prd.DATAMART.VM_PLANOGRAM` |
| Model | `gemini-4-argon` @ `asia-southeast1` (utama), `gemini-3.5-flash` @ `global` (cepat) |
| Admin IAM | rekan Anda, mengikuti `PANDUAN_IAM.md` |

---

## Langkah 1 — Ganti isi repo dengan versi baru (laptop)

Isi repo dikosongkan dulu (kecuali `.git`) agar tidak ada file lama yang tertinggal. Pilih sesuai terminal Anda.

**Windows — Command Prompt (CMD).** Jalankan baris per baris dari folder induk repo:

```bat
cd agent-bei-csls
git pull
for /d %d in (*) do @rmdir /s /q "%d"
for %f in (*) do @del /q "%f"
if exist %TEMP%\gla rmdir /s /q %TEMP%\gla
mkdir %TEMP%\gla
tar -xf %USERPROFILE%\Downloads\ge-library-agent.zip -C %TEMP%\gla
xcopy /e /h /y /q %TEMP%\gla\ge-library-agent\* .
git add -A
git commit -m "v2.1: semua format file, Retail x Planogram, perbaikan report_prefix dan unggah Excel"
git push
```

`for /d` hanya menghapus folder biasa; folder `.git` aman karena tersembunyi. Jika perintah di atas disimpan ke file
`.bat`, ganti `%d`/`%f` menjadi `%%d`/`%%f`.

**Git Bash / Mac / Linux:**

```bash
cd agent-bei-csls && git pull
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
rm -rf /tmp/gla && unzip -q ~/Downloads/ge-library-agent.zip -d /tmp/gla
cp -r /tmp/gla/ge-library-agent/. .
git add -A && git commit -m "v2.1: semua format file, Retail x Planogram, perbaikan report_prefix dan unggah Excel" && git push
```

Hasil yang diharapkan: `git push` berhasil dan `git status` bersih.

## Langkah 2 — Ambil kode & cek model (Cloud Shell)

```bash
cd ~/agent-bei-csls && git status --short && git pull
find . -name __pycache__ -prune -exec rm -rf {} +
source .venv/bin/activate && pip install -q -r requirements.txt
LIB_MODEL_PRO=gemini-4-argon LIB_GEMINI_LOCATION_PRO=asia-southeast1 python scripts/check_models.py
```

Hasil yang diharapkan: dua baris `OK` dan `HASIL: OK — kedua model bisa dipanggil.`
Jika baris Argon `GAGAL`, kirim pesan errornya ke admin (PANDUAN_IAM langkah 6) dan **jangan lanjut ke langkah 4**.
Jika `git status --short` menampilkan file sebelum `git pull`, ada perubahan lokal di Cloud Shell; jalankan
`git reset --hard @{u}` dulu agar sama persis dengan GitHub.

## Langkah 3 — Cek pengetahuan Data Agent & daftar tabel planogram (Cloud Shell)

```bash
python scripts/check_knowledge.py
```

Hasil yang diharapkan: tiga baris `[retail]`, `[industri]`, `[planogram]` dengan `sumber=api`, lalu
`HASIL: OK — pengetahuan Data Agent terbaca lewat API.`

Salin baris `[planogram] … tabel=…` dan kirim ke admin bersama `PANDUAN_IAM.md`. Admin menjalankan langkah 2–5
di panduan itu. Tunggu konfirmasi admin, lalu tunggu 3 menit sebelum langkah 4.

Jika `[planogram]` menampilkan instruksi 0 / glossary 0 / contoh query 0, jalankan
`python scripts/check_knowledge.py --dump planogram` dan kirim hasilnya ke Jason; agent tetap bisa jalan memakai
aturan planogram bawaan, tetapi pengetahuan resmi tim data belum ikut terserap.

## Langkah 4 — Redeploy di tempat (Cloud Shell)

```bash
bash scripts/update_agent.sh
```

Script ini otomatis:
1. Mengambil kode terbaru dan memasang dependensi.
2. Merapikan `.env`: membuang pengaturan perpustakaan dokumen, mengatur `LIB_MODEL_PRO=gemini-4-argon` dan
   `LIB_GEMINI_LOCATION_PRO=asia-southeast1`, menambah Data Agent & tabel planogram.
3. Memperbarui `ge-docs-agent/config/settings.json`: kunci planogram ditambahkan, kunci perpustakaan dibuang,
   nilai yang pernah Anda ubah tidak ditimpa.
4. Menjalankan 119 uji unit.
5. Meng-update agent `5516874359156768768` (5–10 menit).

Hasil yang diharapkan: baris terakhir `Selesai. Buka chat baru di Gemini Enterprise untuk mencoba.`
**Jangan tekan `Ctrl+C`** sebelum itu, dan **jangan menjalankan script ini lagi** selama update masih berjalan
(server akan menolak dengan `not in ACTIVE state. Current state: UPDATING`). Jika terminal terputus, pantau dengan:

```bash
gcloud ai reasoning-engines describe 5516874359156768768 --region=asia-southeast2 --format="value(updateTime)" 2>/dev/null \
  || echo "Cek di Konsol: Vertex AI > Agent Engine > marketing-insight-assistant"
```

## Langkah 5 — Ganti deskripsi agent di Gemini Enterprise (Konsol)

Konsol → **Gemini Enterprise** → app GE → **Agents** → klik **Marketing Insight Assistant** → **Edit**.
Nama dan otorisasi tidak diubah. Ganti **Agent description** dengan:

```
Asisten Marketing Intelligence PT Pertamina Lubricants. Menjawab pertanyaan data survei Retail (harga, gap, margin, Product Hero), Industri/B2B (gap % vs HTD, channel, main stage), dan Planogram (outlet carry, ND, availability & visibility, whitespace per SR dan KIMAP) langsung dari BigQuery lewat Data Agent resmi tim data, termasuk analisis silang Retail × Planogram per KIMAP (harga × kondisi rak, double jeopardy, white space). Membaca file yang diunggah: data CSV/Excel dianalisis dengan aturan bisnis yang sama, dokumen (PDF, Word, PowerPoint, teks, gambar) diringkas dan bisa dipakai sebagai prompt atau template laporan. Membuat laporan — template baku (Daya Saing Harga Retail, Daya Saing Harga Industri B2B, Kinerja Planogram, Competitive Battlefield Retail × Planogram) dalam PDF/PowerPoint/HTML, atau laporan custom HTML sesuai permintaan dengan alur review dan approval.
```

Klik **Save**.

## Langkah 6 — Uji di Gemini Enterprise (chat baru untuk setiap blok)

Daftar uji lengkap (64 test case, termasuk fitur v2.1) ada di `Test_Script_UAT_Marketing_Insight_Assistant_v2.1.xlsx`.
Tabel di bawah adalah uji cepat setelah deploy.

| No | Kirim | Yang diharapkan |
|---|---|---|
| 1 | `Halo, kamu bisa apa saja?` | Menyebut tiga kemampuan: data BigQuery (retail, industri, planogram), analisis CSV/Excel, laporan template/custom. Tidak menyebut perpustakaan dokumen |
| 2 | Unggah file PDF apa pun + `tolong rangkum` | Agent meringkas isi PDF, menyebut jenis dokumennya, dan mengusulkan langkah berikutnya |
| 3 | `Berapa ND PTPL per SR di Q3 2026 dibanding Q2 2026?` | Jawaban dari Data Agent Planogram (sumber "Planogram Marketing Intelligence (VM_PLANOGRAM)"), tabel, link grafik; tidak menyebut market share |
| 4 | `Buatkan laporan` | Agent bertanya: Template atau Custom |
| 5 | `Template planogram, PDF` | Link PDF 6 halaman: ringkasan, sebaran outlet, viskositas, availability & visibility, whitespace, rekomendasi; periode Q2 2026 vs Q3 2026 |
| 6 | `Sekarang versi PowerPoint` | Link PPTX 6 slide |
| 7 | `Buat laporan custom planogram: whitespace MCO Automatic per SR Q3 vs Q2 2026 untuk Sales Regional Manager` | Agent memberi tahu proses beberapa menit, lalu link HTML berstatus DRAFT (label merah di kanan atas) |
| 8 | `Tambahkan grafik tren ND per SR` | Link DRAFT baru (revisi) |
| 9 | `approve` | Link FINAL; label kanan atas hijau "FINAL · Disetujui …" |
| 10 | Unggah CSV planogram (perintah di bawah) + `profil file ini` | Jenis "planogram", jumlah baris, periode, pengetahuan Data Agent planogram yang dipakai, baris yang dikecualikan |
| 11 | `ND PTPL per SR dan kuartal dari file ini` | Tabel dari file (preset planogram), grafik |
| 12 | `Buat laporan template planogram dari file ini dalam HTML` | Link HTML; footer sumber "File unggahan …" |
| 13 | `Buat dashboard daya saing harga retail Q3 2026 vs Q2 2026, PDF` | Dashboard retail seperti sebelumnya (regresi) |
| 14 | `Buat laporan industri Agustus 2026, HTML` | One-pager B2B seperti sebelumnya (regresi) — juga membuktikan bug `report_prefix` sudah hilang |
| 15 | Unggah file prompt `.txt` + file Excel data dalam satu pesan | Prompt diringkas; Excel tercatat sebagai file data `f…` dan diprofil; tidak ada error 400 |
| 16 | `Bagaimana daya saing PCO 10W-40 dari sisi harga dan planogram di Q3 2026?` | Insight per KIMAP: keunggulan harga, gap AV, status, ancaman kompetitor; sumber Retail × Planogram |
| 17 | `Buat laporan template Competitive Battlefield, PDF` | PDF 6 halaman: ringkasan, kategori, head-to-head, momentum & white space, Sales Region, action matrix |
| 18 | `Buat laporan gabungan retail dan industri` | Agent menjelaskan gabungan hanya bisa Retail × Planogram |

File uji untuk no. 10 (Cloud Shell, lalu unduh lewat menu ⋮ → Download):

```bash
bq query --use_legacy_sql=false --format=csv --max_rows=20000 \
"SELECT * EXCEPT(CUSTOMER_NAME, COORDINATE, PRC_DT, JOB_ID)
 FROM \`ptpl-curated-prd.DATAMART.VM_PLANOGRAM\`
 WHERE DT_PR BETWEEN '2026-04-01' AND '2026-09-30'" > uji_planogram.csv
```

Lulus jika no. 1–14 sesuai harapan.

---

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| `check_models.py`: `GAGAL gemini-4-argon` | Model belum aktif/izin di `asia-southeast1` | PANDUAN_IAM langkah 6; jangan redeploy sebelum OK |
| Agent: "Data planogram tidak bisa diambil… belum punya akses ke tabel VM_PLANOGRAM" | Izin tabel belum ada | PANDUAN_IAM langkah 2, tunggu 3 menit |
| Tanya data planogram: "Service account agent belum memiliki izin ke Data Agent atau tabel" | Data Agent planogram membaca tabel lain | Langkah 3 panduan ini → PANDUAN_IAM langkah 3 |
| Agent masih menyebut perpustakaan dokumen / BEI / CSLS | Chat lama atau deskripsi GE lama | Buka chat baru; pastikan langkah 5 sudah disimpan |
| Laporan template planogram: "Tidak ada data … untuk Q3 2026" | Data kuartal itu belum ada di tabel | Sebut kuartal lain, mis. `periode Q2 2026`, atau ubah `planogram_default_period` di `settings.json` |
| Laporan custom: catatan pemeriksa di halaman terakhir | Argon menulis angka yang tidak ada di data | Minta revisi ("hapus angka yang tidak ada di data") atau periksa angka itu sebelum approve |
| Laporan custom lama (> 3 menit) | Penarikan data + penulisan Argon | Normal untuk laporan panjang; tunggu jawaban di chat yang sama |
| `update_agent.sh`: uji gagal | Paket belum terpasang lengkap | Jalankan ulang langkah 2, lalu langkah 4 |
| "'Settings' object has no attribute 'report_prefix'" | Masih versi v2 | Pastikan langkah 1–4 v2.1 sudah dijalankan; cek `grep report_prefix library_agent/config.py` di Cloud Shell |
| Excel "tidak terdeteksi" atau error 400 saat unggah | Masih versi v2, atau bentuk lampiran baru | Setelah v2.1, kirim hasil `gcloud logging read` dengan filter `user_content parts` (lihat README) |
| Dokumen dibaca tetapi isinya kosong | PDF hasil scan atau format lama (.doc/.ppt) | PDF scan dibaca langsung model di giliran unggah; .doc/.ppt simpan ulang sebagai DOCX/PPTX/PDF |
| Error 404 model saat chat | `.env` tidak ikut ter-update | `grep LIB_MODEL .env` harus menunjukkan `gemini-4-argon` dan `asia-southeast1`; ulangi langkah 4 |
