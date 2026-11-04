# Panduan IAM — Planogram & Gemini 4 Argon (untuk admin project)

Dikerjakan oleh rekan yang punya akses admin IAM di `ptpl-land-dev` dan `ptpl-curated-prd`.
Semua perintah dijalankan di **Cloud Shell** dengan akun admin tersebut. Perkiraan waktu: 10 menit.

| Item | Nilai |
|---|---|
| Service account agent | `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com` |
| Project agent & Data Agent | `ptpl-land-dev` |
| Data Agent planogram | `projects/ptpl-land-dev/locations/global/dataAgents/agent_5f69a707-a240-49ea-9c96-dd12493f659c` |
| Tabel planogram | `ptpl-curated-prd.DATAMART.VM_PLANOGRAM` |
| Model utama | `gemini-4-argon` di `asia-southeast1` (Vertex AI, project `ptpl-land-dev`) |

Izin retail & industri yang sudah ada **tidak berubah**. Izin perpustakaan dokumen (Discovery Engine Editor) tidak
dipakai lagi; boleh dibiarkan atau dicabut.

---

## Langkah 1 — Siapkan variabel

```bash
SA=service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com
```

## Langkah 2 — Akses tabel VM_PLANOGRAM

Dipakai template planogram (query langsung) dan Data Agent planogram saat dipanggil agent.

```bash
bq add-iam-policy-binding --member="serviceAccount:$SA" --role="roles/bigquery.dataViewer" \
  ptpl-curated-prd:DATAMART.VM_PLANOGRAM
```

## Langkah 3 — Tabel lain yang dibaca Data Agent planogram

Jason akan mengirimkan daftar tabel dari langkah 3 `PANDUAN_REDEPLOY.md` (baris `[planogram] … tabel=`).
Untuk **setiap** tabel di daftar itu selain `VM_PLANOGRAM`, jalankan (ganti `PROJECT:DATASET.TABEL`, perhatikan titik
dua setelah nama project):

```bash
bq add-iam-policy-binding --member="serviceAccount:$SA" --role="roles/bigquery.dataViewer" PROJECT:DATASET.TABEL
```

Contoh jika `pertamina-lubricants-project.STAGING.MIR_MASTERDATA` ikut tercantum:

```bash
bq add-iam-policy-binding --member="serviceAccount:$SA" --role="roles/bigquery.dataViewer" \
  pertamina-lubricants-project:STAGING.MIR_MASTERDATA
```

Jika daftar tabel kosong atau hanya `VM_PLANOGRAM`, lewati langkah ini.

## Langkah 4 — Role di project `ptpl-land-dev`

Perintah berikut aman diulang (role yang sudah ada tidak berubah). Role Data Agent dan BigQuery Job User di level
project sudah mencakup Data Agent planogram; `dataAgentViewer` dipakai agent untuk membaca pengetahuan Data Agent.

```bash
for ROLE in roles/geminidataanalytics.dataAgentUser roles/geminidataanalytics.dataAgentStatelessUser \
            roles/geminidataanalytics.dataAgentViewer roles/bigquery.jobUser roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding ptpl-land-dev --member="serviceAccount:$SA" --role="$ROLE" \
    --condition=None --quiet >/dev/null && echo "OK $ROLE"
done
```

Jika salah satu role ditolak dengan pesan *role not found*, lewati role itu dan catat namanya; role lain tetap jalan.

## Langkah 5 — Cek hasil

```bash
gcloud projects get-iam-policy ptpl-land-dev --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:$SA" --format="table(bindings.role)"
bq get-iam-policy ptpl-curated-prd:DATAMART.VM_PLANOGRAM | grep -B2 -A2 "$SA"
```

Hasil yang diharapkan: kelima role di langkah 4 tercantum, dan `roles/bigquery.dataViewer` muncul untuk SA di
`VM_PLANOGRAM`. Izin berlaku dalam 2–3 menit.

## Langkah 6 — Akses Gemini 4 Argon (hanya jika langkah 2 PANDUAN_REDEPLOY gagal untuk Argon)

Jika `scripts/check_models.py` menampilkan `GAGAL gemini-4-argon @ asia-southeast1` dengan 403/404:
- **403 / permission**: pastikan akun yang menjalankan cek punya `roles/aiplatform.user` di `ptpl-land-dev`.
- **404 / not found**: model belum diaktifkan untuk project ini di region tersebut. Buka Konsol → **Vertex AI** →
  **Model Garden** → cari *Gemini 4 Argon* → **Enable** untuk project `ptpl-land-dev`, lalu ulangi cek. Jika model
  hanya tersedia di region lain, kabari Jason nama region-nya.
