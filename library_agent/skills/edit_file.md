# Skill mengedit file milik user (Excel, PowerPoint, Word)

File asli yang diunggah user tersedia di sandbox dengan awalan ID (mis. f1_Data.xlsx, d2_Laporan_Q3.pptx). File
Excel juga tersedia sebagai CSV per sheet untuk analisis; untuk MENGEDIT gunakan file aslinya.

Langkah:
1. Buka dan inventaris isi dulu, cetak ringkasannya: Excel (sheet, ukuran, header, rumus di sel kunci), PowerPoint
   (jumlah slide, judul & jenis shape per slide), Word (heading, jumlah tabel, paragraf kunci).
2. Konfirmasi ke user perubahan yang akan dilakukan bila permintaan ambigu.
3. Ubah seminimal mungkin; pertahankan gaya, rumus, dan format asli (openpyxl: load_workbook tanpa data_only agar
   rumus tetap; python-pptx: ubah teks di run yang ada agar format tetap; python-docx: ubah run, bukan paragraf baru).
4. Simpan sebagai file BARU berakhiran _revisi, lalu buka lagi dan cetak bukti perubahan (sebelum → sesudah).
5. Laporkan ke user: daftar perubahan dan link file revisi.

Catatan: openpyxl tidak menghitung ulang rumus; nilai rumus akan dihitung saat dibuka di Excel. Grafik/pivot Excel
yang kompleks bisa hilang saat disimpan ulang dengan openpyxl — ingatkan user bila file berisi pivot/grafik khusus.
