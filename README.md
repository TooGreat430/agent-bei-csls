# Marketing Insight Assistant — PT Pertamina Lubricants

Agent ADK di Vertex AI Agent Engine (Jakarta, `asia-southeast2`), terdaftar di Gemini Enterprise sebagai
**Marketing Insight Assistant**. Satu chat, tiga kemampuan yang berdiri sendiri:

| Kemampuan | Isi |
|---|---|
| **Data BigQuery** | Tanya-jawab lewat tiga Data Agent resmi tim data: **Retail**, **Industry**, dan **Planogram Marketing Intelligence**. Angka persis dari Data Agent, tabel + grafik, simpan sebagai insight |
| **Analisis silang Retail × Planogram** | Harga jual, margin outlet, carry, dan skor AV digabung per KIMAP → status Pemenang Kompetitif / Gap Eksekusi / Gap Ekonomi / Gap Harga / Double Jeopardy, white space, ancaman kompetitor. Hanya kombinasi ini; Industri tidak bisa digabung |
| **File unggahan (semua format)** | **CSV/Excel**: jenis dikenali (retail / industri / planogram / lainnya), **pengetahuan resmi Data Agent** diserap, angka dihitung pandas. **Dokumen** (PDF, Word, PowerPoint, teks, Markdown, HTML, gambar): isi dicerna, diringkas, jenisnya dikenali (laporan, prompt/metodologi, template), lalu agent mengusulkan langkah berikutnya |
| **Laporan** | **Template**: Daya Saing Harga Retail, Daya Saing Harga Industri (B2B), **Kinerja Planogram PTPL vs Kompetitor**, **Competitive Battlefield (Retail × Planogram)** — PDF/PowerPoint/HTML. **Custom**: disusun Gemini 4 Argon dengan prompt laporan MIR (Retail Only / Industry Only / Planogram / Retail × Planogram), bisa mengikuti dokumen prompt/template unggahan, HTML gaya design system PTPL, DRAFT → revisi → approve FINAL |

Perpustakaan dokumen BEI/CSLS (data store, folder `ge-docs-datastore`, tanya-jawab dokumen) **sudah dihapus**
dari agent ini. Data store dan isi folder di GCP tidak disentuh, hanya tidak dipakai lagi.

## Arsitektur

```
Gemini Enterprise ──► marketing_insight_assistant (router, model cepat)
                        ├─ data_agent    (model cepat) ─► Data Agent Retail / Industry / Planogram (Conversational Analytics API)
                        │                                  + analisis silang Retail × Planogram (battlefield_data)
                        ├─ file_agent    (Gemini 4 Argon) ─► dokumen: ekstraksi teks (documents) · data: pandas + knowledge
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
  callbacks.py                  tangkap lampiran semua format, bersihkan request ke model, jawaban tidak kosong, cek angka
  documents.py                  kenali jenis file & ekstrak teks dokumen (PDF, DOCX, PPTX, TXT/MD, HTML)
  data_agent.py, knowledge.py   Data Agent (3 domain) & penyerapan pengetahuannya
  data_engine.py                analisis file (retail/industri/planogram/umum) + preset
  planogram_data.py             ND, AV, whitespace, KIMAP (dipakai template & preset analisis file)
  planogram_report.py           template Kinerja Planogram (6 halaman)
  battlefield_data.py           analisis silang Retail × Planogram per KIMAP (template, chat, laporan custom)
  battlefield_report.py         template Competitive Battlefield (6 halaman)
  custom_report.py              laporan custom: prompt MIR, Argon, pemeriksa angka, approve
  ptpl_design.py                renderer design system PTPL (HTML/PDF/PPTX)
  report_assets/
    ptpl_design_system.html     DESIGN SYSTEM PTPL (CSS + JS grafik) — satu sumber untuk semua laporan bergaya MIR
    custom_prompts/             retail.txt, industri.txt, planogram.txt, retail_planogram.txt — prompt laporan MIR
  price_*.py, dashboard_render.py, industry_*.py   template retail & industri (tidak berubah)
scripts/   update_agent.sh (redeploy di tempat), deploy_agent_engine.py, check_knowledge.py, enable_user_auth.py
setup/settings.json              nilai awal pengaturan tanpa deploy
tests/                           146 uji unit (tanpa GCP)
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

## Template Competitive Battlefield (Retail × Planogram)

Disarikan dari laporan MIR "PTPL Competitive Battlefield Q3 2026 V7" (24 halaman) menjadi 6 halaman. Bagian yang
membutuhkan data di luar BigQuery (KLine CAGR, sellout mix, matriks portofolio) tidak dipakai.

| Hal | Isi |
|---|---|
| 01 Ringkasan | KPI jumlah status head-to-head · status per segmen (stack) · temuan utama |
| 02 Kategori | Exposure semua brand per Segmen × Usage × Viskositas · leader / 2nd · white space |
| 03 Head-to-head | Matriks keunggulan harga × gap AV · tabel cek Harga / Ekonomi / Rak + status + SR lemah |
| 04 Momentum | Kompetitor dengan pertambahan outlet terbesar (TRUE / DISTRIBUTION THREAT) · white space |
| 05 Sales Region | KIMAP double weakness per SR × segmen · ancaman utama per SR |
| 06 Action matrix | Diagnosis → sinyal → owner → aksi → metrik sukses · rekomendasi |

Aturan hitung (`battlefield_data.py`):
- Kunci gabung KIMAP (retail) = PAIR_KIMAP (planogram). Head-to-head = brand kompetitor dengan carry terbesar di KIMAP.
- Harga: HJ/L dari `SURVEY_PRODUCTS` (filter AVAILABILITY 1, outlier DATA USE, kemasan valid). Pembanding = brand
  head-to-head bila sampel ≥ `battlefield_min_price_n` (default 10), selain itu rata-rata kompetitor di KIMAP.
- ✓ Harga: PTPL lebih murah · ✓ Ekonomi: margin/L PTPL ≥ kompetitor · ✓ Rak: rasio carry ≥ 70% dan gap AV ≥ 0.
- Status: Pemenang Kompetitif · Gap Eksekusi · Gap Ekonomi · Gap Ekonomi + Eksekusi · Gap Harga · Double Jeopardy.
- Momentum kompetitor: TRUE THREAT (outlet ↑ & AV ↑), DISTRIBUTION THREAT (outlet ↑), CONVERSION WINDOW (outlet ↓ & AV ↓).
- Double weakness per SR: rasio carry < 70% DAN AV di bawah kompetitor utama di SR itu.

Sumber: BigQuery (default) atau dua file unggahan (`retail_file_id` + `planogram_file_id`).

## File unggahan

- **Semua format diterima.** CSV/Excel masuk analisis data. Format lain disimpan di `ge-docs-agent/doc-files/<chat>/`
  beserta teks hasil ekstraksinya (`documents.py`).
- Bentuk lampiran yang ditangani: `inline_data`, `file_data` (gs:// atau https://), dan artifact ADK
  (`[Uploaded Artifact: …]`). Jenis file dikenali juga dari isinya, jadi Excel tanpa nama/tipe tetap terbaca.
- **Request ke model dibersihkan** (`sanitize_request`): Gemini menolak Excel/Word/PowerPoint mentah, jadi setiap lampiran
  diganti teks — file data menjadi rujukan `f1`, dokumen yang baru diunggah menjadi isi teksnya (maks. 30.000 karakter,
  sisanya lewat `read_document`), dokumen lama menjadi rujukan `d1`. Gambar dan PDF scan pada giliran unggah dikirim
  apa adanya karena Gemini bisa membacanya.
- Dokumen bisa dipakai sebagai prompt/template laporan custom (`instruction_doc_id`). Angka laporan tetap hanya dari
  BigQuery atau file data.
- Belum didukung: `.doc`/`.ppt` lama (minta simpan ulang sebagai DOCX/PPTX/PDF), skor kuantil khusus (mis. RFM).

## Laporan custom

1. Data ditarik dulu: dari Data Agent (1–3 pertanyaan yang disusun agent dari permintaan user), dari kedua Data Agent
   + analisis silang hitungan kode (sumber `retail_planogram`), atau dari file (analisis standar + hasil analisis &
   insight di chat). Dokumen unggahan dapat ditambahkan sebagai instruksi (`instruction_doc_id`).
2. Prompt `report_assets/custom_prompts/<domain>.txt` diisi permintaan user + data. Bagian **FORMAT OUTPUT** diganti
   saat dijalankan: model menulis **hanya isi halaman**, lalu kode membungkusnya dengan `ptpl_design_system.html`.
   Hasilnya: CSS/JS grafik tidak pernah rusak dan token keluaran Argon jauh lebih hemat.
3. Pemeriksa angka mencocokkan angka di teks dan grafik dengan data sumber. Jika ada yang tidak cocok, Argon menulis
   ulang sekali; jika masih ada, laporan diberi catatan pemeriksa di halaman terakhir.
4. Status **DRAFT** → user mengetik *approve* → terbit versi **FINAL** (label "FINAL · Disetujui <user> · <tanggal>").
   Masukan revisi → ditulis ulang dengan data yang sama.

Mengubah prompt custom: edit file di `report_assets/custom_prompts/`, lalu redeploy. Bagian FORMAT OUTPUT di file
boleh dibiarkan (selalu diganti otomatis).

## Analisis berbasis kode (Agent Engine Code Execution) — MATI secara default

Untuk analisis file yang bebas (metodologi dari user seperti prompt RFM, perhitungan khusus, file output sesuai
permintaan), agent analisis file bisa menulis dan menjalankan Python di **sandbox terisolasi** Agent Engine Code
Execution: tanpa internet, tanpa kredensial, hanya melihat file data chat (Excel dikonversi ke CSV per sheet).
Sandbox dibuat di bawah resource agent ini sendiri (region sama, `asia-southeast2`), satu per chat, TTL 30 menit.

| Pengaman | Pengaturan (`settings.json`) |
|---|---|
| Saklar fitur | `code_execution_enabled` (default `false`) |
| Hanya user tertentu | `code_execution_users` (daftar ID user GE; kosong = semua user bila fitur menyala) |
| Batas langkah per pesan | `code_execution_max_steps` (default 25), lalu agent melapor & bertanya |
| **Batas biaya harian** | `code_execution_daily_budget_usd` (default 5) — dari meteran; tercapai → eksekusi berhenti sampai besok |
| Umur sandbox | `code_execution_ttl_seconds` (default 1800) |
| Tarif meteran | `price_*` (USD per 1 juta token / per jam) — sesuaikan dengan harga resmi |

**Meteran biaya** (`usage.py`) mencatat setiap panggilan model (token input/cache/output/thinking) dan setiap eksekusi
sandbox, per hari & per user, di `ge-docs-agent/usage/YYYY-MM-DD.json`. Lihat dengan `python scripts/usage_report.py`.
Angkanya estimasi; tagihan resmi tetap di Cloud Billing.

Uji end-to-end sandbox: `python scripts/check_code_execution.py`. Panduan uji coba: `PANDUAN_UJI_COBA_CODE_EXECUTION.md`.

## Ekspor Excel hasil analisis file (tanpa Code Execution)

Setiap `analyze_data` di chat dicatat (`file_analyses`, dengan `analisis_id`). Tool `ekspor_excel` menjalankan ulang
rencana analisis itu dengan kode baku yang sama **tanpa batas baris tampilan** (mis. 5.918 outlet SR1, bukan Top 50),
lalu menulis satu workbook multi-sheet: sheet *Keterangan* (isi tiap sheet, sumber file, jumlah baris, baris yang
dikecualikan aturan data) + satu sheet per analisis (header berwarna, baris judul dibekukan, filter, lebar kolom
otomatis). File disimpan di folder laporan dan dibagikan sebagai link. Agent dilarang menyuruh user menjalankan
Python/script sendiri.

## Ketahanan kapasitas model (429 RESOURCE_EXHAUSTED)

Jika endpoint model utama penuh (429/503), panggilan yang sama otomatis dicoba ke daftar cadangan `model_fallbacks`
(default `pro@global`, lalu `fast@global`; "pro"/"fast" = `LIB_MODEL_PRO`/`LIB_MODEL_FAST`). Jika semuanya penuh, agent
membalas "layanan model sedang padat, kirim ulang dalam 1–2 menit" — bukan error 400 yang membuat chat macet.
Endpoint `global` dapat memproses di region mana pun; kosongkan `model_fallbacks` bila PTPL mensyaratkan region tetap.
Log: `Kapasitas model penuh …` / `Memakai model cadangan …`.

Tracing (Cloud Trace) dimatikan secara default (`LIB_ENABLE_TRACING=false`) karena service account belum punya role
Cloud Trace Agent (log `Failed to export span … 403`). Untuk menyalakan: beri role `roles/cloudtrace.agent` ke service
account di `ptpl-land-dev`, set `LIB_ENABLE_TRACING=true` di `.env`, lalu redeploy.

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
| `battlefield_min_price_n` | Sampel harga minimum per sisi untuk perbandingan harga Retail × Planogram (default 10) |
| `hero_products`, `status_aman_below`, `status_kritis_above` | Dashboard retail |
| `industry_htd_column`, `industry_focus_products`, `industry_competitors`, `industry_segment_column`, `industry_segments` | Laporan industri |
| `model_fallbacks` | Cadangan saat kapasitas model penuh, format `model@lokasi` (default `pro@global`, `fast@global`) |
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
python -m unittest discover tests      # 146 uji, tanpa GCP
```

## Log diagnostik (unggahan file & error)

Setiap pesan mencatat bentuk lampirannya (`user_content parts`) dan setiap error di Cloud Logging:

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"
  AND resource.labels.reasoning_engine_id="5516874359156768768"
  AND (severity>=ERROR OR textPayload:"user_content parts" OR jsonPayload.message:"user_content parts")' \
  --project=ptpl-land-dev --freshness=2d --limit=40 \
  --format="value(timestamp,severity,textPayload,jsonPayload.message)"
```

`user_content parts` menunjukkan apakah lampiran datang sebagai `inline_data`, `file_data` (beserta URI-nya), atau
teks `[Uploaded Artifact: …]`. Ketiganya ditangani; jika muncul bentuk lain, kirim baris log tersebut ke tim teknis.
