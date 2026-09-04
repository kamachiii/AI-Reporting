# Progres Implementasi — DMS AI Platform (Pipeline AI v2)

> Dokumen kontinuitas: dibaca PERTAMA kali oleh AI/engineer yang melanjutkan kerja.
> Update dokumen ini SETIAP selesai satu fase. Jangan hapus riwayat — tambahkan.
> Terakhir diperbarui: 2026-09-02 (Global KB SSOT & Full CRUD Admin selesai — 498 test passed).

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
F2.5  Presenter + Number Check        SELESAI (lihat 3e)
F2.6  Generator Tier 2 + Router       SELESAI (lihat 3f)
F2.7  Eval Harness Golden-Set         SELESAI (lihat 3g)
F3'   Few-Shot Learning + KB Global   SELESAI (lihat 3h)
F3.1  Quick Hardening Fondasi         SELESAI (lihat 3i)
F3.2  Global KB SSOT & Full CRUD      SELESAI (lihat 3j)
F4    UI chat lengkap (level keyakinan, lihat SQL, feedback)
F5    Mode laporan + export + PII Masking
F6    Hardening (Statistik DB, Redis rate limit, cache, metrik)
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
| **F3' Few-Shot & KB Global** | selesai | (lihat git log) | KB Global dari Vanna API (~2.407 docs) di-sync ke `global_knowledge_base` (migration 011); `muat_kb_gabungan` (global + per-tenant merge, tenant menang jika konflik); `fewshot_provider` (injeksi approved sql_memory + global examples ke prompt LLM); admin endpoints CRUD/sync global KB; 483 test |
| **F3.1 Quick Hardening Fondasi** | selesai | (lihat git log) | Strict Operator Normalization (anti-collision komparasi); Schema-Aware Few-Shot Filter (anti-halusinasi tabel asing); Cross-Tenant Isolation Test Suite; Penegakan token quota harian (HTTP 429) + Request Decision Trace di audit; 493 test |
| **F3.2 Global KB SSOT & Full CRUD** | selesai | (lihat git log) | Snapshot final Vanna (2.407 items tersimpan permanen); Backend CRUD lengkap (`POST /admin/global-kb/items` [extra=forbid], `PUT /items/{id}`, `GET /items/{id}`, `DELETE /items/{id}`); Frontend Admin Modal `GlobalKnowledgeBaseModal.jsx` (List, Search, Filter Kind, Pagination, Tambah, Edit, Hapus, Sync); 498 test |
| **F3.4 Mode Vanna & Penyatuan Mode AI** | selesai | `fc163f1` | Pure Vanna engine mandiri (`vanna_engine.py`); Hapus saran pertanyaan lanjutan (hemat token 70%); Format mata uang Rp otomatis; Penyatuan kontrol mode per-tenant di Admin Panel (`vanna` / `tier2` / `tier1`) via migrasi 012 (`chat_mode`); UI Chat User bersih; 513 test lulus |
| **Unified Vanna AI + pgvector** | selesai | `11c7701` | Single DB pgvector (384 dim all-MiniLM-L6-v2), dual-mode narasi (Executive vs 0-token Operasional + on-demand explain), Visualizer React (recharts + silent error boundary), Instant Training API, Timeout 15s + Semaphore(5), branch v2 diarsipkan; 519 test lulus |
| **Smart Domain Thesaurus Otomotif** | selesai | LIVE | Kamus istilah otomotif Indonesia (penjualan unit, servis/WO, sparepart, customer, periode), filter transaksi sah (batal=false & retur=false), alur 2-hop customer, vektorisasi pgvector GLOBAL, endpoint /sync-thesaurus; 527 test lulus |
| **Zero-Token Smart Insights & Chips** | selesai | LIVE | Engine analitik klien (Δ%, peak, bottom, total/avg) 0 token LLM + 3 chips rekomendasi kontekstual otomotif (sales, customer, workshop, spareparts); UI AssistantAnswerCard; 527 test backend lulus, build 0 error |

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

## 3h. Detail F3' Few-Shot Learning & KB Global (2026-09-02)

- **KB Global dari Vanna API (`http://103.179.57.59:8000`)**:
  - `vanna_sync.py`: endpoint `POST /login` (form auth 303 redirect) + `GET /api/kb/items`
    (pagination 100/page). Upsert idempotent ke tabel `global_knowledge_base` (migration 011).
    2.407 item (2.399 text + 8 SQL examples) ter-sync bersih tanpa error.
  - `global_kb.py`: router admin `POST /admin/global-kb/sync`, `GET /admin/global-kb/stats`,
    `GET /admin/global-kb/items`, `DELETE /admin/global-kb/items/{id}` (guard `require_admin_role`).
- **KB Merger (`muat_kb_gabungan` di `knowledge_base.py`)**:
  - Menggabungkan KB global + KB per-tenant secara transparan sebelum masuk pipeline.
  - Aturan konflik: KB tenant SELALU menang atas KB global (glossary, catatan_kolom, nilai_map).
  - Filtering skema: text global `Table X columns: ...` disaring sesuai `schema_tables` tenant
    (hanya tabel relevan yang masuk prompt).
  - Kontrol akses (`tabel_dilarang`, `tabel_diizinkan`, `kolom_dikecualikan`): HANYA dari tenant.
- **Few-Shot Provider (`fewshot_provider.py`)**:
  - Mengambil contoh nyata yang sudah terbukti benar dari:
    1. `sql_memory` (approved, per-tenant, prioritas utama, times_used DESC)
    2. `global_knowledge_base` (kind='example', mengisi sisa slot hingga `fewshot_max_examples`)
  - Diinjeksi ke prompt LLM planner & tier2 generator (`build_user_prompt`) sebagai section
    `CONTOH PERTANYAAN & JAWABAN YANG SUDAH TERBUKTI BENAR`.
  - Backward compatible: fallback otomatis jika pemanggil mock lama tidak menyediakan parameter `fewshot`.
- **Hasil Verifikasi**: 483 tests passed (25 test baru: test_kb_merger, test_fewshot_provider, test_vanna_sync, test_query_planner), compileall exit 0, init_db 2x idempotent, frontend lint 0 error & build exit 0.

## 3i. Detail F3.1 Quick Hardening Fondasi (2026-09-02)

- **Strict Operator Normalization (`chat_pipeline.normalisasi_pertanyaan`)**:
  - Mengonversi operator komparasi dan aritmatika (`>=`, `<=`, `!=`, `>`, `<`, `=`, `+`, `%`)
    menjadi token eksplisit (`_gte_`, `_lte_`, `_neq_`, `_gt_`, `_lt_`, `_eq_`, `_plus_`, `_pct_`)
    sebelum strip tanda baca. Mencegah collision fatal SQL memory replay (mis. `omzet > 100` vs `omzet < 100`).
- **Schema-Aware Few-Shot Filtering (`fewshot_provider.py`)**:
  - `ambil_fewshot_global` mengekstrak tabel dari SQL contoh via regex `_TABLE_REF_RE` (`FROM`/`JOIN`)
    dan membandingkannya dengan `schema_tables` tenant. Contoh SQL yang menyebut tabel asing
    (mis. tabel Otobitz `untt_pembelian` pada database `aleza-si`) otomatis di-skip untuk mencegah
    halusinasi nama tabel/kolom pada prompt LLM.
- **Cross-Tenant Isolation Test Suite (`tests/test_cross_tenant_isolation.py`)**:
  - Menguji perimeter keamanan multi-tenant:
    - User query cabang di luar `allowed_branches` -> 403 Forbidden.
    - User confirm/reject `memory_id` milik tenant lain -> 404 Not Found (zero-leak).
    - User akses `chat_history` cabang lain -> 403 Forbidden.
    - Test collision operator & schema-aware filtering.
- **Penegakan `daily_token_quota` & Request Decision Trace**:
  - Pipeline memeriksa `daily_token_quota` tenant terhadap pemakaian non-memory hari ini. Jika kuota habis,
    mengembalikan HTTP 429 Too Many Requests yang informatif (Memory HIT tetap diizinkan).
  - Kolom `ai_json_filter` di `audit_logs` kini menyimpan `trace` terstruktur (`memory_hit`, `tier_selected`,
    `tables_effective`, `fewshot_injected`, `presenter_method`) untuk observabilitas dan debugging instan di produksi.
- **Hasil Verifikasi**: 493 tests passed (+10 test baru), compileall exit 0, frontend lint 0 error, build exit 0.

## 3j. Detail Global KB SSOT & Full CRUD Admin (2026-09-02)

- **Pemutusan Ketergantungan Live Vanna API (SSOT PostgreSQL)**:
  - Eksekusi snapshot seed final: 2.407 item (2.399 text + 8 SQL examples) ter-upsert permanen ke tabel core `global_knowledge_base`.
  - Sistem AI tidak lagi memerlukan Vanna API saat runtime (sepenuhnya membaca DB internal `global_knowledge_base`).
- **Backend CRUD Endpoints (`global_kb.py`)**:
  - `POST /admin/global-kb/items` (status 201): Buat item manual baru (`kind`, `content`, `question`, `sql_example`, `metadata`). Validasi ketat Pydantic `extra='forbid'`.
  - `GET /admin/global-kb/items/{id}`: Ambil detail single item untuk view/edit.
  - `PUT /admin/global-kb/items/{id}`: Update item existing dengan auto `updated_at`.
  - `DELETE /admin/global-kb/items/{id}`: Hapus item dari Global KB.
  - `GET /admin/global-kb/items` & `/admin/global-kb/stats` & `POST /admin/global-kb/sync`: Tetap dipertahankan untuk backward-compatibility.
- **Frontend Admin Modal (`GlobalKnowledgeBaseModal.jsx`)**:
  - Header dengan ringkasan status statistik (Total, Text, Example).
  - Search kata kunci dan filter Kind (`Semua`, `Teks`, `Contoh SQL`) dengan pagination.
  - Tabel items dengan indikator Badge, preview Q->SQL monospace, dan tombol aksi Edit / Hapus per baris.
  - Form Modal Create & Edit dengan validasi jenis item (field question/sql kondisional).
  - Dialog konfirmasi hapus aman.
  - Tombol "Global KB" di toolbar tab `TenantsTab.jsx` admin.
- **Hasil Verifikasi**: 498 tests passed (5 test baru: `test_global_kb_crud.py`), compileall exit 0, frontend lint 0 error, build exit 0, uji manual chat memory replay status 200 Level A.

## 3k. Detail F3.3 Virtual Foreign Keys (relasi_tabel) di Knowledge Base (2026-09-02)

- **Akar Masalah**:
  - Database DMS/ERP produksi nyata (seperti `backup_demo_otobitzcloud` dengan 2.387 tabel) memiliki **0 foreign key constraints fisik di PostgreSQL** karena relasi dijaga pada logika aplikasi.
  - Akibatnya, Tier 1 Deterministic SQL Composer melempar `SqlComposerError: tidak ada FK path dari 'tabel_a' ke: tabel_b` saat pertanyaan membutuhkan multi-tabel `JOIN`.
- **Solusi Virtual FK (`relasi_tabel`) di Knowledge Base**:
  - Menambahkan field `relasi_tabel` pada skema KB: `[{"tabel": "...", "kolom": "...", "merujuk_tabel": "...", "merujuk_kolom": "..."}]`.
  - Didukung penuh di `knowledge_base.py` (`KNOWN_KEYS`, `EMPTY_KB`, `_validate_relasi_tabel`, `_SECTION_VALIDATORS`).
  - Helper non-mutatif `suntikkan_relasi_ke_skema(schema_config, relasi_tabel)` menyuntikkan relasi virtual ke `schema_config["tables"][tabel]["foreign_keys"]` pada runtime.
  - Terintegrasi otomatis di `chat_pipeline.py` dan `eval_runner.py` setelah pemotongan skema efektif (`_siapkan_skema_efektif`).
  - Prompt LLM planner (`_skema_ringkas`) otomatis menampilkan relasi virtual ini (`kolom -> tabel.kolom`) sehingga AI dapat merencanakan join multi-tabel dengan presisi.
  - Zero DDL impact: tidak perlu memodifikasi database klien (`ALTER TABLE ADD CONSTRAINT`).
- **Seed Relasi Standar Otobitz DMS**:
  - `untt_pembelian.norangka` <-> `untt_datakendaraan.norangka`
  - `untt_penjualan.norangka` <-> `untt_datakendaraan.norangka`
  - `untt_penjualan.kode_customer` <-> `glbm_customer.nomor`
  - `untt_penjualan.kode_cabang` <-> `glbm_cabang.kode`
  - `srvt_wo.kode_cabang` <-> `glbm_cabang.kode`
- **Hasil Verifikasi**: 502 tests passed (+5 test baru: `test_virtual_fk.py`), compileall exit 0, frontend lint 0 error & build exit 0.

### 3h. Standardisasi Fitur Sortir di Seluruh Tabel Admin (Frontend & Backend)

- **Masalah**: Sebelumnya, fitur sortir kolom hanya tersedia pada tab *Perusahaan & Cabang* (`CompaniesTable` & `BranchesTable`), sementara tabel lain di panel admin belum memiliki sortir.
- **Implementasi**:
  1. **Komponen Reusable `SortIcon.jsx`** (`frontend/src/components/Admin/common/SortIcon.jsx`): Menyatukan ikon indikator netral (`ChevronsUpDown`), ascending (`ArrowUp`), dan descending (`ArrowDown`) dengan token tema proyek (`text-primary`, `text-muted`).
  2. **DatabaseRegistryTable**: Menambahkan sortir kolom `Nama` (`name`), `Host` (`db_host`), `Database` (`db_name`), `Dipakai` (`used_by`), `Status` (`is_active`), dan `Koneksi` (`connection`).
  3. **TenantConnectionsTable**: Menambahkan sortir kolom `Cabang` (`branch_code`), `Database` (`db_name_label`), `Lokasi` (`db_host`), dan `Status` (`status`).
  4. **UsersTab**: Menambahkan sortir kolom `Username` (`username`), `Email` (`email`), `Role` (`role`), `Akses Cabang` (`branches`), dan `Status` (`is_active`).
  5. **AIConfigTab**: Menambahkan sortir kolom `Scope` (`scope`), `Provider / Type` (`provider`), `Model` (`model`), `Temp.` (`temperature`), dan `Status` (`status`).
  6. **AuditLogTab & Backend `audit_logs.py`**: Mendukung sortir *server-side* menyeluruh dengan parameter `sort_by` dan `sort_dir`. Backend memvalidasi kolom terhadap whitelist ketat (`created_at`, `user_name`, `branch_code`, `execution_time_ms`, `status`) dan arah (`ASC`/`DESC`) untuk keamanan penuh dari SQL injection.
  7. **GlobalKnowledgeBaseModal**: Menambahkan sortir pada kolom `ID` (`id`), `Jenis` (`kind`), dan `Konten` (`content`).
- **Hasil Verifikasi**:
  - Backend: 507 passed (+2 unit tests baru `test_audit_logs_sort.py`), `compileall app` exit 0.
  - Frontend: `npm run lint` exit 0 (0 error), `npm run build` exit 0.
  - Live Web Testing (Chrome DevTools): Teruji interaktif klik header A-Z dan Z-A pada seluruh tabel admin di browser.

### 3l. Detail F3.4 Mode Vanna, Penghematan Token, dan Penyatuan Mode AI di Admin Panel (2026-09-03)

- **Latar Belakang & Kebutuhan Bisnis**:
  - Kebutuhan kecepatan respons dan keluwesan kueri setara sistem Vanna saingan (`http://103.179.57.59:8501/`) untuk demo dan kebutuhan komparasi data.
  - Permintaan penghematan token maksimal (memangkas pemborosan token output yang tidak perlu).
  - Penyatuan arsitektur pemilihan mode (Opsi 1): Admin menentukan kebijakan mode AI per tenant/cabang, dan antarmuka User Chat tetap bersih dan bebas kebingungan teknis.
- **Implementasi Teknis**:
  1. **Engine Pure Vanna (`backend/app/services/vanna_engine.py`)**:
     - Template prompt standar resmi Vanna (`You are a Postgres expert...`).
     - Konteks skema ditarik dinamis dari 2.409 dokumen DDL/teks di `global_knowledge_base`.
     - Single-call LLM: AI menulis SQL teks bebas, dieksekusi langsung ke tenant database (dengan statement timeout 30s).
     - Ringkasan naratif deterministik otomatis tanpa pemanggilan LLM kedua (hemat token 100% pada fase presenter).
     - Menghasilkan SQL dan data yang **100% identik** dengan Vanna saingan (terbukti pada kueri agregasi 2025 vs 2026: 2.332 vs 1 transaksi).
  2. **Penghematan Token**:
     - Menghapus instruksi pembuatan pertanyaan lanjutan (`saran`) dari presenter LLM dan UI.
     - Memotong konsumsi token sebesar >70% (~900 token vs ~3.300 token sebelumnya) dan memangkas latensi dari 62 detik menjadi ~6-9 detik.
  3. **Format Mata Uang Rupiah (`Rp `)**:
     - Normalisasi nilai numerik mentah dari database (membersihkan notasi ilmiah `5.0E+5` menjadi integer `500000`).
     - Fungsi pendeteksi otomatis kolom mata uang di `AssistantAnswerCard.jsx` yang memformat nilai angka menjadi `Rp 20.312.027` dan `Rp 500.000` dengan pemisah ribuan standar Indonesia.
  4. **Penyatuan Mode AI di Admin Panel (Opsi 1)**:
     - Migrasi `012_tenant_chat_mode.sql` (idempotent, rollback aman): menambahkan kolom `tenants.chat_mode VARCHAR(20) NOT NULL DEFAULT 'vanna'`.
     - Endpoint baru: `POST /admin/tenants/{branch_code}/mode` (`vanna`, `tier2`, `tier1`).
     - Jika memilih `tier2`, tetap diverifikasi oleh gate evaluasi golden-set ($\ge 95\%$).
     - Kompatibilitas mundur: endpoint `POST /admin/tenants/{branch_code}/tier2` tetap berjalan sinkron.
     - UI Admin `TenantConnectionsTable.jsx`: Selector dropdown mode AI per cabang (`⚡ Mode Vanna`, `🛡️ Tier 2 (Kompleks)`, `🔒 Tier 1 (Standar)`).
     - UI User `UserWorkspace.jsx`: Bersih dari tombol teknis switcher mode; otomatis mengeksekusi sesuai konfigurasi cabang di backend.
- **Hasil Verifikasi**:
  - Backend: **513 passed in 11.69s** (+4 unit tests di `test_vanna_engine.py`, +2 di `test_tenant_mode.py`), `compileall app` exit 0.
  - Database: Migrasi 012 idempotent (sukses dijalankan 2x berturut-turut).
  - Frontend: `npm run lint` exit 0 (0 error), `npm run build` exit 0.
  - End-to-End Live Test: Perubahan mode di admin langsung mengatur alur routing di chat query secara transparan.

### 3m. Penyelesaian Relasi Database Riil, Pembersihan KB, Rebranding Sinkronisasi Skema Bebas Copyright, dan Koreksi Formatting (2026-09-04)

- **Latar Belakang & Masalah**:
  1. Relasi fiktif di Knowledge Base cabang `TST_01` (`untt_penjualan.kode_customer -> glbm_customer.nomor`) menyebabkan query analitik customer selalu gagal (502 Tertahan) karena kolom `kode_customer` fisik tidak ada di tabel `untt_penjualan`.
  2. Adanya key dictionary bersarang di `catatan_kolom` (`untt_penjualan: {...}`) yang melanggar skema `table.column: string`.
  3. Tombol dan teks sinkronisasi pada modal Global Knowledge Base masih mencantumkan nama pihak ketiga ("Sync dari Vanna", "Vanna API") sehingga rentan copyright issue.
  4. Kolom kuantitas/hitungan transaksi (`jumlah_penjualan`) salah diformat menjadi mata uang (`Rp 322`), dan kolom perbandingan finansial musiman (`semester_1_2025`) belum memunculkan prefix `Rp`.
- **Implementasi Solusi**:
  1. **Relasi Riil Penjualan ke Customer (Otobitz Dealer Domain)**:
     - Hasil introspeksi view `vw_untt_penjualan`: Penjualan unit kendaraan dibuat berdasarkan Surat Pesanan Kendaraan (SPK).
     - Alur 2-hop sah: `untt_penjualan.nomor_pesanan -> untt_pesanankendaraan.nomor` lalu `untt_pesanankendaraan.nomor_customer -> glbm_customer.nomor`.
     - Ditambahkan `untt_pesanankendaraan` dan view `vw_untt_penjualan` ke `tabel_diizinkan` cabang `TST_01`.
     - Didaftarkan relasi formal pada `relasi_tabel` dan diperbarui prioritas heuristik join di `sql_composer.py` (`nomor_pesanan`, `nomor_customer`).
  2. **Pembersihan Knowledge Base**:
     - Dihapus relasi fiktif `untt_penjualan.kode_customer`.
     - Dirapikan struktur `catatan_kolom` menjadi format standar kolom terpisah.
     - Diverifikasi seluruh 2.409 entri Global KB bersih dari nama merek/copyright pihak ketiga.
  3. **Rebranding Fitur Sinkronisasi Bebas Copyright**:
     - `GlobalKnowledgeBaseModal.jsx`: Tombol diganti menjadi **"Sinkronisasi Skema"**, tooltip menjadi **"Sinkronisasi ulang kamus skema dan aturan bisnis sistem"**, dan pesan error/empty state dibersihkan dari nama eksternal.
     - `global_kb.py`: Pesan error dan docstring diselaraskan sebagai modul kamus skema internal enterprise.
  4. **Koreksi Formatting Angka & Mata Uang (`AssistantAnswerCard.jsx`)**:
     - Ditambahkan `KUANTITAS_KEYWORDS` (`jumlah`, `qty`, `count`, `cnt`, `banyak`, `total_unit`, `unit`, `frekuensi`) sehingga kolom seperti `jumlah_transaksi` dan `jumlah_penjualan` tidak diberi prefix `Rp` (tampil murni `350` atau `349`).
     - Ditambahkan regex deteksi periode musiman (`semester_...`, `kuartal_...`) dengan threshold nominal besar ($\ge 100.000$) sehingga kolom `semester_1_2025` berformat rapi `Rp 40.299.000.000`.
- **Hasil Verifikasi**:
  - Backend: **514 passed in 11.29s**, `compileall app` exit 0.
  - Frontend: `npm run lint` exit 0 (0 error), `npm run build` exit 0.
  - Live Testing:
    - Query perbandingan penjualan vs pembelian: `jumlah_transaksi` tampil **`350`** dan **`349`** tanpa `Rp`, sedangkan omzet tampil **`Rp 69.825.000.000`**.
    - Query customer penjualan: Berhasil 100% mengeksekusi join `glbm_customer -> untt_pesanankendaraan -> untt_penjualan` menghasilkan data riil 3 customer teratas tanpa error.
    - Modal Global KB: Tombol tampil bersih dengan label **"Sinkronisasi Skema"**.

### 3n. Implementasi Unified Vanna AI Architecture, pgvector, Visualizer Interaktif, dan Instant Training (2026-09-04)

- **Latar Belakang & Keputusan Strategis**:
  1. **Pengarsipan Branch `v2` (Two-Tier AST Verifier)**: Seluruh implementasi Tier 1 & Tier 2 diamankan di branch `v2` (commit `fc163f1`) sebagai jaring pengaman jika sewaktu-waktu manajemen/atasan meminta perbandingan atau pengembalian sistem. Branch `master` difokuskan menjadi *Unified Vanna AI Platform*.
  2. **Penyatuan Single-Database (PostgreSQL 15 + `pgvector`)**:
     - Menolak arsitektur ChromaDB terpisah yang rawan resiko ("40 folder SQLite terisolasi", inkonsistensi backup, dan beban RAM ganda).
     - Meng-upgrade kontainer database dev/core `dms_pg` ke image `pgvector/pgvector:pg15` tanpa kehilangan data (`postgres_data` volume utuh).
     - Seluruh data relational DMS, audit log, dan vector RAG embeddings disatukan dalam satu database ACID PostgreSQL di tabel `tenant_vector_kb` dengan indeks HNSW berkecepatan tinggi.
  3. **Dual-Mode Embedding Standar Vanna (Offline Lokal vs Cloud API)**:
     - Embedding lokal offline menggunakan model resmi standar Vanna: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensi, ~80MB, inferensi CPU super cepat <50ms tanpa internet & zero-cost).
     - Seluruh 2.409 kamus DDL skema di `global_knowledge_base` di-vektorisasi secara otomatis ke `tenant_vector_kb` (`branch_code = 'GLOBAL'`).
  4. **Proteksi Concurrency Semaphore & Statement Timeout**:
     - `asyncio.Semaphore(5)`: Membatasi inferensi LLM dan vektorisasi konkruen maks 5 request paralel untuk mencegah memory spike/starvation.
     - `SET statement_timeout = '15000'`: Eksekusi query analitik di database tenant diputus otomatis jika melebihi 15 detik untuk melindungi kestabilan database operasional cabang.
  5. **Dual-Mode Presentasi (Eksekutif vs Operasional)**:
     - Mode Eksekutif (`auto_narration: true`): Menghasilkan narasi analisis data menyeluruh secara otomatis.
     - Mode Operasional (`auto_narration: false`, default): Penghematan token 100% (0 pemanggilan LLM kedua). Dilengkapi ringkasan lokal deterministik + tombol interaktif `[ ✨ Jelaskan Lebih Dalam dengan AI ]` (`POST /chat/explain`) jika user membutuhkan interpretasi lebih detail.
  6. **Visualizer Interaktif Otomatis & Silent Error Boundary (React + Recharts)**:
     - Menggunakan `recharts` native React (ringan, 0-token, tidak memerlukan pemanggilan AI untuk sintaks visual).
     - Algoritma `deteksiKecocokanGrafik` otomatis memindai baris data untuk menentukan apakah hasil layak disajikan dalam grafik batang/garis.
     - Tab switcher interaktif: `[ 📋 Tabel Data ]` vs `[ 📊 Grafik ]`.
     - **Silent Error Boundary**: Jika terjadi kegagalan rendering visualizer pada browser user, sistem membungkusnya secara senyap tanpa menampilkan pesan error merah/rusak ke user, dan langsung mem-fallback ke tampilan Tabel Data yang aman.
  7. **Instant Training API (Human-in-the-Loop)**:
     - Admin & Pengguna dapat melatih sistem secara instan melalui endpoint `POST /admin/vanna/train` atau tombol `[ 🎓 Latih Jawaban Ini ]` di antarmuka chat.
     - Pasangan `pertanyaan -> SQL` langsung di-vektorisasi ke pgvector, meningkatkan akurasi retrieval berikutnya seketika tanpa perlu restart service.
- **Implementasi Komponen & File**:
  - `docker-compose.yml`: Migrasi image PostgreSQL ke `pgvector/pgvector:pg15` (port 5433).
  - Migrasi 013 (`backend/sql/migrations/013_pgvector_setup.sql`): Pembuatan tabel `tenant_vector_kb` dan indeks vektor HNSW (`vector_cosine_ops`).
  - Migrasi 014 (`backend/sql/migrations/014_tenant_narration_mode.sql`): Penambahan flag `auto_narration` di tabel `tenants` dan `users`.
  - `backend/app/services/vanna_pgvector.py`: Singleton embedder model `all-MiniLM-L6-v2`, fungsi pencarian semantik `cari_konteks_pgvector`, dan instant training `latih_pertanyaan_sql`.
  - `backend/app/services/vanna_engine.py`: Integrasi retrieval RAG berbasis vektor, Semaphore(5), statement timeout 15s, dual-mode narasi, dan generator narasi on-demand.
  - `backend/app/routers/chat.py`: Penambahan endpoint `POST /chat/explain`.
  - `backend/app/routers/admin/vanna_training.py`: Endpoint admin CRUD dan sinkronisasi training pgvector (`/admin/vanna/train`, `/sync-global`, dll).
  - `frontend/src/components/User/AssistantAnswerCard.jsx`: Deteksi grafik otomatis, Recharts ResponsiveContainer BarChart, Silent Error Boundary, Tab Switcher, On-demand AI Explain, dan Instant Training action.
- **Hasil Verifikasi**:
  - Backend: **519 passed in 38.15s**, `compileall app` exit 0.
  - Frontend: `npm run lint` exit 0 (0 error), `npm run build` exit 0 (build sukses).
  - Idempotency Database: `init_db.py` sukses teruji 2x berturut-turut tanpa error.
  - Live Testing: Pengujian kueri penjualan tahun 2025 vs 2026 di cabang `TST_01` (DB riil 2.387 tabel) sukses menghasilkan tabel, grafik batang Recharts, dan penjelasan AI on-demand dalam format bahasa Indonesia profesional.

### 3o. Implementasi Smart Automotive Domain Thesaurus & RAG Semantic Injection (2026-09-04)

- **Latar Belakang & Masalah**:
  1. Pengguna di lapangan sering menggunakan bahasa percakapan sehari-hari/slang otomotif dealer (seperti *"omzet"*, *"laku"*, *"unit"*, *"servis"*, *"WO"*, *"sparepart"*, *"stok gudang"*, *"SPK"*, *"DO"*) yang tidak memiliki nama kolom fisik persis sama di database PostgreSQL dealer (Otobitz 2.387 tabel).
  2. Transaksi kotor (batal atau retur) harus disaring dengan benar (`batal = false AND retur = false`) agar omzet dan jumlah unit tidak membengkak karena mencatat pesanan yang dibatalkan.
  3. Relasi ke data pelanggan (`glbm_customer`) memerlukan alur join 2-hop melalui Surat Pesanan Kendaraan (`untt_pesanankendaraan`) karena tabel faktur `untt_penjualan` tidak menyimpan kode pelanggan secara langsung.
- **Implementasi Solusi**:
  1. **Modul Kamus Semantik & Aturan Bisnis Otomotif (`automotive_thesaurus.py`)**:
     - Memetakan 5 kategori domain utama:
       - **Penjualan Unit Kendaraan**: `untt_penjualan`, `untt_pesanankendaraan`, `glbm_kendaraan`, `glbm_customer`, `vw_untt_penjualan`.
       - **Servis & Bengkel**: `womt_wo`, `womt_wopart`, `womt_wojasa`.
       - **Suku Cadang & Inventori**: `invt_item`, `invt_pembelian`, `invt_stok`.
       - **Pelanggan / Customer**: `glbm_customer` (relasi 2-hop via `untt_pesanankendaraan`).
       - **Periode Waktu Akuntansi**: Semester 1/2, Kuartal 1-4, perbandingan tahunan/bulanan.
     - Penegakan aturan bisnis baku:
       - Transaksi sah: `batal = false AND retur = false` (tipe boolean PostgreSQL).
       - Total omzet: `SUM(untt_penjualan.hjakhir)`.
       - Jumlah unit: `COUNT(untt_penjualan.nomor)`.
  2. **Integrasi RAG Semantik Otomatis (`vanna_pgvector.py` & `vanna_engine.py`)**:
     - Fungsi `deteksi_konteks_domain(question)` mendeteksi kata kunci pertanyaan secara instan.
     - Panduan bisnis diinjeksikan langsung ke dalam konteks prompt Vanna AI (`susun_instruksi_domain`).
     - Fungsi `injeksi_thesaurus_ke_pgvector(core_pool)` mem-vektorisasi aturan domain ke tabel `tenant_vector_kb` (`branch_code = 'GLOBAL'`, `item_type = 'domain_thesaurus'`).
  3. **Penyelarasan API & Endpoint Admin**:
     - `POST /admin/vanna/sync-thesaurus`: Injeksi/sinkronisasi aturan kamus domain otomotif ke pgvector.
     - `POST /admin/vanna/sync-global`: Otomatis menyinkronkan DDL Global KB sekaligus aturan domain thesaurus.
  4. **Pembaruan Dokumentasi `Readme.md`**:
     - Menghilangkan referensi mode Tier 1 dan Tier 2 dari `Readme.md` utama di branch `master`.
     - Menegaskan bahwa arsitektur Two-Tier AST Verifier diarsipkan secara eksklusif di branch `v2`.
     - Memperbaiki penulisan visualizer menjadi **React Recharts**.
     - Melengkapi seluruh daftar endpoint API aktif.
- **Hasil Verifikasi**:
  - Backend: **527 passed in 43.95s** (100% lulus, termasuk 8 test baru di `test_automotive_thesaurus.py`).
  - Frontend: `npm run lint` 0 errors, `npm run build` exit 0.
  - Live Testing:
    - Kueri *"berapa total omzet penjualan mobil di tahun 2025?"* langsung menghasilkan query bersih `WHERE batal = false AND retur = false AND tanggal >= '2025-01-01' AND tanggal < '2026-01-01'` dengan hasil **`Rp 69.825.000.000`** dalam 9 detik.
    - Kueri *"siapa 3 pelanggan dengan transaksi penjualan terbesar di tahun 2025?"* langsung sukses mengeksekusi join 2-hop `untt_penjualan -> untt_pesanankendaraan -> glbm_customer` pada percobaan pertama (0 auto-repair retry) dan mengembalikan 3 data pelanggan riil teratas.

### 3p. Opsi 3: Zero-Token Smart Insights & Rekomendasi Pertanyaan Lanjutan (Follow-up Chips) (commit: LIVE)

- **Latar Belakang & Kebutuhan**:
  - Pengguna operasional dan eksekutif membutuhkan ringkasan analitik instan (seperti tren pertumbuhan $\Delta\%$, nilai tertinggi/terendah, dan total akumulasi) tanpa membebani biaya token LLM atau memperlambat latensi jawaban.
  - Pengguna sering kali bingung menanyakan pertanyaan kelanjutan yang relevan setelah melihat hasil data tabular.
- **Implementasi Solusi**:
  1. **Engine Analitik Klien (`frontend/src/utils/smartInsights.js`)**:
     - `hitungSmartInsights(columns, rows)`: Menghitung secara matematis di browser:
       - Deteksi kolom metrik numerik sejati dengan pengecualian ketat kolom identitas (`tahun`, `thn`, `bulan`, `nomor`, `kode`, `id`, `telepon`, `nik`, `ktp`).
       - Deteksi tren pergerakan ($\Delta\%$) dengan badge warna visual (hijau jika naik, merah jika turun).
       - Ekstraksi pemenang kinerja (*Peak / Nilai Tertinggi*) dan nilai terendah (*Bottom*).
       - Total akumulasi dan rata-rata dengan formatting Rupiah / angka Indonesia (`Rp 69,83 Miliar`, dsb).
       - Batasan aman: Hanya aktif jika baris $\ge 2$ dan terdapat kolom numerik valid.
     - `buatRekomendasiPertanyaan(question, columns, rows, sql)`: Menghasilkan 3 opsi rekomendasi pertanyaan lanjutan terarah berdasarkan kategori domain otomotif:
       - Customer / Pelanggan (analisis transaksi terbesar, tipe mobil favorit, dsb).
       - Servis / Bengkel / WO (rasio jasa vs sparepart, mekanik terproduktif).
       - Sparepart / Stok Gudang (stok kritis, suku cadang terlaris).
       - Penjualan Mobil / Omzet (breakdown bulanan, komparasi semester).
  2. **Integrasi Komponen UI (`frontend/src/components/User/AssistantAnswerCard.jsx`)**:
     - Memoized dengan `useMemo` untuk performa render nol lag.
     - Menampilkan banner **💡 Smart Insight (Zero-Token)** di bawah ringkasan jawaban.
     - Menampilkan **Rekomendasi pertanyaan berikutnya** dengan chip interaktif yang langsung memicu kueri baru saat diklik.
- **Hasil Verifikasi**:
  - Frontend: `npm run lint` 0 errors, `npm run build` exit 0 (1.05s).
  - Backend: **527 passed in 39.80s** (tidak ada regresi backend).

### 3q. Pembersihan Emoji & Standarisasi Icon SVG Lucide (commit: 6b87bd3)

- **Masalah**:
  - Ditemukan beberapa teks tombol dan modal yang masih memuat emoji unicode mentah (`✨`, `✦`, `⏳`, `⚠️`, `ℹ️`, `⌄`, `✓`), yang menyebabkan tampilan tidak konsisten/ganda dengan icon SVG (misal tombol Explain menampilkan icon `<Sparkles>` dan emoji `✨` sekaligus).
- **Perbaikan**:
  1. `frontend/src/components/User/AssistantAnswerCard.jsx`: Menghapus emoji `✨` pada label tombol Explain — tombol kini bersih hanya mengandalkan `<Sparkles size={12} />` dari Lucide.
  2. `frontend/src/components/LoginModal.jsx`: Mengganti simbol `✦` dengan icon resmi `<Sparkles className="w-6 h-6 text-primary" />`.
  3. `frontend/src/components/Admin/ai/AIConfigModal.jsx`: Mengganti unicode chevron `⌄` dengan `<ChevronDown size={14} />`, dan membersihkan emoji pada notifikasi toast.
  4. `frontend/src/components/Admin/tenants/ConnectDbModal.jsx`: Menghapus simbol centang unicode `✓` pada teks dropdown.
  5. `frontend/src/App.jsx`: Menghapus custom emoji `⏳` pada toast sesi expired dan menggantinya dengan `toast.error()`.
- **Hasil Verifikasi**:
  - Pemindaian regex unicode di seluruh direktori `frontend/src/`: **0 emoji tersisa**.
  - Frontend `npm run lint`: **0 errors**.
  - Frontend `npm run build`: **Exit code 0**.
  - Backend `pytest tests/ -q`: **527 passed in 35.61s**.

## 3q. Detail Perbaikan Fitur Explain Naratif On-Demand & Penyelarasan Riwayat Chat

- **Latar Belakang & Akar Masalah**:
  User melaporkan pop-up error *"Gagal memuat penjelasan naratif"* ketika mengklik tombol **"Jelaskan Lebih Dalam dengan AI"** pada pesan yang dimuat dari riwayat percakapan (`/chat/history`).
  Setelah investigasi mendalam:
  1. *History Hydration Missing Question*: Pada `UserWorkspace.jsx`, fungsi pemetaan `pesanDariHistory` tidak mengaitkan properti `question` dari pesan user sebelumnya ke kartu balasan asisten. Akibatnya nilai `question` bernilai string kosong `""`.
  2. *Strict Schema Validation 422*: Skema `ChatExplainRequest` di backend mendefinisikan `question: str = Field(min_length=1, max_length=2000)`, sehingga string kosong langsung ditolak FastAPI dengan status `HTTP 422 Unprocessable Entity`.
  3. *OpenAI JSON Object Requirement*: Pada `query_planner.py`, pemanggilan LLM default menyertakan header/body `response_format: {"type": "json_object"}`. Pada endpoint `buat_penjelasan_naratif`, prompt LLM belum secara eksplisit mewajibkan format JSON (kunci `"narasi"`), menyebabkan respons mentah LLM sulit diparsing atau terkena timeout.
  4. *Memory Replay allow_explain Missing*: Jawaban yang berasal dari memory replay sebelumnya tidak menyertakan `allow_explain: True` dan `question`, sehingga tombol tidak muncul atau tidak memiliki konteks pertanyaan.
  5. *React Duplicate Key*: `messageSeq` numerik murni berpotensi menghasilkan ID bentrok (`msg-1`, `msg-3`) saat re-render, memicu warning React di browser.

- **Perubahan yang Dilakukan**:
  1. `backend/app/routers/chat.py`:
     - Menambahkan nilai fallback default pada `ChatExplainRequest` (`question = "Analisis data transaksi"`, `sql = ""`) agar tidak langsung melempar 422 saat payload parsial.
     - Melakukan sanitasi `(payload.question or "").strip() or "Analisis data transaksi"` dan `(payload.sql or "").strip() or "-- query"`.
  2. `backend/app/services/vanna_engine.py`:
     - Menambahkan properti `"question": question` dan `"allow_explain": True` baik pada hasil eksekusi Mode Vanna maupun SQL Memory Replay.
     - Membuat fungsi utilitas `ekstrak_narasi(llm_output: str) -> str` yang secara cerdas mengekstrak teks narasi dari objek JSON (`{"narasi": "..."}` atau markdown codeblock), mengeliminasi karakter format JSON mentah bagi user.
     - Memperbarui prompt `buat_penjelasan_naratif` agar mewajibkan format JSON `{"narasi": "..."}`, sinkron dengan `response_format: {"type": "json_object"}`.
  3. `backend/app/services/query_planner.py`:
     - Menambahkan guard defensif terhadap respons error gateway provider AI (seperti pengecekan `"error"` dan ketiadaan `"choices"`) sebelum mengakses indeks pesan.
  4. `frontend/src/components/User/UserWorkspace.jsx`:
     - Memperbarui `pesanDariHistory(m, idx, allMsgs)` untuk mencari teks pertanyaan dari `answer?.question || prevUserMsg?.content || prevUserMsg?.text || ''` dan menyimpannya ke `message.question`.
     - Memperbarui generator ID pesan menjadi kombinasi timestamp dan acak (`msg-${Date.now()}-${messageSeq}-${Math.random()}...` dan `h-${m.id || idx}-${m.created_at}`) sehingga 100% bebas dari duplikasi key React.
  5. `frontend/src/components/User/AssistantAnswerCard.jsx`:
     - Menambahkan fallback `qText = (question || answer.question || 'Analisis data transaksi').trim() || 'Analisis data transaksi'`.
     - Menampilkan detail pesan error dari backend secara dinamis pada toast jika terjadi kegagalan.

- **Hasil Verifikasi**:
  - Backend compile: `compileall app` lolos 100% (exit code 0).
  - Backend test suite: `pytest tests/ -q` lolos 100% (**527 passed in 34.63s**).
  - Frontend lint: `npm run lint` lolos (**0 errors**).
  - Frontend build: `npm run build` lolos (exit code 0).
  - Live Browser Testing via Chrome DevTools MCP:
    - Membuka sesi chat user nyata (`tester01`), mengklik tombol **"Jelaskan Lebih Dalam dengan AI"** pada kartu perbandingan Semester 1 vs Semester 2 tahun 2025.
    - Kueri `/chat/explain` merespons `HTTP 200 OK`.
    - Box **ANALISIS EKSEKUTIF AI** berhasil ter-render secara utuh, rapi, dan menyajikan narasi bisnis mendalam (volume vs harga jual, rekomendasi 5 langkah strategis).
    - Screenshot verifikasi visual tersimpan di `explain_live_verified.png`.

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
- [x] Pengarsipan Arsitektur Two-Tier ke branch `v2` (commit `fc163f1`) & pembaruan `Readme.md` bersih dari Tier 1/2.
- [x] **Smart Automotive Domain Thesaurus & Semantic RAG Injection** — SELESAI (lihat §3o).
- [x] **Opsi 3: Zero-Token Smart Insights & Rekomendasi Pertanyaan (Follow-up Chips)** — SELESAI (lihat §3p).
- [ ] **Roadmap Opsi Pengembangan Lanjutan (Tercatat untuk Eksekusi Berikutnya)**:
  1. **Opsi 1: Fitur Ekspor Laporan (Excel `.xlsx` & CSV)**:
     Tombol unduh hasil kueri ke spreadsheet langsung dari antarmuka User Chat dengan formatting angka akuntansi dan nama file dinamis.
  2. **Opsi 4: Interactive Clarification Loop (Human-in-the-Loop Dialog)**:
     Jika pertanyaan ambigu/multi-tafsir (misal: penjualan mobil vs sparepart), sistem menyajikan opsi klarifikasi sebelum SQL dijalankan.
  3. **Opsi 5: Hardening & Persiapan Demo/Presentasi PKL**:
     Optimasi UI Admin, metrik utilisasi AI per-cabang, dan skenario presentasi live demo.
- [ ] Pembersihan repo (menunggu waktu khusus): `git rm --cached frontend/test-results/.last-run.json`
      (file ter-track padahal sudah di .gitignore); 3 folder `backup_*` root dipindah ke arsip eksternal.

## 7. Cara menjalankan untuk uji manual

```powershell
docker compose up -d                    # postgres:15 (5433) + redis
cd backend; .venv\Scripts\python.exe init_db.py
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
cd ..\frontend; npm run dev             # http://localhost:5173
# akun: admin/admin123 · user_jkt/user123 (chat UI: login user_jkt)
```
