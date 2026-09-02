# Progres Implementasi — DMS AI Platform (Pipeline AI v2)

> Dokumen kontinuitas: dibaca PERTAMA kali oleh AI/engineer yang melanjutkan kerja.
> Update dokumen ini SETIAP selesai satu fase. Jangan hapus riwayat — tambahkan.
> Terakhir diperbarui: 2026-09-02 (F2.7 eval harness selesai — janji desain v2 tuntas).

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
F2.2  SQL Composer Tier 1             SELESAI (lihat 3c)
F2.4  Query Executor (gerbang #6)        SELESAI (lihat 3d)
F3    Chat API (Tier 1 + SQL Memory replay) SELESAI (lihat 3d)
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
| **F2.2 Composer** | selesai | (lihat git log) | `sql_composer.py`: `validate_plan` + `compose_sql` (deterministik, params $1..$n, auto-join FK path, preset waktu dari `now`, belt-and-suspenders `verify_sql`); 91 test baru (total 254); 4 cacat dari run terputus ditemukan & diperbaiki (lihat 3c) |
| **F2.4 + F3 Executor & Chat API** | selesai | `7b09158` | Pipeline end-to-end: planner LLM (retry 1x, config user>tenant>global) -> composer -> verifier -> executor (READ ONLY + timeout 10s + cap 500); POST /chat/query + GET /chat/history (guard user, isolasi allowed_branches, rate limit); sql_memory replay (verifier tetap jalan, auto-stale); 62 test baru (total 316); smoke nyata vs DB tenant (source=memory, rows nyata) |
| **F4 UI chat nyata + skema efektif** | selesai | `6961f3a` | UI chat -> POST /chat/query (badge keyakinan, Lihat SQL, Jawaban benar/salah); KB `tabel_diizinkan`+`kolom_dikecualikan` -> skema efektif per tenant (DB 2.387 tabel terkelola); prompt planner dipadatkan 37.648->9.109 chars (lolos TPM); live: Groq/GLM tier1 B + replay memory A |
| **F2.5 Presenter + Number Check** | selesai | `653ea0c` | `presenter.py`: ringkasan maks 2 kalimat + saran lanjutan; NUMBER CHECK id-ID (ribuan titik/desimal koma/persen) — angka karangan ditolak, 1x retry, fallback template; migration 007 (sql_memory.ringkasan+saran); replay pakai cache = 0 LLM, self-heal bila kosong; UI: paragraf ringkasan + chip saran; 385 test |
| **F2.6 Tier 2 Verified Text2SQL** | selesai | `238ad2d` | Generator 1-panggilan router tier1/tier2 + self-repair maks 2x (feedback verifier); flag `chat_tier2` per tenant (default OFF, toggle admin UI); tier2 = source tier2/Level C/attempts; replay tier2 dgn literal tanggal = MISS; fallback tier1 otomatis; 410 test |
| **F2.7 Eval Harness Golden-Set** | selesai | `2df6c41` | eval_cases (009) + eval_runs (010); jalankan_eval (persis/semantik/pelanggaran), status_gate pass>=95% & 0 pelanggaran; toggle Tier 2 kini wajib lolos gate; admin CRUD eval-cases + eval-run + riwayat; 458 test |
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

## 3c. Detail F2.2 SQL Composer (yang baru selesai) - penting untuk F3

**Kontrak rencana JSON (dipakai prompt planner F3):**
```jsonc
{
  "tables":   ["penjualan", "kendaraan"],   // >=1; tables[0] utama; sisanya via FK path
  "columns":  ["penjualan.tanggal", {"agg": "SUM", "column": "penjualan.harga_deal", "alias": "omzet"}],
  "filters":  [{"column": "penjualan.metode_pembayaran", "op": "eq", "value": "cash"}],
  "time_range": {"field": "penjualan.tanggal", "preset": "this_month"},  // ATAU {"field", "from", "to"}
  "group_by": ["kendaraan.merek"],
  "order_by": [{"by": "omzet", "dir": "DESC"}],  // by = alias SELECT atau kolom tabel
  "limit": 50,                                // clamp 1..500; default 200
  "distinct": false
}
```

**API:**
- `validate_plan(plan, schema_config) -> (clean_plan, errors)` - ketat, error per indeks.
- `compose_sql(plan, schema_config, now=None) -> {"sql", "params", "used_tables", "limit"}`
  - DETERMINISTIK (plan+now sama -> SQL byte-identik); urutan bagian selalu
    SELECT->FROM->JOIN->WHERE->GROUP BY->ORDER BY->LIMIT.
  - SEMUA nilai jadi parameter asyncpg $1..$n (urut: filter lalu time_range) -
    SQL string TIDAK PERNAH memuat nilai literal (injection via value terbukti aman).
  - Preset waktu dihitung dari `now` yang DI-INJECT pemanggil (keputusan TZ di pemanggil;
    preset tanpa now = error). `now` beda -> hanya PARAMS yang berubah, teks SQL sama.
  - Kolom wajib qualified `tabel.kolom`; tabel perantara auto-join via BFS FK path.
  - Belt-and-suspenders: hasil wajib lolos `verify_sql()` (sql_guard) - composer yang
    benar selalu lolos; gagal = raise (bug composer, bukan lubang keamanan).
  - `ganti_placeholder_null(sql)` HANYA untuk verifikasi offline (node Parameter belum
    terdaftar profil verifier v1) - JANGAN untuk eksekusi.

**Bug yang ditemukan & diperbaiki saat audit (file dari run terputus):**
1. `_fk_join_chain`: loop kedalaman meng-unpack entri root `{root: None}` -> TypeError
   (observed via smoke test). Fix: guard `entri is None`.
2. Cacat A: `validate_plan` membuang `value` filter di clean plan -> compose selalu gagal.
3. Cacat B1/B2: `op`/`preset` bertipe unhashable (mis. list) memicu TypeError, bukan
   error validasi. Fix: guard tipe -> masuk daftar errors.

**Test**: `backend/tests/test_sql_composer.py` - 91 kasus (32 fungsi, sebagian parametrize):
positif (semua preset, FK chain 3 tabel, auto-join perantara, clamp, distinct, field
presentasional tak memengaruhi SQL, urutan params), negatif (skema asing, agg/op asing,
alias jahat, field asing, FK tak terhubung & tak berarah, preset tanpa now, injection
masuk params bukan SQL), determinisme byte-per-byte.

## 3d. Detail F2.4 + F3 (yang baru selesai) - penting untuk F4/F2.5

**Alur POST /chat/query** (guard `require_user_role`, admin=403):
  body {question, branch_code} -> cek allowed_branches token (403) -> rate limit 10/60dtk
  -> load tenant by branch (join tenants+db_connections; 409 bila tak ada/nonaktif/belum
  introspeksi) -> resolve ai_config user>tenant>global (503 bila kosong)
  -> normalisasi pertanyaan (lowercase, tanda baca->spasi, collapse)
  -> memory HIT (approved): verify_and_execute SQL tersimpan (VERIFIER TETAP JALAN),
     params dihitung ulang dari plan_json (jendela waktu relatif); komposisi ulang !=
     SQL tersimpan / verifier menolak -> status stale + lanjut MISS
  -> MISS: plan_query (LLM #1, injectable llm_call_fn, retry 1x dgn feedback; PlanningError=502)
     -> compose_sql (now=TZ server) -> verify_and_execute -> upsert sql_memory pending
  -> conversation per user+branch + 2 pesan (assistant menyimpan SQL+rows JSON)
  -> audit SELALU (sukses/rejected/error) -> response {source, confidence, sql, params,
     columns, rows, row_count, truncated, duration_ms}

**Keputusan penting:**
- SQL berparameter: profil verifier v1 belum kenal node Parameter -> gerbang #1-#5 dijalankan
  pada teks NULL (ganti_placeholder_null); SEBELUM eksekusi struktur SQL asli dibuktikan
  identik dgn final_sql (parse, Parameter->Null, bandingkan render) - fail-closed.
- Konversi JSON: Decimal->float, date/datetime->ISO str, UUID/bytes->str.
- Row cap: fetch row_cap+1; lebih -> truncated=true (baris ke-501 dibuang).
- TenantPoolManager: LRU maks 8 pool, max_size=2, idle sweep 600dtk lazy; close_all saat
  shutdown; kredensial Fernet dari db_connections; interface tunggal (siap deployment B).
- Memory write: upsert berkunci (tenant, pertanyaan_ternormalisasi, sql); status tidak
  pernah diturunkan. Konfirmasi pending->approved = F4 (tombol 'Jawaban benar') / admin.
- Error map: PlanningError 502; verifier tolak 422 (gate+reason); timeout 504; tanpa
  config 503; tenant bermasalah 409; semua ter-audit.

**Bug yang tertangkap saat integrasi nyata (bukti smoke):**
1. Komentar migration 006 memuat ';' - jebakan 4.2 (sudah didokumentasi, terulang lagi).
2. get_pool mencari kunci 'id' vs baris join 'db_connection_id' - diterima keduanya.
3. _buat_pool KeyError 'id' - cid diresolusi eksplisit.
4. json.dumps pesan assistant gagal krn params berisi date - konversi sebelum simpan.

**Bukti integrasi nyata**: init_db 2x idempotent (006 ter-apply); uvicorn :8010; login
user_jkt; seed 1 entri approved; POST /chat/query -> source=memory, confidence=A,
rows=[[2]] (DB tenant aleza-si); admin 403; history 6 pesan; audit 3 sukses;
times_used=3; normalisasi tahan kapitalisasi & tanda baca. Jejak smoke dibersihkan.

**Belum dikerjakan (urutan berikutnya)**: F4 UI chat nyata (tukar askAssistant mock ->
POST /chat/query; tampilkan SQL+confidence; tombol 'Jawaban benar' -> endpoint konfirmasi
memory pending->approved); F2.5 presenter LLM #2 + number check; Tier 2 + eval harness.

## 3e. Detail F2.5 + status LIVE (2026-09-01)

- Sistem LIVE: UI browser -> chat API -> planner (GLM 5.3-flash via B.AI utk tester01;
  Groq pernah dipakai) -> composer -> verifier -> executor -> presenter -> DB Backup nyata
  (2.387 tabel). Data & jawaban tervalidasi live.
- Skema efektif per tenant: KB `tabel_diizinkan` (wajib utk skema besar; >150 tabel tanpa
  allowlist = 422 gate skema) + `kolom_dikecualikan` (sembunyikan kolom sensitif).
- Prompt planner padat: kolom `nama:tipe` satu string per tabel + FK `kol -> tabel.kol` +
  peta tipe singkat; 37.648 -> 9.109 chars (76% hemat) utk 11 tabel x 70 kolom.
- Presenter: LLM #2 ringkasan maks 2 kalimat + 2-3 saran; NUMBER CHECK mekanis id-ID;
  karangan -> retry 1x -> fallback template (fail-open, tidak pernah menggagalkan query);
  ringkasan di-cache di sql_memory (migration 007) -> replay 0 LLM; metode response:
  llm | template | cache.
- Konfigurasi AI: user > tenant > global; B.AI rate limit harian bisa 503
  (activity_cost_limit_reached) — error ter-audit; pemakaian live menyusul konfigurasi
  admin (UI chat sudah dipakai user nyata untuk pertanyaan pembelian/penjualan/customer).

## 3f. Detail F2.6 Tier 2 (arsitektur v2 KOMPLET)

- `tier2_generator.generate_sql`: SATU panggilan LLM -> {"tier":1,"plan":...} atau
  {"tier":2,"sql":...}; tier2 diverifikasi `verify_query` (EXPLAIN via conn_factory);
  gagal -> self-repair maks 2x (feedback gate+reason+output lama) -> Tier2Error.
- Pipeline: flag `tenants.chat_tier2` (default OFF; toggle POST /admin/tenants/{b}/tier2;
  GET admin tenants menyertakan flag). Flag ON: generator dipanggil dulu; tier1 hasil
  compose di-reuse (tidak compose 2x); tier2 -> verify_and_execute ULANG (defense in
  depth) -> source=tier2, confidence=C, attempts=N -> memory pending (sumber=tier2,
  plan_json={"tier2":true}) -> presenter normal. Tier2Error -> fallback alur tier1 lama;
  dua2nya gagal -> 502 pesan gabungan.
- Replay tier2: SQL dengan literal tanggal (regex YYYY-MM-DD / ::date) = MISS tanpa
  menghapus baris (anti data basi); tanpa literal -> replay normal (verify ulang).
- UI: chip 'Tier 2 ON/OFF' per tenant (Admin), badge 'SQL Kompleks (Level C)' +
  'N percobaan' di chat.
- BELUM: eval harness golden-set (gate aktivasi otomatis), metrik mingguan, kuota token.

## 3g. Detail F2.7 Eval Harness (2026-09-02)

- Golden set per tenant: tabel `eval_cases` (pertanyaan + sql_harapan; sql_harapan wajib
  lolos verify_sql saat dibuat/diedit — golden set salah tidak boleh masuk).
- `POST /admin/tenants/{b}/eval-run`: jalankan_eval memanggil pipeline internal per case
  (tanpa presenter), bandingkan SQL final vs harapan: `persis` (normalisasi: lowercase,
  spasi, kutip-ganda, LIMIT implisit) atau `semantik` (eksekusi keduanya, bandingkan hasil
  maks 20 baris, params dipakai utk SQL pipeline). Pelanggaran verifier dihitung terpisah.
- Snapshot ke `eval_runs`; `GET eval-runs?limit=5` riwayat.
- GATE: `status_gate` — Tier 2 hanya boleh diaktifkan bila run terakhir pass_rate>=95%
  & 0 pelanggaran; toggle menolak 400 + pesan alasan (belum pernah run -> 'jalankan eval
  dulu'). Ini melaksanakan janji v2 §8 secara mekanis.
- Alat regresi: eval TIDAK mengubah state (memory tidak di-stale saat eval).
- Sisa roadmap desain v2: hanya F5 (laporan+export PDF) & F6 (hardening: kuota token,
  Redis rate limit, cache skema, metrik mingguan) — keduanya peningkatan, bukan fondasi.

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
9. File besar dari run AI terputus WAJIB di-smoke-test dini (jangan tunggu semua selesai)
   - file 700+ baris F2.2 pertama ternyata mengandung 4 bug dan belum pernah dieksekusi.
   Sisa file probe/debug (`_*.py`) harus dibersihkan sebelum commit.
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
- [x] F2.2 SQL Composer Tier 1 - SELESAI (lihat 3c).
- [x] F2.4 Executor: gerbang #6 via `query_executor.verify_and_execute` - SELESAI (lihat 3d).
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
