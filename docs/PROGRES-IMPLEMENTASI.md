# Progres Implementasi — DMS AI Platform (Pipeline AI v2)

> Dokumen kontinuitas: dibaca PERTAMA kali oleh AI/engineer yang melanjutkan kerja.
> Update dokumen ini SETIAP selesai satu fase. Jangan hapus riwayat — tambahkan.
> Terakhir diperbarui: 2026-09-01 (F2.3' selesai).

## 0. Cara cepat paham konteks (5 menit)

1. Baca `docs/PERANCANGAN-PIPELINE-AI-v2.md` — desain final yang disetujui owner (dua tier:
   Tier 1 constrained composer + Tier 2 verified text2sql, verifier 6 gerbang, SQL Memory,
   taxonomy kegagalan, rollout order). Dokumen v1 (`PERANCANGAN-PIPELINE-AI.md`) masih berisi
   acuan bentuk Knowledge Base (§3), model deployment, dan skalabilitas dasar.
2. Baca `Readme.md` untuk arsitektur umum, setup, dan ERD.
3. Keputusan owner yang mengikat (dari diskusi 2026-08-31):
   - Desain v2 disetujui sebagai dasar eksekusi, bertahap, wajib verifikasi tiap fase.
   - Default TANPA antrean persetujuan admin untuk SQL baru (mode `auto`, §7 v2) —
     keamanan dari verifier, bukan persetujuan manusia.
   - UI chat role `user` sudah ada (mock) — dibangun lebih dulu atas permintaan owner.

## 1. Urutan kerja yang disepakati (dari v2 §10)

```
F2.0  Knowledge base                 ← SELESAI (lihat §3)
F2.3' Verifier v2 (gerbang #1–#5)    ← SELESAI (lihat §3b)
F2.2  SQL Composer Tier 1            ← BERIKUTNYA
F3    Chat API (Tier 1 + SQL Memory replay)
F2.5  Generator Tier 2 + SQL Memory tulis + eval harness
F4    UI chat lengkap (level keyakinan, lihat SQL, feedback)
F5    Mode laporan + export
F6    Hardening (kuota, Redis rate limit, cache, metrik)
```

## 2. Status fase

| Fase | Status | Commit | Catatan |
|---|---|---|---|
| UI chat user (mock, data mockChat.js) | ✅ | `0b098fb` | Kontrak `askAssistant()` di `frontend/src/services/mockChat.js` — saat F3 tinggal tukar ke API nyata, UI tidak berubah |
| Draft desain v2 disetujui | ✅ | `0b098fb` | `docs/PERANCANGAN-PIPELINE-AI-v2.md` |
| **F2.0 Knowledge Base** | ✅ | (lihat git log) | KB = JSONB `tenants.knowledge_base`; endpoint admin CRUD + dry-run validate; 20 test unit; round-trip HTTP lolos; migration idempotent 2x |
| **F2.3' Verifier v2** | ✅ | (lihat git log) | Gerbang #1–#4 offline (`sql_guard.verify_sql`) + #5 EXPLAIN (`query_verifier.verify_query`); 30 kasus positif + 49 kasus serangan; 163 test lulus; `tabel_dilarang` KB terintegrasi |
| F2.2 Composer | ⬜ belum | — | |
| F3 Chat API | ⬜ belum | — | Juga: sambungkan `askAssistant` mock → endpoint; pindahkan pipeline stage names |
| F2.5 Tier 2 + eval | ⬜ belum | — | Jangan mulai sebelum verifier teruji |

## 3. Detail F2.0 (yang baru selesai) — penting untuk lanjutan

**Skema KB** (`tenants.knowledge_base`, JSONB, NULL = kosong):
```jsonc
{
  "glossary":      [{"istilah": "omzet", "arti": "SUM(penjualan.harga_deal)"}],
  "catatan_kolom": {"penjualan.harga_deal": "Harga final setelah negosiasi"},  // dict-of-string
  "nilai_map":     {"penjualan.metode_pembayaran": {"cash": "tunai"}},          // dict-of-dict
  "contoh_tanya":  [{"tanya": "omzet bulan ini", "tabel": ["penjualan"], "agg": "sum(harga_deal)", "time_range": "this_month"}],
  "tabel_dilarang": ["log_audit_internal"]
}
```

**File kunci:**
- `backend/app/services/knowledge_base.py` — `load_kb` (NULL/rusak → struktur kosong),
  `validate_kb(payload) -> (clean, errors)` (validasi ketat, error per indeks).
- `backend/app/routers/admin/knowledge_base.py` — `GET/PUT /admin/tenants/{branch}/knowledge-base`,
  `POST .../validate` (dry-run, tidak menyimpan). Guard: `require_admin_role` (pola sama router lain).
- `backend/sql/migrations/005_knowledge_base.sql` + `005_knowledge_base_rollback.sql`.
- Frontend: tombol "Knowledge Base" per baris tenant (`TenantConnectionsTable.jsx`) →
  `KnowledgeBaseModal.jsx` (textarea JSON + tombol Validasi/Simpan).
- `backend/init_db.py` — +guard: file `*_rollback.sql` di-skip oleh loop migrasi.

**Keputusan kecil yang sudah diambil (jangan diubah tanpa alasan):**
- `catatan_kolom` = dict-of-string, `nilai_map` = dict-of-dict (mengikuti bentuk v1 §3).
- Field tak dikenal = error validasi (bukan diabaikan).
- `tabel_dilarang` HANYA disimpan — integrasi ke whitelist verifier adalah bagian F2.3'.
- Endpoint validate tidak mengecek eksistensi tenant (dry-run murni).
- `updated_at` yang ditampilkan = `tenants.updated_at` (bukan khusus KB).

## 3b. Detail F2.3' (yang baru selesai) — penting untuk lanjutan

**File kunci:**
- `backend/app/services/sql_guard.py` — DUA API dalam satu file:
  - `validate_readonly_query(sql, allowed_tables)` (F2.3 lama) **tidak diubah sama sekali**
    (kompatibel pemanggil lama; saat ini hanya dipakai test).
  - `verify_sql(sql, schema_config, kb_forbidden=None, budget=None) -> Verdict`
    (F2.3') — gerbang offline #1–#4, TANPA DB. Verdict = `{ok, gate, reason, detail}`;
    `gate` = `"bentuk"|"whitelist"|"profil"|"budget"` (None bila lolos);
    `detail["final_sql"]` = SQL siap eksekusi (LIMIT 500 dipaksa).
- `backend/app/services/query_verifier.py` — `verify_query(sql, schema_config,
  tenant_conn_factory, kb_forbidden=None)` — gerbang #1–#4 lalu #5 EXPLAIN
  pre-flight (`EXPLAIN (FORMAT JSON)`; cost ≤ 100_000, rows ≤ 500_000;
  EXPLAIN gagal = TOLAK). TIDAK mengeksekusi query (itu F2.4, gerbang #6).
- `backend/tests/conftest.py` — fixture `schema_config_dealer` (bentuk
  `schema_config_json` ala dealer_dummy: 5 tabel + FK), dipakai test verifier tanpa DB.
- `backend/tests/test_sql_guard.py` — + `TestVerifierV2` (30 positif, 49 serangan).
- `backend/tests/test_query_verifier.py` — gerbang #5 dengan fake conn factory (11 test).

**Keputusan teknis yang diambil (review bila perlu):**
- Nama gerbang Verdict pakai bahasa Indonesia: `bentuk`, `whitelist`, `profil`,
  `budget`, `explain` — nyambung dengan audit log & self-repair (reason = umpan balik).
- Profil fitur `SQL_FEATURE_PROFILE_V1` (dict publik + `PROFILE_VERSION`):
  whitelist node AST sqlglot (struktur/agregasi/fungsi string & tanggal umum
  postgres) + `exp.Anonymous` eksplisit hanya `replace` + denylist eksplisit
  (pg_sleep, dblink, pg_read_file, pg_ls_dir, lo_import/export, DDL/DML,
  RECURSIVE, UNION dedup, CROSS JOIN, window function, HAVING, OFFSET, EXISTS).
  Node AST yang tidak tercantum = tolak (default-deny).
- Kolom divalidasi per-scope postgres: unquoted = case-insensitive, quoted =
  case-sensitive. Kolom unqualified ambigu dalam satu scope = tolak (minta
  kualifikasi). Korrelasi subquery ke scope luar diizinkan; korrelasi MELINTASI
  batas CTE dihentikan (sesuai semantik postgres).
- CTE/subquery ber-`SELECT *`: kolom output tidak bisa diinfer → fallback
  "kolom ada di tabel basis di dalam body-nya"; ambiguitas yang tak pasti
  diserahkan ke gerbang #5 (EXPLAIN mengecek DB sungguhan, fail-closed).
- JOIN wajib ON/USING dan kedua sisi harus terhubung FK skema (dua arah);
  self-join tabel yang sama diizinkan; JOIN dengan CTE/subquery dilewati dari
  cek FK (biayanya ditangkap gerbang #4/#5).
- Budget default: kedalaman_ast 12 (semua node termasuk daun — konservatif),
  join 6, CTE 4, UNION 3; bisa dioverride per panggilan (`budget={...}`).
- `tenant_conn_factory` = async callable () -> koneksi; verifier TIDAK menutup
  koneksi (pemilik pool yang mengelola) — kontrak terdokumentasi di docstring.

## 4. Pelajaran teknis & jebakan (baca sebelum menyentuh backend)

1. **Python yang benar**: `backend\.venv\Scripts\python.exe` (venv proyek). Jangan pakai
   python global — tidak ada pytest di sana.
2. **init_db memecah file SQL per `;`** — KOMENTAR di file migration TIDAK BOLEH mengandung
   `;` di tengah kalimat (pernah memicu syntax error di migration 005, sudah diperbaiki).
3. **Loop migrasi menjalankan semua `*.sql` di `migrations/` urut nama** — penomoran file
   baru harus lanjut (006, 007, ...), dan jangan taruh SQL non-migration di folder itu.
4. **Guard admin**: selalu pakai dependency `require_admin_role` yang sama dengan router
   admin lain — jangan bikin mekanisme auth baru.
5. **Semua query asyncpg wajib parameterized** ($1, $2, ...) — tidak ada eksepsi.
6. **Frontend**: React 19 + Tailwind 4 + token tema custom (`bg-canvas`, `border-hairline`,
   `font-serif`, `bg-surface-soft`, `text-primary` — lihat komponen Admin). Lint gate CI:
   0 error wajib (warning boleh, tapi file BARU harus 0 warning). `npm run build` harus exit 0.
7. **CI**: frontend lint+build; backend compileall + import app.main + pytest. Playwright e2e
   TIDAK jalan di CI (manual saja). Snapshot visual berbasis win32.
8. Migration 005 sudah ter-apply ke DB dev docker (`dms_pg`) + teruji idempotent 2x.
   Kolom KB di DB dev sengaja dikembalikan NULL setelah round-trip test.

## 5. Checklist verifikasi standar (jalankan SETIAP selesai fase)

```powershell
# Backend (dari backend/, pakai .venv)
.venv\Scripts\python.exe -m compileall app              # exit 0
.venv\Scripts\python.exe -m pytest tests/ -q            # exit 0, semua passed
# Frontend (dari frontend/)
npm run lint                                            # exit 0, 0 error
npm run build                                           # exit 0
# Integrasi DB (bila fase menyentuh skema/migrasi)
.venv\Scripts\python.exe init_db.py                     # exit 0, jalankan 2x untuk idempotency
```

Konvensi commit: `feat(scope): ...` / `fix(scope): ...` bahasa Indonesia, 1 commit per fase.

## 6. Yang sedang / belum dikerjakan (jangan lupa)

- [x] F2.3' Verifier v2: gerbang #2 whitelist AST menyeluruh, #3 profil fitur versioned,
      #4 budget kompleksitas, #5 EXPLAIN pre-flight — SELESAI (lihat §3b).
      `tabel_dilarang` dari KB sudah terintegrasi (parameter `kb_forbidden`).
- [ ] F2.4 Executor: eksekusi terkurung (gerbang #6) memakai
      `query_verifier.verify_query` — verdict + `detail["final_sql"]` sudah disiapkan.
- [ ] Keputusan terbuka v2 §11 (ambang eval 95%, normalisasi replay, retensi, number check numerik).
- [ ] Pembersihan repo (belum tereksekusi): `git rm --cached frontend/test-results/.last-run.json`
      (file ter-track padahal sudah di .gitignore); 3 folder `backup_*` root dipindah ke
      `D:\Kerja PKL\arsip-backup` (terblokir Safety Guard saat itu, butuh approval ulang).
- [ ] README perlu update tabel endpoint (tambah KB endpoints + branches-with-tenants +
      ai-configs/test-all yang belum tercantum).

## 7. Cara menjalankan untuk uji manual

```powershell
docker compose up -d                    # postgres:15 (5433) + redis
cd backend; .venv\Scripts\python.exe init_db.py
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
cd ..\frontend; npm run dev             # http://localhost:5173
# akun: admin/admin123 · user_jkt/user123 (chat UI: login user_jkt)
```
