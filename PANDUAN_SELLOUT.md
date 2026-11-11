# Panduan v3.1 — Data Agent "Selling Out Intelligence" (Sell-out)

Menambahkan Data Agent Sell-out ke Marketing Insight Assistant: tanya-jawab data sell-out, laporan **custom**
(belum ada template), pengenalan file sell-out yang diunggah, dan pengetahuan tambahan dari tim MIR tanpa deploy.
Data Sell-out **berdiri sendiri** (tidak digabung dengan Retail/Industri/Planogram). v3.1 = v3.0 (Claude + skill) + Sell-out.

## Data yang dipakai (sudah terisi)

| Item | Nilai |
|---|---|
| Data Agent | `projects/ptpl-land-dev/locations/global/dataAgents/agent_e188b55c-e61b-4c3f-9f91-3c97a54a6d4a` |
| Service account agent (penerima izin) | `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com` |
| Project agent | `ptpl-land-dev` |
| Pengetahuan tambahan MIR (opsional) | `gs://ptpl-ge-bucket/ge-docs-agent/config/knowledge/sellout.md` |

---

## A. Izin yang perlu Anda atur

Semua untuk service account **`service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com`**.

| No | Izin | Di mana | Untuk apa | Catatan |
|---|---|---|---|---|
| 1 | **Akses ke Data Agent** — role yang sama dengan yang diberikan untuk tiga Data Agent lain (umumnya *Gemini Data Analytics Data Agent User*) | Data Agent Selling Out Intelligence, atau project `ptpl-land-dev` | Agent bisa bertanya ke Data Agent dan membaca definisinya (pengetahuan) | Jika dulu diberikan di level project, **tidak perlu apa-apa lagi** |
| 2 | **BigQuery Data Viewer** (`roles/bigquery.dataViewer`) | **Setiap tabel** yang dipakai Data Agent Sell-out (lihat langkah B1) | Data Agent membaca data atas nama service account; agent membaca skema tabel untuk mengenali file sell-out | Jika tabel ada di project lain, diberikan oleh pemilik project itu (seperti VM_PLANOGRAM dulu) |
| 3 | **BigQuery Job User** (`roles/bigquery.jobUser`) | Project `ptpl-land-dev` | Menjalankan query | Sudah ada untuk tiga Data Agent lain |
| 4 | **Fine-Grained Reader** (`roles/datacatalog.categoryFineGrainedReader`) | Policy tag terkait | Hanya jika tabel sell-out memakai keamanan level kolom (policy tag) | Tanyakan ke pemilik tabel |
| 5 | Akses ke tabel sumber **authorized view** | Dataset sumber | Hanya jika tabel sell-out berupa view ke dataset lain | Tanyakan ke pemilik tabel |
| 6 | **Data Viewer untuk setiap user** pada tabel yang sama | Tabel sell-out | Hanya jika agent memakai mode akses per-user (OAuth) — cek langkah B2 | Pada mode service account (umumnya), tidak perlu |

## B. Langkah

### B1 — Ambil kode & lihat tabel yang dipakai Data Agent (Cloud Shell)

Ganti isi repo dengan zip ini di laptop (CMD, sama seperti panduan sebelumnya), commit
`"v3.2: Sell-out + melihat gambar"`, push. Lalu:

```bash
cd ~/agent-bei-csls && git pull && source .venv/bin/activate && pip install -q -r requirements.txt
python scripts/check_knowledge.py
```

Pada baris **sellout**, catat daftar `tabel=…` — itulah tabel untuk izin no. 2. Jika baris sellout gagal membaca
definisi, akun Anda belum punya akses lihat ke Data Agent tersebut; minta pemilik Data Agent.

### B2 — Cek mode akses data

```bash
gcloud storage cat gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json | grep -E "data_auth_mode|data_auth_id"
```

Kosong / `service_account` → izin no. 6 **tidak** diperlukan. Bila berisi mode per-user (OAuth), setiap user perlu
Data Viewer pada tabel sell-out.

### B3 — Berikan izin A1–A5, lalu deploy

```bash
find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```

Hasil yang diharapkan: uji `OK` (211 uji), `Selesai.` Data Agent Sell-out ditambahkan otomatis ke `.env`.

### B4 — (Kapan saja) Tambahkan pengetahuan dari tim MIR

Saat user memberi panduan sell-out (definisi metrik, struktur laporan yang diinginkan, dll.), simpan sebagai file
Markdown/teks lalu:

```bash
python scripts/set_knowledge.py upload sellout panduan_sellout.md
python scripts/set_knowledge.py show sellout          # cek isi
```

Berlaku untuk chat baru, tanpa deploy. Pengetahuan ini dipakai di analisis file sell-out dan di prompt laporan custom
Sell-out, bersama pengetahuan resmi Data Agent. Ganti kapan saja dengan perintah yang sama; hapus dengan
`python scripts/set_knowledge.py hapus sellout`.

## C. Uji di Gemini Enterprise (chat baru per blok)

| No | Kirim | Lulus jika |
|---|---|---|
| 1 | `Berapa volume sell-out per region bulan lalu?` | Tabel per region; sumber "Selling Out Intelligence" |
| 2 | `Bagaimana tren Active Customer 6 bulan terakhir?` | Tren per bulan + link grafik |
| 3 | `Kontribusi channel terhadap volume sell-out kuartal ini` | Persentase per channel |
| 4 | Setelah no. 1–3 dijawab, agent menawarkan laporan → `ya` → `PDF` | Laporan custom Sell-out bergaya PTPL (Claude), angka sama dengan jawaban tadi |
| 5 | `Gabungkan data sell-out dengan planogram per region` | Agent menjelaskan Sell-out berdiri sendiri; menawarkan analisis terpisah |
| 6 | `Buat laporan template sell-out` | Agent menjelaskan belum ada template; menawarkan laporan custom |
| 7 | Unggah file sell-out (Excel/CSV dengan kolom seperti tabel Data Agent) + `profil file ini` | Jenis data terdeteksi **sell-out** (atau agent bertanya, lalu Anda jawab "sell-out") |

Jika no. 1 gagal dengan pesan akses/izin: periksa izin A1 (Data Agent) dan A2 (tabel), lalu ulangi.

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| "Data Agent tidak bisa diakses" / 403 | Izin A1 belum ada | Beri role yang sama dengan tiga Data Agent lain |
| "Access Denied: Table …" | Izin A2 belum ada pada tabel itu | Beri Data Viewer pada tabel yang disebut di pesan |
| Pertanyaan sell-out dijawab dengan data retail | Kata kunci ambigu | Sebut "sell-out" atau "Selling Out" di pertanyaan; laporkan contoh pertanyaannya untuk penyesuaian routing |
| File sell-out terdeteksi "format umum" | Kolom file berbeda dari tabel Data Agent, atau izin A2 belum ada | Jawab "sell-out" saat agent bertanya; agent tetap memakai pengetahuan Sell-out |
