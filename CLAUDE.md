# Marketing Insight Assistant — ADK agent untuk PT Pertamina Lubricants (PTPL)

Vendor: tim mii.co.id (Jason Kusuma). Klien: tim MIR PTPL (user NON-IT). Bahasa ke user & dokumen: **Indonesia**.
Agent ADK di Agent Engine, dipakai lewat **Gemini Enterprise (GE)**. Versi terakhir: **v3.5.3** (250 uji).
Detail lengkap: `README.md` (fitur per versi), `PANDUAN_DEPLOY_V3.5.md` (deploy), `PANDUAN_SELLOUT.md`,
`PANDUAN_CLAUDE_DAN_SKILL.md`. Pengetahuan non-kode di `docs/knowledge/`: `keputusan.md` (keputusan + alasan per
versi), `insiden.md` (riwayat error & log), `biaya_sizing.md` (sizing & tarif), `klien.md` (konteks & ekspektasi
klien). Baca hanya bila tugasnya butuh; perbarui file terkait saat ada keputusan/insiden baru.
**Kelanjutan sesi chat sebelumnya**: riwayat percakapan lengkap ada di `riwayat-chat/` (lokal, TIDAK di-commit).
Mulai dari `riwayat-chat/03_sesi_2026-11-11_v3.0-v3.5.2.md` (kronologi terakhir + pekerjaan terbuka). Transkrip
lengkap 01/02 (±4 MB) jangan dibaca seluruhnya — cari dengan grep kata kunci bila butuh detail lama.

## Infrastruktur (tetap)
- Project `ptpl-land-dev` (no. 37078813825). Agent Engine: `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768`
- SA agent: `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (mode data `service_account`)
- Bucket `gs://ptpl-ge-bucket`, folder `ge-docs-agent/` (settings `config/settings.json`, meteran `usage/`,
  pengetahuan tambahan `config/knowledge/<domain>.md`, laporan `reports/`)
- Repo GitHub `TooGreat430/agent-bei-csls`; edit di VS Code laptop (Claude Code) → commit & push → di Cloud Shell
  `~/agent-bei-csls` (`.venv`): `git pull` lalu deploy. Perintah yang butuh GCP (log, check_*, deploy) di Cloud Shell.
- Data Agent (global): Retail `agent_4df3074b-…`, Industri `agent_04f517f4-…`, Planogram `agent_5f69a707-…`,
  Sell-out `agent_e188b55c-e61b-4c3f-9f91-3c97a54a6d4a` (tabel `ptpl-curated-prd.DATAMART.SALES_OUT_DAILY`,
  `pertamina-lubricants-project.STAGING.{AC_PARAMETER,TARGET_AO_SO_INDUSTRY,TARGET_AO_SO_RETAIL}`)
- Model: router & tanya-jawab data = Gemini Flash (`gemini-3.5-flash` @ global); **tugas berat** (analisis file,
  skill, laporan) = **Claude `claude-opus-5-5` @ `global`** (Vertex AI) dengan cadangan **Gemini 4 Argon**.
  Claude hanya tersedia di lokasi global/us/eu. Saklar tanpa deploy: `python scripts/set_model.py claude|gemini`.
- Code Execution (sandbox) aktif hanya untuk `jason.kusuma@mii.co.id`, `mirptpl@gmail.com`.

## Peta kode (`library_agent/`)
- `agent.py` root router → `subagents/data.py` (Flash, Data Agent BQ + insight + laporan),
  `subagents/files.py` (Claude, file unggahan, sandbox, skill), `subagents/report.py` (Claude, laporan)
- `prompts.py` semua instruksi agent (+ `model_note()` komposisi model aktif) · `callbacks.py` lampiran GE,
  `sanitize_request`, lampiran gambar ke model, `verify_numbers` (pemeriksa angka), `fallback_reply`/`compose_fallback`
- `llm.py` (PinnedGemini, cadangan 429) · `llm_claude.py` (ClaudeVertex: konversi ADK↔Anthropic, cadangan Argon,
  `create_sync/async` tahan beda versi SDK) · `report_engine.py` (`_claude_first`, `_with_fallback`)
- `data_agent.py` (DOMAINS retail/industri/planogram/sellout) · `knowledge.py` (serap definisi Data Agent,
  `table_refs`, `extra_knowledge`) · `data_engine.py` (CSV/Excel, pivot, per liter, `run_plan`)
- `insight_charts.py` (18 chart katalog Strategist Toolkit + fakta dihitung kode + `recommend`) ·
  `strategy_diagrams.py` (diagram kerangka; nilai harapan & skor berbobot dihitung kode) · `vision.py` (gambar)
- `tools/`: `data_tools`, `file_tools`, `report_tools`, `export_tools`, `code_tools` (sandbox + `muat_skill`),
  `doc_tools` (`lihat_gambar`), `chart_insight_tools` (`daftar_data`, `buat_insight`, `korelasi_data`),
  `strategy_tools` (`panduan_kerangka`, `buat_diagram`)
- `skills/*.md` (excel, powerpoint, word, edit_file, pdf, analisis_data, strategist = 68 kerangka pptx)
- `custom_report.py` + `report_assets/custom_prompts/*.txt` (prompt MIR per domain) · `ptpl_design.py`, `html_convert.py`
- `usage.py` meteran & batas biaya · `config.py` (`live()` = settings.json, cache 5 menit)

## Aturan bisnis & keputusan (JANGAN dilanggar)
- **Angka bisnis dihitung kode / berasal dari hasil tool, bukan model.** Pemeriksa angka aktif di chat & laporan.
  Pembulatan wajar ke ratusan/ribuan diterima. Jangan menyebut "80% akurat" ke klien.
- Laporan: HTML/PDF/PPTX (atau DOCX lewat skill), template PTPL; **tidak pernah TXT/MD**. Tawarkan laporan (ya/tidak)
  setelah analisis; tanyakan format bila belum disebut. Laporan custom: DRAFT → approve → konversi.
- Gabungan/korelasi data: **hanya sumber yang sama atau Retail × Planogram**. Sell-out & Industri berdiri sendiri.
- Insight otomatis tiap tarikan/analisis: **minimal 3 chart** (dijamin kode), headline = kesimpulan, sorotan dari
  `fakta`, takeaway, link. Jawaban gaya Minto/SCQA. Kerangka Strategist dipilih sesuai jenis pertanyaan
  ("kenapa" → driver tree + 5 Whys; "apa yang dilakukan" → evaluation/decision tree + Eisenhower; dst.).
  Hipotesis/asumsi wajib ditandai. Bull/bear hanya bila diminta.
- Retail: gap harga negatif = PTPL lebih murah (baik); bandingkan harga **per liter**. Industri: gap % positif = kompetitif.
- Gambar referensi: tiru bentuk, **jangan salin angka dari gambar**.
- User non-IT → hasil berupa file siap pakai, bukan kode. `save_data_insight` hanya bila user meminta.

## Batasan platform yang sudah diketahui
- GE **tidak menampilkan gambar** dari agent ADK (muncul `asc_slot://`) → chart dikirim sebagai link
  (`chat_inline_chart` = false). GE mengirim lampiran sebagai penanda teks + artifact, bukan inline.
- Argon sering 429 (kuota TPM) → cadangan global; Data Agent umumnya mengembalikan tabel agregat (≤300 baris disimpan).
- Flash lemah untuk insight/kerangka di jalur BigQuery (opsi tertunda: alihkan pertanyaan analisis dalam ke Claude).

## Alur kerja pengembangan
- Uji (tanpa GCP, stub di `tests/_stubs.py`): `python -m unittest discover tests` — **semua harus lulus**;
  tambahkan uji untuk setiap perubahan perilaku.
- Uji sungguhan Claude: `python scripts/check_claude.py`; pengetahuan Data Agent: `python scripts/check_knowledge.py`.
- Deploy: `find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh` (sekali, jangan Ctrl+C).
  Opsi: `NEW_GEMINI_LOCATION_PRO=global`, `NEW_MODEL_CLAUDE=…`, `NEW_CLAUDE_REGION=…`.
- Operasi tanpa deploy: `scripts/usage_report.py`, `set_budget.py`, `code_execution_switch.py`, `set_model.py`,
  `set_knowledge.py upload <domain> file.md`.
- Log: `gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND
  resource.labels.reasoning_engine_id="5516874359156768768"' --project=ptpl-land-dev --freshness=1d --limit=50`.
- Rollback: tag git `cadangan-v*` + `settings.cadangan-*.json` di bucket (lihat panduan deploy).
- Jangan ubah `settings.json` di bucket atau IAM tanpa konfirmasi user. Jangan commit kredensial.

## Preferensi user
- Panduan langkah demi langkah: **tanyakan semua info yang dibutuhkan di awal**, lalu beri langkah lengkap berurutan.
- Jawaban ringkas, Bahasa Indonesia, jujur soal keterbatasan; sertakan cara verifikasi (perintah/log).

## Status & pekerjaan terbuka
- v3.5.3 siap deploy (perbaikan akar jawaban kosong setelah Periksa Angka: signature + error model → fallback).
  v3.5.2: pemeriksa angka terima pembulatan, insight ≥3 chart.
- Konfirmasi: angka laporan custom 97.389/37.742/85.513 (log 11 Nov 15:08) diduga disalin dari gambar referensi.
- Opsi ditawarkan: jalur campuran (pertanyaan "kenapa/apa yang dilakukan" di jalur BQ → Claude).
- Checklist uji: `Checklist_Uji_Chart_Kerangka_v3.4.xlsx` (37 uji). Kuota Argon/Claude perlu dipantau.
