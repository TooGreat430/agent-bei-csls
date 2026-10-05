# Panduan — Mengaktifkan & Menguji Data BigQuery (Service Account)

Marketing Insight Assistant mengambil data BigQuery lewat Data Agent **Marketing Intelligence**, dengan identitas **service account agent**. User tidak perlu klik *Authorize*.

| Item | Nilai |
|---|---|
| Service account agent | `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com` |
| Project agent & Data Agent | `ptpl-land-dev` |
| Data Agent | `agent_4df3074b-9d7e-4f9f-993b-b3969b8a2095` |
| Tabel utama Data Agent | `ptpl-curated-prd.DATAMART.SURVEY_PRODUCTS` |
| Tabel pendukung (lokasi outlet) | `pertamina-lubricants-project.STAGING.MIR_MST_OUTLET_GADM` |
| Pengaturan | `data_auth_mode = service_account` (default kode terbaru) |

Perkiraan waktu: 15 menit (izin sudah lengkap; tinggal deploy dan uji).

---

## Langkah 1 — Izin (✅ selesai)

| Izin untuk service account | Di mana | Status |
|---|---|---|
| Gemini Data Analytics Data Agent User | Project `ptpl-land-dev` | ✅ |
| Gemini Data Analytics Stateless Chat User | Project `ptpl-land-dev` | ✅ |
| Gemini for Google Cloud User | Project `ptpl-land-dev` | ✅ |
| BigQuery Job User | Project `ptpl-land-dev` | ✅ |
| BigQuery Data Viewer | Tabel `ptpl-curated-prd.DATAMART.SURVEY_PRODUCTS` | ✅ |
| BigQuery Data Viewer | Tabel `pertamina-lubricants-project.STAGING.MIR_MST_OUTLET_GADM` | ✅ |
| Discovery Engine Editor, Aiplatform Editor, Storage Object Admin (bucket) | (fitur dokumen & laporan) | ✅ sebelumnya |

Tidak ada izin lain yang perlu diberikan. Untuk pengguna baru, cukup bagikan agent di Gemini Enterprise; akses data BigQuery lewat agent mengikuti service account.

---

## Langkah 2 — Perbarui repo (laptop)

Ekstrak `ge-library-agent.zip` terbaru ke repo, lalu push:
```bash
cd agent-bei-csls
git pull
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
rm -rf /tmp/gla && unzip -q ~/Downloads/ge-library-agent.zip -d /tmp/gla
cp -r /tmp/gla/ge-library-agent/. .
git add -A && git commit -m "Data BigQuery via service account" && git push
```

---

## Langkah 3 — Update agent (Cloud Shell)

```bash
cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh
```
Tunggu sampai `Selesai.` (5–10 menit). Jangan tekan `Ctrl+C`.

**Checkpoint:** baris terakhir menyebut `reasoningEngines/5516874359156768768` (agent yang sama, pendaftaran GE tidak berubah).

Jika `settings.json` di bucket pernah diberi `"data_auth_mode": "user"`, ubah menjadi `"service_account"` (Konsol → Cloud Storage → `ptpl-ge-bucket/ge-docs-agent/config/settings.json` → download, edit, upload ulang).

---

## Langkah 4 — Uji di Gemini Enterprise (chat baru)

| No | Prompt | Yang diharapkan |
|---|---|---|
| 1 | `Hitung rata-rata per liter pricelist, harga survei, dan gap produk Hero PTPL dibanding kompetitor Shell pada Juli 2026.` | Angka Rupiah per liter, tabel ringkas, sumber "Survey Response Report Retail". **Tidak** diminta Authorize |
| 2 | `Fokus ke segmen MCO saja.` | Memahami konteks sebelumnya |
| 3 | `Di provinsi mana saja outlet survei berada?` | Menguji tabel lokasi outlet (`MIR_MST_OUTLET_GADM`) |
| 4 | Tanyakan prompt no. 1 ke agent **Marketing Intelligence** di GE | Angka **sama** dengan no. 1 |
| 5 | `Gunakan workspace POC Data.` → `Simpan jawaban data tadi sebagai insight.` | Insight bersumber BigQuery tersimpan |
| 6 | `Buatkan laporan dengan template Daya Saing Harga Retail dari insight di workspace ini dalam format PDF.` | PDF berisi KPI, matriks, grafik, insight strategis |

Skenario lanjutan: `PANDUAN_TESTING.md` Bagian 8–9.

---

## Jika gagal

Ambil pesan error terakhir dari agent:
```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND textPayload:"Data Agent gagal"' \
  --limit=2 --freshness=1h --format="value(timestamp,textPayload)" | grep -E "denied|Permission|403|404|Access" | cut -c1-400
```

| Isi pesan error | Penyebab | Tindakan |
|---|---|---|
| `Access Denied: Table ptpl-curated-prd:DATAMART.SURVEY_PRODUCTS` | Data Viewer belum di tabel utama | Langkah 1B, tabel pertama |
| `Access Denied: Table pertamina-lubricants-project:...` | Tabel sumber view / tabel lokasi belum dibuka | Beri Data Viewer di tabel yang disebut pesan error |
| `bigquery.jobs.create` | BigQuery Job User belum ada | Langkah 1A |
| `geminidataanalytics` ... `denied` | Role Data Agent belum aktif | Cek langkah 1A; tunggu 2–3 menit setelah grant |
| `cloudaicompanion` | Gemini for Google Cloud User belum ada | Langkah 1A |
| Agent meminta *Authorize* | Mode masih `user` atau pendaftaran GE punya Authorization | Cek `data_auth_mode` di `settings.json`; hubungi tim teknis bila `enable_user_auth.py` pernah dijalankan |
| Tidak ada error, tetapi jawaban "data tidak tersedia" | Data memang tidak ada untuk periode/filter tersebut | Coba periode lain (mis. Mei 2026) |

Setelah izin diperbaiki, tunggu 2–3 menit lalu ulangi di **chat baru**. Tidak perlu deploy ulang.
