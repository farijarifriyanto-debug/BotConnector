# HANDOFF — BotConnector AI Workspace (Study AI & Coding AI)

Hub alat AI ringan (teks) untuk publik: **UMKM, pelajar, umum**. Dibuat 2026-08-06.
VPS **103.58.101.207** (user `botadmin`).

============================================================
## 1. AKSES
- **URL:** https://botconnector.id/workspace  (juga kartu "AI Workspace" di homepage)
- **Publik & gratis** (rate-limited). Mode **"Bagus"** (bisa pakai DeepSeek berbayar) **khusus admin**.
- Login admin (untuk "Bagus"): https://botconnector.id/panel (akun admin@botconnector.id). Cookie admin `bc_admin` domain-wide → Workspace otomatis tahu kamu admin.

============================================================
## 2. ARSITEKTUR
```
User → botconnector.id/workspace (nginx, rate-limit)
     → AI Workspace (127.0.0.1:18170, FastAPI)
        ├── /api/study    (tools/study.py)
        ├── /api/coding   (tools/coding.py)
        ├── /api/extract  (tools/extract.py — baca PDF/Word/TXT)
        └── semua ke AI Gateway 127.0.0.1:18130  (multi-provider; free→paid)
```
- **Gate biaya:** `_gate()` di app.py memaksa `task="main"` → `"fast"` kalau bukan admin (cek cookie `bc_admin` pakai `ADMIN_SECRET` bersama). Jadi publik cuma kena free tier.
- **Rate-limit:** nginx `limit_req zone=ws_ai 30r/m burst=8` di `/workspace/api/`.

============================================================
## 3. LOKASI & SERVICE
- Folder: `~/ai-workspace/` (VPS, user botadmin)
- Service systemd: **`ai-workspace`** (enabled, auto-restart) · uvicorn `127.0.0.1:18170`
- Venv: `~/ai-workspace/venv` (fastapi, uvicorn, httpx, python-multipart, pypdf, python-docx)
- Env: `~/ai-workspace/.env` (chmod 600) → `ADMIN_SECRET` (SAMA dengan admin-gate)
- nginx: `botconnector-cutover.conf` (blok botconnector.id) — `location = /workspace` redirect, `location ^~ /workspace/api/` (rate-limit) + `^~ /workspace/`. Zona `limit_req_zone ws_ai` di atas file. Backup: `/root/nginx-backups/`.
- Kartu homepage: `/var/www/studio-card.js` (kartu "AI Workspace", di-inject nginx sub_filter).

============================================================
## 4. FILE (di ~/ai-workspace/)
| File | Fungsi |
|---|---|
| `app.py` | FastAPI: routes /api/study, /api/coding, /api/extract, /api/admin/status, serve SPA. Admin-gate + `_gate`. |
| `tools/study.py` | Study AI: mode ringkas/jelaskan/tanya (teks), flashcard/kuis (JSON), via gateway |
| `tools/coding.py` | Coding AI: mode buat/jelaskan/debug/konversi/tanya (markdown + blok kode) |
| `tools/extract.py` | Ekstrak teks PDF (pypdf) / DOCX (python-docx) / TXT |
| `tools/__init__.py` | penanda package |
| `static/index.html` | SPA: hub (kartu) + view Study + view Coding |
| `ai-workspace.service` | unit systemd |
| `.env` | ADMIN_SECRET |

Salinan file juga di laptop scratchpad `ai-workspace/`.

============================================================
## 5. KONTRAK API (di bawah /workspace, nginx strip prefix)
- `POST /api/study {mode, text?, question?, task}` → `{type, content|items, _meta, _gated?}`
  - mode: `ringkas`|`jelaskan`|`tanya` → `type:"text"` (`content`)
  - mode: `flashcard` → `type:"cards"` (`items:[{q,a}]`)
  - mode: `kuis` → `type:"quiz"` (`items:[{q,options[4],answer,why}]`)
- `POST /api/coding {mode, code?, desc?, lang?, extra?, question?, task}` → `{type:"code", content(markdown), _meta, _gated?}`
  - mode: `buat`(pakai desc+lang) | `jelaskan`|`debug`(pakai code, extra=error) | `konversi`(code→lang) | `tanya`(question)
- `POST /api/extract` (multipart `file`) → `{text, chars, name}` (PDF/DOCX/TXT, maks 15MB)
- `GET /api/admin/status` → `{admin, login}`
- `GET /health`

`task`: `"fast"` (gratis) / `"main"` (Bagus; non-admin otomatis diturunkan ke fast → `_gated:true`).

============================================================
## 6. FITUR (LIVE & teruji)
**📚 Study AI** — target pelajar. Tempel materi ATAU **upload PDF/Word/TXT** → 📝 Ringkas · 🃏 Flashcard (klik utk balik) · ❓ Kuis (interaktif, cek jawaban + alasan) · 💡 Jelaskan · 💬 Tanya. PDF scan → pesan arahkan ke Document Assistant (OCR).
**💻 Coding AI** — target umum/dev. 💡 Buat kode (pilih bahasa) · 📖 Jelaskan · 🐛 Debug (+pesan error) · 🔄 Konversi (ke bahasa lain) · 💬 Tanya. Output blok kode + tombol **salin**.
Keduanya: gratis (free tier), "Bagus"(DeepSeek) khusus admin.

============================================================
## 7. NAMBAH ALAT BARU (REUSABLE — mis. Business AI berikutnya)
Kerangka sudah siap; 1 alat baru = ~3 langkah:
1. `tools/<nama>.py` — fungsi `run(mode, ..., task)` yang manggil gateway (contoh: study.py/coding.py).
2. `app.py` — tambah `<Nama>Req(BaseModel)` + `@app.post("/api/<nama>")` yang panggil `_gate(request, req.task)`.
3. `static/index.html` — aktifkan kartunya (hapus `soon`, `onclick=open<Nama>()`) + tambah view + fungsi JS.
Deploy: scp → `sudo systemctl restart ai-workspace`. Semua (gateway, admin-gate, rate-limit, homepage) otomatis berlaku.

============================================================
## 8. MAINTENANCE / CATATAN
- Ubah kode → scp ke `~/ai-workspace/` → `sudo systemctl restart ai-workspace`.
- Log: `journalctl -u ai-workspace -n 50`.
- Model default AI diatur di **AI Gateway** (:18130), bukan di sini.
- **Ketahanan JSON:** flashcard/kuis retry 1x kalau model keluarkan JSON cacat.
- **Rate-limit** publik 30 req/menit/IP (ubah di nginx `zone=ws_ai`).
- Batas materi ke LLM: 60.000 karakter (extract.py `MAX_CHARS`).

============================================================
## 9. BELUM ADA (kandidat berikutnya)
- **💼 Business AI** (masih "Segera" di hub) — caption/deskripsi produk/nama+slogan/rencana bisnis. Pola sama, cepat.
- Upload file di Coding (mis. tempel file kode) — opsional.
- Riwayat/simpan hasil (sekarang stateless).
- Monetisasi: akun user + pembayaran + kuota per-user (fase 2; sekarang gratis + Bagus-admin).
- Login user biasa (bukan cuma admin) untuk tier menengah.

Terkait: Admin Gate `~/admin-gate/README.md` · AI Gateway `~/ai-orchestrator/`.
