# Asisten Perpustakaan Dokumen — Gemini Enterprise (ADK)

Agent ADK yang menjadikan Gemini Enterprise (GE) sebagai **perpustakaan dokumen bersama**, dengan semua pekerjaan dilakukan dalam **satu chat**.

| Requirement | Cara dipenuhi |
|---|---|
| Satu chat untuk semua | Satu root agent terdaftar di GE, dengan `research_agent` dan `report_agent` sebagai sub-agent |
| Pilih dokumen, chat terpusat, dan bisa diperluas di tengah chat | Daftar dokumen aktif di session state, dan setiap pencarian dipaksa filter `doc_key: ANY(...)` di level API |
| Upload dokumen dari chat ke perpustakaan | Callback menangkap lampiran, Gemini mengekstrak judul/jenis/versi/tanggal (`extract_upload_metadata`), agent menampilkan hasilnya untuk dikonfirmasi user, lalu dokumen disimpan (`confirm_upload`) ke GCS, data store, dan katalog. User hanya memperbaiki bagian yang salah |
| Impor dokumen yang sudah ada di folder bucket | `scripts/import_folder.py`: scan → cek CSV → run, aman diulang berkala |
| Hapus dokumen dan insight bersama | `delete_document` (semua user, dengan konfirmasi, tombstone agar tidak diimpor ulang). Insight per workspace terlihat semua user, diubah hanya oleh pembuatnya |
| Laporan dari template perusahaan | Gemini hanya mengisi JSON sesuai `schema.json`, lalu Jinja2 merender `template.html` ke HTML/PDF |

> **Status POC:** jalur upload via chat bergantung pada apakah GE meneruskan lampiran ke agent custom. Uji dulu dengan `poc/upload_probe` sebelum demo ke klien (lihat bagian POC).

---

## Arsitektur

```
                     Gemini Enterprise — 1 chat
                               │
                 ┌──── asisten_perpustakaan (root) ────┐
                 │  before_agent_callback: capture_uploads
      ┌──────────┴───────────┐           ┌─────────────┴──────────┐
      │ research_agent       │           │ report_agent           │
      │ • katalog            │           │ • list template        │
      │ • upload → library   │           │ • pilih insight        │
      │ • dokumen aktif      │           │ • generate_report      │
      │ • tanya-jawab+sitasi │           │   (JSON → Jinja → PDF) │
      │ • insight            │           └────────────────────────┘
      └──────────────────────┘
   GCS bucket utama: staging/, library/, templates/, catalog/index.json, insights/
   GCS bucket laporan: reports/  (satu-satunya bucket yang bisa dibaca user)
   Data store GE (dokumen + metadata, layout parser, chunking)
```

## Struktur folder

```
library_agent/
  agent.py            root agent (didaftarkan ke GE)
  subagents/          research_agent, report_agent
  tools/              tool ADK (library_tools.py, report_tools.py)
  callbacks.py        penangkap lampiran chat + log POC
  search.py           pencarian berfilter dokumen aktif + label sitasi
  ingest.py           staging, salin ke library/, impor ke data store
  metadata.py         ekstraksi metadata dokumen otomatis dengan Gemini
  folder_import.py    impor dokumen dari folder bucket (dipakai scripts/import_folder.py)
  library_admin.py    operasi hapus dokumen (dipakai agent dan script impor)
  store.py            baca/tulis JSON di GCS, aman untuk penulisan bersamaan
  catalog.py          katalog perpustakaan (catalog/index.json di GCS)
  insights.py         insight per workspace (insights/<workspace>.json di GCS)
  report_engine.py    registry template, composer, validasi, render
  prompts.py          instruksi agent
  llm.py              model Gemini dengan lokasi endpoint dikunci (LIB_GEMINI_LOCATION)
  config.py           semua konfigurasi (env LIB_*)
templates/laporan_studi/   CONTOH template (ganti dengan template klien)
poc/upload_probe/          agent POC uji lampiran chat
scripts/                   setup data store, upload template, deploy, preview
setup/                     skema data store
tests/                     uji unit (tanpa GCP)
```

---

## 1. Prasyarat

**API yang perlu diaktifkan:**
```bash
gcloud services enable discoveryengine.googleapis.com aiplatform.googleapis.com storage.googleapis.com
```

**Resource:**
- **Bucket utama** (`LIB_BUCKET`): dokumen, template, katalog, dan insight. Hanya agent yang boleh mengakses.
- **Bucket laporan** (`LIB_REPORT_BUCKET`): hasil laporan. Hanya bucket ini yang diberi izin baca ke user, supaya katalog dan insight milik user lain tidak ikut terbuka.
- Tidak butuh database. Katalog dan insight disimpan sebagai file JSON di bucket utama.
- App Gemini Enterprise di lokasi yang sama dengan data store (`global`, `us`, atau `eu`).

**IAM untuk service account Agent Engine** (`service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`):
- `roles/discoveryengine.editor`
- `roles/aiplatform.user`
- `roles/storage.objectAdmin` di bucket utama **dan** bucket laporan

**IAM untuk user:** `roles/storage.objectViewer` **hanya di bucket laporan**, agar link laporan (`storage.cloud.google.com/...`) bisa dibuka.

## 2. Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # isi nilainya
set -a && source .env && set +a
gcloud auth application-default login
```

**a. Data store perpustakaan** (unstructured + metadata, layout parser, chunking, skema `doc_key` bisa difilter):
```bash
python scripts/setup_datastore.py
```
Setelah itu, hubungkan data store ini ke app GE jika perpustakaan juga ingin bisa dicari lewat pencarian bawaan GE.

**b. Upload template laporan ke GCS:**
```bash
python scripts/upload_templates.py
```

## 3. Jalankan lokal

```bash
adk web          # dari root repo, pilih "library_agent"
```
Untuk pengembangan template tanpa GCS, set `LIB_TEMPLATE_SOURCE=local`.

Pratinjau template tanpa GCP sama sekali:
```bash
python scripts/preview_template.py laporan_studi tests/fixtures/sample_content.json
```

Uji unit:
```bash
python -m unittest discover tests -v
```

---

## 4. POC: apakah lampiran chat diteruskan ke agent custom?

Ini satu-satunya titik yang belum pasti. `poc/upload_probe` membalas dengan struktur pesan yang diterima, tanpa memanggil model.

```bash
python scripts/deploy_agent_engine.py --probe
```
Daftarkan resource-nya ke GE (langkah sama dengan bagian 5), lalu uji:

| Uji | Yang diharapkan |
|---|---|
| Kirim teks saja | 1 part `text` |
| Kirim teks + PDF kecil | Muncul part `inline_data` (bytes > 0) atau `file_data` |
| Kirim DOCX | Sama seperti PDF |
| Kirim file besar (±20 MB) | Mencari batas ukuran |

**Interpretasi:**
- `inline_data` dengan bytes > 0: **upload via chat bisa**, dan agent utama langsung berfungsi.
- `file_data` dengan URI `gs://`: bisa, tetapi pastikan service account agent punya izin baca ke URI tersebut.
- `file_data` dengan URI lain: catat formatnya, lalu `callbacks.py` perlu diadaptasi.
- Hanya `text`: lampiran tidak diteruskan, sehingga perlu jalur cadangan (upload via folder Drive, ditunda).

Log juga tercatat di Cloud Logging dengan kata kunci `UPLOAD_PROBE`.

## 5. Deploy dan daftarkan ke Gemini Enterprise

```bash
python scripts/deploy_agent_engine.py
# perbarui deployment yang sudah ada:
python scripts/deploy_agent_engine.py --update projects/<p>/locations/<r>/reasoningEngines/<id>
```
Lalu di konsol Gemini Enterprise, buka **Agents**, tambahkan agent custom berbasis Agent Engine, dan masukkan resource name hasil deploy. Ikuti dokumentasi resmi *Register and manage ADK agents*, karena nama menu bisa berubah. Alternatifnya, daftarkan lewat A2A.

---

## 6. Menambah template laporan klien

1. Buat folder `templates/<template_id>/` berisi:
   - `manifest.json`: `id`, `title`, `description`, `outputs` (`["html"]` atau `["html","pdf"]`)
   - `schema.json`: JSON Schema isi laporan. Setiap `description` field adalah instruksi untuk Gemini.
   - `template.html`: template Jinja2. Isi diakses via `c.<field>`, sedangkan metadata sistem via `meta.*` (`company_name`, `report_title`, `generated_by`, `generated_date`, `generated_at`, `template_title`).
   - `style_examples.md` (opsional): 2 sampai 3 potongan laporan lama sebagai acuan gaya bahasa.
2. Cek tampilannya dengan `scripts/preview_template.py` dan contoh JSON.
3. Upload dengan `python scripts/upload_templates.py <template_id>`. Tidak perlu redeploy agent.

**Tips konversi laporan lama klien:** Gemini bisa membantu membuat draf `template.html` dan `schema.json` dari PDF/Word laporan lama, tetapi hasilnya **wajib direview manusia** sebelum di-upload. Gemini hanya terlibat saat membuat template, tidak saat laporan dihasilkan.

---

## 7. Catatan desain

- **Sentralisasi ditegakkan di API, bukan prompt.** `search.build_doc_filter` membatasi query ke `doc_key` aktif, dan hasil tetap disaring ulang di kode sebagai lapis kedua.
- **Callback terpasang di root dan kedua sub-agent**, karena setelah transfer, pesan berikutnya bisa langsung masuk ke sub-agent yang terakhir aktif. Duplikasi dicegah dengan hash konten.
- **Indexing butuh beberapa menit.** Selama itu, isi lampiran masih bisa dibaca model langsung dari pesan user. Status indexing bisa dicek dengan `check_indexing_status`.
- **Tanpa database.** Katalog (`catalog/index.json`) dan insight (`insights/<user>.json`) disimpan di GCS. Penulisan bersamaan aman karena setiap tulis memakai `if_generation_match` dan diulang otomatis jika bentrok. Satu file katalog cukup untuk ratusan sampai beberapa ribu dokumen. Jika perpustakaan tumbuh jauh lebih besar, katalog bisa dipindah ke BigQuery tanpa mengubah tool agent, karena semua akses lewat `catalog.py`.
- **Metadata otomatis + konfirmasi saat upload** (`metadata.py`). Hasil ekstraksi selalu ditampilkan ke user sebelum disimpan. User cukup menjawab "benar" atau menyebut bagian yang salah. Field yang tidak yakin ditandai "mohon dicek". Versi dan tanggal yang tidak tertulis di dokumen diusulkan default (v1 dan tanggal upload) dengan keterangan. Isi `LIB_DOC_TYPE_HINTS` dengan penjelasan tiap jenis dokumen agar klasifikasi BEI/CSLS lebih akurat. User bisa mengoreksi kapan saja ("judulnya salah, harusnya ...") lewat `update_document_metadata`.
- **Versi dokumen:** judul dan jenis yang sama dengan file berbeda memicu konfirmasi "versi baru". Versi lama tetap tersimpan dengan `is_latest=false`.
- **Composer laporan memakai skema dinamis** per template lewat `google-genai` (`response_json_schema`), bukan `output_schema` ADK yang statis. Output divalidasi dengan `jsonschema` dan dicoba ulang sekali jika tidak valid.
- **Model:** default `gemini-3.5-flash`. Agent ADK memanggil Gemini lewat endpoint `LIB_GEMINI_LOCATION` (default `global`), terpisah dari region Agent Engine, supaya agent bisa berjalan di Jakarta tanpa bergantung pada ketersediaan model di region itu.

## 8. Belum termasuk (tahap berikutnya)

- Koleksi terbatas dengan ACL per dokumen di data store (field `collection` sudah disiapkan).
- Jalur cadangan upload via folder Drive (hanya jika POC upload via chat gagal).
- Pemilihan dokumen dengan komponen UI (A2UI), jika komponennya tersedia.
- Hapus atau tarik dokumen oleh penyumbang/admin, beserta peran kontributor/pembaca.
- Signed URL untuk link laporan (saat ini memakai link terautentikasi GCS).
- Output PowerPoint/Word (python-pptx / docxtpl) jika template klien berformat tersebut.
