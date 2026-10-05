# Panduan — Data BigQuery atas Nama User (OAuth)

Marketing Insight Assistant mengambil data BigQuery dengan **akun user yang login**, sama seperti Data Agent *Marketing Intelligence* di Gemini Enterprise. Fitur dokumen, insight, dan laporan tetap memakai service account agent (izinnya sudah lengkap).

| Item | Nilai |
|---|---|
| Project | `ptpl-land-dev` |
| Agent | `projects/37078813825/locations/asia-southeast2/reasoningEngines/5516874359156768768` |
| Data Agent | `projects/ptpl-land-dev/locations/global/dataAgents/agent_4df3074b-9d7e-4f9f-993b-b3969b8a2095` |
| ID Authorization | `mia-bigquery` |
| Akun pengguna | `mirptpl@gmail.com`, `jason.kusuma@mii.co.id` |

**Tidak ada role baru untuk service account.** Role BigQuery dan Data Agent untuk service account tidak dipakai.

Perkiraan waktu: 20–30 menit.

---

## Langkah 0 — Perbarui repo (laptop)

Ekstrak `ge-library-agent.zip` terbaru ke repo, lalu push:

```bash
cd agent-bei-csls
git pull
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
rm -rf /tmp/gla && unzip -q ~/Downloads/ge-library-agent.zip -d /tmp/gla
cp -r /tmp/gla/ge-library-agent/. .
git add -A && git commit -m "Data BigQuery atas nama user (OAuth)" && git push
```

**Checkpoint:** folder `scripts/` berisi `enable_user_auth.py`.

---

## Langkah 1 — Consent screen (Konsol, sekali saja)

Kenapa perlu: agent custom wajib memakai OAuth client milik project, dan Konsol mewajibkan consent screen sebelum OAuth client bisa dibuat. (Data Agent bawaan Google tidak perlu, karena memakai OAuth client milik Google.)

1. Konsol → pilih project **ptpl-land-dev** → **Google Auth Platform** (atau **APIs & Services → OAuth consent screen**) → **Get started**.
2. **App information**
   - App name: `Marketing Insight Assistant`
   - User support email: email Anda
3. **Audience:** pilih **External**
   (kedua akun pengguna berada di luar organisasi project).
4. **Contact information:** email Anda → centang persetujuan → **Create**.
5. Buka menu **Audience** → klik **Publish app** → **Confirm**.
   Status menjadi **In production**: otorisasi tidak kedaluwarsa tiap 7 hari dan tidak perlu mendaftarkan test user.

Jika consent screen ternyata sudah pernah dibuat, pastikan saja **Audience = External** dan status **In production**.

---

## Langkah 2 — OAuth client (Konsol)

1. **APIs & Services → Credentials → + Create credentials → OAuth client ID**.
2. **Application type:** `Web application`
3. **Name:** `Marketing Insight Assistant GE`
4. **Authorized redirect URIs** → **+ Add URI** dua kali:
   - `https://vertexaisearch.cloud.google.com/oauth-redirect`
   - `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`
5. **Create** → di panel *OAuth client created* klik **Download JSON**.
6. Buka **Cloud Shell** → menu **⋮ → Upload** → pilih file JSON tadi.
   File tersimpan di folder home dengan nama berawalan `client_secret_`.

**Checkpoint:**
```bash
ls ~/client_secret_*.json
```
harus menampilkan satu file.

---

## Langkah 3 — Pasang Authorization ke agent (Cloud Shell)

```bash
cd ~/agent-bei-csls && git pull
source .venv/bin/activate && set -a && source .env && set +a
python scripts/enable_user_auth.py ~/client_secret_*.json
```

Yang diharapkan:
```
1/3 Membuat Authorization 'mia-bigquery' (200)
2/3 Pendaftaran ditemukan: 'Marketing Insight Assistant' di app <id-app>
3/3 Authorization terpasang pada pendaftaran agent.

Selesai. ID Authorization: mia-bigquery
```

| Hasil | Tindakan |
|---|---|
| `3/3 Authorization terpasang` | ✅ Lanjut ke langkah 4 |
| `GAGAL` di langkah 3/3 (pendaftaran tidak bisa diubah) | Jalankan **Rencana B** di bawah |
| `GAGAL` di langkah 1/3 atau 2/3 | Kirim pesan error-nya ke tim teknis |

**Rencana B** — buat pendaftaran baru yang sudah berisi Authorization:
```bash
python scripts/enable_user_auth.py ~/client_secret_*.json --register-new
```
Lalu di Konsol → **Gemini Enterprise** → klik app → **Agents**:
1. Buka agent **Marketing Insight Assistant** yang **baru** → bagikan ke `mirptpl@gmail.com` dan `jason.kusuma@mii.co.id`.
2. Hapus pendaftaran **lama** (yang tanpa Authorization) agar tidak muncul dua kali.

**Setelah berhasil, hapus file rahasia:**
```bash
rm ~/client_secret_*.json
```

---

## Langkah 4 — Update kode agent (Cloud Shell)

```bash
cd ~/agent-bei-csls && git pull && bash scripts/update_agent.sh
```
Tunggu sampai muncul `Selesai.` (5–10 menit). Jangan tekan `Ctrl+C`.

---

## Langkah 5 — Uji di Gemini Enterprise

1. Buka **chat baru** di **Marketing Insight Assistant**.
2. Saat diminta, klik **Authorize** → pilih akun.
3. Muncul peringatan *"Google hasn't verified this app"* → klik **Advanced** → **Go to Marketing Insight Assistant (unsafe)** → **Continue**.
   Peringatan ini normal untuk aplikasi internal yang belum diverifikasi Google (berlaku hingga 100 pengguna).
4. Kirim:
   ```
   Hitung rata-rata per liter pricelist, harga survei, dan gap produk Hero PTPL dibanding kompetitor Shell pada Juli 2026.
   ```

| Hasil | Arti | Tindakan |
|---|---|---|
| Angka dan tabel muncul | ✅ Berhasil | Lanjut ke skenario uji BigQuery di `PANDUAN_TESTING.md` |
| Agent meminta otorisasi | Token belum diterima agent | Buka chat baru dan klik Authorize. Jika tetap, cek bahwa ID Authorization adalah `mia-bigquery` (sama dengan `data_auth_id` di `settings.json`) |
| *"Akun Anda belum memiliki akses ke Data Agent atau tabel BigQuery"* | Akun user butuh izin API chat | Berikan **Gemini Data Analytics Stateless Chat User** (`roles/geminidataanalytics.dataAgentStatelessUser`) ke **akun user** di project `ptpl-land-dev` (IAM & Admin → IAM → Grant access). Tunggu 2–3 menit, coba lagi |
| Masih ditolak setelah itu | Izin lain akun user | Kirim pesan error dan jam kejadian ke tim teknis |
| *"Otorisasi akun Anda sudah kedaluwarsa"* | Token habis | Buka chat baru dan klik Authorize lagi |

---

## Catatan

- **Pengguna baru:** cukup bagikan agent ke akunnya di Gemini Enterprise. Saat pertama memakai data BigQuery, ia akan diminta Authorize. Akses datanya mengikuti akses akun tersebut.
- **Kembali ke service account** (tanpa deploy): ubah `"data_auth_mode": "service_account"` di `gs://ptpl-ge-bucket/ge-docs-agent/config/settings.json`, lalu berikan role service account di `PANDUAN_SETUP.md` bagian 2.4.
- **Mengganti OAuth client** (mis. secret bocor): buat client baru (langkah 2), lalu jalankan ulang langkah 3. Authorization `mia-bigquery` akan diperbarui.
