# Panduan Setup — Marketing Insight Assistant (POC)

| Item | Nilai |
|---|---|
| Project | `ptpl-land-dev` (nomor project `37078813825`) |
| App Gemini Enterprise | lokasi `global` |
| Region agent (Agent Runtime) | `asia-southeast2` (Jakarta) |
| Bucket | `gs://ptpl-ge-bucket` (Jakarta) |
| Repo | `https://github.com/TooGreat430/agent-bei-csls` |
| Agent di Agent Runtime | `marketing-insight-assistant` (nama internal; sebelumnya `document-insight-agent`) — `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| Nama di Gemini Enterprise | Marketing Insight Assistant |

---

## 1. Gambaran singkat

```
ptpl-ge-bucket/
├── ge-docs-datastore/   ← SEMUA dokumen perpustakaan (PDF, DOCX, PPTX, HTML, TXT)
├── ge-docs-agent/       ← file kerja agent
│   ├── catalog/         index.json — daftar dokumen (dibuat & diperbarui otomatis)
│   ├── config/          settings.json — pengaturan yang bisa diubah tanpa deploy
│   ├── templates/       template laporan
│   ├── reports/         laporan yang dihasilkan
│   └── staging/         lampiran chat yang menunggu konfirmasi (dibersihkan otomatis)
└── agent_engine/        file deploy Agent Runtime (dibuat otomatis, jangan diubah)
```

- **`ge-docs-datastore/` adalah sumber kebenaran.** Katalog otomatis disamakan dengan isi folder ini setiap kali user membuka katalog atau memilih dokumen.
- Dokumen diindeks ke **data store** `perpustakaan-dokumen` (lokasi `global`) agar bisa ditanya-jawab dengan sitasi.
- Laporan dibuat dari template di `ge-docs-agent/templates/` dalam format **PDF, PowerPoint, atau HTML**, sesuai permintaan user.
- Pertanyaan **data pasar** (harga, HET/HTO, gap, margin, TOV, Product Hero, zona) dijawab lewat Data Agent BigQuery **Marketing Intelligence**. Aturan bisnisnya tetap dikelola di Data Agent tersebut, tidak diduplikasi.
- Setiap pesan user selalu diarahkan ulang oleh agent induk, jadi pertanyaan data bisa diajukan kapan saja (awal, tengah, akhir), dan kemampuan dokumen, data, dan laporan bisa dipakai sendiri-sendiri.

---

## 2. Izin yang dibutuhkan

### 2.1 Akun yang menjalankan setup (mis. `jason.kusuma@mii.co.id`)
Cukup **Editor** di project `ptpl-land-dev`. Akun ini bisa: deploy agent, membuat data store, mengatur izin **bucket**.

### 2.2 Service account agent — izin bucket (bisa dijalankan sendiri)

```bash
PN=37078813825
for SA in "service-${PN}@gcp-sa-aiplatform-re.iam.gserviceaccount.com:roles/storage.objectAdmin" \
          "service-${PN}@gcp-sa-aiplatform.iam.gserviceaccount.com:roles/storage.objectViewer" \
          "service-${PN}@gcp-sa-discoveryengine.iam.gserviceaccount.com:roles/storage.objectViewer"; do
  gcloud storage buckets add-iam-policy-binding gs://ptpl-ge-bucket \
    --member="serviceAccount:${SA%%:*}" --role="${SA##*:}" >/dev/null && echo "OK ${SA%%:*}"
done
```

| Service account | Role di bucket | Fungsi |
|---|---|---|
| `...@gcp-sa-aiplatform-re...` (agent) | Storage Object Admin | Baca/tulis dokumen, katalog, insight, laporan |
| `...@gcp-sa-aiplatform...` (Vertex AI) | Storage Object Viewer | Gemini membaca PDF untuk ekstraksi metadata |
| `...@gcp-sa-discoveryengine...` (data store) | Storage Object Viewer | Data store membaca file untuk diindeks |

### 2.3 Service account agent — izin project (harus admin project)

| Role | Wajib? | Fungsi |
|---|---|---|
| `roles/discoveryengine.editor` | **Wajib** | Mengindeks dokumen dan mencarinya saat tanya-jawab |
| `roles/aiplatform.user` | Opsional | Pengaman akses Gemini (biasanya sudah tercakup izin bawaan Agent Runtime) |

Perintah untuk admin:
```bash
SA="serviceAccount:service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
for ROLE in roles/discoveryengine.editor roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding ptpl-land-dev --member="$SA" --role=$ROLE --condition=None
done
```
**Status:** `discoveryengine.editor` sudah diberikan.

### 2.4 Izin untuk data BigQuery lewat service account — **cara yang dipakai**

Marketing Insight Assistant memanggil Data Agent `agent_4df3074b-9d7e-4f9f-993b-b3969b8a2095` (project `ptpl-land-dev`). Query BigQuery dijalankan dengan identitas service account agent, jadi service account ini butuh izin ke Data Agent **dan** ke dua tabel sumbernya yang berada di project lain.

| Role | Di mana | Fungsi |
|---|---|---|
| `roles/geminidataanalytics.dataAgentUser` | project `ptpl-land-dev` | Chat dengan Data Agent |
| `roles/geminidataanalytics.dataAgentStatelessUser` | project `ptpl-land-dev` | Memanggil Chat API (mode stateless) |
| `roles/cloudaicompanion.user` | project `ptpl-land-dev` | Gemini for Google Cloud (dibutuhkan untuk chat dengan Data Agent) |
| `roles/bigquery.jobUser` | project `ptpl-land-dev` | Menjalankan query |
| `roles/bigquery.dataViewer` | tabel `ptpl-curated-prd.DATAMART.SURVEY_PRODUCTS` | Baca data survei retail |
| `roles/bigquery.dataViewer` | tabel `pertamina-lubricants-project.STAGING.MIR_MST_OUTLET_GADM` | Baca data lokasi outlet |

Perintah untuk admin (izin tabel diberikan **per tabel**, bukan seluruh project):
```bash
SA="serviceAccount:service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
for ROLE in roles/geminidataanalytics.dataAgentUser roles/geminidataanalytics.dataAgentStatelessUser \
            roles/cloudaicompanion.user roles/bigquery.jobUser; do
  gcloud projects add-iam-policy-binding ptpl-land-dev --member="$SA" --role=$ROLE --condition=None
done
bq add-iam-policy-binding --member="$SA" --role=roles/bigquery.dataViewer ptpl-curated-prd:DATAMART.SURVEY_PRODUCTS
bq add-iam-policy-binding --member="$SA" --role=roles/bigquery.dataViewer pertamina-lubricants-project:STAGING.MIR_MST_OUTLET_GADM
```

Cek hasilnya (di `ptpl-land-dev` harus muncul 4 role baru):
```bash
gcloud projects get-iam-policy ptpl-land-dev --flatten="bindings[].members" \
  --filter="bindings.members:service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --format="value(bindings.role)"
```

Catatan akses: semua user Marketing Insight Assistant melihat data BigQuery yang sama (lewat service account agent). Ini sudah disetujui karena akses GE dibatasi pada pengguna berlisensi.

---

### 2.5 Data BigQuery atas nama user (OAuth) — **opsional, tidak dipakai saat ini** (panduan: `PANDUAN_OAUTH_BIGQUERY.md`)

Alternatif dari 2.4. Untuk mengaktifkannya: ikuti `PANDUAN_OAUTH_BIGQUERY.md`, lalu set `"data_auth_mode": "user"` di `settings.json`. Data BigQuery kemudian diambil dengan **akun user yang login**. Fitur dokumen, insight, dan laporan tetap memakai service account.

**Kenapa perlu OAuth client sendiri?** Data Agent bawaan Google memakai OAuth client milik Google. Agent custom (ADK) wajib memakai OAuth client milik project, dan Konsol mewajibkan consent screen dikonfigurasi sebelum OAuth client bisa dibuat.

**Langkah 1 — Consent screen (sekali saja, Konsol project `ptpl-land-dev`)**
1. Buka **Google Auth Platform** (atau **APIs & Services → OAuth consent screen**) → **Get started**.
2. **App name:** `Marketing Insight Assistant` · **User support email:** email Anda.
3. **Audience:** pilih **External** (akun `mirptpl@gmail.com` dan `jason.kusuma@mii.co.id` berada di luar organisasi project).
4. **Contact information:** email Anda → setujui kebijakan → **Create**.
5. Menu **Audience** → klik **Publish app** → konfirmasi. Status menjadi **In production**, sehingga otorisasi tidak kedaluwarsa tiap 7 hari dan tidak perlu mendaftarkan test user.

Catatan: karena aplikasi belum diverifikasi Google, saat otorisasi pertama user akan melihat peringatan *"Google hasn't verified this app"*. Klik **Advanced → Go to Marketing Insight Assistant** → **Continue**. Ini normal untuk aplikasi internal (batas 100 user tanpa verifikasi).

**Langkah 2 — OAuth client (Konsol)**
1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. **Application type:** Web application · **Name:** `Marketing Insight Assistant GE`.
3. **Authorized redirect URIs** → tambahkan keduanya:
   - `https://vertexaisearch.cloud.google.com/oauth-redirect`
   - `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`
4. **Create** → pada panel *OAuth client created* klik **Download JSON**.
5. Di Cloud Shell: menu **⋮ → Upload** → pilih file JSON tadi (tersimpan di folder home, nama berawalan `client_secret_`).

**Langkah 3 — Pasang Authorization ke agent (Cloud Shell)**
```bash
cd ~/agent-bei-csls && source .venv/bin/activate && set -a && source .env && set +a
python scripts/enable_user_auth.py ~/client_secret_*.json
```
Yang diharapkan:
```
1/3 Membuat Authorization 'mia-bigquery' (200)
2/3 Pendaftaran ditemukan: 'Marketing Insight Assistant' di app <id-app>
3/3 Authorization terpasang pada pendaftaran agent.
```
**Rencana B** — jika langkah 3/3 GAGAL (pendaftaran lama tidak bisa diubah lewat API):
```bash
python scripts/enable_user_auth.py ~/client_secret_*.json --register-new
```
Lalu di Konsol (**Gemini Enterprise → app → Agents**): bagikan agent baru ke `mirptpl@gmail.com` dan `jason.kusuma@mii.co.id`, kemudian hapus pendaftaran lama (yang tanpa Authorization).

Setelah berhasil, hapus file rahasia: `rm ~/client_secret_*.json`

**Langkah 4 — Update kode agent**
```bash
cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh
```

**Langkah 5 — Uji**
1. Buka **chat baru** di Marketing Insight Assistant → klik **Authorize** saat diminta → pilih akun → lanjutkan melewati peringatan verifikasi → **Continue**.
2. Tanyakan: `Hitung rata-rata per liter pricelist, harga survei, dan gap produk Hero PTPL dibanding kompetitor Shell pada Juli 2026.`

| Hasil | Arti / tindakan |
|---|---|
| Angka dan tabel muncul | ✅ Selesai |
| Agent meminta otorisasi | Token belum diterima. Buka chat baru dan klik Authorize. Jika tetap, cek ID Authorization = `data_auth_id` di `settings.json` (default `mia-bigquery`) |
| "Akun Anda belum memiliki akses ke Data Agent atau tabel BigQuery" | Akun user butuh role **Gemini Data Analytics Stateless Chat User** di project `ptpl-land-dev` (beri ke akun user, bukan service account) |

Beralih antara kedua cara kapan saja tanpa deploy: ubah `data_auth_mode` di `settings.json` (`service_account` atau `user`).

---

## 3. Kode di repo (laptop)

Setiap kali menerima zip kode baru dari tim/AI, perbarui repo seperti ini (Mac/Linux atau Git Bash). Sesuaikan lokasi zip.

```bash
cd agent-bei-csls
git pull
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
rm -rf /tmp/gla && unzip -q ~/Downloads/ge-library-agent.zip -d /tmp/gla
cp -r /tmp/gla/ge-library-agent/. .
git add -A && git commit -m "Update kode agent" && git push
```

**Checkpoint:** root repo berisi `library_agent/`, `scripts/`, `templates/`, `requirements.txt`, `PANDUAN_SETUP.md`.

---

## 4. Cloud Shell: lingkungan kerja (sekali saja)

### 4.1 Clone dan Python
```bash
cd ~ && [ -d agent-bei-csls ] || git clone https://github.com/TooGreat430/agent-bei-csls.git
cd ~/agent-bei-csls && git pull
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 4.2 Buat `.env` (lewati jika sudah ada)
```bash
[ -f .env ] || cat > .env <<'EOF'
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
LIB_SOURCE_FOLDER=gs://ptpl-ge-bucket/ge-docs-datastore/
LIB_FOLDER_BATCH_SIZE=20
LIB_MAX_FILE_MB=100
LIB_TEMPLATE_SOURCE=gcs
LIB_DATASTORE_ID=perpustakaan-dokumen
LIB_AGENT_DISPLAY_NAME=marketing-insight-assistant
LIB_COMPANY_NAME="PT Pertamina Lubricants"
LIB_DOC_TYPES=BEI,CSLS
LIB_DOC_TYPE_HINTS="BEI: Brand Equity Index - laporan studi ekuitas merek pelumas (brand awareness, brand image, preferensi, brand funnel, perbandingan dengan merek pesaing); CSLS: Customer Satisfaction and Loyalty Survey - laporan survei kepuasan dan loyalitas pelanggan (indeks kepuasan, NPS, loyalitas, evaluasi produk dan layanan)"
LIB_AGENT_RESOURCE=projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768
EOF
```

### 4.3 Setiap membuka Cloud Shell baru
```bash
cd ~/agent-bei-csls && source .venv/bin/activate && set -a && source .env && set +a && gcloud config set project ptpl-land-dev
```

---

## 5. Deploy & update agent

### 5.1 Update agent yang sudah ada (cara normal)
```bash
cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh
```

Script ini otomatis:
1. Mengambil kode terbaru dan memasang dependensi.
2. Merapikan `.env` (menambah baris yang kurang).
3. Menyiapkan `ge-docs-agent/`: mengunggah template baru dan `settings.json` jika belum ada (yang sudah ada tidak ditimpa).
4. **Membuat data store `perpustakaan-dokumen` jika belum ada** (beberapa menit).
5. Menjalankan uji unit.
6. Meng-update agent di Agent Runtime (5–10 menit).

**Jangan tekan `Ctrl+C`** sampai muncul `Selesai.` Jika terlanjur, update tetap berjalan di server; cek statusnya dengan perintah di Troubleshooting.

Pendaftaran di Gemini Enterprise **tidak perlu diulang** setelah update.

### 5.2 Deploy pertama kali (hanya jika agent belum pernah ada)
```bash
python scripts/setup_datastore.py
python scripts/upload_templates.py --missing-only
gcloud storage cp setup/settings.json gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json
python scripts/deploy_agent_engine.py
# simpan resource name dari output:
sed -i '/^LIB_AGENT_RESOURCE=/d' .env
echo "LIB_AGENT_RESOURCE=<resource name dari output>" >> .env
```
Lalu daftarkan ke Gemini Enterprise (bagian 6).

---

## 6. Daftarkan ke Gemini Enterprise (sekali saja)

Konsol → **Gemini Enterprise** → app GE → **Agents** → **Add agent** → **Custom agent via Agent Runtime**:

| Isian | Nilai |
|---|---|
| Agent resource | `marketing-insight-assistant` (asia-southeast2), atau resource name di `.env` |
| Agent name | `Marketing Insight Assistant` |
| Agent description | `Asisten marketing PT Pertamina Lubricants: analisis data pasar dari BigQuery (harga, gap, margin, Product Hero per zona), perpustakaan dokumen BEI & CSLS dengan tanya-jawab bersitasi, penyimpanan insight, dan laporan otomatis PDF/PowerPoint/HTML sesuai template perusahaan.` |
| Otorisasi / OAuth | Kosongkan |

Lalu atur user yang boleh memakai agent (mis. `mirptpl@gmail.com`).

---

### 6.1 Mengganti nama agent di Gemini Enterprise (tanpa deploy)

Konsol → **Gemini Enterprise** → app GE → **Agents** → klik agent → **Edit**, lalu ganti:
- **Agent name:** `Marketing Insight Assistant`
- **Agent description:** teks di tabel bagian 6

Nama yang dipakai agent saat memperkenalkan diri diatur oleh `agent_name` di `settings.json` (bagian 10).

## 7. Akses penguji ke link laporan

Link laporan menunjuk ke `ge-docs-agent/reports/`. Penguji perlu izin baca **hanya** di folder itu:

```bash
gcloud storage buckets add-iam-policy-binding gs://ptpl-ge-bucket \
  --member="user:mirptpl@gmail.com" --role=roles/storage.objectViewer \
  --condition='expression=resource.name.startsWith("projects/_/buckets/ptpl-ge-bucket/objects/ge-docs-agent/reports/"),title=hanya-laporan'
```

Akun dengan peran Editor/Owner di project sudah bisa membuka link tanpa langkah ini.

---

## 8. Menambah dokumen

**Cara 1 — lewat bucket:** Konsol → Cloud Storage → `ptpl-ge-bucket` → `ge-docs-datastore` → **Upload files**. Tidak perlu langkah lain: katalog menyesuaikan saat user berikutnya membuka katalog atau memilih dokumen.

**Cara 2 — lewat chat:** lampirkan file → `Masukkan ke perpustakaan.` → agent menampilkan judul, jenis, versi, tanggal → `Benar.` (atau sebut yang salah) → file disimpan ke `ge-docs-datastore/`.

**Aturan:**
- Format: PDF, DOCX, PPTX, HTML, TXT. Maks 100 MB per file.
- **Nama file tanpa spasi**, mis. `black_treasure_bhs_q1_2026_motor.pdf`.
- Indexing butuh 5–20 menit (dokumen besar lebih lama) sebelum bisa ditanya-jawab.
- Dokumen yang gagal diindeks dicoba ulang otomatis setiap katalog dibuka (paling sering tiap 10 menit).

| Perubahan di folder | Di katalog |
|---|---|
| File baru | Ditambahkan, metadata diekstrak otomatis |
| File diganti (nama sama) | Diindeks ulang; koreksi metadata dari user dipertahankan |
| File dihapus | Hilang dari katalog dan pencarian |
| Judul sama, nama file beda | Dicatat sebagai versi baru |
| Isi sama persis dengan file lain | Dilewati |

Hapus dokumen lewat chat juga **menghapus file-nya** dari `ge-docs-datastore/` (dengan konfirmasi).

---

## 9. Template laporan (NONAKTIF sementara)

> Saat ini agent laporan **hanya** membuat dashboard daya saing harga (bagian 9B). Template dokumen BEI/CSLS dipindahkan ke `templates_nonaktif/` dan tidak dipakai agent. Folder `ge-docs-agent/templates/` di bucket boleh dihapus.


Lokasi: `gs://ptpl-ge-bucket/ge-docs-agent/templates/<nama_template>/`

| File | Wajib? | Fungsi |
|---|---|---|
| `manifest.json` | Ya | Judul, format (html/pdf/pptx), warna tema, susunan halaman |
| `schema.json` | Ya | Bagian laporan yang diisi Gemini |
| `style_examples.md` | Tidak | Contoh gaya bahasa laporan lama |
| `template.pptx` | Tidak | PowerPoint resmi klien; master/tema-nya dipakai untuk output PPTX |
| `template.html` | Tidak | Desain HTML khusus |

Template tersedia:

| Template | Untuk | Isi |
|---|---|---|
| `daya_saing_harga_bq` | Insight data BigQuery | Executive summary, kartu KPI per zona, matriks gap dengan status AMAN/WATCH/KRITIS, **grafik** (batang/garis), insight strategis |
| `studi_bei_nps` | Insight dokumen | Gaya deck riset 16:9 |
| `laporan_studi` | Umum | Dokumen sederhana |

**Grafik:** HTML (SVG), PDF (digambar langsung), dan PowerPoint (grafik native yang bisa diedit). Grafik **tidak** tampil di chat GE, hanya di laporan.

**Pengaman angka (template `daya_saing_harga_bq`):** setiap angka di KPI, matriks, dan grafik harus berasal dari tabel data BigQuery atau isi insight. Angka yang tidak ditemukan ditolak; jika masih ada setelah percobaan ulang, angka itu dihapus dari laporan (grafik kosong di titik itu, sel matriks "NA"). Karena itu, simpan jawaban data sebagai insight **sebelum** membuat laporan, agar tabel datanya ikut tersimpan.

Menambah/mengganti template: upload foldernya lewat Konsol (**Upload folder**) ke `ge-docs-agent/templates/`. Langsung berlaku, tanpa deploy. File PDF/PPT laporan lama tidak bisa langsung dipakai sebagai template — perlu dikonversi ke `manifest.json` + `schema.json` dulu.

User meminta format di chat: *"…dalam format PDF / PowerPoint / HTML"*. Hanya format yang diminta yang dibuat; jika tidak disebut, agent menanyakannya.

---

## 9B. Dashboard daya saing harga

Dibuat langsung dari BigQuery (tanpa insight) dengan prompt seperti *"Buatkan dashboard daya saing harga Q3 2026 vs Q2 2026 dalam PDF"*.

| Bagian | Isi |
|---|---|
| Executive Summary | Kartu per zona, matriks gap HJ & margin per zona dengan status, 2 grafik, insight strategis |
| Per zona (Nasional, Zona 1–3) | Halaman konsumen (HET vs harga jual) dan halaman outlet (HTO & margin): KPI + chip status, tabel viskositas & Hero, grafik per segmen, anomali, kompetitor yang gapnya menyempit |
| Format | HTML dengan tombol tab · PDF satu halaman per bagian · PowerPoint satu slide per bagian |

Semua angka dihitung kode dari query (aturan sama dengan Data Agent: filter wajib, per liter, pasangan KIMAP, zona). Gemini hanya menulis narasi; kalimat yang memuat angka di luar data dibuang. Periode mengikuti permintaan user (kuartal, bulan, atau rentang; pembanding opsional). Izin yang dipakai sama dengan agent data (BigQuery Job User + Data Viewer tabel survei).

## 10. Pengaturan tanpa deploy

File `gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json` — ubah lewat Konsol (Download → edit → Upload, timpa). Berlaku maks. 5 menit kemudian.

| Pengaturan | Isi sekarang |
|---|---|
| `agent_name` | Marketing Insight Assistant |
| `hero_products` | Daftar Product Hero untuk dashboard (samakan dengan Data Agent bila berubah) |
| `status_aman_below` / `status_kritis_above` | Ambang status gap: AMAN < −5.000/L, KRITIS > 0, selain itu WATCH |
| `price_table` | Tabel survei untuk dashboard (`ptpl-curated-prd.DATAMART.SURVEY_PRODUCTS`) |
| `data_auth_mode` | `service_account` (dipakai) atau `user` (OAuth) |
| `data_auth_id` | `mia-bigquery` (ID Authorization di GE) |
| `company_name` | PT Pertamina Lubricants |
| `allowed_doc_types` | `["BEI", "CSLS"]` |
| `doc_type_hints` | Penjelasan BEI dan CSLS untuk Gemini |
| `max_active_docs` | 10 |
| `source_folder` | `gs://ptpl-ge-bucket/ge-docs-datastore/` |
| `folder_batch_size` | 20 |
| `max_file_mb` | 100 |

Perubahan perilaku/instruksi agent tetap butuh update kode (bagian 5.1).

---

## 11. Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| Agent: "Permission Denied / 403" saat membuka katalog | Izin bucket belum ada | Jalankan bagian 2.2, tunggu 2–3 menit |
| Status dokumen "Gagal diindeks" | Data store belum ada, atau izin `discoveryengine.editor` belum ada | Jalankan `bash scripts/update_agent.sh` (membuat data store otomatis); pastikan bagian 2.3. Dokumen dicoba ulang otomatis saat katalog dibuka lagi |
| Perlu memastikan data store ada | — | Perintah A di bawah. `"code": 404` berarti belum ada |
| Perlu melihat pesan error agent | — | Perintah B di bawah |
| Terlanjur `Ctrl+C` saat update | Update tetap berjalan di server | Cek dengan Perintah C. Jangan langsung jalankan ulang script |
| `update_agent.sh`: resource agent tidak ditemukan | `LIB_AGENT_RESOURCE` kosong dan nama agent tidak cocok | Tambahkan baris `LIB_AGENT_RESOURCE=...` (lihat tabel paling atas) ke `.env` |
| Agent menyebut "Research Agent / Report Agent" atau versi lama | GE masih memakai kode lama | Buka **chat baru**. Jika tetap, cek resource yang terdaftar di GE sama dengan `LIB_AGENT_RESOURCE` |
| File di folder tidak masuk katalog | Format/ukuran/duplikat | Agent menyebutkan alasannya saat katalog dibuka |
| Jenis dokumen sering "perlu dicek" | Hints kurang jelas | Perjelas `doc_type_hints` di `settings.json` |
| Link laporan tidak bisa dibuka | Akun belum punya akses | Bagian 7 |
| Error 404 model | Lokasi Gemini salah | Pastikan `LIB_GEMINI_LOCATION=global`, lalu update |
| Agent: "Data tidak bisa diambil… belum memiliki izin ke Data Agent atau tabel BigQuery" | Izin bagian 2.4 belum lengkap | Jalankan perintah admin di bagian 2.4, tunggu 2–3 menit, tanya ulang |
| Grafik di laporan kosong sebagian / sel "NA" | Angka tidak ada di data yang tersimpan | Simpan jawaban data yang relevan sebagai insight (agar tabelnya ikut), lalu buat laporan lagi |

**Perintah A — cek data store:**
```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "X-Goog-User-Project: ptpl-land-dev" \
  "https://discoveryengine.googleapis.com/v1/projects/ptpl-land-dev/locations/global/collections/default_collection/dataStores/perpustakaan-dokumen" \
  | grep -E '"name"|"code"|"message"'
```

**Perintah B — error terakhir agent:**
```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND severity>=ERROR' \
  --limit=5 --freshness=2h --format="value(timestamp,textPayload)" | cut -c1-600
```

**Perintah C — status update setelah terlanjur `Ctrl+C`** (ganti `<OPERATION>` dengan angka setelah `/operations/` di output):
```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://asia-southeast2-aiplatform.googleapis.com/v1/projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768/operations/<OPERATION>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('MASIH BERJALAN' if not d.get('done') else ('GAGAL: '+str(d['error']) if 'error' in d else 'BERHASIL'))"
```
