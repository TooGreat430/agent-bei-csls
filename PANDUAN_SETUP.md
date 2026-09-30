# Panduan Setup sampai Penggunaan — Document Insight Agent (POC)

Project: `ptpl-land-dev` · App GE: lokasi `global` · Repo: `github.com/TooGreat430/agent-bei-csls`

## Keputusan konfigurasi

| Hal | Nilai | Alasan |
|---|---|---|
| Region agent | `asia-southeast2` (Jakarta) | Agent Engine tersedia di Jakarta dan sama dengan region bucket, jadi data tidak berpindah region dan staging bucket saat deploy tidak bermasalah |
| Model | `gemini-3.5-flash` lewat endpoint `global` | gemini-2.5 dipensiunkan 20 Oktober 2026. Kode memanggil model lewat endpoint `global` walaupun agent berjalan di Jakarta |
| Nama perusahaan | PT Pertamina Lubricants | Nama resmi (bagian dari PT Pertamina Patra Niaga) |
| Bucket | `ptpl-ge-bucket` (sudah ada), semua file agent di folder `ge-docs-agent/` | Tidak mengganggu isi bucket yang sudah ada |
| Akses laporan penguji | Izin baca hanya ke `ge-docs-agent/reports/` | Penguji tidak bisa membaca isi bucket lainnya |
| Folder dokumen | **Semua** dokumen hanya di `gs://ptpl-ge-bucket/ge-docs-datastore/`, baik yang ditaruh manual lewat bucket maupun di-upload lewat chat. Tidak ada salinan di folder lain | Folder adalah sumber kebenaran, katalog hanya cermin isinya |
| Koreksi metadata dokumen | Semua user | Keputusan B1 |
| Insight | Terlihat dan bisa dipakai semua user di workspace yang sama. Hanya pembuatnya yang bisa mengubah/menghapus | Keputusan B2 |
| Hapus dokumen lewat chat | Semua user, dengan konfirmasi. **File ikut dihapus dari `ge-docs-datastore`** | Keputusan B3 + F1 |
| Sinkronisasi folder ↔ katalog | **Otomatis** setiap kali user membuka katalog atau memilih dokumen: file baru ditambahkan, file yang diganti diindeks ulang, file yang dihapus dari folder hilang dari katalog | Keputusan F2 |
| Batas dokumen aktif per chat | 10 | Keputusan B5 |
| BEI / CSLS | BEI = Brand Equity Index, CSLS = Customer Satisfaction & Loyalty Survey | **Interpretasi**, belum dikonfirmasi klien. Hanya membantu Gemini menebak jenis dokumen, dan setiap upload tetap dikonfirmasi user. Jika kurang tepat, ubah `LIB_DOC_TYPE_HINTS` di `.env` |

### Isi bucket `ptpl-ge-bucket`

| Folder | Isi | Diubah oleh |
|---|---|---|
| `ge-docs-datastore/` | **Semua dokumen perpustakaan** (PDF, DOCX, PPTX, HTML, TXT) | User (lewat Konsol atau upload di chat) |
| `ge-docs-agent/catalog/` | `index.json`: daftar dokumen + metadata | Agent (otomatis) |
| `ge-docs-agent/insights/` | JSON insight per workspace | Agent |
| `ge-docs-agent/config/` | `settings.json`: pengaturan agent | Tim teknis (lewat Konsol) |
| `ge-docs-agent/templates/` | Template laporan (bukan dokumen perpustakaan) | Tim teknis (lewat Konsol) |
| `ge-docs-agent/reports/` | Hasil laporan yang dibuat agent | Agent |
| `ge-docs-agent/staging/` | Lampiran chat yang **menunggu konfirmasi**. Setelah dikonfirmasi dipindah ke `ge-docs-datastore/`. Yang tidak dikonfirmasi dihapus otomatis setelah 24 jam | Agent |

Template dan laporan sengaja tidak ditaruh di `ge-docs-datastore/`, karena semua isi folder itu diperlakukan sebagai dokumen perpustakaan. Jika ditaruh di sana, agent akan membaca laporannya sendiri sebagai sumber.

---

## ⚡ Update cepat (agent sudah terdaftar di GE)

Jika agent sudah di-deploy dan terdaftar di GE, **tidak perlu mengulang tahap apa pun**. Cukup dua langkah:

**1. Laptop:** perbarui repo dengan zip terbaru (perintah di Tahap 0).

**2. Cloud Shell:** satu perintah:

```bash
cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh
```

Script ini otomatis: mengambil kode terbaru, memasang dependensi, merapikan `.env`, **memindahkan isi folder lama `agent-perpustakaan/` ke `ge-docs-agent/`** (template, insight, pengaturan, laporan, termasuk izin baca laporan penguji), mengunggah template dan `settings.json` jika belum ada, menjalankan uji unit, mencari resource agent jika belum tersimpan, lalu meng-update agent. Pendaftaran di GE tetap berlaku. Katalog dibangun ulang otomatis dari isi `ge-docs-datastore/`.

**Checkpoint:** buka chat baru di GE dan tulis `Dokumen apa saja yang ada di perpustakaan?` File di `ge-docs-datastore` harus muncul di katalog.

---

## ⚙️ Mengubah pengaturan tanpa Cloud Shell

Pengaturan berikut disimpan di **`gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json`** dan bisa diubah lewat **Konsol web**, tanpa Cloud Shell dan tanpa redeploy. Perubahan berlaku paling lambat **5 menit** kemudian.

| Pengaturan | Isi sekarang | Contoh perubahan |
|---|---|---|
| `company_name` | PT Pertamina Lubricants | Nama di header laporan |
| `allowed_doc_types` | `["BEI", "CSLS"]` | Menambah jenis dokumen baru, misalnya `["BEI", "CSLS", "AUDIT"]` |
| `doc_type_hints` | Penjelasan BEI dan CSLS | Memperbaiki penjelasan agar Gemini lebih tepat mengenali jenis dokumen |
| `max_active_docs` | 10 | Batas dokumen aktif per chat |
| `source_folder` | `gs://ptpl-ge-bucket/ge-docs-datastore/` | Folder dokumen perpustakaan |
| `folder_batch_size` | 20 | Jumlah maksimal file baru/berubah yang diproses per sekali sinkronisasi |
| `max_file_mb` | 100 | Batas ukuran file dokumen |

**Cara mengubah:** Konsol → **Cloud Storage → `ptpl-ge-bucket` → `ge-docs-agent/config/`** → klik `settings.json` → **Download** → edit dengan Notepad → **Upload files** ke folder yang sama (timpa file lama). Jika isi file rusak atau salah format, agent otomatis memakai nilai bawaan, jadi agent tidak akan error.

Yang **tetap** butuh update kode (Cloud Shell): perubahan perilaku atau instruksi agent, dan fitur baru.

---

## 📄 Template laporan dan format output

Laporan bisa dikeluarkan dalam **PDF, PowerPoint (.pptx), atau HTML**. Agent hanya membuat format yang diminta user, misalnya *"Buatkan laporannya dalam PDF"*. Jika user tidak menyebut format, agent menanyakannya sekali.

**Template yang tersedia:**

| Template | Gaya | Format |
|---|---|---|
| `studi_bei_nps` | Deck riset pasar 16:9 (meniru gaya laporan Studi BEI & NPS): sampul, ringkasan, latar belakang, tujuan, temuan per topik dengan tabel data, rekomendasi | PDF, PPTX, HTML |
| `laporan_studi` | Dokumen laporan sederhana | PDF, PPTX, HTML |

Keduanya adalah **template uji**, dan nanti diganti dengan template resmi klien.

**Lokasi:** `gs://ptpl-ge-bucket/ge-docs-agent/templates/<nama_template>/`

| File | Wajib? | Fungsi |
|---|---|---|
| `manifest.json` | Ya | Judul, format yang didukung, warna tema, susunan halaman |
| `schema.json` | Ya | Bagian-bagian laporan yang diisi Gemini |
| `style_examples.md` | Tidak | Contoh gaya bahasa dari laporan lama |
| `template.pptx` | Tidak | File PowerPoint resmi klien. Master/tema slide-nya (latar, logo, font) dipakai untuk output PPTX |
| `template.html` | Tidak | Desain HTML khusus. Jika tidak ada, HTML dibuat dari susunan halaman di `manifest.json` |

**Menambah atau mengganti template:** upload folder template lewat Konsol (**Upload folder**) ke `ge-docs-agent/templates/`. Template langsung bisa dipakai, tanpa redeploy dan tanpa Cloud Shell. File PDF atau PPT laporan lama **tidak bisa langsung dipakai** sebagai template, karena perlu diubah dulu menjadi `manifest.json` dan `schema.json`.

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
LIB_INTERNAL_FOLDER=ge-docs-agent
LIB_TEMPLATE_SOURCE=gcs
LIB_DATASTORE_ID=perpustakaan-dokumen
LIB_COMPANY_NAME="PT Pertamina Lubricants"
LIB_DOC_TYPES=BEI,CSLS
LIB_SOURCE_FOLDER=gs://ptpl-ge-bucket/ge-docs-datastore/
LIB_FOLDER_BATCH_SIZE=20
LIB_MAX_FILE_MB=100
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
- `gcloud storage ls gs://ptpl-ge-bucket/ge-docs-agent/templates/laporan_studi/` menampilkan 4 file.

---

## Tahap 5B — Menambah dokumen

Ada dua cara, dan keduanya menyimpan file di `ge-docs-datastore/`:

**Cara 1: taruh manual di bucket.** Konsol → **Cloud Storage → `ptpl-ge-bucket` → `ge-docs-datastore` → Upload files**. Setelah itu, **tidak perlu langkah apa pun**. Saat user berikutnya membuka katalog atau memilih dokumen di chat, agent otomatis menyamakan katalog dengan isi folder:

> **User:** `Dokumen apa saja yang ada di perpustakaan?`
>
> **Agent:** Katalog diperbarui dari folder: 2 dokumen baru. Satu dokumen perlu dicek: *Ringkasan Survei* — jenisnya belum terbaca, BEI atau CSLS?
> *(lalu menampilkan katalog)*

**Cara 2: upload di chat.** Lampirkan file → `Masukkan ke perpustakaan.` → agent menampilkan metadata → `Benar.` → file disimpan ke `ge-docs-datastore/`.

**Aturan sinkronisasi:**

| Perubahan di folder | Yang terjadi di katalog |
|---|---|
| File baru | Metadata diekstrak Gemini lalu ditambahkan. Field yang tidak yakin ditandai "perlu dicek" dan ditanyakan ke user |
| File diganti (nama sama, isi baru) | Diindeks ulang, metadata diekstrak ulang. Koreksi yang pernah dibuat user tetap dipertahankan |
| File dihapus | Dokumen hilang dari katalog dan pencarian |
| Nama file berbeda tetapi judul dokumen sama | Dicatat sebagai versi baru, versi lama tetap tersedia |
| Isi file sama persis dengan file lain | Dilewati dan dilaporkan |
| Format tidak didukung / terlalu besar | Dilewati dan dilaporkan |

Catatan:
- Dokumen yang baru masuk butuh beberapa menit untuk diindeks sebelum bisa dipakai tanya-jawab.
- Satu kali sinkronisasi memproses maksimal 20 file baru/berubah. Sisanya diproses pada pemeriksaan berikutnya, dan agent akan memberi tahu.
- Sebaiknya nama file **tanpa spasi**, misalnya `studi_bei_2026.pdf`.
- Jika folder ini juga dipakai oleh data store lain di app GE, dokumen akan terindeks dua kali. Fungsi agent tidak terganggu, tetapi biaya penyimpanan indeks bertambah.

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

Sama seperti Tahap 4.3. Nama tampilan: **Document Insight Agent**. Tambahkan `mirptpl@gmail.com` sebagai user yang boleh memakai agent.

### 7.3 Akses baca laporan untuk penguji

Jika Tahap 3 hasilnya `True`:

```bash
gcloud storage buckets add-iam-policy-binding gs://ptpl-ge-bucket \
  --member="user:mirptpl@gmail.com" --role=roles/storage.objectViewer \
  --condition='expression=resource.name.startsWith("projects/_/buckets/ptpl-ge-bucket/objects/ge-docs-agent/reports/"),title=hanya-laporan-perpustakaan'
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
6. **Laporan:** "Buatkan laporan dengan template Studi BEI & NPS dari semua insight dalam format PDF. Judulnya Laporan Uji POC." → buka link. Ulangi dengan "dalam format PowerPoint" dan "dalam format HTML". Setiap permintaan hanya menghasilkan satu file sesuai format yang diminta. Tanpa menyebut format, agent harus menanyakannya.
7. **Koreksi:** "Judul dokumen <judul> salah, harusnya <judul baru>." (semua user boleh)
8. **Sinkronisasi folder:** (a) taruh 1 PDF di `ge-docs-datastore` lewat Konsol → `Dokumen apa saja yang ada di perpustakaan?` → dokumen baru langsung muncul. (b) Hapus file itu dari folder lewat Konsol → tanyakan katalog lagi → dokumen hilang dari katalog. (c) Upload file lewat chat → cek di Konsol bahwa file muncul di `ge-docs-datastore/`.
9. **Insight bersama:** login dengan akun lain, buka workspace yang sama ("Gunakan workspace BEI Study 2026"), lalu "Tampilkan insight." Insight dari user pertama harus terlihat, tetapi tidak bisa diubah oleh user kedua.
10. **Hapus dokumen:** "Hapus dokumen <judul> dari perpustakaan." Agent meminta konfirmasi dulu, lalu menghapus. Cek di Konsol bahwa file juga hilang dari `ge-docs-datastore/`. Jika dokumen itu punya versi sebelumnya, versi sebelumnya otomatis menjadi terbaru.

---

## Tahap 9 — Update di kemudian hari

| Kebutuhan | Perintah (di Cloud Shell, setelah memuat `.env`) |
|---|---|
| Ubah template laporan | `python scripts/upload_templates.py` |
| Ubah pengaturan (nama perusahaan, jenis dokumen, batas-batas) | Edit `settings.json` lewat Konsol, tanpa Cloud Shell |
| Ubah kode atau instruksi agent | Push ke repo, lalu di Cloud Shell: `cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh` |
| Tambah penguji | Tambahkan di GE (7.2), lalu perintah 7.3 dengan email baru |
| Menambah, mengganti, atau menghapus dokumen | Langsung di folder `ge-docs-datastore` lewat Konsol. Katalog menyesuaikan otomatis saat user membuka katalog atau memilih dokumen |

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
| Agent melaporkan file dilewati karena "Format tidak didukung" | Hanya PDF, DOCX, PPTX, HTML, TXT yang didukung. Simpan ulang file (mis. dari .doc atau .xlsx) ke PDF |
| Agent melaporkan file dilewati karena ukuran | Ubah `max_file_mb` di `settings.json` lewat Konsol (lihat bagian Mengubah pengaturan) |
| Dokumen hasil impor tidak pernah siap dipakai | Minta agent "cek status indexing dokumen <judul>". Jika `failed`, biasanya file rusak atau terproteksi password |
| Agent menjawab "Folder dokumen belum dikonfigurasi" | Isi `source_folder` di `settings.json` lewat Konsol, tunggu 5 menit |
| File sudah ditaruh di folder tetapi belum muncul di katalog | Katalog diperbarui saat user membuka katalog atau memilih dokumen. Tanyakan `Dokumen apa saja yang ada di perpustakaan?`. Jika file dilewati, agent menyebutkan alasannya |
