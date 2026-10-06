# Panduan Testing — Marketing Insight Assistant (POC)

## A. Persiapan

1. Agent sudah di-update dengan kode terbaru (`bash scripts/update_agent.sh` selesai sampai `Selesai.`).
2. `ge-docs-datastore/` **hanya** berisi dokumen Black Treasure, dengan nama **tanpa spasi**: `black_treasure_bhs_q1_2026_motor.pdf`.
3. Siapkan file dari `dokumen_uji.zip` di laptop:

| File | Kode | Dipakai di skenario |
|---|---|---|
| `bei_black_treasure_copy.pdf` | A-kembar (isi sama dengan dokumen Black Treasure) | 3, 7 |
| `uji_catatan_bei.docx` | Dokumen Word | 3, 31–32 |
| `uji_tabel.csv` | Format tidak didukung | 3, 8 |
| `uji_csls_2026.pdf` | Dokumen CSLS fiktif v1, upload lewat chat | 5–6 |
| `uji_csls_2026_v2.pdf` | CSLS versi 2 | 29, 33 |
| `untuk_uji_ganti/uji_csls_2026.pdf` | Nama sama dengan v1, isi beda | 30 |

4. Siapkan lembar hasil: No, Lulus/Gagal, Catatan, Screenshot, Jam.

Gunakan **satu chat baru** sampai Bagian 6.

---

## B. Skenario

### Bagian 1 — Perkenalan & sinkronisasi folder

| No | Prompt / aksi | Yang diharapkan |
|---|---|---|
| 1 | `Halo, apa saja yang bisa kamu bantu?` | Memperkenalkan diri sebagai Marketing Insight Assistant; menyebut laporan PDF/PowerPoint/HTML; tidak menyebut "Research Agent"/"Report Agent" |
| 2 | `Dokumen apa saja yang ada di perpustakaan?` | 1 dokumen dari folder: judul *Monitoring Performa dan Potensi di Market melalui Studi BEI dan NPS 2026*, jenis **BEI**, versi **1**, status **sedang diindeks** (bukan gagal) |
| 3 | Upload `uji_catatan_bei.docx`, `uji_tabel.csv`, `bei_black_treasure_copy.pdf` ke `ge-docs-datastore/` lewat Konsol → ulangi no. 2 | DOCX ditambahkan; CSV dilewati (format tidak didukung); copy PDF dilewati (isi sama) |
| 4 | Jika ada field "perlu dicek", jawab mis. `Jenisnya BEI.` | Metadata diperbarui |

### Bagian 2 — Upload lewat chat

| No | Prompt / aksi | Yang diharapkan |
|---|---|---|
| 5 | Lampirkan `uji_csls_2026.pdf` → `Masukkan ke perpustakaan.` | Judul *Customer Satisfaction & Loyalty Survey (CSLS) 2026*, jenis **CSLS**, versi **1**, tanggal **2026-07-15**, lalu "Sudah benar?". **Konsol: belum ada di `ge-docs-datastore/`** |
| 6 | `Benar.` | Tersimpan. **Konsol: `uji_csls_2026.pdf` ada di `ge-docs-datastore/`** |
| 7 | Lampirkan `bei_black_treasure_copy.pdf` → `Masukkan ke perpustakaan.` | Memberi tahu dokumen yang sama sudah ada |
| 8 | Lampirkan `uji_tabel.csv` → `Masukkan ke perpustakaan.` | Format tidak didukung |

### ⏳ Tunggu indexing (10–20 menit; dokumen Black Treasure 116 halaman)

| No | Prompt | Yang diharapkan |
|---|---|---|
| 9 | `Apakah semua dokumen sudah siap dipakai?` | Semua `ready`. Jika `indexing`, tunggu 5 menit lalu ulangi. Jika `failed`, kirim screenshot |

### Bagian 3 — Sentralisasi & tanya-jawab (inti POC)

| No | Prompt | Kunci jawaban |
|---|---|---|
| 10 | `Pakai dokumen Black Treasure saja untuk chat ini.` | Dokumen aktif: hanya Black Treasure |
| 11 | `Pertamina Enduro Series berada di peringkat berapa dalam Brand Equity Index, dan peringkat berapa pada Q4 2025?` | Peringkat **3**; Q4 2025 peringkat **2**. Sitasi ±hal. 30–31 |
| 12 | `Merek apa yang memimpin brand funnel dari sisi awareness dan consideration, dan bagaimana posisi Pertamina?` | **Castrol** memimpin awareness & consideration; AHM funnel terkuat & loyalitas tertinggi; Pertamina awareness kuat tapi sulit konversi ke consideration. ±hal. 33 |
| 13 | `Bagaimana persepsi harga varian Pertamina Lubricants?` | Area **priced right**. ±hal. 49 |
| 14 | `Apa yang harus diperbaiki Pertamina Enduro?` | **Out of stock**/ketersediaan di toko; **persepsi harga** lewat promosi & value for money; **rekomendasi mekanik**. ±hal. 111 |
| 15 | `Berapa skor CSI kanal e-commerce?` | **"Tidak ditemukan di dokumen aktif."** (hanya ada di CSLS) — **uji terpenting** |
| 16 | `Berapa harga oli Fastron di pasaran sekarang?` | Tidak ditemukan; tidak menjawab dari pengetahuan umum |
| 17 | `Tambahkan juga dokumen CSLS.` → ulangi no. 15 | **76**, sitasi CSLS hal. 3 |
| 18 | `Berapa NPS dan CSI keseluruhan di dokumen CSLS?` | NPS **42**, CSI **81**. CSLS hal. 2 |
| 19 | `Keluarkan dokumen Black Treasure.` → ulangi no. 11 | "Tidak ditemukan" |
| 20 | `Pakai lagi dokumen Black Treasure dan CSLS.` | Dua dokumen aktif |

Nomor halaman boleh berbeda ±1 (nomor slide tercetak ≠ urutan halaman PDF).

### Bagian 4 — Insight

| No | Prompt | Yang diharapkan |
|---|---|---|
| 21 | `Tampilkan insight yang sudah disimpan.` | Daftar insight di chat ini (awalnya kosong) |
| 22 | Setelah jawaban no. 11 (tanyakan ulang jika perlu): `Simpan jawaban tadi sebagai insight.` | Tersimpan dengan sitasi; insight tersimpan di chat ini |
| 23 | Ulangi untuk jawaban no. 14 dan no. 18 | Total 3 insight |
| 24 | `Tampilkan insight yang sudah disimpan.` | 3 insight |

### Bagian 5 — Laporan

| No | Prompt | Yang diharapkan |
|---|---|---|
| 25 | `Buatkan laporan dengan template Studi BEI & NPS dari semua insight. Judulnya Laporan Uji POC.` | Agent **menanyakan format** |
| 26 | `PDF.` | 1 link PDF. Cek: gaya deck, PT Pertamina Lubricants, sitasi tiap temuan, **tidak ada angka di luar insight** |
| 27 | `Buatkan juga dalam PowerPoint.` | 1 link .pptx, isi & urutan sama |
| 28 | `Sekarang dalam HTML.` | 1 link HTML |

### Bagian 6 — Kelola dokumen

| No | Prompt / aksi | Yang diharapkan |
|---|---|---|
| 29 | Upload `uji_csls_2026_v2.pdf` ke folder → `Dokumen apa saja yang ada? Tampilkan juga versi lama.` | CSLS **v2** jadi versi terbaru; v1 tetap ada |
| 30 | Upload `untuk_uji_ganti/uji_csls_2026.pdf` lewat Konsol (timpa v1) → `Dokumen apa saja yang ada?` | **1 dokumen diperbarui** |
| 31 | `Judul dokumen catatan rapat salah, ubah menjadi Notulen Review BEI Q1 2026.` | Judul berubah |
| 32 | `Hapus dokumen Notulen Review BEI Q1 2026.` → `Ya.` | Konfirmasi dulu, lalu terhapus. **Konsol: `uji_catatan_bei.docx` hilang dari folder** |
| 33 | Hapus `uji_csls_2026_v2.pdf` dari folder lewat Konsol → `Dokumen apa saja yang ada?` | Dokumen itu hilang; CSLS v1 kembali jadi versi terbaru |

### Bagian 7 — Chat baru & user lain

| No | Prompt | Yang diharapkan |
|---|---|---|
| 34 | **Chat baru:** `Tampilkan insight yang sudah disimpan.` | Kosong — insight hanya hidup di chat tempat ia disimpan |

### Bagian 8 — Data BigQuery (Marketing Intelligence)

Prasyarat: izin bagian 2.4 di `PANDUAN_SETUP.md` sudah diberikan. Gunakan **chat baru**.

| No | Prompt | Yang diharapkan |
|---|---|---|
| 36 | `Berapa gap harga jual per liter Enduro Matic-S 0.8L dibanding kompetitornya di Zona 1 pada Mei 2026?` | Jawaban dengan angka Rupiah per liter, tabel ringkas, sumber "Survey Response Report Retail". **Tidak** menawarkan dokumen |
| 37 | `Bagaimana dengan Zona 2?` | Memahami konteks (produk & periode sama), menjawab untuk Zona 2 |
| 38 | Bandingkan angka no. 36–37 dengan jawaban agent Marketing Intelligence di GE untuk pertanyaan yang sama | Angka **sama** |
| 39 | `Tampilkan grafiknya.` | Menjelaskan grafik tidak tampil di chat, tersedia di laporan, dan menawarkan simpan insight |
| 40 | `Simpan jawaban data tadi sebagai insight.` | Insight tersimpan (sumber BigQuery, tabel data ikut) |
| 41 | `Bandingkan gap harga jual Hero MCO, PCO, dan Commercial di Nasional dan Zona 1–3 untuk Q3 2026.` → `Simpan sebagai insight.` | Jawaban per segmen/zona; insight kedua tersimpan |
| 42 | `Buatkan laporan dengan template Daya Saing Harga Retail dari insight di chat ini dalam format PDF. Judulnya Uji Laporan BQ.` | Link PDF berisi: ringkasan, KPI per zona, matriks dengan status, **grafik**, insight strategis |
| 43 | Cocokkan angka di KPI/matriks/grafik dengan jawaban no. 36–41 | Semua angka ada di jawaban/tabel data. Tidak ada angka karangan |
| 44 | `Buatkan juga dalam PowerPoint.` | PPTX dengan **grafik native** (klik kanan grafik → Edit Data di PowerPoint) |

### Bagian 9 — Pindah-pindah kemampuan dalam satu chat

| No | Prompt | Yang diharapkan |
|---|---|---|
| 45 | `Pakai dokumen Black Treasure saja.` | Dokumen aktif |
| 46 | `Berapa margin bengkel Enduro Matic-S di Nasional bulan Mei 2026?` | Dijawab dari **data BigQuery**, walau sedang membahas dokumen |
| 47 | `Apa kata dokumen soal persepsi harga Enduro?` | Kembali ke **dokumen** (Black Treasure tetap aktif), dengan sitasi halaman |
| 48 | `Bandingkan margin tadi dengan temuan dokumen soal harga.` | Menggabungkan keduanya **hanya karena diminta** |

---

## C. Kriteria lulus POC

| Skenario | Membuktikan |
|---|---|
| 2, 3, 33 | Katalog selalu sama dengan isi `ge-docs-datastore` |
| 5–6 | Upload lewat chat dikonfirmasi dulu, tersimpan di `ge-docs-datastore` |
| 11–14 | Jawaban akurat dan bersitasi |
| 15, 19 | Chat terpusat pada dokumen yang dipilih |
| 17 | Sentralisasi bisa diperluas di tengah chat |
| 25–28 | Laporan sesuai template, sesuai format yang diminta, tidak mengarang |
| 36–38 | Data BigQuery dijawab akurat lewat Data Agent yang sama dengan di GE |
| 42–44 | Laporan BQ dengan grafik di PDF/PPT/HTML, angka terverifikasi |
| 46–47 | Pertanyaan data/dokumen diarahkan dengan benar kapan pun dalam chat |

Jika gagal: screenshot chat + jam kejadian, dan output **Perintah B** di `PANDUAN_SETUP.md` (bagian Troubleshooting).
