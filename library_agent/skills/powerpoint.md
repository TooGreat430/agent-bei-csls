# Skill PowerPoint (.pptx) — deck yang bisa diedit user

Library: python-pptx; grafik native (pptx.chart) agar bisa diedit, atau gambar matplotlib bila jenis grafik khusus.
Gunakan skill ini untuk deck/presentasi yang diminta bebas (bukan laporan standar). Untuk LAPORAN berbasis template
PTPL, gunakan generate_custom_report (bisa PowerPoint) — bukan skill ini.

Struktur deck: 1) judul (judul, subjudul periode, "PT Pertamina Lubricants"), 2) ringkasan eksekutif (3–5 poin
berangka), 3–n) satu pesan per slide: judul slide = kesimpulan (bukan topik), isi = grafik/tabel + 2–3 poin,
terakhir) rekomendasi/aksi per owner.

Gaya: ukuran 16:9 (prs.slide_width = Inches(13.333), slide_height = Inches(7.5)); latar putih; bilah judul navy
#0C1E3C dengan teks putih 24pt; aksen gold #B58012; teks isi 14–16pt abu gelap; maks ±6 poin per slide; footer kecil
"Sumber: … · PT Pertamina Lubricants · Confidential".

Grafik native:
```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.dml.color import RGBColor
prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
s = prs.slides.add_slide(prs.slide_layouts[6])
cd = CategoryChartData(); cd.categories = labels; cd.add_series("Volume", values)
ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.4), Inches(8), Inches(5), cd).chart
ch.plots[0].series[0].format.fill.solid(); ch.plots[0].series[0].format.fill.fore_color.rgb = RGBColor(0x0C, 0x1E, 0x3C)
prs.save("Deck.pptx")
```
Tabel: shapes.add_table, header navy teks putih, angka rata kanan, maks ±12 baris per slide (pecah ke slide berikut).
Verifikasi: buka lagi, cetak jumlah slide dan judul tiap slide.
