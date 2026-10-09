# Panduan — Analisis File CSV/Excel, Pengetahuan Data Agent, dan Pengecekan Angka

## 1. Ringkasan fitur

| Fitur | Isi |
|---|---|
| **Analisis file unggahan** | User mengunggah CSV/XLSX/XLS di chat. File disimpan per chat (`ge-docs-agent/data-files/<chat>/`), tidak masuk perpustakaan dokumen, dan **tidak membuat tabel BigQuery**. Agent memprofil file, mengenali formatnya (survei retail / survei industri / umum), menerapkan aturan bisnis otomatis, mencari kolom penghubung antar-file, lalu menghitung dengan **pandas** (Gemini hanya menyusun rencana analisis) |
| **Pengetahuan Data Agent** | Instruksi, glossary, dan contoh query resmi dari Data Agent retail & industri dibaca otomatis lewat API (diperbarui tiap 30 menit) dan dipakai agent analisis file. Salinan cadangan: `ge-docs-agent/config/knowledge_<retail|industri>.json` |
| **Pengecekan angka otomatis** | Jawaban agent data dan agent analisis file dicek: angka yang tidak ada di hasil tool → model diminta menulis ulang sekali; jika masih ada, jawaban diberi catatan transparan |
| **Laporan dari file** | Dashboard retail dan one-pager industri bisa dibuat dari file unggahan berformat survei, dengan mesin perhitungan yang sama seperti dari BigQuery |

## 2. Izin service account

Service account: `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com`

| Role | Di mana | Untuk | Status |
|---|---|---|---|
| Storage Object Admin | bucket `ptpl-ge-bucket` | Menyimpan file unggahan per chat | Sudah ada |
| BigQuery Data Viewer | `ptpl-curated-prd.DATAMART.survey_industry` | Laporan industri dari BigQuery | **Tambahkan** |
| Gemini Data Analytics Data Agent Viewer | project `ptpl-land-dev` | Membaca definisi Data Agent | **Tambahkan** (atau pakai salinan cadangan, langkah 3.4) |

```bash
SA=service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com
bq add-iam-policy-binding --member="serviceAccount:$SA" --role="roles/bigquery.dataViewer" \
  ptpl-curated-prd:DATAMART.survey_industry
gcloud projects add-iam-policy-binding ptpl-land-dev \
  --member="serviceAccount:$SA" --role="roles/geminidataanalytics.dataAgentViewer"
```

## 3. Deploy

1. **Laptop** — ganti isi repo dengan zip (hapus isi lama dulu agar file lama tidak tertinggal):
   ```bash
   cd agent-bei-csls && git pull
   find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
   rm -rf /tmp/gla && unzip -q ~/Downloads/ge-library-agent.zip -d /tmp/gla
   cp -r /tmp/gla/ge-library-agent/. .
   git add -A && git commit -m "Analisis file CSV/Excel, pengetahuan Data Agent, pengecekan angka" && git push
   ```
2. **Cloud Shell** — deploy (paket baru: pandas, openpyxl, xlrd):
   ```bash
   cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh
   ```
3. Tunggu `Selesai.`
4. **Cloud Shell** — buat salinan cadangan pengetahuan Data Agent (memakai akun Anda):
   ```bash
   cd ~/agent-bei-csls && source .venv/bin/activate && python scripts/check_knowledge.py
   ```
   Hasil yang diharapkan: kedua domain `sumber=api` dengan jumlah instruksi, glossary, dan contoh query > 0.
   Salinan ini dipakai agent jika service account belum bisa membaca definisi Data Agent.

   **Cadangan dari agent card** (jika API belum bisa diakses): simpan JSON agent card dari tim data sebagai
   `card_retail.json` dan `card_industri.json` di Cloud Shell, lalu:
   ```bash
   python scripts/check_knowledge.py --from-card retail card_retail.json
   python scripts/check_knowledge.py --from-card industri card_industri.json
   ```
   Ulangi setiap kali tim data memperbarui agent card (tanpa deploy).

## 4. Menyiapkan file uji dari BigQuery

```bash
bq query --use_legacy_sql=false --format=csv --max_rows=5000 \
  "SELECT * EXCEPT(PRC_DT, JOB_ID) FROM \`ptpl-curated-prd.DATAMART.SURVEY_PRODUCTS\`
   WHERE DT_PR = '2026-07-31' AND AVAILABILITY = '1'" > uji_retail_juli.csv
bq query --use_legacy_sql=false --format=csv --max_rows=5000 \
  "SELECT * EXCEPT(prc_date, job_id, koordinat) FROM \`ptpl-curated-prd.DATAMART.survey_industry\`
   WHERE dt_pr BETWEEN '2026-08-01' AND '2026-09-30' AND data_status = 'OK'" > uji_industri.csv
```
Unduh kedua file dari Cloud Shell (menu ⋮ → Download), lalu unggah di chat GE.

## 5. Skenario uji (chat baru untuk setiap blok)

| No | Langkah | Yang diharapkan |
|---|---|---|
| 1 | Unggah `uji_retail_juli.csv` + `Tolong profil file ini.` | Jenis "survei retail", jumlah baris, periode, baris yang dikecualikan aturan |
| 2 | `Bandingkan harga jual per liter Product Hero dengan rata-rata kompetitornya per zona.` | Tabel gap per zona dalam KIMAP yang sama (negatif = PTPL lebih murah) + grafik |
| 3 | `Buat cross-tab rata-rata harga tebus per liter per brand dan segmen.` | Tabel pivot dari file |
| 4 | `Berapa market share Pertamina tahun 2025?` | Agent menyatakan data tidak ada di file, tanpa mengarang |
| 5 | `Simpan sebagai insight.` lalu `Buatkan laporan dari file ini dalam HTML.` | Dashboard retail dari file (sumber: nama file) |
| 6 | Chat baru: unggah `uji_industri.csv` + `Berapa gap Shell vs HTD+3% per channel untuk main stage EARLY?` | Gap % per channel (positif = PTPL kompetitif) |
| 7 | `Buatkan laporan industri dari file ini dalam PDF.` | One-pager B2B dari file |
| 8 | Chat baru: unggah dua file (mis. retail + file berisi `OUTLET_ID`) + `Gabungkan kedua file.` | Agent menunjukkan kandidat kolom penghubung beserta % kecocokan dan meminta konfirmasi |
| 9 | Unggah Excel dengan beberapa sheet + `Pakai sheet kedua.` | Sheet yang diminta dibaca |

## 6. Log yang berguna

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND timestamp>="'$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)'"' \
  --limit=80 --format="value(timestamp,severity,textPayload)" | grep -iE "File data disimpan|Angka tidak terverifikasi|Definisi Data Agent|gagal" | cut -c1-250
```
- `File data disimpan` → GE meneruskan file ke agent (uji paling awal).
- `Definisi Data Agent … memakai salinan` → service account belum bisa membaca Data Agent (jalankan langkah 3.4 / tambahkan role).
- `Angka tidak terverifikasi` → pengecekan angka bekerja.
