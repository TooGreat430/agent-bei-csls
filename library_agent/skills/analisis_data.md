# Skill analisis data — cara kerja analis (pandas)

1. INTAKE: baca file (pd.read_csv), cetak bentuk, kolom & tipe, 5 baris contoh, rentang tanggal, nilai kosong.
2. AUDIT: cek duplikasi kunci (mis. Customer Code × bulan), baris total/subtotal (kolom kunci kosong, nilai = jumlah
   baris lain), satuan (KL/liter/kemasan), nilai negatif/nol/aneh, konsistensi periode. Laporkan temuan + jumlah baris
   yang dikecualikan, dan minta keputusan user bila ada pilihan.
3. METODOLOGI: bila user memberi prompt/metodologi, ikuti persis; tulis ulang definisi yang akan dipakai (rumus,
   periode, filter, ambang) dan BERHENTI untuk persetujuan bila metodologi memintanya atau bila ada asumsi penting.
4. HITUNG: satu langkah satu tujuan; simpan hasil antara di variabel/CSV; cetak tabel kunci (df.head(20).to_string())
   dan angka total untuk rekonsiliasi (jumlah baris/outlet/volume sebelum = sesudah).
5. VALIDASI: cek silang (total per segmen = total keseluruhan; jumlah outlet per segmen = outlet aktif; tidak ada
   kategori hilang). Cetak hasil validasi PASS/FAIL.
6. OUTPUT: tabel ringkas di jawaban (Top N), file lengkap (Excel via skill excel), grafik PNG bila membantu.
7. NARASI: fakta (berangka, dari output) dipisah dari hipotesis; sebut keterbatasan data.

Teknik yang sering dipakai: groupby/agg, pivot_table, pd.qcut (kuintil; tangani ties dengan rank(method="first")),
cohort/migrasi (crosstab), YoY (periode yang sebanding), rasio per liter, scipy.stats untuk uji sederhana.
