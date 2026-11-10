# Skill PDF — dokumen PDF siap cetak

Library: reportlab (platypus: SimpleDocTemplate, Paragraph, Table, Image, Spacer, PageBreak) + matplotlib untuk grafik.
Untuk LAPORAN berbasis template PTPL, gunakan generate_custom_report (bisa PDF) — skill ini untuk PDF lain yang
diminta bebas (mis. lembar ringkas, tabel cetak, lampiran, sertifikat, daftar).
Membaca/mengekstrak PDF user tidak dilakukan di sandbox (pypdf tidak tersedia); isi PDF user sudah diekstrak agent
dan bisa dibaca dengan read_document.

Gaya: A4 (portrait untuk dokumen, landscape untuk tabel lebar), margin 2 cm, judul navy #0C1E3C 16pt, isi 10pt,
tabel header navy teks putih + baris selang-seling #F8FAFC, footer "PT Pertamina Lubricants · Confidential · hal. N".

```python
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
doc = SimpleDocTemplate("Ringkasan.pdf", pagesize=A4); ss = getSampleStyleSheet()
data = [list(df.columns)] + df.astype(str).values.tolist()
t = Table(data, repeatRows=1); t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0C1E3C")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")])]))
doc.build([Paragraph("Judul", ss["Title"]), Spacer(1, 8), t, Image("grafik.png", width=480, height=240)])
```
Verifikasi: cetak jumlah halaman dengan membaca ulang ukuran file / jumlah flowable; pastikan file tidak kosong.
