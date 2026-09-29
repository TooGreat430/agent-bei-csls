# Panduan Setup sampai Penggunaan — Asisten Perpustakaan Dokumen (POC)

Project: `ptpl-land-dev` · App GE: lokasi `global` · Repo: `github.com/TooGreat430/agent-bei-csls`

## Keputusan konfigurasi

| Hal | Nilai | Alasan |
|---|---|---|
| Region agent | `asia-southeast2` (Jakarta) | Agent Engine tersedia di Jakarta dan sama dengan region bucket, jadi data tidak berpindah region dan staging bucket saat deploy tidak bermasalah |
| Model | `gemini-3.5-flash` lewat endpoint `global` | gemini-2.5 dipensiunkan 20 Oktober 2026. Kode memanggil model lewat endpoint `global` walaupun agent berjalan di Jakarta |
| Nama perusahaan | PT Pertamina Lubricants | Nama resmi (bagian dari PT Pertamina Patra Niaga) |
| Bucket | `ptpl-ge-bucket` (sudah ada), semua file agent di folder `agent-perpustakaan/` | Tidak mengganggu isi bucket yang sudah ada |
| Akses laporan penguji | Izin baca hanya ke `agent-perpustakaan/reports/` | Penguji tidak bisa membaca isi bucket lainnya |
| Dokumen yang sudah ada | Folder `gs://ptpl-ge-bucket/ge-docs-datastore/` diimpor lewat script (Tahap 5B), dapat diulang berkala | File disalin ke folder perpustakaan agent. File asli tidak pernah diubah atau dihapus |
| Koreksi metadata dokumen | Semua user | Keputusan B1 |
| Insight | Terlihat dan bisa dipakai semua user di workspace yang sama. Hanya pembuatnya yang bisa mengubah/menghapus | Keputusan B2 |
| Hapus dokumen lewat chat | Semua user, dengan konfirmasi | Keputusan B3. Dokumen yang dihapus tidak akan diimpor ulang dari folder |
| Sinkronisasi folder | Hanya lewat script oleh tim teknis | Keputusan B4 |
| Batas dokumen aktif per chat | 10 | Keputusan B5 |
| BEI / CSLS | BEI = Brand Equity Index, CSLS = Customer Satisfaction & Loyalty Survey | **Interpretasi**, belum dikonfirmasi klien. Hanya membantu Gemini menebak jenis dokumen, dan setiap upload tetap dikonfirmasi user. Jika kurang tepat, ubah `LIB_DOC_TYPE_HINTS` di `.env` |

---

## Tahap 0 — Perbarui kode di repo (di laptop)

Jalankan di folder repo lokal `agent-bei-csls` (Mac/Linux, atau Git Bash di Windows). Sesuaikan lokasi file zip.

```bash
cd agent-bei-csls
git pull
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
rm -rf /tmp/gla && unzip -q ~/Downloads/ge-library-agent.zip -d /tmp/gla
cp -r /tmp/gla/ge-library-agent/. .
ls
git add -A && git commit -m "Update: impor folder, hapus dokumen, insight bersama" && git push
```

**Checkpoint:** `ls` langsung menampilkan `library_agent`, `scripts`, `templates`, `requirements.txt`, dan `PANDUAN_SETUP.md` di root repo, tanpa folder `ge-library-agent`.

---

## Tahap 1 — Cloud Shell: clone ulang dan cek akses

```bash
cd ~ && rm -rf agent-bei-csls
git clone https://github.com/TooGreat430/agent-bei-csls.git
cd agent-bei-csls && ls
```

Cek role akun Anda dan API yang aktif:

```bash
gcloud config set project ptpl-land-dev
gcloud projects get-iam-policy ptpl-land-dev --flatten="bindings[].members" \
  --filter="bindings.members:user:$(gcloud config get-value account 2>/dev/null)" \
  --format="value(bindings.role)"
gcloud services list --enabled \
  --filter="config.name:(aiplatform.googleapis.com discoveryengine.googleapis.com storage.googleapis.com)" \
  --format="value(config.name)"
```

| Hasil | Tindakan |
|---|---|
| Role berisi `roles/owner` | ✅ Semua langkah bisa dijalankan sendiri |
| Role berisi `roles/editor` tanpa owner | ⚠️ Semua bisa **kecuali** pemberian izin (Tahap 4.2 dan 7.3). Minta admin memberi `roles/resourcemanager.projectIamAdmin` dan `roles/storage.admin` sebelum lanjut |
| Tidak ada role di atas | ⛔ Minta admin memberi `roles/owner` di `ptpl-land-dev` untuk POC |
| Ketiga API muncul | ✅ Lanjut |
| `aiplatform.googleapis.com` tidak muncul | ⛔ Minta izin klien untuk mengaktifkannya sebelum lanjut |

---

## Tahap 2 — Python dan `.env`

```bash
cd ~/agent-bei-csls
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Buat `.env` (salin seluruh blok, tidak perlu mengedit):

```bash
cat > .env <<'EOF'
LIB_PROJECT_ID=ptpl-land-dev
GOOGLE_CLOUD_PROJECT=ptpl-land-dev
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_LOCATION=global
LIB_SEARCH_LOCATION=global
LIB_AGENT_ENGINE_REGION=asia-southeast2
LIB_GEMINI_LOCATION=global
LIB_MODEL_FAST=gemini-3.5-flash
LIB_MODEL_PRO=gemini-3.5-flash
LIB_BUCKET=ptpl-ge-bucket
LIB_REPORT_BUCKET=ptpl-ge-bucket
LIB_LIBRARY_PREFIX=agent-perpustakaan/library
LIB_STAGING_PREFIX=agent-perpustakaan/staging
LIB_TEMPLATE_PREFIX=agent-perpustakaan/templates
LIB_REPORT_PREFIX=agent-perpustakaan/reports
LIB_CATALOG_PATH=agent-perpustakaan/catalog/index.json
LIB_INSIGHT_PREFIX=agent-perpustakaan/insights
LIB_TEMPLATE_SOURCE=gcs
LIB_DATASTORE_ID=perpustakaan-dokumen
LIB_COMPANY_NAME="PT Pertamina Lubricants"
LIB_DOC_TYPES=BEI,CSLS
LIB_DOC_TYPE_HINTS="BEI: Brand Equity Index - laporan studi ekuitas merek pelumas (brand awareness, brand image, preferensi, brand funnel, perbandingan dengan merek pesaing); CSLS: Customer Satisfaction and Loyalty Survey - laporan survei kepuasan dan loyalitas pelanggan (indeks kepuasan, NPS, loyalitas, evaluasi produk dan layanan)"
EOF
```

Muat konfigurasi dan jalankan uji unit:

```bash
set -a && source .env && set +a
python -m unittest discover tests
```

**Checkpoint:** muncul `OK`.

> **Setiap kali membuka Cloud Shell baru**, jalankan ini dulu:
> ```bash
> cd ~/agent-bei-csls && source .venv/bin/activate && set -a && source .env && set +a && gcloud config set project ptpl-land-dev
> ```

---

## Tahap 3 — Cek bucket

```bash
gcloud storage buckets describe gs://ptpl-ge-bucket --format="value(location,uniform_bucket_level_access)"
```

| Hasil | Tindakan |
|---|---|
| `ASIA-SOUTHEAST2  True` | ✅ Lanjut ke Tahap 4, tidak ada perubahan |
| `ASIA-SOUTHEAST2  False` | Izin per folder tidak bisa dipakai. Buat bucket khusus laporan dengan perintah di bawah, lalu lanjut ke Tahap 4 |

```bash
# Hanya jika hasilnya False:
gcloud storage buckets create gs://ptpl-ge-bucket-laporan --location=asia-southeast2 --uniform-bucket-level-access
sed -i 's/^LIB_REPORT_BUCKET=.*/LIB_REPORT_BUCKET=ptpl-ge-bucket-laporan/' .env
set -a && source .env && set +a
```

---

## Tahap 4 — POC upload lampiran

### 4.1 Deploy agent probe (sekitar 5–10 menit)

```bash
python scripts/deploy_agent_engine.py --probe
```

Salin nilai `Resource name: projects/.../reasoningEngines/<ID>` dari output.

### 4.2 Beri izin ke service account

```bash
PROJECT_NUMBER=$(gcloud projects describe ptpl-land-dev --format="value(projectNumber)")
AGENT_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
VERTEX_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com"
DE_SA="service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com"

for ROLE in roles/discoveryengine.editor roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding ptpl-land-dev \
    --member="serviceAccount:$AGENT_SA" --role=$ROLE --condition=None
done
for B in $(echo "$LIB_BUCKET $LIB_REPORT_BUCKET" | tr ' ' '\n' | sort -u); do
  gcloud storage buckets add-iam-policy-binding gs://$B \
    --member="serviceAccount:$AGENT_SA" --role=roles/storage.objectAdmin
done
for SA in $VERTEX_SA $DE_SA; do
  gcloud storage buckets add-iam-policy-binding gs://$LIB_BUCKET \
    --member="serviceAccount:$SA" --role=roles/storage.objectViewer
done
```

### 4.3 Daftarkan probe ke GE

Konsol **Gemini Enterprise** → pilih app GE (lokasi `global`) → **Agents** → tambahkan agent custom berbasis **Agent Engine** → tempel resource name dari 4.1.

### 4.4 Uji di GE

Buka agent `upload_probe`, lalu kirim: (1) teks saja, (2) teks + PDF kecil, (3) teks + DOCX.

| Balasan probe | Tindakan |
|---|---|
| Ada `inline_data` dengan `bytes` > 0, atau `file_data` dengan `gs://` | ✅ Lanjut ke Tahap 5 |
| `file_data` dengan URI lain | ⚠️ Kirim balasan probe untuk penyesuaian kode |
| Hanya `text` | ⛔ Lampiran tidak diteruskan GE. Kirim balasan probe sebelum lanjut |

Setelah hasilnya tercatat, hapus agent probe dari GE.

---

## Tahap 5 — Perpustakaan dan template

```bash
python scripts/setup_datastore.py
python scripts/upload_templates.py
```

**Checkpoint:**
- Konsol GE → **Data Stores**: muncul "Perpustakaan Dokumen" (lokasi `global`).
- `gcloud storage ls gs://ptpl-ge-bucket/agent-perpustakaan/templates/laporan_studi/` menampilkan 4 file.

---

## Tahap 5B — Impor dokumen yang sudah ada di folder

Dokumen di `gs://ptpl-ge-bucket/ge-docs-datastore/` belum dikenal agent sampai diimpor. Script ini dijalankan dari Cloud Shell dan **tidak memerlukan redeploy agent**.

### 5B.1 Pindai folder

```bash
python scripts/import_folder.py scan gs://ptpl-ge-bucket/ge-docs-datastore/
```

Script membaca setiap file, Gemini mengekstrak judul/jenis/versi/tanggal, lalu hasilnya ditulis ke `import_review.csv`. Di terminal akan muncul ringkasan jumlah file yang akan diimpor dan dilewati beserta alasannya (format tidak didukung, file kembar, dan sebagainya). Durasinya sekitar beberapa detik per file.

### 5B.2 Periksa CSV

Pilih salah satu cara:

- **Di Cloud Shell:** `cloudshell edit import_review.csv`, perbaiki, lalu simpan (`Ctrl+S`).
- **Di Google Sheets:** `cloudshell download import_review.csv` → buka Google Sheets → **File → Import** → upload file → perbaiki → **File → Download → CSV** → di Cloud Shell klik **⋮ → Upload** → lalu jalankan `mv ~/import_review*.csv ~/agent-bei-csls/import_review.csv`.

Yang perlu diperiksa:

| Kolom | Isi |
|---|---|
| `action` | `IMPORT` untuk diimpor, ubah ke `SKIP` untuk dilewati |
| `title`, `doc_type`, `version`, `doc_date` | Hasil ekstraksi. Perbaiki jika salah. `doc_type` harus `BEI` atau `CSLS`, tanggal `YYYY-MM-DD` |
| `note` | Baris dengan **MOHON DICEK** wajib diperiksa. Catatan "versi baru" berarti judulnya sama dengan dokumen lain |

Jangan mengubah kolom `source_uri`, `sha256`, dan `mime_type`.

### 5B.3 Impor

```bash
python scripts/import_folder.py run --wait
```

**Checkpoint:** muncul daftar dokumen yang berhasil didaftarkan, lalu `Indexing: siap=<jumlah> gagal=0`. Baris yang bermasalah ditampilkan dengan alasannya dan tidak diimpor. Perbaiki di CSV, lalu jalankan `run` lagi (dokumen yang sudah masuk otomatis dilewati).

> **Catatan:** jika folder ini juga dipakai oleh data store lain di app GE, dokumen akan terindeks dua kali (sekali oleh data store lama, sekali oleh perpustakaan agent). Hal ini tidak mengganggu fungsi agent, tetapi menambah biaya penyimpanan indeks.

---

## Tahap 6 — Uji di Cloud Shell

```bash
adk web --port 8080
```

Klik **Web Preview → Preview on port 8080**, pilih `library_agent`, lalu jalankan skenario Tahap 8 (termasuk upload PDF lewat tombol lampiran). Hentikan dengan `Ctrl+C`.

---

## Tahap 7 — Deploy agent utama ke GE

### 7.1 Deploy

```bash
python scripts/deploy_agent_engine.py
```

> Jika agent utama **sudah pernah** di-deploy dengan kode versi sebelumnya, jangan buat baru. Perbarui saja dengan `python scripts/deploy_agent_engine.py --update <RESOURCE_NAME_LAMA>`, dan lewati langkah 7.2 karena pendaftaran di GE tetap berlaku.

Simpan resource name ke `.env` (ganti `<RESOURCE_NAME>`):

```bash
echo "LIB_AGENT_RESOURCE=<RESOURCE_NAME>" >> .env && set -a && source .env && set +a
```

### 7.2 Daftarkan ke app GE

Sama seperti Tahap 4.3. Nama tampilan: **Asisten Perpustakaan Dokumen**. Tambahkan `mirptpl@gmail.com` sebagai user yang boleh memakai agent.

### 7.3 Akses baca laporan untuk penguji

Jika Tahap 3 hasilnya `True`:

```bash
gcloud storage buckets add-iam-policy-binding gs://ptpl-ge-bucket \
  --member="user:mirptpl@gmail.com" --role=roles/storage.objectViewer \
  --condition='expression=resource.name.startsWith("projects/_/buckets/ptpl-ge-bucket/objects/agent-perpustakaan/reports/"),title=hanya-laporan-perpustakaan'
```

Jika Tahap 3 hasilnya `False`:

```bash
gcloud storage buckets add-iam-policy-binding gs://ptpl-ge-bucket-laporan \
  --member="user:mirptpl@gmail.com" --role=roles/storage.objectViewer
```

> **Catatan akun Gmail:** jika perintah di atas atau pendaftaran user di GE ditolak karena *domain restricted sharing* atau user di luar organisasi, project hanya mengizinkan akun perusahaan. Ganti `mirptpl@gmail.com` dengan akun korporat penguji, lalu jalankan ulang.

### 7.4 Uji ulang

Jalankan skenario Tahap 8 langsung dari GE, login sebagai penguji.

---

## Tahap 8 — Skenario penggunaan

1. **Upload:** lampirkan PDF → "Masukkan ke perpustakaan." Agent menampilkan judul, jenis, versi, tanggal hasil ekstraksi. Jawab "benar" atau sebutkan bagian yang salah.
2. **Katalog:** "Dokumen apa saja yang ada di perpustakaan?"
3. **Pilih dokumen:** "Pakai dokumen <judul> saja."
4. **Tanya:** pertanyaan yang jawabannya ada di dokumen (harus ada sitasi) dan yang tidak ada (harus "tidak ditemukan").
5. **Insight:** "Gunakan workspace BEI Study 2026." → "Simpan temuan ini sebagai insight."
6. **Laporan:** "Buatkan laporan dengan template laporan studi dari semua insight. Judulnya Laporan Uji POC." → buka link.
7. **Koreksi:** "Judul dokumen <judul> salah, harusnya <judul baru>." (semua user boleh)
8. **Insight bersama:** login dengan akun lain, buka workspace yang sama ("Gunakan workspace BEI Study 2026"), lalu "Tampilkan insight." Insight dari user pertama harus terlihat, tetapi tidak bisa diubah oleh user kedua.
9. **Hapus dokumen:** "Hapus dokumen <judul> dari perpustakaan." Agent meminta konfirmasi dulu, lalu menghapus. Jika dokumen itu punya versi sebelumnya, versi sebelumnya otomatis menjadi terbaru.

---

## Tahap 9 — Update di kemudian hari

| Kebutuhan | Perintah (di Cloud Shell, setelah memuat `.env`) |
|---|---|
| Ubah template laporan | `python scripts/upload_templates.py` |
| Ubah kode, prompt, atau `.env` | `git pull && python -m unittest discover tests && python scripts/deploy_agent_engine.py --update $LIB_AGENT_RESOURCE` |
| Tambah penguji | Tambahkan di GE (7.2), lalu perintah 7.3 dengan email baru |
| Ada file baru di folder `ge-docs-datastore` | `python scripts/import_folder.py scan gs://ptpl-ge-bucket/ge-docs-datastore/` → cek CSV → `python scripts/import_folder.py run --wait`. Hanya file baru atau yang isinya berubah yang diproses |
| Impor cepat tanpa cek CSV | `python scripts/import_folder.py auto gs://ptpl-ge-bucket/ge-docs-datastore/ --wait` |
| Ada file yang dihapus dari folder dan ingin ikut dihapus dari perpustakaan | `python scripts/import_folder.py prune gs://ptpl-ge-bucket/ge-docs-datastore/` |

---

## Troubleshooting

| Gejala | Solusi |
|---|---|
| Error 404 model tidak ditemukan | Pastikan `.env` berisi `LIB_GEMINI_LOCATION=global`, lalu deploy `--update` |
| Metadata tidak terbaca, agent meminta semua field diisi | Ulangi baris `VERTEX_SA` di Tahap 4.2 |
| Dokumen tersimpan tetapi tidak pernah ditemukan | Ulangi baris `DE_SA` di Tahap 4.2, lalu minta agent "cek status indexing dokumen itu" |
| Error filter `doc_key` | `python scripts/setup_datastore.py --schema-only`, tunggu beberapa menit |
| Link laporan tidak bisa dibuka | Ulangi Tahap 7.3, pastikan login dengan akun yang diberi akses |
| Hanya link HTML, tanpa PDF | Normal untuk POC, HTML tetap valid |
| `scan` melewati file dengan catatan "Format tidak didukung" | Hanya PDF, DOCX, PPTX, HTML, TXT yang didukung. Simpan ulang file (mis. dari .doc atau .xlsx) ke PDF |
| `scan` melewati file karena ukuran | Tambahkan `--max-mb 200` pada perintah `scan` |
| `run --wait` menampilkan `gagal` | Cek log di Konsol → Logging. Biasanya file rusak atau terproteksi password |
| Dokumen yang dihapus lewat chat tidak muncul lagi setelah impor ulang | Memang disengaja. Untuk memasukkannya kembali, upload file tersebut lewat chat |
