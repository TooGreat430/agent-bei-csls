# Skill Word (.docx) — dokumen yang bisa diedit

Library: python-docx; grafik sebagai gambar PNG dari matplotlib (dpi 200) disisipkan dengan add_picture.
Pakai untuk dokumen tertulis: memo, notulen, kajian, SOP, ringkasan analisis dalam bentuk dokumen, surat.

Struktur: judul (Heading 0/Title), baris info (periode · sumber · tanggal), "Ringkasan" (3–5 poin), bagian bernomor
dengan Heading 1/2, tabel dan grafik dengan keterangan ("Tabel 1. …", "Gambar 1. …"), penutup/rekomendasi, lampiran.

Gaya: font Calibri 11pt, judul navy #0C1E3C; tabel style "Table Grid" atau "Light Grid Accent 1" dengan header
tebal ber-shading navy dan teks putih (set lewat XML shading w:shd); margin 2,5 cm; header/footer berisi
"PT Pertamina Lubricants · Confidential" dan nomor halaman bila memungkinkan.

Contoh inti:
```python
from docx import Document
from docx.shared import Pt, RGBColor, Inches
doc = Document(); st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11)
h = doc.add_heading("Analisa RFM Retail SR1 2025", 0)
doc.add_paragraph("Periode Jan–Des 2025 · Sumber: SORetail_24-26_DataReadRFM_SR1.xlsx")
t = doc.add_table(rows=1, cols=len(df.columns)); t.style = "Table Grid"
for i, c in enumerate(df.columns): t.rows[0].cells[i].text = str(c)
for row in df.itertuples(index=False):
    cells = t.add_row().cells
    for i, v in enumerate(row): cells[i].text = f"{v:,.0f}".replace(",", ".") if isinstance(v, (int, float)) else str(v)
doc.add_picture("grafik.png", width=Inches(6)); doc.save("Analisa_RFM_SR1.docx")
```
Verifikasi: buka lagi, cetak jumlah paragraf, judul-judul heading, dan jumlah tabel.
