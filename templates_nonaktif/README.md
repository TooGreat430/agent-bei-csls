# Template laporan nonaktif

Template di folder ini **tidak dipakai agent** saat ini (agent laporan hanya membuat dashboard
daya saing harga dari BigQuery). Disimpan untuk diaktifkan kembali nanti:

- `studi_bei_nps/` — laporan studi BEI (deck riset 16:9)
- `laporan_studi/` — laporan studi umum
- `daya_saing_harga_bq/` — laporan data BigQuery berbasis insight (digantikan dashboard)

Untuk mengaktifkan kembali: pindahkan foldernya ke `templates/`, unggah dengan
`python scripts/upload_templates.py`, dan kembalikan tool `generate_report` ke agent laporan.
