# Sizing & biaya (asumsi — perlu dikonfirmasi dengan PTPL)

Asumsi sizing: 1 akun dipakai 5 orang; 2 sesi/hari; 8 pertanyaan/sesi; 22 hari kerja = 1.760 pertanyaan/bulan
(704 dokumen, 704 data); laporan 50/bulan (pernah 352 — belum dikonfirmasi). Kurs Rp18.500.

Total ADK (Opsi B full-code, Argon untuk laporan, sebelum Claude): **USD 248,24/bulan ≈ Rp4.592.511**.
Rincian: agent induk (Flash) 27,72; agent dokumen 38,02; agent data 59,14; laporan Argon (template) 14,70;
Data Agents (Conversational Analytics) 89,76 (gratis trial s.d. 31 Des 2026); BigQuery 9,20; Agent Engine runtime 2,98;
Sessions 0,03; Cloud Storage 0,17; Logging 0; GCP Support 4% ±9,55.
Opsi A (low-code Agent Designer GE): +USD 9–11/bulan di luar lisensi; lisensi GE USD 35/seat (Standard) di kedua opsi.

Tarif yang dipakai: Argon USD 2/10 per 1M token (promo s.d. 30 Nov 2026), USD 4/20 mulai 1 Des 2026;
Claude Opus 5.5 USD 4/20 (setara Argon standar; cache baca ±0,4); Flash (sizing) USD 1,50/7,50.
Code Execution (sumber sekunder, cek harga resmi): USD 0,0864/vCPU-jam, 0,0090/GiB-jam; asumsi 110 analisis
berbasis kode/bulan → +USD 87–116 (Argon) atau 34–62 (Flash). Total dengan Code Execution: USD 335–364 (Argon).
Catatan: biaya terbesar = token model, bukan sandbox. Insight otomatis & kerangka Strategist (v3.3+) menaikkan token
per pertanyaan — pantau `scripts/usage_report.py` (per model: claude-opus-5-5 vs gemini).
