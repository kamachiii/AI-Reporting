# AGENTS.md — Panduan untuk AI Agent & Engineer yang Melanjutkan Repo Ini

> Pintu masuk pertama. Jika kamu AI agent yang baru "bangun" di repo ini: baca file ini
> sampai habis SEBELUM menulis kode apa pun, lalu ikuti urutan baca di §2.
> Aturan emas repo ini: **jangan klaim selesai tanpa bukti** (exit code / output test nyata).

---

## 1. Apa ini

**DMS AI Platform** — platform multi-tenant (proyek PKL) yang menjawab pertanyaan bahasa
natural dengan data nyata dari database per-cabang (dealer), dengan keamanan enterprise:

- **Bukan text2sql murni.** Arsitektur **dua tier** (desain final:
  `docs/PERANCANGAN-PIPELINE-AI-v2.md`):
  - **Tier 1** — LLM membuat *rencana JSON* → SQL dikomposisi deterministik (`sql_composer`).
  - **Tier 2** — LLM menulis SQL bebas, tapi WAJIB lolos **verifier 6 gerbang**
    (default-deny) + eksekusi terkurung (read-only, timeout, cap baris). Aktif per tenant
    lewat flag `chat_tier2`, dan hanya bisa diaktifkan setelah **eval golden-set lulus**
    (pass ≥ 95% & 0 pelanggaran verifier — dijaga kode, bukan disiplin).
- **SQL Memory** — jawaban yang dikonfirmasi user ("Jawaban benar") diputar ulang persis
  (0 panggilan LLM, Level Keyakinan A).
- **Presenter + NUMBER CHECK** — ringkasan naratif yang angkanya dijamin tidak dikarang
  (mekanis, format Indonesia; gagal → fallback template).
- **Stack**: FastAPI + asyncpg (backend), React 19 + Vite + Tailwind 4 (frontend),
  PostgreSQL core di Docker + database tenant eksternal.

## 2. Status saat ini & urutan baca

**Status (2026-09-02): arsitektur v2 KOMPLET dan LIVE** — sudah dipakai nyata via browser
(login user → pertanyaan → SQL → data nyata). Head: `2466052`. Test: **458 passed**.

Urutan baca (semua di `docs/`):

1. **`PROGRES-IMPLEMENTASI.md`** — PALING PENTING. Status per fase + commit, detail
   teknis per fase (§3a–3g: kontrak API, keputusan, bug yang pernah terjadi), jebakan
   teknis (§4), checklist verifikasi standar (§5), sisa kerja (§6).
2. **`PERANCANGAN-PIPELINE-AI-v2.md`** — desain final yang disetujui owner (dua tier,
   verifier, SQL Memory, taxonomy kegagalan, keputusan domain: hanya role `user` yang
   boleh chat). v1 (`PERANCANGAN-PIPELINE-AI.md`) masih acuan bentuk Knowledge Base.
3. `Readme.md` — arsitektur umum & setup awal (sedikit drift utk endpoint baru; yang
   benar ada di kode + PROGRESS §3).

## 3. Kontrak teknis yang TIDAK boleh dilanggar

**Backend:**
- Python yang benar: `backend\.venv\Scripts\python.exe` — python global TIDAK punya pytest.
- Semua query asyncpg **parameterized** (`$1, $2, ...`) — tanpa eksepsi.
- Auth: pakai dependency `require_admin_role` / `require_user_role` yang ada (chat =
  user guard; admin → 403 di chat). Jangan bikin mekanisme auth baru.
- Koneksi ke DB tenant **WAJIB lewat `tenant_pool.py`** (interface tunggal, siap
  deployment agent-outbound).
- Migration: penomoran lanjut (`011`, `012`, ...), **idempotent**, komentar TIDAK BOLEH
  mengandung karakter `;` (init_db memecah file per `;` — 2x insiden nyata), rollback
  terpisah `*_rollback.sql` (di-skip otomatis oleh init_db).
- Verifier (`sql_guard.py`, `query_verifier.py`) bersifat **default-deny**. Menambah
  kemampuan = revisi profil versioned (`SQL_FEATURE_PROFILE_V1`) + test katalog serangan,
  BUKAN membuka bypass.
- Response chat selalu menyertakan SQL (transparansi) + audit selalu ditulis (sukses &
  gagal).

**Frontend:**
- Token tema existing (`bg-canvas`, `border-hairline`, `font-serif`, `bg-surface-soft`,
  `text-primary`, `surface-card`...) — jangan import palet Tailwind default liar.
- `npm run lint`: 0 error wajib; file BARU/UBAHAN harus 0 warning (warning pre-existing
  di file Admin/App lama boleh). `npm run build` harus exit 0.
- Tidak menambah dependency tanpa kebutuhan nyata (backend & frontend sama).

**Proses:**
- 1 commit per fase, pesan `feat(scope)/fix(scope): ...` bahasa Indonesia.
- **Update `docs/PROGRES-IMPLEMENTASI.md` SETIAP selesai fase** (baris status + section
  detail §3x baru). Dokumen itu adalah memori lintas-sesi.
- UI chat role `user`; admin tidak chat (keputusan domain owner, v1 §7).

## 4. Checklist verifikasi (jalankan tiap selesai fase)

```powershell
# Backend (dari backend/)
.venv\Scripts\python.exe -m compileall app          # exit 0
.venv\Scripts\python.exe -m pytest tests/ -q        # semua passed (458 saat ini)
# Frontend (dari frontend/)
npm run lint                                        # exit 0, 0 error
npm run build                                       # exit 0
# Bila fase menyentuh skema/migration (dari backend/)
.venv\Scripts\python.exe init_db.py                 # jalankan 2x — harus idempotent
```

## 5. Menjalankan dev stack

```powershell
docker compose up -d                                    # postgres:15 core (port 5433)
cd backend; .venv\Scripts\python.exe init_db.py         # skema + migrasi + seed
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd ..\frontend; npm run dev                             # http://localhost:5173
```

- Akun: `admin/admin123` (panel admin) · `tester01/tester123` (user → cabang TST_01 →
  DB "DB Backup" = `backup_demo_otobitzcloud`, **2.387 tabel**) · `user_jkt/user123`
  (JKT_01 → `aleza-si`).
- Database tenant nyata ada di host (port 5432), core di Docker (5433).
- Config AI per user > tenant > global (Fernet-encrypted di `ai_configs`).
  Batas provider nyata: Groq free TPM 8.000; B.AI punya daily activity limit (503).

## 6. Arsitektur alur (gambaran 1 menit)

```
user (allowed_branches) → /chat/query
  → rate limit → load tenant+KB → SKEMA EFEKTIF (tabel_diizinkan − tabel_dilarang,
     kolom_dikecualikan; skema >150 tabel tanpa allowlist = tolak cepat)
  → SQL Memory replay (approved, pertanyaan ternormalisasi; verifier TETAP jalan;
     entri tier2 dengan literal tanggal = MISS anti-data-basi)
  → MISS: planner LLM (rencana JSON, retry 1x) ── flag chat_tier2 ON → tier2_generator
     (router tier1/tier2 1 panggilan, self-repair maks 2x; Tier2Error → fallback tier1)
  → composer (SQL parameterized) → VERIFIER gerbang #1–#5 (+EXPLAIN pre-flight)
  → EXECUTOR gerbang #6 (READ ONLY, timeout 10s, cap 500) → PRESENTER (number check)
  → memory pending → audit selalu → response {source: memory|tier1|tier2,
     confidence: A|B|C, sql, params, rows, ringkasan, saran, metode, attempts}
```

Detail kontrak & keputusan: `PROGRESS §3a–3g`.

## 7. Sisa kerja / keputusan terbuka

- **F5** — mode laporan + export PDF (belum mulai).
- **F6** — hardening: kuota token harian per tenant (kolom sudah ada), Redis rate limit
  (rate limit sekarang in-memory single-instance), cache skema, metrik mingguan ke admin.
- Keputusan terbuka desain: `PERANCANGAN-PIPELINE-AI-v2.md` §11 (normalisasi replay
  masih longgar: lowercase+strip tanda baca — pertanyaan beda kapitalisasi-angka dianggap
  beda; retensi; number check numerik).
- Kebersihan repo (butuh approval user): `git rm --cached frontend/test-results/.last-run.json`
  (ter-track padahal di-gitignore, selalu muncul modified); 3 folder `backup_*/` di root
  sebaiknya dipindah keluar repo; `backend/backups/` berisi dump pg_dump yang menumpuk.
- README perlu sinkronisasi endpoint baru (KB, tier2, eval, chat).

## 8. Jebakan yang pernah nyata (detail & pelajaran: PROGRESS §4)

1. Komentar SQL migration memuat `;` → syntax error saat init_db (2x terjadi).
2. File besar dari run AI terputus → wajib smoke-test dini, jangan tunggu "selesai".
3. Model API merespons 413/429/503 → itu batas provider (TPM/kuota), bukan bug sistem;
   error tetap harus ter-audit dan pesan ke user tetap ramah.
4. Kolom tabel besar & prompt padat: skema efektif + format kolom `nama:tipe` sudah
   menyelesaikan limit TPM — jangan kembalikan prompt verbatim array-of-objects.
5. `git status` yang selalu menampilkan `frontend/test-results/.last-run.json` modified
   itu pre-existing — abaikan, jangan ikut di-commit.

---

*File ini di-maintain seperti kode: ubah lewat commit, jangan edit diam-diam di production
branch. Terakhir diperbarui: 2026-09-02 (setelah F2.7 eval harness — head `2466052`).*
