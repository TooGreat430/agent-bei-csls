# Panduan v3.0 — Claude sebagai Model Tugas Berat + Skill File

Hasil v3.0 bagi user: analisis file, pembuatan laporan, dan pembuatan file (Excel, PowerPoint, Word, PDF) dikerjakan
**Claude** di dalam Marketing Insight Assistant (Gemini Enterprise), dengan **cadangan otomatis Gemini 4 Argon** bila
Claude penuh. Router dan tanya-jawab data BigQuery tetap memakai model cepat Gemini. Perkiraan waktu: 45 menit.

## Data yang dipakai (sudah terisi)

| Item | Nilai |
|---|---|
| Project | `ptpl-land-dev` |
| Model tugas berat | `claude-opus-5-5` @ `global` (Vertex AI, sudah aktif di Model Garden) |
| Cadangan | `gemini-4-argon` (lokasi sesuai `.env`), lalu Argon `global` |
| Resource agent | `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| Akun Code Execution (skill file) | `jason.kusuma@mii.co.id`, `mirptpl@gmail.com` |
| settings.json | `gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json` |
| Tag cadangan | `cadangan-v210` |
| Zip | `%USERPROFILE%\Downloads\ge-library-agent.zip` |

Tidak ada izin IAM baru: service account agent sudah punya role Vertex AI yang juga berlaku untuk model Claude.

---

## Langkah 0 — Titik cadangan

**Laptop (CMD):**
```bat
cd agent-bei-csls
git pull
git tag cadangan-v210
git push origin cadangan-v210
```
**Cloud Shell:**
```bash
gcloud storage cp gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json \
  gs://ptpl-ge-bucket/ge-docs-agent/config/settings.cadangan-v210.json
```

## Langkah 1 — Ganti isi repo (laptop, CMD)

```bat
cd agent-bei-csls
for /d %d in (*) do @rmdir /s /q "%d"
for %f in (*) do @del /q "%f"
if exist %TEMP%\gla rmdir /s /q %TEMP%\gla
mkdir %TEMP%\gla
tar -xf %USERPROFILE%\Downloads\ge-library-agent.zip -C %TEMP%\gla
xcopy /e /h /y /q %TEMP%\gla\ge-library-agent\* .
git add -A
git commit -m "v3.0: Claude untuk tugas berat (cadangan Argon), skill Excel/PowerPoint/Word/PDF/edit file"
git push
```

## Langkah 2 — Uji Claude dengan kode agent SEBELUM deploy (Cloud Shell)

```bash
cd ~/agent-bei-csls && git status --short && git pull
source .venv/bin/activate && pip install -q -r requirements.txt
python scripts/check_claude.py
```

Hasil yang diharapkan:
```
1) Teks       : OK — Jakarta …
2) Alat       : OK — memanggil analyze_data([...]) lalu menjawab: … · model dipakai: claude-opus-5-5
```
- Jika `model dipakai: gemini-4-argon` → Claude gagal dipanggil dan cadangan bekerja; lihat Troubleshooting.
- Jika baris 1 `GAGAL` → jangan lanjut; kirim pesan errornya ke tim teknis.

## Langkah 3 — Deploy (Cloud Shell)

```bash
find . -name __pycache__ -prune -exec rm -rf {} + && bash scripts/update_agent.sh
```

Hasil yang diharapkan: tampil `Tugas berat: claude-opus-5-5 @ global (cadangan Argon)`, uji `OK` (196 uji), lalu
`Selesai.` Jalankan sekali saja, jangan `Ctrl+C`.

## Langkah 4 — Nyalakan Code Execution (skill file) untuk dua akun

1. Masuk ke Gemini Enterprise dengan **kedua** akun bergantian, buka chat baru di Marketing Insight Assistant, kirim
   `halo`.
2. Di Cloud Shell, lihat ID user yang tercatat:
```bash
python scripts/usage_report.py 1
```
   Baris paling bawah menampilkan ID per user. Biasanya sama dengan email; jika berbeda, pakai ID yang tampil.
3. Nyalakan (ganti ID bila berbeda):
```bash
python scripts/code_execution_switch.py on jason.kusuma@mii.co.id mirptpl@gmail.com --budget 10 --steps 25
python scripts/code_execution_switch.py status
```
4. (Disarankan) Batas pemakaian seluruh agent dengan notifikasi ke user:
```bash
python scripts/set_budget.py set --harian 15 --bulanan 250 --peringatan 80 --cakupan berat
```
   Angka contoh; sesuaikan dengan anggaran yang disepakati PTPL.

Tunggu 5 menit.

## Langkah 5 — Uji di Gemini Enterprise (akun mirptpl@gmail.com, chat baru per baris)

| No | Kirim | Lulus jika |
|---|---|---|
| 1 | Unggah Excel SR1 + `Hitung volume dan bulan aktif per outlet per tahun, lalu buatkan file Excel dengan rumus total dan grafik per tahun` | Link .xlsx: sheet Ringkasan dengan grafik, header navy, rumus total di sel (bukan angka mati), sheet Keterangan |
| 2 | Lanjutan no. 1: `Buatkan deck PowerPoint 5 slide dari hasil ini yang bisa saya edit` | Link .pptx 16:9 bergaya PTPL; grafik bisa diedit di PowerPoint |
| 3 | Lanjutan no. 1: `Buatkan memo Word untuk management berisi temuan utama` | Link .docx dengan judul, ringkasan, tabel |
| 4 | Unggah sebuah .pptx milik Anda + `Ganti judul slide 1 menjadi "Review Q3 2026" dan perbaiki ejaan di slide 2` | Link file `_revisi.pptx`; agent menyebut perubahan sebelum → sesudah |
| 5 | `Buatkan laporan one pager PDF dari hasil analisa tadi` | Laporan lewat template PTPL (alat laporan), bukan file buatan sandbox |
| 6 | Pertanyaan data BigQuery seperti biasa | Jawaban seperti sebelumnya (tetap Data Agent + model cepat) |

Setelah uji, cek bahwa Claude yang menjawab:
```bash
python scripts/usage_report.py 1
```
Bagian per model harus menampilkan `claude-opus-5-5` (bukan hanya `gemini-4-argon`).

## Saklar & rollback

| Kebutuhan | Perintah (Cloud Shell) | Berlaku |
|---|---|---|
| Kembali ke Gemini 4 Argon untuk tugas berat (tanpa deploy) | `python scripts/set_model.py gemini` | ≤ 5 menit |
| Kembali ke Claude | `python scripts/set_model.py claude` | ≤ 5 menit |
| Matikan skill file / Code Execution | `python scripts/code_execution_switch.py off` | ≤ 5 menit |
| Rollback penuh ke v2.10 | Bagian Rollback di `PANDUAN_DEPLOY_AMAN.md` dengan tag `cadangan-v210` | ±10 menit |

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| `check_claude.py` baris 1: 403 / permission / "not enabled" | Model Claude belum diaktifkan untuk project, atau syarat Marketplace belum disetujui | Model Garden → Claude Opus 5.5 → Enable, untuk project `ptpl-land-dev` |
| 404 model not found | Model ID / region berbeda | Cek di Model Garden; ubah dengan `NEW_MODEL_CLAUDE=… NEW_CLAUDE_REGION=… bash scripts/update_agent.sh` |
| Jawaban berakhir "(Catatan: Claude sedang padat …)" sering muncul | Kuota Claude kecil | Konsol → IAM & Admin → Quotas & System Limits, filter model `claude-opus-5-5` region `global`, ajukan kenaikan |
| Skill file tidak dipakai / agent bilang tidak bisa membuat Excel | ID user tidak cocok atau belum 5 menit | `code_execution_switch.py status`; cocokkan ID dengan `usage_report.py 1` |
| Ingin bandingkan Claude vs Argon | — | Jalankan kasus sama dengan `set_model.py claude` lalu `gemini`, bandingkan hasil & `usage_report.py` |
