# Log keputusan & alasannya (dari diskusi dengan tim vendor, s.d. v3.5.2)

| Versi | Keputusan | Alasan |
|---|---|---|
| v2.1 | Perbaiki `report_prefix`, unggah Excel via artifact, pemeriksa angka | Laporan custom & grafik gagal tersimpan (log 4–5 Nov); angka model harus dicek |
| v2.2 | Code Execution (sandbox) dibuat tapi MATI default; per akun | Biaya perlu dipantau dulu; RFM tidak bisa dihitung tanpa sandbox |
| v2.3 | Cadangan kapasitas model (429) ke endpoint global; tracing dimatikan | Argon kena "TPM quota exhausted"; span export 403 |
| v2.4 | Ekspor Excel penuh (bukan 50 baris chat) | User non-IT butuh file, bukan kode |
| v2.5 | Baca PivotTable/header bertingkat, harga per liter | File Mesrania 2T gagal dibaca; kemasan beda (1 L vs 0,7 L) → bandingkan /L |
| v2.6–2.8 | Laporan HTML/PDF/PPTX, selalu template PTPL, tawarkan laporan setelah analisis, TIDAK PERNAH TXT | User sempat terpaksa minta TXT setelah laporan gagal 429 |
| v2.9 | Laporan dari data BigQuery yang sudah ditarik (`bq_pulls`), tanpa tarik ulang | Konsistensi angka chat vs laporan |
| v2.10 | Coba ulang + Argon global untuk laporan; batas pemakaian harian/bulanan | 429 saat laporan; kontrol biaya klien |
| v3.0 | **Claude `claude-opus-5-5` @ global untuk tugas berat**, cadangan Argon; skill file (Excel/PPT/Word/PDF/edit) | **Requirement klien**: user utama sangat terbiasa Claude; GE dibeli PTPL. Router & data tetap Flash (hemat) |
| v3.0.1 | Panggilan SDK Anthropic tahan beda versi (buang parameter tak dikenal) | SDK terbaru menolak `temperature` |
| v3.1 | Data Agent Sell-out; laporan custom saja; berdiri sendiri; pengetahuan MIR via `set_knowledge.py` | BQ agent baru, belum ada template; user akan memberi knowledge belakangan |
| v3.2 | Model melihat gambar unggahan (GE tidak mengirim gambar inline) + gambar referensi laporan | User mengirim contoh laporan (WhatsApp image) tapi agent bilang tidak bisa melihat |
| v3.3 | Insight otomatis (katalog chart Strategist Toolkit) + korelasi hanya sumber sama / Retail × Planogram | Klien minta analisis mendalam ala pptx "Overnight Strategist" |
| v3.4 | Seluruh 68 kerangka pptx (Define→Act) sebagai skill + diagram; dipilih sesuai jenis pertanyaan | Klien ingin teknik analisis pptx, bukan hanya chart |
| v3.5 | Minimal 3 chart dijamin kode; agregasi kategori berulang; pencilan dipisah; warna gap Retail terbalik | Agent (Flash) hanya membuat 1 chart; label berulang & nilai ekstrem hilang |
| v3.5.1 | Jawaban tidak pernah kosong (`compose_fallback`); `create_chart` dihapus dari agent | Jawaban hilang setelah pemeriksa angka minta revisi; instruksi lama bentrok |
| v3.5.3 | Error model non-kapasitas → jawaban dari hasil tool (bukan exception); signature dummy pada panggilan sintetis; draf sebelum revisi dikirim bila revisi gagal | Jawaban kosong berulang setelah Periksa Angka |
| v3.5.2 | Pemeriksa angka menerima pembulatan wajar; larang salin angka dari gambar referensi | Log: "Rp 91.000" ditolak; angka laporan diduga disalin dari gambar |

Prinsip yang konsisten: angka dari kode/tool; jujur soal keterbatasan; user non-IT; saklar operasional tanpa deploy.
