# Marketing Insight Assistant — PT Pertamina Lubricants

Agent ADK di Vertex AI Agent Engine (Jakarta, `asia-southeast2`), terdaftar di Gemini Enterprise sebagai
**Marketing Insight Assistant**. Satu chat, tiga kemampuan yang berdiri sendiri:

| Kemampuan | Isi |
|---|---|
| **Data BigQuery** | Tanya-jawab lewat tiga Data Agent resmi tim data: **Retail**, **Industry**, dan **Planogram Marketing Intelligence**. Angka persis dari Data Agent, tabel + grafik, simpan sebagai insight |
| **Analisis file CSV/Excel** | Hanya CSV/Excel yang diterima. Langkah pertama: jenis file dikenali (retail / industri / planogram / lainnya) dan **pengetahuan resmi Data Agent** domain itu diserap (instruksi, glossary, contoh query). Angka dihitung pandas, bukan model |
| **Laporan** | **Template**: Daya Saing Harga Retail, Daya Saing Harga Industri (B2B), **Kinerja Planogram PTPL vs Kompetitor** — PDF/PowerPoint/HTML. **Custom**: disusun Gemini 4 Argon dengan prompt laporan MIR (Retail Only / Industry Only / Planogram), HTML gaya design system PTPL, DRAFT → revisi → approve FINAL |

Perpustakaan dokumen BEI/CSLS (data store, folder `ge-docs-datastore`, tanya-jawab dokumen) **sudah dihapus**
dari agent ini. Data store dan isi folder di GCP tidak disentuh, hanya tidak dipakai lagi.

## Arsitektur

```
Gemini Enterprise ──► marketing_insight_assistant (router, model cepat)
                        ├─ data_agent    (model cepat) ─► Data Agent Retail / Industry / Planogram (Conversational Analytics API)
                        ├─ file_agent    (Gemini 4 Argon) ─► pandas (data_engine) + pengetahuan Data Agent (knowledge)
                        └─ report_agent  (Gemini 4 Argon)
                              ├─ TEMPLATE ─► query BigQuery langsung / file ─► angka dihitung kode ─► PDF/PPTX/HTML
                              └─ CUSTOM   ─► tarik data dari Data Agent / file ─► prompt MIR + Argon ─► design system PTPL
                                             ─► pemeriksa angka ─► DRAFT ─► approve ─► FINAL
```

| Model | Dipakai untuk | Pengaturan |
|---|---|---|
| `gemini-3.5-flash` (`global`) | router, tanya-jawab data BigQuery | `LIB_MODEL_FAST`, `LIB_GEMINI_LOCATION` |
| `gemini-4-argon` (`asia-southeast1`) | analisis file, laporan custom, narasi laporan template | `LIB_MODEL_PRO`, `LIB_GEMINI_LOCATION_PRO` |

## Struktur folder

```
library_agent/
  agent.py, subagents/          root agent + data_agent, file_agent, report_agent
  prompts.py                    instruksi agent (ubah perilaku di sini)
  callbacks.py                  tangkap CSV/Excel (tolak file lain), jawaban tidak kosong, pemeriksa angka chat
  data_agent.py, knowledge.py   Data Agent (3 domain) & penyerapan pengetahuannya
  data_engine.py                analisis file (retail/industri/planogram/umum) + preset
  planogram_data.py             ND, AV, whitespace, KIMAP (dipakai template & preset analisis file)
  planogram_report.py           template Kinerja Planogram (6 halaman)
  custom_report.py              laporan custom: prompt MIR, Argon, pemeriksa angka, approve
  ptpl_design.py                renderer design system PTPL (HTML/PDF/PPTX)
  report_assets/
    ptpl_design_system.html     DESIGN SYSTEM PTPL (CSS + JS grafik) — satu sumber untuk semua laporan bergaya MIR
    custom_prompts/             retail.txt, industri.txt, planogram.txt — prompt laporan MIR (boleh diedit)
  price_*.py, dashboard_render.py, industry_*.py   template retail & industri (tidak berubah)
scripts/   update_agent.sh (redeploy di tempat), deploy_agent_engine.py, check_knowledge.py, enable_user_auth.py
setup/settings.json              nilai awal pengaturan tanpa deploy
tests/                           100 uji unit (tanpa GCP)
```

## Template planogram

Kuartal berjalan vs kuartal sebelumnya (default **Q3 2026 vs Q2 2026**, ubah lewat `planogram_default_period`).
Audiens: Management (C-level), Brand Owner, Sales Regional Manager.

| Hal | Isi |
|---|---|
| 01 Ringkasan | KPI carry PTPL, ND PTPL, gap AV, whitespace · ND per segmen (dumbbell) · temuan utama |
| 02 Sebaran outlet | Carry PTPL vs leader kompetitor per SR · ND per SR Q2→Q3 · tabel SR dengan momentum |
| 03 Viskositas | Perubahan ND terbesar · tabel 12 viskositas dengan carry terbesar |
| 04 Availability & visibility | KPI A/V · matriks KIMAP (rasio carry PTPL/leader × gap AV; DEFEND/EXPAND/FIX AV/FIX & EXPAND) · gap AV per SR |
| 05 Whitespace | Outlet whitespace per SR · komposisi per segmen · 10 KIMAP whitespace terbesar |
| 06 Rekomendasi | Temuan · Implikasi · Aksi · Owner · prioritas Sales Region |

Aturan hitung (sama dengan preset analisis file `planogram_nd`, `planogram_av`, `planogram_whitespace`):
- Sumber `ptpl-curated-prd.DATAMART.VM_PLANOGRAM`, periode dari `DT_PR`. Tidak memakai MIR_MASTERDATA.
- Carry = outlet unik (exposure, bukan market share). ND = carry / total carry semua brand di segmen + usage + viskositas yang sama.
- Satu outlet satu suara: baris berulang dirata-rata per kuartal × outlet × brand × series × viskositas × KIMAP.
- Head-to-head (AV, rasio carry, whitespace) hanya dalam `PAIR_KIMAP` yang sama; baris tanpa KIMAP tetap masuk sebaran & ND.
- Whitespace = outlet yang men-carry kompetitor di suatu KIMAP tetapi tidak men-carry PTPL di KIMAP itu.
- Momentum ND ±2 pp, gap AV ±0,10; carry total < 30 = sampel kecil. 2T dinormalisasi; NO VISCOSITY di PCO/Commercial dibuang.
- Narasi dari Argon dicek: kalimat dengan angka di luar data dibuang; jika gagal, dipakai narasi berbasis aturan.

## Laporan custom

1. Data ditarik dulu: dari Data Agent (1–3 pertanyaan yang disusun agent dari permintaan user) atau dari file
   (analisis standar per jenis file + hasil analisis & insight di chat).
2. Prompt `report_assets/custom_prompts/<domain>.txt` diisi permintaan user + data. Bagian **FORMAT OUTPUT** diganti
   saat dijalankan: model menulis **hanya isi halaman**, lalu kode membungkusnya dengan `ptpl_design_system.html`.
   Hasilnya: CSS/JS grafik tidak pernah rusak dan token keluaran Argon jauh lebih hemat.
3. Pemeriksa angka mencocokkan angka di teks dan grafik dengan data sumber. Jika ada yang tidak cocok, Argon menulis
   ulang sekali; jika masih ada, laporan diberi catatan pemeriksa di halaman terakhir.
4. Status **DRAFT** → user mengetik *approve* → terbit versi **FINAL** (label "FINAL · Disetujui <user> · <tanggal>").
   Masukan revisi → ditulis ulang dengan data yang sama.

Mengubah prompt custom: edit file di `report_assets/custom_prompts/`, lalu redeploy. Bagian FORMAT OUTPUT di file
boleh dibiarkan (selalu diganti otomatis).

## Pengaturan tanpa deploy

`gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json` — edit lewat Konsol (Download → edit → Upload, timpa).
Berlaku maks. 5 menit kemudian. `update_agent.sh` menambahkan kunci baru tanpa menimpa nilai yang sudah Anda ubah.

| Pengaturan | Fungsi |
|---|---|
| `agent_name`, `company_name` | Nama agent & perusahaan |
| `data_agent`, `data_agent_industry`, `data_agent_planogram` | ID Data Agent retail / industri / planogram |
| `price_table`, `industry_table`, `planogram_table` | Tabel BigQuery untuk laporan template |
| `planogram_default_period` | Kuartal default template planogram (mis. `2026-Q3`; pembanding = kuartal sebelumnya) |
| `planogram_carry_ratio_line` | Garis kuadran rasio carry PTPL/leader (default 70) |
| `planogram_min_carry` | Batas "sampel kecil" (default 30) |
| `hero_products`, `status_aman_below`, `status_kritis_above` | Dashboard retail |
| `industry_htd_column`, `industry_focus_products`, `industry_competitors`, `industry_segment_column`, `industry_segments` | Laporan industri |
| `data_auth_mode`, `data_auth_id` | `service_account` (dipakai) atau `user` (OAuth, lihat `PANDUAN_OAUTH_BIGQUERY.md`) |
| `max_file_mb` | Batas ukuran file CSV/Excel |

## Panduan

| File | Isi |
|---|---|
| `PANDUAN_REDEPLOY.md` | Redeploy di tempat versi ini, langkah demi langkah, termasuk update deskripsi di GE dan uji |
| `PANDUAN_IAM.md` | Izin yang perlu diberikan admin project untuk planogram dan Gemini 4 Argon |
| `PANDUAN_OAUTH_BIGQUERY.md` | Opsional: data BigQuery atas nama user |

## Uji lokal

```bash
python -m unittest discover tests      # 100 uji, tanpa GCP
```
