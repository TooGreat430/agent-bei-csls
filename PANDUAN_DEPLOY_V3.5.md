# Panduan Deploy v3.5 — Claude + Skill File + Sell-out + Gambar + Insight Otomatis + Kerangka Strategist

Satu kali deploy untuk semua perubahan sejak v2.10. Ikuti berurutan; semua nilai sudah terisi.
Perkiraan waktu: 45–60 menit (deploy ±10 menit di dalamnya).

| Isi v3.2 | Ringkas |
|---|---|
| Claude | `claude-opus-5-5` @ `global` untuk analisis file, skill, laporan; cadangan otomatis Gemini 4 Argon |
| Skill file | Excel (rumus & grafik), PowerPoint & Word yang bisa diedit, PDF, edit file user — lewat Code Execution |
| Sell-out | Data Agent Selling Out Intelligence: tanya-jawab + laporan custom (berdiri sendiri) |
| Melihat gambar | JPG/PNG/WhatsApp Image dilihat model; bisa jadi contoh bentuk laporan |
| Kerangka Strategist | Seluruh kerangka analisis pptx (Define, Split, Analyse kualitatif, Insight, Story, Decide, Act) dipakai otomatis sesuai jenis pertanyaan, dengan diagram (driver tree, hypothesis, 5 Whys, evaluation berbobot, decision tree, Eisenhower, execution plan, dll.) |
| Insight otomatis | Setiap tarikan data / analisis file langsung disertai beberapa chart (katalog Strategist Toolkit: trend, comparison, mix, Pareto, waterfall, actual vs target, heat map, scatter, dll.) + headline, angka sorotan, takeaway; korelasi dengan data sebelumnya (hanya sumber sama atau Retail × Planogram) |

## Data yang dipakai (sudah terisi)

| Item | Nilai |
|---|---|
| Repo laptop / Cloud Shell | `agent-bei-csls` / `~/agent-bei-csls` |
| Zip | `%USERPROFILE%\Downloads\ge-library-agent.zip` |
| Project | `ptpl-land-dev` |
| Resource agent | `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| Service account agent | `service-37078813825@gcp-sa-aiplatform-re.iam.gserviceaccount.com` |
| settings.json | `gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json` |
| Akun Code Execution | `jason.kusuma@mii.co.id`, `mirptpl@gmail.com` |
| Tag cadangan | `cadangan-v35` |

Prasyarat (sudah dicek): Claude Opus 5.5 aktif di Model Garden; akses Data Agent (level project) dan Data Viewer di 4
tabel Sell-out sudah ada. Tidak ada izin baru yang perlu diberikan.

---

## Langkah 1 — Cadangan (laptop CMD + Cloud Shell)

**Laptop (CMD):**
```bat
cd agent-bei-csls
git pull
git tag cadangan-v35
git push origin cadangan-v35
```
Jika muncul `tag 'cadangan-v35' already exists`, lewati.

**Cloud Shell:**
```bash
gcloud storage cp gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json \
  gs://ptpl-ge-bucket/ge-docs-agent/config/settings.cadangan-v35.json
```

## Langkah 2 — Ganti isi repo & push (laptop CMD)

```bat
cd agent-bei-csls
for /d %d in (*) do @rmdir /s /q "%d"
for %f in (*) do @del /q "%f"
if exist %TEMP%\gla rmdir /s /q %TEMP%\gla
mkdir %TEMP%\gla
tar -xf %USERPROFILE%\Downloads\ge-library-agent.zip -C %TEMP%\gla
xcopy /e /h /y /q %TEMP%\gla\ge-library-agent\* .
git add -A
git commit -m "v3.5.2: jawaban tidak pernah kosong, pemeriksa angka terima pembulatan, insight min. 3 chart"
git push
```

## Langkah 3 — Ambil kode & cek sebelum deploy (Cloud Shell)

```bash
cd ~/agent-bei-csls && git status --short && git pull && git log --oneline -1
```
Baris terakhir harus `… v3.5.2: jawaban tidak pernah kosong, pemeriksa angka terima pembulatan, insight min. 3 chart`. Jika `git status` menampilkan file
selain `.venv/` atau `log_*.txt`, jalankan `git reset --hard @{u}` lalu ulangi.

```bash
source .venv/bin/activate && pip install -q -r requirements.txt
python scripts/check_claude.py
python scripts/check_knowledge.py
```
Hasil yang diharapkan:
- `check_claude`: baris `1) Teks : OK` dan `2) Alat : OK … model dipakai: claude-opus-5-5`.
- `check_knowledge`: baris `[sellout]` diikuti 4 alamat tabel (`ptpl-curated-prd.DATAMART.SALES_OUT_DAILY`, dll.).

Jika salah satu gagal, berhenti dan kirim outputnya ke tim teknis.

## Langkah 4 — Deploy (Cloud Shell)

```bash
find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```
Hasil yang diharapkan, berurutan:
- `Model utama: gemini-4-argon @ …` dan `Tugas berat: claude-opus-5-5 @ global (cadangan Argon)`
- Uji: `OK` (242 uji)
- `Selesai.`

Jalankan **sekali saja** dan jangan `Ctrl+C`. Jika terminal terputus, jangan jalankan ulang; cek status deploy di
Konsol → Vertex AI → Agent Engine.

## Langkah 5 — Perbarui deskripsi agent di Gemini Enterprise

Konsol Gemini Enterprise → Agents → Marketing Insight Assistant → Edit → Description, ganti dengan:

> Asisten Marketing Intelligence PT Pertamina Lubricants. Menjawab pertanyaan data langsung dari BigQuery lewat Data Agent resmi: survei harga Retail dan Industri/B2B, Planogram (outlet carry, ND, availability & visibility, whitespace), analisis silang Retail × Planogram, serta data Sell-out distributor (volume, fulfillment, Active Customer, kontribusi region/channel/produk). Membaca file yang diunggah (Excel/CSV, PDF, Word, PowerPoint, gambar), menganalisisnya sesuai instruksi atau metodologi user, dan menghasilkan file jadi: Excel dengan rumus dan grafik, PowerPoint dan Word yang bisa diedit, serta PDF. Membuat laporan template maupun custom dalam HTML, PDF, atau PowerPoint dengan alur review dan approval.

Simpan.

## Langkah 6 — Nyalakan Code Execution (skill file) untuk dua akun

1. Login ke Gemini Enterprise dengan `jason.kusuma@mii.co.id`, buka chat baru di Marketing Insight Assistant, kirim
   `halo`. Ulangi dengan `mirptpl@gmail.com`.
2. Cloud Shell:
```bash
python scripts/usage_report.py 1
```
   Catat dua ID di baris paling bawah (biasanya sama dengan email).
3. Nyalakan (ganti ID bila berbeda dari email):
```bash
python scripts/code_execution_switch.py on jason.kusuma@mii.co.id mirptpl@gmail.com --budget 10 --steps 25
python scripts/code_execution_switch.py status
```
4. (Disarankan) Batas pemakaian seluruh agent dengan notifikasi ke user — angka contoh, sesuaikan anggaran PTPL:
```bash
python scripts/set_budget.py set --harian 15 --bulanan 250 --peringatan 80 --cakupan berat
```

Tunggu **5 menit** sebelum uji.

## Langkah 7 — Uji (akun mirptpl@gmail.com, chat baru per blok)

| No | Kirim | Lulus jika |
|---|---|---|
| 1 | `Berapa gap HTO Product Hero vs kompetitor di Zona 1 Q3 2026?` | Jawaban + tabel seperti biasa (regresi data Retail) |
| 2 | `Berapa volume sell-out per region bulan lalu?` | Tabel per region; sumber Selling Out Intelligence |
| 3 | Setelah no. 2 dijawab dan agent menawarkan laporan → `ya` → `PDF` | Link PDF laporan custom Sell-out bergaya PTPL |
| 4 | Unggah Excel SR1 + `Hitung volume dan bulan aktif per outlet per tahun, lalu buatkan file Excel dengan rumus total dan grafik per tahun` | Link .xlsx: grafik, header navy, rumus total di sel |
| 5 | Lanjutan no. 4: `Buatkan deck PowerPoint 5 slide dari hasil ini yang bisa saya edit` | Link .pptx bergaya PTPL |
| 6 | Setelah ada laporan custom: unggah gambar contoh tabel + gambar keterangan simbol, `Buat laporannya seperti ini, kelompokkan berdasarkan PTPL product name` | Agent menjelaskan isi gambar; revisi laporan meniru susunan & simbol, angka dari data |
| 7 | `Gabungkan data sell-out dengan planogram` | Agent menjelaskan Sell-out berdiri sendiri |
| 8 | `Berapa gap harga jual PTPL vs kompetitor per SR Q3 2026?` (tanpa meminta grafik) | Minimal 3 chart (mis. peringkat per produk + heat map produk × SR + sebaran), masing-masing dengan headline, sorotan, takeaway, link; produk tidak berulang di chart; nilai ekstrem disebut |
| 9 | Lanjutan no. 8: `Berapa ND PTPL per SR Q3 2026?` | Insight planogram + **korelasi** gap harga × ND per SR (r, n, scatter), disebut sebagai asosiasi |
| 10 | Lanjutan chat no. 2 (sell-out): `Berapa ND PTPL per SR?` | Insight planogram tanpa dikorelasikan dengan sell-out (berdiri sendiri) |
| 11 | `Kenapa volume sell-out SR5 turun di Q3 2026 dibanding Q2 2026?` | Driver tree + chart per cabang + 5 Whys; hipotesis ditandai |
| 12 | Lanjutan no. 11: `Apa yang sebaiknya kami lakukan? Bandingkan program display, diskon outlet, dan distributor baru. Bobot: dampak 40, biaya 30, kecepatan 30.` | Pros & cons + evaluation berbobot dengan skor dihitung; rekomendasi |

Daftar uji lengkap (37 uji chart & kerangka, dengan kolom status) ada di `Checklist_Uji_Chart_Kerangka_v3.4.xlsx`.

Setelah uji, pastikan Claude yang bekerja:
```bash
python scripts/usage_report.py 1
```
Bagian per model harus memuat `claude-opus-5-5`.

---

## Saklar cepat (tanpa deploy, berlaku ≤ 5 menit)

| Kebutuhan | Perintah (Cloud Shell, di `~/agent-bei-csls` dengan `.venv` aktif) |
|---|---|
| Tugas berat kembali ke Gemini 4 Argon | `python scripts/set_model.py gemini` |
| Kembali ke Claude | `python scripts/set_model.py claude` |
| Matikan skill file / Code Execution | `python scripts/code_execution_switch.py off` |
| Matikan batas pemakaian | `python scripts/set_budget.py off` |
| Tambah pengetahuan Sell-out dari user | `python scripts/set_knowledge.py upload sellout panduan.md` |

## Rollback penuh (jika ada masalah serius)

**Laptop (CMD):**
```bat
cd agent-bei-csls
git pull
git rm -r -q .
git checkout cadangan-v210 -- .
git commit -m "rollback ke v2.10"
git push
```
(Pakai tag `cadangan-v210` = versi terakhir yang pernah ter-deploy. Jika tag itu tidak ada, pakai `cadangan-v35`.)

**Cloud Shell:**
```bash
cd ~/agent-bei-csls && git reset --hard @{u} && git pull
gcloud storage cp gs://ptpl-ge-bucket/ge-docs-agent/config/settings.cadangan-v35.json \
  gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json
find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```

## Troubleshooting

| Gejala | Solusi |
|---|---|
| Jawaban sering berakhir "(Catatan: Claude sedang padat …)" | Kuota Claude kecil: Konsol → IAM & Admin → Quotas & System Limits, filter `claude-opus-5-5`, region `global`, ajukan kenaikan |
| Agent bilang tidak bisa membuat Excel/PowerPoint | ID user tidak cocok atau belum 5 menit: `code_execution_switch.py status`, cocokkan dengan `usage_report.py 1` |
| Pertanyaan Sell-out error akses | Kirim pesan errornya; akses tabel dan Data Agent sudah terverifikasi sebelumnya |
| Gambar tidak terbaca | Format HEIC belum didukung — minta user kirim JPG/screenshot |
| Chart insight tidak muncul / hanya satu | Tabel hasil tarikan terlalu kecil (mis. satu angka) — wajar; untuk data berbentuk tabel, kirim log bila chart gagal |
| Error lain | Kirim hasil perintah *Log diagnostik* di README |
