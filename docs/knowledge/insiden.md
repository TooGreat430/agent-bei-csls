# Insiden & temuan log (untuk diagnosis berikutnya)

| Tanggal (UTC) | Gejala | Penyebab | Status |
|---|---|---|---|
| 3 Nov | 429 "TPM quota exhausted… contact sales" | Kuota token/menit Argon | Cadangan global (v2.3/v2.10); ajukan kenaikan kuota |
| 4–5 Nov | Laporan custom/grafik gagal | `'Settings' object has no attribute 'report_prefix'` (v2) | Diperbaiki v2.1 |
| 6 Nov 02:25 | Error 400 FAILED_PRECONDITION setelah unggah Excel SR1 | Lampiran mentah dikirim ke model; GE mengubah Excel ke CSV `…xlsx_Sheet1_Sheet1.csv` | `sanitize_request` (v2.1) |
| 7 Nov 05:49 | Laporan HTML per segmen gagal 2× 429 → user minta TXT | Kapasitas Argon | Coba ulang + global (v2.10); tidak pernah TXT |
| — | `Failed to export span batch code: 403` | SA tanpa Cloud Trace Agent | Tracing dimatikan (v2.3) |
| 10 Nov | `check_claude`: `Messages.create() got an unexpected keyword argument 'temperature'` | Versi SDK Anthropic | `create_sync/async` (v3.0.1) |
| 10 Nov | 404 publisher model claude-opus-5-5 | Model belum di-enable di Model Garden | User enable; Claude hanya global/us/eu |
| 11 Nov | Agent menjawab "Anda memakai Gemini, bukan Claude" | Router (Flash) menjawab dari dirinya sendiri | `model_note()` di semua instruksi |
| 11 Nov | "Ini cuman satu chart" + label berulang, nilai −38.056 hilang | Flash memilih 1 chart; data produk × SR; batas 20 baris | v3.5 (≥3 chart, agregasi, pencilan) |
| 11 Nov | Tidak ada jawaban akhir setelah `Periksa Angka` | Model berhenti setelah diminta revisi; fallback terblokir kalimat pembuka | v3.5.1 |
| 12 Nov | Lagi: langkah Ask Retail → Daftar Data → Buat Insight → Periksa Angka selesai, tanpa jawaban ("Bandingkan harga jual per liter PCO 10W-40 …") | Panggilan sintetis `periksa_angka` tanpa `thought_signature` → 400 Gemini 3.x → exception, `ensure_reply` tak jalan (diagnosis v3.5.1 belum menyentuh ini) | v3.5.3 — **terkonfirmasi log**: `400 INVALID_ARGUMENT … missing a thought_signature … default_api:periksa_angka` (juga 11 Nov 15:11 "Rp 91.000"). Kemungkinan besar insiden v3.5.1 penyebabnya sama |
| 11 Nov 15:11–15:13 | Angka ditolak: "Rp 91.000", "Rp 6.000/L"; 03:38 "27.018" | Pembulatan/hitungan model | v3.5.2 terima pembulatan wajar |
| 11 Nov 15:08–15:16 | Laporan custom: 12–20 angka ditolak (97.389, 37.742, 85.513, 84,7%…) | Diduga disalin dari gambar referensi | v3.5.2 (larangan + log jumlah gambar) — **menunggu konfirmasi user** |

Izin terverifikasi (11 Nov): SA punya `geminidataanalytics.dataAgentUser/StatelessUser/Viewer` di level project
`ptpl-land-dev`; Data Viewer di 4 tabel Sell-out (level tabel); `bigquery.jobUser`; `aiplatform.editor`.
