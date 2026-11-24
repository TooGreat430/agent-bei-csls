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
| v3.5.2 | Pemeriksa angka menerima pembulatan wajar; larang salin angka dari gambar referensi | Log: "Rp 91.000" ditolak; angka laporan diduga disalin dari gambar |
| v3.6 | **`analisis_rfm`**: RFM sell-out dihitung kode langsung dari `SALES_OUT_DAILY` (bukan Data Agent), HTML 8 section SR7 v5 + Excel register, per region/nasional; **maks. 1 laporan berat per pesan**; RFM di laporan custom dialihkan; **semua region + nasional dalam satu pesan** (`region="semua"`, paralel, halaman paket, batas waktu internal) atas permintaan Jason: tim MIR ingin hasil instan "seperti Claude", bukan satu per satu; ditambah `buat_laporan_sekaligus` untuk beberapa laporan BERBEDA dalam satu pesan (paralel, batas waktu internal) | DEADLINE_EXCEEDED 20 Nov (2 laporan custom dalam 1 giliran) + bagian RFM selalu "n/a" karena Data Agent hanya memberi ringkasan ≤ 300 baris |
| v3.7 | **Laporan visual otomatis** (`buat_laporan_visual`): mesin `visual_report/` (komponen → PPTX chart native/PDF/HTML identik) + perencana storyboard Claude + pemeriksa angka + 1 revisi + jaring terakhir (lampiran angka kunci, catatan pemeriksa, storyboard cadangan kode). Jadi pilihan utama untuk semua permintaan laporan/deck dari analisis; custom tetap untuk template milik user. **Angka tidak pernah dibulatkan** (permintaan Jason 23 Nov). Semua agent dilarang menampilkan istilah teknis saat gagal | Klien: visualisasi & kreativitas laporan ADK jauh di bawah Claude Web (deck SWOT ADK 0 chart vs deck Claude). Jason: "jangan ada internal error ke user" (malu sebagai konsultan) dan "angka hasil analitik jangan sampai ada yang miss" |

Asumsi v3.6 yang perlu dikonfirmasi user: `DT_PR` = tanggal transaksi (deskripsi skema: "processing/partition
date"); seri = `PRODUCT_SEGMENT`; volume = `TOTAL_VOL_KL_DELIVERED` semua status order; region & tipe outlet =
dominan per volume; footer "Prepared with ChatGPT Analytics" (v5) diganti `rfm_footer_credit`; HTML v5 asli belum
diterima (desain dari spesifikasi docx). `scripts/check_rfm.py` menampilkan bukti untuk tiap asumsi.
**Hasil `check_rfm.py` 20 Nov — LULUS:** DT_PR harian = tanggal transaksi; REGION I–VII → SR1–SR7; `PRODUCT_SEGMENT` =
seri; 50.980 outlet; query 13,6 dtk. Temuan nasional: Champions = 87,3% volume; Can't Lose Them = 0 (struktural,
bukan bug).

Prinsip yang konsisten: angka dari kode/tool; jujur soal keterbatasan; user non-IT; saklar operasional tanpa deploy.
