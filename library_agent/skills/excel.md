# Skill Excel (.xlsx) — workbook rapi dengan rumus, format, dan grafik

Library: openpyxl (rumus, format, grafik native), xlsxwriter (alternatif cepat untuk file baru), pandas.

Struktur standar:
1. Sheet "Ringkasan": judul (A1, tebal 14pt navy), periode & sumber (A2), lalu tabel KPI utama.
2. Satu sheet per tabel analisis; sheet "Data" berisi data dasar bila user butuh menelusuri.
3. Sheet "Keterangan": definisi kolom, rumus/metodologi, baris yang dikecualikan.

Format wajib:
- Header: tebal, putih di atas navy #0C1E3C, rata tengah, wrap; freeze_panes di bawah header; auto_filter.
- Lebar kolom menyesuaikan isi (maks ±50); angka dengan number_format: '#,##0' (bilangan), '#,##0.00' (desimal),
  '0.0%' (persen — simpan sebagai pecahan 0,123), '"Rp" #,##0' (rupiah).
- Kondisional: nilai negatif merah, positif hijau untuk kolom gap/selisih (openpyxl.formatting.rule CellIsRule).

Rumus (bila user ingin bisa dihitung ulang): tulis rumus Excel, bukan nilai mati, untuk total/rata-rata/selisih/
persentase, mis. ws["E2"] = "=C2-D2", ws["F2"] = "=IFERROR(E2/D2,0)", total: "=SUM(C2:C100)". Hitung juga nilainya
dengan pandas dan cetak beberapa untuk verifikasi.

Grafik native openpyxl: BarChart/LineChart/PieChart + Reference ke rentang sel; judul, judul sumbu, warna seri dari
palet PTPL; letakkan di sheet Ringkasan (ws.add_chart(chart, "H2")).

Contoh inti:
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.chart import BarChart, Reference
from openpyxl.utils.dataframe import dataframe_to_rows
wb = Workbook(); ws = wb.active; ws.title = "Ringkasan"
for r in dataframe_to_rows(df, index=False, header=True): ws.append(r)
for c in ws[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="0C1E3C")
ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
ch = BarChart(); ch.title = "Volume per segmen"
ch.add_data(Reference(ws, min_col=2, min_row=1, max_row=ws.max_row), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)); ws.add_chart(ch, "H2")
wb.save("Analisa.xlsx")
```
Verifikasi: load_workbook lalu cetak sheetnames, max_row tiap sheet, dan 3 nilai kunci.
