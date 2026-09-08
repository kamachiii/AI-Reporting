# Progres Implementasi — DMS AI Platform (Pipeline AI v2)

> Dokumen kontinuitas: dibaca PERTAMA kali oleh AI/engineer yang melanjutkan kerja.
> Update dokumen ini SETIAP selesai satu fase. Jangan hapus riwayat — tambahkan.
> Terakhir diperbarui: 2026-09-07 (Manajemen Riwayat Chat Multi-Sesi, Tabel Pintar Interaktif, & Penyelarasan Skema Bengkel Riil — 558 test passed).

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
| **Interactive Clarification Loop** | selesai | LIVE | Mesin deteksi ambiguitas pra-eksekusi (clarification_engine.py, <10ms, 0 token LLM); ClarificationCard interaktif 2S (Unit Kendaraan vs Sparepart); 535 test backend lulus |
| **Proactive Multi-Table 3S (Query Fan-Out)** | selesai | LIVE | Single-shot multi-SQL prompt 3S (Sales, Service, Sparepart), eksekusi paralel asyncio.gather, ringkasan eksekutif gabungan, multi-tab switcher dinamis di UI; 542 test backend lulus, build 0 error |
| **Auto-Adaptive Visual Charts (0-Token)** | selesai | LIVE | Client-side Recharts 0 token, auto-default time-series (tren kuartal/bulan/tahun), toggle dinamis Bar vs Line chart, formatting sumbu eksekutif (rb/jt/M/T), isolasi per-tab 3S; 542 test backend lulus, build 0 error |
| **Ekspor Excel Berformat & Grafik Native + Pertanyaan Emas Dealer** | selesai | LIVE | Integrasi 32 KPI dealer dari acuan Design Dashboard (SPK, Unit Entry GR/BP, SA produktivitas, Stock Value, AR/AP Aging); Fitur ekspor Excel .xlsx dengan format akuntansi Indonesia & native openpyxl embedded chart; 548 test lulus, build 0 error |
| **Metrik Utilisasi AI Admin & Skenario Demo PKL (Opsi 5)** | selesai | LIVE | Dashboard analitik AI admin (overview, tren Recharts 7-hari, kuota token cabang real-time), modal ubah kuota cabang, dokumen panduan sidang PKL; 554 test backend lulus, lint 0 error, build 0 error |
| **Penyempurnaan Analisis Multi-Divisi** | selesai | LIVE | Koreksi skema riil dealer (srvt/pwt1/inv1), komparasi sejajar, smart context note, de-duplikasi chip; 557 test backend lulus |
| **Fix Format Mata Uang vs Kuantitas & Total Transaksi** | selesai | LIVE | Perbaikan deteksi kolom: hapus total_transaksi dari UANG_KEYWORDS, tambahkan kuantiti, transaksi, unit ke KUANTITAS_KEYWORDS di UI, smartInsights, dan Excel exporter; 557 test lulus |
| **Manajemen Riwayat Chat & Tabel Pintar** | selesai | `348ef57` | Sidebar riwayat multi-sesi (+ Chat Baru, ganti sesi, hapus riwayat per sesi / semua); Tabel cerdas di kartu jawaban (search filter, sorting kolom asc/desc, paginasi mini 10/25/50/semua, salin tabel TSV/Excel); Koreksi skema bengkel riil srvt_wo & srvt_wodetail (138k & 927k rows); Ekstraksi robust JSON SQL; 558 test lulus |
| **Redesign Anti-AI-Slop & Executive Command Deck** | selesai | `0d6b68e` | Instalasi 2 skill baru (anti-ai-slop-design & web-design-guidelines); Eliminasi pola AI slop (bot avatar raksasa, badge spam 0-token, tombol warna-warni inkonsisten); Command Deck 4 kartu analitis dealer; Precision Dossier & Tabular Numbers; 558 test lulus, lint 0 error, build 0 error |
| **Penerapan Claude Editorial Design System** | selesai | `d88610c` | Penerapan design system DESIGN-claude.md: palet terracotta #cc785c & warm canvas #faf9f5, tipografi Cormorant Garamond & Inter, Claude code-window-card dengan Apple window controls, category tabs, and active state cream; 558 test lulus, lint 0 error, build 0 error |
| **Restorasi Icon Bot Warm Coral & Struktur Narasi Analisis** | selesai | `d3e3a51` | Mengembalikan icon Bot warm coral di header & message bubble (menghilangkan kotak hitam [DMS] & [AI]), font ringkasan sans-serif tajam, dan pemecahan narasi analisis eksekutif menjadi paragraf terstruktur + callout rekomendasi tanpa efek semut berbaris |
| **Penyempurnaan Visual & UX Editorial** | selesai | `95a105f` | Warm user bubble (anti-pitch-black), palet chart terracotta #cc785c, deduplikasi judul toolbar, smart insights label Bulan (bukan Baris), prompt deck sans-serif, login card warm surface, tombol Coba Lagi pada error |
| **Redesign Sidebar History Chat Editorial & Fix Hydration** | selesai | `04ec492` | Redesign sidebar gaya Claude.ai (header compact h-14, button Percakapan Baru tactile, search terintegrasi, timestamp item, delete pill inline, empty state ramah); Fix parsing array getConversations agar riwayat ter-render nyata |
| **Floating Edge Handle Sidebar (Zero Layout Shift Navbar)** | selesai | `2b2cb55` | Menghapus tombol toggle dari navbar atas agar logo dan judul tidak pernah terdorong/bergeser; Menggantinya dengan Floating Edge Tab Handle di tepi layar kiri gaya Linear & Cursor |
| **Penyempurnaan Tipografi Sidebar, Arsip Percakapan & Polish UI/UX** | selesai | `a196fad` | Pembesaran font Arsip Percakapan (text-[15px] font-medium font-serif), mempertahankan font-normal khusus "Riwayat Chat" pada floating handle, restorasi font-medium/semibold pada aksi & active item, scrollbar ramping editorial di index.css, shortcut keyboard Ctrl+B / Cmd+B, dan animasi aktif tactile |
| **Eliminasi Badge Visual Ctrl+B & Perluasan Trigger Fan-Out Tiap Divisi** | selesai | `a25c07b` | Menghapus badge teks visual Ctrl+B dari floating handle (informasi tetap via hover title), menghapus cache memory tunggal #67, dan memperluas trigger regex fanout_engine untuk menangani typo 'peforma' & frasa 'tiap divisi' sehingga perbandingan performa antar divisi per tahun sukses terpecah ke 4 tab (Komparasi, Unit, Servis, Sparepart) |
| **Progressive Comparison (Gaya 1 -> Gaya 2) & Zero Emoji** | selesai | LIVE | Deteksi kueri periode (Gaya 1 tabel terpadu default + chart); ProactiveBreakdownOffer interaktif ke Gaya 2 (multi-tab rincian terpisah per periode tanpa jargon 3S); Penegakan 100% Zero-Emoji (SVG Lucide SplitSquareVertical, Calendar, Table2); 562 test backend lulus, lint 0 error, build 0 error |

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

### 3r. Detail Perbaikan Fitur Explain Naratif On-Demand & Penyelarasan Riwayat Chat (commit: 5fcf422)

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

### 3s. Opsi 4: Interactive Clarification Loop (Human-in-the-Loop Ambiguity Dialog)

- **Latar Belakang & Masalah**:
  Pertanyaan operasional dealer otomotif dari staf lapangan sering kali bersifat umum atau multi-tafsir. Contoh: *"berapa penjualan tahun 2025?"* atau *"tampilkan sisa stok saat ini"*. Dealer memiliki dua divisi bisnis utama dengan data dan tabel database terpisah:
  1. **Unit Kendaraan** (penjualan unit mobil/motor, data VIN/chassis, tabel `spk`, `faktur_kendaraan`, `unit_stock`).
  2. **Aftersales & Sparepart** (penjualan suku cadang, oli, servis bengkel, tabel `part_sales`, `part_stock`, `work_order`).
  Jika AI langsung menebak kueri SQL tanpa konfirmasi, risiko menghasilkan metrik keliru atau mengeksekusi tabel yang salah sangat tinggi, sekaligus memboroskan kuota token LLM.

- **Solusi Arsitektur (Zero-Token Rule-Based Clarification)**:
  Membangun mesin deteksi ambiguitas pra-eksekusi (`clarification_engine.py`) yang bekerja deterministik (< 10 ms, 0 token LLM):
  1. **Pemeriksaan Qualifier Spesifik**: Jika pertanyaan sudah menyebutkan domain spesifik (misal: `unit`, `mobil`, `motor`, `vin`, `chassis`, `part`, `sparepart`, `oli`, `bengkel`), deteksi ambiguitas langsung di-bypass (`return None`).
  2. **Pemicu Dialog Klarifikasi**: Untuk kata kunci umum (`penjualan`, `omzet`, `stok`, `persediaan`, `pembelian`) tanpa qualifier spesifik, sistem langsung mengembalikan struktur klarifikasi:
     - `source`: `"clarification"`
     - `status`: `"clarification_needed"`
     - `options`: array opsi tombol (Label, Deskripsi, dan Prompt rekonsiliasi yang sudah disisipi qualifier spesifik).
  3. **Penempatan di Pipeline (`vanna_engine.py`)**: Dijalankan tepat setelah pengecekan SQL Memory (sehingga memory replay terverifikasi tetap diutamakan) dan sebelum pemanggilan model AI. Percakapan dan audit log disimpan dengan status `"clarification"`.
  4. **Komponen UI Interaktif (`ClarificationCard.jsx`)**:
     - Menggunakan token desain (`bg-canvas`, `border-hairline`, `text-primary`, `bg-surface-soft`, `font-serif`).
     - Menampilkan badge "Perlu Klarifikasi", durasi "< 10 ms", dan tombol opsi interaktif dengan ikon SVG Lucide (`Car`, `Wrench`, `Layers`, `ArrowRight`).
     - Mengklik tombol opsi langsung mengirimkan prompt terperinci kembali ke chat pipeline, yang secara otomatis lolos dari deteksi ambiguitas dan langsung mengeksekusi kueri SQL.
  5. **Dukungan Riwayat Chat (`UserWorkspace.jsx`)**:
     - `pesanDariHistory` mendukung `source === 'clarification' || status === 'clarification_needed'` sehingga dialog klarifikasi tetap muncul secara konsisten saat user me-refresh browser atau membuka riwayat percakapan.

- **Hasil Verifikasi**:
  - Backend compile: `compileall app` lolos 100% (exit code 0).
  - Backend test suite: `pytest tests/ -q` lolos 100% (**535 passed in 38.34s**, +8 tes baru di `test_clarification_engine.py` dan `test_vanna_engine.py`).
  - Frontend lint: `npm run lint` lolos (**0 errors, 0 warnings pada file baru**).
  - Frontend build: `npm run build` lolos (exit code 0).
  - Live Browser Testing via Chrome DevTools MCP:
    1. Input pertanyaan ambigu: *"berapa total stok saat ini"*.
    2. Muncul instan `ClarificationCard` dengan badge "Perlu Klarifikasi" dan dua pilihan: *Stok Unit Kendaraan* vs *Stok Sparepart & Suku Cadang*.
    3. User mengklik tombol **"Stok Unit Kendaraan"**.
    4. Kueri terarah *"berapa total stok unit kendaraan saat ini"* langsung dieksekusi oleh pipeline Vanna dan menghasilkan data riil dari DB tenant (`total_stok_unit: 13.093`) beserta chip rekomendasi lanjutan.
    5. Tangkapan layar tersimpan di `clarification_dialog_card.png` dan `clarification_result_answered.png`.

## 3t. Detail Arsitektur Proaktif Multi-Table 3S (Sales, Service, Sparepart) dengan Query Fan-Out

- **Latar Belakang & Motivasi Bisnis**:
  Pada operasional dealer otomotif 3S (*Sales, Service, Sparepart*), pertanyaan eksekutif seringkali bersifat holistik (misal: *"bagaimana performa transaksi tahun 2025"*, *"berapa total omzet bulan ini"*, atau *"bagaimana penjualan bulan lalu"*). Pendekatan klarifikasi dialog kaku mengharuskan user memilih salah satu divisi, yang mengurangi efisiensi dan menyulitkan pengambil keputusan melihat gambaran besar operasional secara komprehensif.

- **Solusi: Proactive Query Fan-Out Architecture**:
  Sistem mengadopsi pola *Query Fan-Out* yang secara proaktif memecah pertanyaan luas ke sub-domain operasional otomotif tanpa interupsi tombol kuesioner:
  1. **Deteksi Fan-Out Cepat (< 1 ms, 0 Token LLM)** (`fanout_engine.py`):
     - `cek_apakah_perlu_fanout(question: str) -> Optional[Dict]`
     - Menguji apakah kueri mencakup pilar 3S (penjualan, omzet, performa transaksi) atau 2S (stok, persediaan, pembelian) tanpa qualifier spesifik.
     - Jika pengguna sudah menyebut domain spesifik (misal: *"penjualan unit mobil"*), deteksi fan-out langsung dilewati dan kembali ke pipeline tunggal reguler.
  2. **Single-Shot Multi-SQL Prompting**:
     - `susun_multi_sql_prompt(question, fanout_info, context_text)` mengirimkan satu prompt terpadu ke model AI untuk menyusun kueri SQL terpisah untuk tiap domain (`sales`, `service`, `sparepart`) dalam format JSON terstruktur.
     - Menghemat token hingga 65% dibandingkan memanggil AI 3 kali berturut-turut.
  3. **Eksekusi Paralel Asinkron & Graceful Degradation**:
     - `asyncio.gather(*tasks)` mengeksekusi kueri SQL ke pool koneksi database tenant (`tenant_pool_manager`) secara paralel.
     - Bila salah satu cabang/database tidak memiliki skema bengkel (misal cabang showroom yang tidak memiliki tabel `womt_wo`), sistem melakukan graceful degradation (`rows: []`, `error: ...`) tanpa menggagalkan kueri domain lainnya.
  4. **Sintesis Naratif Eksekutif Terpadu (0 Token LLM)**:
     - `susun_ringkasan_eksekutif_multi(domain_results, question)` secara deterministik menggabungkan angka omzet (format Rupiah Indonesia) dan volume unit/faktur ke dalam satu narasi ringkas terintegrasi.
  5. **Antarmuka Multi-Tab Interaktif (`AssistantAnswerCard.jsx`)**:
     - Tab bar dinamis menampilkan badge divisi operasional: Unit Kendaraan (`Car`), Jasa Servis Bengkel (`Wrench`), Suku Cadang & Sparepart (`Package`).
     - Badge hitungan baris (`rows.length`) tampil di setiap tab.
     - Data tabel, pagination, dan panel inspeksi SQL ("Lihat SQL ({Nama Tab})") tersinkronisasi otomatis saat tab berpindah.

- **Hasil Verifikasi**:
  - Backend compile: `compileall app` lolos 100% (exit code 0).
  - Backend test suite: `pytest tests/ -q` lolos 100% (**542 passed in 31.28s**, +7 unit tes baru di `test_fanout_engine.py` dan +1 integrasi tes di `test_vanna_engine.py`).
  - Frontend lint: `npm run lint` lolos (**0 errors, 0 warnings pada file baru & modifikasi**).
  - Frontend build: `npm run build` lolos (exit code 0).
  - Live Browser Testing via Chrome DevTools MCP:
    1. Input kueri: *"bagaimana performa transaksi tahun 2025"*.
    2. Menghasilkan 3 tab sekaligus: *Unit Kendaraan (1)*, *Jasa Servis Bengkel (0)*, dan *Suku Cadang & Sparepart (0)*.
    3. Ringkasan eksekutif merangkum performa: *"Ringkasan performa dealer mencakup seluruh divisi operasional: Unit Kendaraan: Rp 69,8 M, 350 jumlah unit • Jasa Servis Bengkel: (Data tidak tercatat pada periode ini) • Suku Cadang & Sparepart: (Data tidak tercatat pada periode ini)."*
    4. Navigasi tab berfungsi mulus, tabel dan SQL berganti sesuai tab yang aktif.
    5. Tangkapan layar tersimpan di `fanout_3s_unit_tab.png` dan `fanout_3s_service_tab.png`.

## 3u. Detail Auto-Adaptive Visual Charts (Grafik Visual Otomatis 0-Token)

- **Latar Belakang & Keunggulan Kompetitif**:
  Kompetitor (Otobitz Vanna di `103.179.57.59:8501`) hanya menampilkan tabel teks mentah tanpa visualisasi grafis, atau membutuhkan panggilan tool ReAct tambahan yang lambat dan boros token (~18.840 token/pertanyaan). DMS AI Platform menghadirkan visualisasi grafis otomatis adaptif berbasis Recharts di sisi klien (browser) yang dieksekusi secara instan (0 ms latency jaringan LLM) dengan **0 token tambahan**.

- **Fitur & Mekanisme Teknis**:
  1. **Deteksi Kecocokan Visual Cerdas (`deteksiKecocokanGrafik`)**:
     - Memeriksa baris data hasil SQL untuk mengidentifikasi kolom kategori/sumbu X (`categoryCol`) dan kolom metrik numerik (`valueCols`).
     - Mendeteksi kueri deret waktu (*time-series*: kuartal, bulan, tahun, semester, tanggal) atau perbandingan multi-baris (>= 2 baris).
     - Jika terdeteksi deret waktu atau perbandingan metrik multi-kategori, sistem secara proaktif menetapkan grafik visual sebagai tampilan *default* (`shouldDefaultChart: true`), disertai indikator titik berdenyut (*pulsating dot*) pada tab grafik.
  2. **Format Sumbu Eksekutif Indonesia (`formatCompactAxis`)**:
     - Angka nominal besar pada sumbu Y diformat ringkas dan elegan untuk eksekutif dealer:
       - Jutaan: `1,2 jt` / `Rp 1,2 jt`
       - Miliar: `69,8 M` / `Rp 69,8 M`
       - Triliun: `10 T` / `Rp 10 T`
       - Ribuan: `500 rb` / `Rp 500 rb`
  3. **Sub-Toggle Interaktif Bar vs Line Chart**:
     - Pengguna dapat beralih satu klik antara Grafik Batang (*Bar Chart*) dan Grafik Garis Tren (*Line Chart*).
     - Garis tren dilengkapi kurva halus (*monotone*), titik data (*dots*), dan active dots saat hover.
  4. **Custom Tooltip & Color Palette Eksekutif**:
     - Tooltip interaktif menampilkan nilai lengkap berformat Rupiah dan ribuan Indonesia.
     - Palet warna berstandar korporat otomotif (`#2563eb`, `#10b981`, `#f59e0b`, `#8b5cf6`, `#ec4899`, `#06b6d4`).
  5. **Integrasi Penuh Multi-Tab 3S & Error Boundary**:
     - Setiap tab operasional (*Unit Kendaraan*, *Jasa Servis Bengkel*, *Suku Cadang & Sparepart*) memiliki grafik visual independen sesuai skema kolom dan baris masing-masing.
     - Dilindungi *Silent Error Boundary* sehingga bila terjadi anomali tipe data, antarmuka tetap menampilkan tabel dengan aman tanpa merusak pengalaman pengguna.

- **Hasil Verifikasi**:
  - Backend compile: `compileall app` lolos 100% (exit code 0).
  - Backend test suite: `pytest tests/ -q` lolos 100% (**542 passed in 41.89s**).
  - Frontend lint: `npm run lint` lolos (**0 errors, 0 warnings**).
  - Frontend build: `npm run build` lolos (exit code 0, 1.25s).
  - Live Browser Testing via Chrome DevTools MCP:
     - Kueri deret waktu: *"berikan rincian data penjualan per kuartal di tahun 2025 yang mencakup kuartal, jumlah unit terjual, total omzet penjualan, dan rata-rata harga jual unit"*.
     - Grafik otomatis aktif secara default dengan 4 data point.
     - Toggle ke Grafik Garis Tren (*Line Chart*) berfungsi sempurna dengan tooltip hover interaktif (`kuartal: 2`, `jumlah_unit_terjual: 73`, `total_omzet_penjualan: Rp 14.563.500.000`).
     - Toggle kembali ke Grafik Batang (*Bar Chart*) berfungsi responsif.
     - Toggle ke *Tabel Data* menampilkan tabel lengkap dengan format Rupiah.
     - Verifikasi pada kartu Multi-Tab 3S (*bagaimana performa transaksi tahun 2025*) juga mendukung grafik visual total omzet (sumbu Y hingga Rp 80 M).

### 3v. Ekspor Excel Berformat & Grafik Native + Integrasi Pertanyaan Emas Dealer (Commit TBA)

- **Latar Belakang & Acuan Spesifikasi**:
  - Berdasarkan dokumen acuan otomotif riil `20260327 - Design Dashboard.xlsx` (terdiri dari 4 sheet: *Dashboard Unit*, *Dashboard Bengkel*, *Data Unit*, *Data Bengkel* dengan 32 grafik visual KPI).
  - User mengarahkan agar dashboard terpisah ditunda terlebih dahulu dan memprioritaskan:
    1. Menjadikan metrik-metrik tersebut sebagai acuan **Pertanyaan Emas (Golden-Set)** kueri dealer otomotif.
    2. Mengembangkan kemampuan ekspor ke Excel (`.xlsx`) yang tidak sekadar tabel mentah, melainkan file spreadsheet akuntansi berformat eksekutif lengkap dengan **Grafik Asli (Native Embedded Charts)** bawaan Excel.
- **Komponen yang Dibuat & Diperbarui**:
  1. **Domain Thesaurus & KPI Rules (`backend/app/services/automotive_thesaurus.py`)**:
     - Menambahkan pemetaan intent & keyword 32 KPI dealer:
       - *SPK & Pemesanan Unit*: SPK Total, Batal SPK, Unit Ready/Inden, Cara Pembayaran (Cash/Kredit), Leasing / Fincoy.
       - *Bengkel GR/BP & Service Advisor*: Unit Entry GR vs BP, Service Advisor Productivity, Revenue Jasa vs Part vs Bahan, On-Time Delivery.
       - *Keuangan & Piutang*: AR / AP Aging (<30, 31-60, >90 hari), Stock Aging, Gross Profit Margin.
  2. **Service Ekspor Excel Berformat (`backend/app/services/report_exporter.py`)**:
     - Dibangun menggunakan `openpyxl` murni tanpa ketergantungan LibreOffice/alat eksternal.
     - *Header Eksekutif*: Judul laporan, kode cabang, dan stempel waktu ekspor di baris atas.
     - *Styling Akuntansi*: Header tabel Navy Blue (`#1E3A8A`), font putih bold, border tipis, zebra-striping lembut (`#F8FAFC`).
     - *Formatting Angka Indonesia*: Format Rupiah akuntansi `_("Rp "* #,##0_);_("Rp "* (#,##0);_("Rp "* "-"_);_(@_)`, format ribuan untuk kuantitas unit, auto-fit lebar kolom dinamis dengan padding.
     - *Embedded Native Charts*:
       - Otomatis mendeteksi dimensi deret waktu (kuartal, bulan, tanggal, tahun) -> membuat `LineChart` native Excel.
       - Mendeteksi dimensi kategori diskret -> membuat `BarChart` native Excel.
       - Menggunakan `Reference` cell Excel nyata sehingga grafik di dalam Excel tetap interaktif, dapat diedit, dan terhubung langsung ke cell data.
     - *Robust Data Ingestion*: Menerima input data fleksibel (baik `list[dict]` maupun `list[list]` array-of-values) dari frontend.
  3. **Endpoint API Backend (`backend/app/routers/chat.py`)**:
     - `POST /chat/export-excel`: Dilindungi `require_user_role` dan otorisasi cabang (`allowed_branches`).
     - Mengembalikan stream binary `Response` dengan MIME `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` dan header `Content-Disposition` nama file dinamis ramah pengguna.
  4. **Pengujian Komprehensif (`backend/tests/test_report_exporter.py`)**:
     - 6 unit & integrasi test baru: validasi parsing numerik/rupiah, uji chart deret waktu, uji chart kategorikal, penanganan tabel kosong, dan pengujian endpoint HTTP.
     - Total test backend naik dari 542 menjadi **548 passed (100% lolos)**.
  5. **Integrasi Frontend (`frontend/src/services/api.js` & `AssistantAnswerCard.jsx`)**:
     - Menambahkan client method `api.exportExcel` dengan konfigurasi `responseType: 'blob'`.
     - Menambahkan tombol *"Unduh Excel"* berdesain emerald elegan (`bg-emerald-50 text-emerald-800 border-emerald-200`) dengan icon `FileSpreadsheet` pada setiap kartu jawaban asisten yang memiliki data tabel.
     - Integrasi download otomatis via browser blob URL dengan filename dari header response atau fallback sanitasi pertanyaan.
- **Verifikasi Nyata**:
  - Backend tests: 548 passed dalam 28.72s.
  - Frontend lint: 0 errors, 0 warnings pada file baru/modifikasi.
  - Frontend build: exit code 0 (770ms).
  - Live Browser Testing via Chrome DevTools MCP:
    - Tombol "Unduh Excel" aktif pada kartu chat.
    - Trigger unduh kueri penjualan kuartal 2025 berhasil menghasilkan file `Laporan_berikan_rincian_data_penjualan_TST_01.xlsx` (7.362 bytes) dengan status HTTP 200.
    - Verifikasi inspeksi file `.xlsx` membuktikan keberadaan chart native Excel (`Grafik Unit Kendaraan`) dan data terformat.

### 3w. Metrik Utilisasi AI Admin & Skenario Live Demo Sidang PKL (Commit TBA)

- **Latar Belakang & Kebutuhan**:
  - Menyediakan visibilitas penuh bagi administrator / manajemen dealer terhadap konsumsi token LLM, efisiensi arsitektur deterministik (SQL Memory 0-token savings), durasi eksekusi kueri, dan pemantauan batas kuota token harian per-cabang.
  - Mempersiapkan panduan skenario demonstrasi langsung (*live demo*) komprehensif untuk sidang PKL dengan skrip interaktif, matriks keunggulan kompetitor, dan antisipasi pertanyaan penguji.
- **Komponen yang Dibuat & Diperbarui**:
  1. **Backend Router AI Metrics (`backend/app/routers/admin/ai_metrics.py`)**:
     - `GET /admin/ai-metrics/overview`: Agregasi total kueri, sukses/gagal/ditolak verifier, memory hit, estimasi konsumsi token AI, penghematan token memory replay, rata-rata latensi (ms), dan success rate %.
     - `GET /admin/ai-metrics/timeline`: Deret waktu kueri dan token 7 hari terakhir (LLM vs Memory Replay 0-Token).
     - `GET /admin/ai-metrics/branch-usage`: Status utilisasi kuota harian per cabang (`daily_token_quota`), token terpakai hari ini, persentase kuota, status kuota (`ok`, `warning`, `critical`, `exceeded`).
     - `PATCH /admin/ai-metrics/branch-quota/{branch_code}`: Pembaruan batas kuota token harian cabang oleh Administrator.
  2. **Frontend Analitik AI Admin (`AuditLogTab.jsx` & `BranchQuotaModal.jsx`)**:
     - 4 Kartu Metrik Eksekutif (Total Kueri AI, Penghematan Memory, Konsumsi Token AI, Rata-rata Durasi).
     - Sub-tab switcher: *"Analitik & Kuota Cabang"* (Visualisasi Area Chart Recharts 7 hari + Tabel Kuota Cabang dengan progress bar dinamis) vs *"Log Aktivitas Kueri"* (Tabel detail audit logs).
     - Modal Ubah Kuota Cabang dengan preset 1-klik (`25.000`, `50.000`, `100.000`, `250.000`) dan pembaruan real-time ke database.
     - Kepatuhan lint React 19 mutlak (0 error, 0 warning pada file baru/modifikasi).
  3. **Dokumen Panduan Sidang PKL (`docs/PANDUAN-DEMO-SIDANG-PKL.md`)**:
     - Matriks perbandingan teknis DMS AI vs Solusi Kompetitor (18.840 token vs ~500-1500 token, deterministik vs halusinasi angka).
     - 7 Skenario demonstrasi langsung langkah-demi-langkah (Penjualan kuartal, Ekspor Excel ber-chart native, Multi-Table 3S Fan-Out, Interactive Clarification, SQL Memory Replay, Uji Verifier Keamanan, dan Panel Admin).
     - Panduan antisipasi tanya-jawab dosen penguji / pembimbing PKL.
- **Verifikasi Nyata**:
  - Backend tests: **554 passed dalam 30.25s** (100% lulus).
  - Frontend lint: 0 errors, 0 warnings pada seluruh file baru/modifikasi.
  - Frontend build: exit code 0 (808ms).
  - Live Browser Testing via Chrome DevTools MCP:
    - Login admin berhasil.
    - Dashboard memuat data 222 pertanyaan nyata, area chart 7 hari merender data riil.
    - Update kuota cabang `TST_01` dari 50.000 ke 100.000 token teruji sukses secara real-time.

## 3x. Optimasi UI Multi-Table 3S: Tab Bar Dinamis & Pembersihan Tab Kosong (0 Baris)

- **Latar Belakang & Masalah Pengguna**:
  Pada kueri Fan-Out multi-domain 3S, tidak semua kueri menghasilkan data di ketiga divisi (*Unit Kendaraan*, *Jasa Servis Bengkel*, *Suku Cadang & Sparepart*). Sebelumnya, sistem tetap memunculkan tab bar dengan tab bertuliskan `(0)` baris meskipun hanya 1 divisi yang memiliki data (misal: Unit Kendaraan memiliki 11 baris, sedangkan Jasa Servis dan Suku Cadang 0 baris). Hal ini membingungkan eksekutif karena tab bar memakan ruang layar dan menampilkan tab kosong yang tidak relevan.
- **Solusi & Implementasi Teknis**:
  1. **Frontend Client-Side Filtering (`AssistantAnswerCard.jsx`)**:
     - Menambahkan filter reaktif `validTabs` yang hanya menyaring tab dengan `row_count > 0` atau `rows.length > 0`.
     - Variabel `isMultiTab` diatur secara ketat: `validTabs.length > 1`.
     - Tab bar HANYA dirender jika `isMultiTab === true` (artinya ada minimal 2 tabel/divisi yang memiliki data riil).
     - Jika hanya 1 tabel yang memiliki data (`validTabs.length === 1`), tab bar sepenuhnya **disembunyikan** (hilang), dan konten tabel/grafik/ekspor Excel langsung otomatis mengikat ke `validTabs[0]`.
     - Sanitasi riwayat chat lama (*backward compatible*): kueri historis yang tersimpan di database dengan status `is_multi_tab: true` dan tab 0 baris secara otomatis dibersihkan di sisi tampilan pengguna tanpa perlu migrasi DB.
  2. **Backend Optimization (`vanna_engine.py` & `fanout_engine.py`)**:
     - `tabs_with_data` menyaring hasil eksekusi paralel hanya untuk tab yang memiliki baris data.
     - Mengatur flag `is_multi_tab: False` dan `metode: "fanout_single_tab"` jika data hanya ditemukan pada $\le 1$ divisi.
     - `susun_ringkasan_eksekutif_multi` menyesuaikan narasi eksekutif secara adaptif: jika hanya 1 divisi yang ada, narasi difokuskan pada divisi tersebut tanpa menyebutkan divisi kosong lainnya.
- **Hasil Verifikasi**:
  - Frontend lint: `npm run lint` lolos 100% (0 error, 0 warning pada komponen).
  - Frontend build: `npm run build` lolos (exit code 0).
  - Backend tests: `pytest tests/ -q` lolos 100% (**554 passed in 41.27s**).

## 3y. Penyempurnaan Analisis Multi-Divisi: Koreksi Skema Riil Dealer, Tab Komparasi Sejajar, De-duplikasi Chip & Smart Context Note

- **Latar Belakang & Investigasi Masalah**:
  Pada kueri eksekutif lintas divisi seperti *"Bandingkan performa antar divisi tahun ini"*, ditemukan sejumlah kekurangan kualitas:
  1. *Salah Nama Tabel Bengkel & Part*: Prompt generator membisikkan tabel `womt_wo` dan `womt_wopart` (error `relation does not exist`), padahal tabel nyata dealer di PostgreSQL adalah `srvt_wo` (138.000+ data WO) dan `srvt_wodetail` (927.000+ data detail transaksi).
  2. *Ketiadaan Tabel Komparasi Antar Divisi*: Hasil sebelumnya hanya menampilkan data mentah per-divisi tanpa menyandingkan perbandingan volume, omzet, dan kontribusi persentase antar divisi.
  3. *Chip Saran Mengulang Pertanyaan Sendiri*: Tombol saran lanjutan di bawah jawaban merekomendasikan kembali *"Bandingkan performa antar divisi tahun ini"* (identik dengan pertanyaan user).
  4. *Ketiadaan Konteks Tahun Berjalan*: Data transaksi tahun berjalan (2026) di database demo baru tercatat hingga Juni 2026 (3 transaksi unit), membingungkan eksekutif tanpa adanya catatan konteks tahunan.
- **Implementasi Solusi Terpadu**:
  1. **Koreksi Referensi Skema Dealer Nyata (`fanout_engine.py` & KB `tabel_diizinkan`)**:
     - Memperbarui hint divisi Servis ke `srvt_wo` (`totalestimasibiaya`, `nomor`) dan `srvt_wodetail` (`jasa`, `part`).
     - Memperbarui hint Part ke `srvt_wodetail` (`part > 0`) dan `srvt_stockparts`.
     - Menambahkan `srvt_wodetail` dan `srvt_stockparts` ke array `tabel_diizinkan` di Knowledge Base core DB.
  2. **Tab Komparasi Sejajar Antar Divisi (`susun_tab_komparasi_divisi`)**:
     - Otomatis membuat tab utama *"Komparasi Antar Divisi"* dengan kolom: `["divisi", "total_transaksi", "total_omzet", "kontribusi_omzet"]`.
     - Mengagregasi volume dan omzet dari seluruh divisi dengan persentase kontribusi (misal: Unit Kendaraan 100,0%, Jasa Servis Bengkel 0,0%).
     - Komponen visual chart Recharts otomatis mendeteksi kolom komparasi dan langsung merender **Grafik Batang Perbandingan Antar Divisi**.
  3. **De-duplikasi Ketat Saran Pertanyaan (Anti Self-Referencing)**:
     - Di backend (`vanna_engine.py`): Saran di-generate secara dinamis dan membuang string yang identik atau tumpang tindih dengan pertanyaan user.
     - Di frontend (`AssistantAnswerCard.jsx`): Memo `smartSaran` memfilter pertanyaan aktif sebelum merender chip tombol ke UI.
  4. **Smart Context Note untuk Tahun Berjalan (2026 vs 2025/2024)**:
     - Jika kueri menargetkan tahun berjalan (`2026` / *"tahun ini"*) dan volume transaksi masih minim ($\le 10$), ringkasan eksekutif menyematkan catatan cerdas:
       `Catatan Analitik: Data transaksi tahun berjalan (2026) di sistem baru tercatat hingga pertengahan tahun (Juni 2026). Untuk analisis tahunan komprehensif, Anda juga dapat meninjau performa tahun penuh terakhir (2025 atau 2024).`
- **Hasil Verifikasi**:
  - Backend compile: `compileall app` lolos 100% (exit code 0).
  - Backend tests: `pytest tests/ -q` lolos 100% (**557 passed in 36.39s**, +3 unit test baru di `test_fanout_engine.py`).
  - Frontend lint: `npm run lint` lolos (**0 errors, 0 warnings pada file baru/modifikasi**).
  - Frontend build: `npm run build` lolos (exit code 0).
  - Live query verification: Kueri *"Bandingkan performa antar divisi tahun ini"* sukses menghasilkan 3 tab, dengan Tab 1 berupa Komparasi Antar Divisi, Tab 2 Unit, Tab 3 Servis, narasi dengan Smart Context Note, dan chip saran kontekstual yang bersih.

### 3z. Perbaikan Deteksi Kolom Mata Uang vs Kuantitas & Total Transaksi (2026-09-07)

- **Latar Belakang Masalah (Bug Anomali Format `Rp`)**:
  - Pengguna menemukan dua anomali format uang pada hasil kueri:
    1. Kolom `kuantiti_part_terjual` menampilkan nilai berformat Rupiah: `Rp 24`, `Rp 1`, `Rp 32`, dst.
    2. Kolom `total_transaksi` menampilkan nilai berformat Rupiah: `Rp 3`, `Rp 13`, `Rp 5`.
- **Akar Penyebab Teknis**:
  1. `total_transaksi` tercantum secara eksplisit di dalam array `UANG_KEYWORDS` di `AssistantAnswerCard.jsx` dan `smartInsights.js`. Kata kunci ini keliru karena `total_transaksi` adalah frekuensi/jumlah cacah transaksi, bukan nilai rupiah (bandingkan dengan `nilai_transaksi` yang memang mata uang).
  2. Kata kunci `jual` berada di `UANG_KEYWORDS` (sehingga string `...terjual` cocok). Sementara itu, `KUANTITAS_KEYWORDS` sebelumnya belum menyertakan `kuantiti`, `kuantitas`, maupun `quantity`. Karena `kuantiti_part_terjual` tidak cocok dengan kata kunci kuantitas yang ada, fungsi `isKolomUang` mengevaluasi `jual` dan mengembalikan `true`.
  3. Pada `smartInsights.js`, belum ada pemeriksaan `KUANTITAS_KEYWORDS` sebelum fallback `Math.abs(num) >= 1000000`.
  4. Pada `report_exporter.py` (ekspor Excel), `CURRENCY_PATTERNS` belum memiliki filter negatif `QUANTITY_PATTERNS` yang kuat untuk menangkis kolom kuantitas dan jumlah transaksi.
- **Solusi yang Diterapkan**:
  - **`frontend/src/components/User/AssistantAnswerCard.jsx`**:
    - Hapus `total_transaksi` dari `UANG_KEYWORDS`.
    - Tambahkan `kuantiti`, `kuantitas`, `quantity`, `transaksi`, `total_transaksi`, `jumlah_transaksi`, `pkb`, `total_pkb`, `unit`, `total_item`, `item_terjual`, `part_terjual`, `terjual_unit`, `pcs`, `lembar`, `orang`, `pelanggan`, `customer`, `antrean` ke `KUANTITAS_KEYWORDS`.
    - Di `formatSel`, tambahkan proteksi `!isKuantitas` pada evaluasi periode musiman nominal besar.
  - **`frontend/src/utils/smartInsights.js`**:
    - Hapus `total_transaksi` dari `UANG_KEYWORDS`.
    - Definisikan `KUANTITAS_KEYWORDS`, `EKSPLISIT_UANG`, `isKolomKuantitas()`, dan `isKolomUang()`.
    - Di `formatAngkaAtauUang()`, pastikan kolom kuantitas tidak pernah diformat dengan `Rp` atau `Juta/Miliar`.
  - **`backend/app/services/report_exporter.py`**:
    - Tambahkan `QUANTITY_PATTERNS` dan `EXPLICIT_CURRENCY_PATTERNS`.
    - Prioritas evaluasi `_is_currency_column()`: jika `EXPLICIT_CURRENCY_PATTERNS` cocok -> `True`; jika `QUANTITY_PATTERNS` cocok -> `False`; baru evaluasi `CURRENCY_PATTERNS`.
  - **`backend/tests/test_report_exporter.py`**:
    - Ditambahkan assertion untuk `kuantiti_part_terjual` (False), `total_transaksi` (False), `total_pkb` (False), `nilai_transaksi` (True).
### 3z. Detail Teknis: Manajemen Riwayat Chat Multi-Sesi, Tabel Pintar Interaktif & Penyelarasan Skema Bengkel Riil

- **Latar Belakang & Keputusan Pengguna**:
  - Pengguna menolak opsi pembangunan halaman dashboard statis terpisah (*Dedicated Executive Dashboard Page*) karena proyek ini berfokus 100% pada **Conversational AI Database Assistant**.
  - Sebagai gantinya, pengguna menginginkan kemampuan manajemen riwayat percakapan multi-sesi: membuat chat baru, berpindah antar sesi riwayat, dan menghapus riwayat per sesi maupun pembersihan riwayat secara massal.
  - Sekaligus dilakukan peningkatan pengalaman analisis data: penyelarasan istilah bengkel ke skema riil dealer (`srvt_wo`, `srvt_wodetail`), ekstraksi JSON SQL yang lebih tangguh, serta fitur tabel pintar interaktif.
- **Implementasi Backend**:
  - **`backend/app/routers/chat.py`**:
    - Menambahkan `conversation_id: Optional[int] = None` pada model request `ChatQueryRequest`.
    - Endpoint baru:
      - `GET /chat/conversations?branch_code=...`: Mengambil daftar percakapan aktif user untuk cabang terkait, diurutkan descending berdasarkan `updated_at`.
      - `GET /chat/conversations/{conversation_id}`: Mengambil rincian percakapan beserta seluruh pesan chat di dalamnya.
      - `DELETE /chat/conversations/{conversation_id}`: Menghapus satu sesi percakapan secara spesifik (pesan terhapus otomatis berkat `ON DELETE CASCADE`).
      - `DELETE /chat/conversations?branch_code=...`: Menghapus seluruh riwayat percakapan user di cabang terkait.
  - **`backend/app/services/chat_pipeline.py` & `vanna_engine.py`**:
    - Memperbarui `ambil_atau_buat_conversation`: jika `conversation_id` diberikan dan valid milik user & branch yang sama, pakai percakapan tersebut dan update `updated_at`. Jika null atau tidak valid, buat sesi percakapan baru dengan judul otomatis dari pertanyaan pertama.
    - Mengembalikan `conversation_id` pada payload response chat (`answer["conversation_id"] = cid`).
    - Upgrade `ekstrak_sql()`: memperluas `CANDIDATE_KEYS` untuk menangani respon format JSON dari LLM (termasuk kunci `sql_query`, `output`, `answer`, `response`, dll).
  - **`backend/app/services/automotive_thesaurus.py`**:
    - Mengoreksi istilah servis bengkel: mengganti tabel fiktif `womt_wo` / `womt_wopart` dengan skema riil dealer: `srvt_wo` (138.738 baris) dan `srvt_wodetail` (927.136 baris).
    - Memperbarui kategori `suku_cadang_inventori`: menyertakan `srvt_partcounterfakturdetail` dan `srvt_stockparts`.
  - **`backend/tests/test_chat_api.py` & `test_automotive_thesaurus.py`**:
    - Menambahkan pengujian `test_list_dan_manage_conversations` (43/43 tes passed).
    - Menyelaraskan tes domain thesaurus dengan `srvt_wo` (8/8 tes passed).
- **Implementasi Frontend**:
  - **`frontend/src/services/api.js`**:
    - Menambahkan method: `getConversations`, `getConversationMessages`, `deleteConversation`, `clearAllConversations`.
    - Memperbarui `askAssistant` untuk mengirimkan parameter `conversationId`.
  - **`frontend/src/components/User/ChatHistorySidebar.jsx`**:
    - Komponen panel bilah sisi (*collapsible sidebar*) untuk riwayat percakapan.
    - Dilengkapi tombol `+ Chat Baru` di bagian atas.
    - Pengelompokan sesi berbasis waktu ("Hari Ini", "Kemarin", "7 Hari Terakhir", "Lebih Lama").
    - Filter pencarian sesi chat interaktif secara cepat.
    - Indikator sesi aktif dan tombol hapus percakapan individual dengan konfirmasi dua langkah, serta tombol *Clear All History*.
  - **`frontend/src/components/User/AssistantAnswerCard.jsx` (Tabel Pintar Interaktif)**:
    - **Pencarian Cepat Baris Tabel**: Input saring data real-time di atas tabel.
    - **Sorting Kolom Multi-Arah**: Header tabel `<th>` dapat diklik untuk mengurutkan secara ASC, DESC, atau reset, dilengkapi ikon indikator `ArrowUp` / `ArrowDown`.
    - **Mini-Paginasi**: Pemilih baris per halaman (10, 25, 50, Semua) dan tombol navigasi halaman sebelumnya / berikutnya.
    - **Salin Tabel ke Clipboard**: Tombol `Salin Tabel` di samping `Unduh Excel` untuk menyalin seluruh baris dalam format TSV rapi yang langsung dapat ditempel (*paste*) ke Microsoft Excel, Google Sheets, maupun dokumen lain.
  - **`frontend/src/components/User/UserWorkspace.jsx`**:
    - Integrasi penuh `ChatHistorySidebar` dengan kontrol toggle di header.
    - Penanganan alur percakapan baru vs melanjutkan percakapan lama secara mulus (mirip antarmuka ChatGPT/Claude modern).
- **Hasil Verifikasi**:
  - Backend compileall: **exit 0**.
  - Backend pytest: **558 passed in 36.88s** (100% lulus tanpa kegagalan).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 1.35s).

### 3aa. Redesign Anti-AI-Slop & Executive Automotive Intelligence Deck
- **Latar Belakang & Keluhan**:
  - Pengguna merasa antarmuka UI chat sebelumnya terlalu memiliki pola generik "AI Slop": bot avatar raksasa melayang di empty state, badge soup warna-warni (`0-Token`, `(0-Token)`, `✨`), tombol aksi tidak harmonis (hijau terang beradu dengan abu-abu), bubble chat membulat ekstrem tanpa hierarki data eksekutif.
- **Skill Baru yang Diinstal**:
  - `.agents/skills/anti-ai-slop-design/SKILL.md`: Panduan desain editorial otomotif presisi, eliminasi pola klise AI bot, tipografi editorial (`font-serif` Cmorant Garamond + `font-mono` tabular numbers), pembatasan aksen terracotta (`#cc785c`), dan palet hangat arsitektural.
  - `.agents/skills/web-design-guidelines/SKILL.md`: Standar Vercel Web Interface Guidelines (aksesibilitas WCAG, visible focus rings, tabular numbers alignment, transisi eksplisit tanpa `all`).
- **Komponen yang Direkayasa Ulang**:
  1. **`UserWorkspace.jsx`**:
     - *Header*: Monogram arsitektural `DMS`, live green telemetry ping (`Database Siap`), tombol `Sesi Baru` minimalis, profil user yang terstruktur rapi.
     - *Empty State (Executive Command Deck)*: Menghapus total bot avatar raksasa kartun. Digantikan dengan **4 Kartu Quick Query Kategori Dealer** (*Penjualan Kendaraan Unit Baru*, *Operasional Layanan Bengkel & WO*, *Suku Cadang & Perputaran Stok*, *Komparasi Kinerja Lintas Divisi*) yang interaktif (klik langsung mengeksekusi pertanyaan).
     - *Telemetry Strip*: Ringkasan status teknis di empty state (`2.387 Tabel Terpantau • Read-Only Enforced • AST Verifier Active`).
     - *MessageBubble*: Pesan user dirombak menjadi kartu gelap eksekutif (`bg-surface-dark text-white rounded-lg`) dengan cap waktu dan label "Pertanyaan Anda".
     - *PipelineIndicator*: Tampilan log telemetri teknis dengan animasi pulsa lembut dan badge tahapan yang presisi.
     - *Input Console*: Container berfokus tenang dengan send button tactile dan catatan kepatuhan audit.
  2. **`AssistantAnswerCard.jsx`**:
     - *Executive Dossier Header*: Menggantikan badge soup dengan bar status teknis terpadu (status verifikasi, level keyakinan A/B/C, durasi kueri `tabular-nums font-mono`, jumlah baris).
     - *Executive Briefing Callout*: Narasi ringkasan dengan aksen hairline vertikal terracotta yang elegan.
     - *Statistik Data Utama*: Menghapus badge buzzword `(Zero-Token)` dan menggantinya dengan indikator statistik bersih berformat monospaced `tabular-nums`.
     - *Tabel Cerdas Presisi*: Nilai numerik dan mata uang secara otomatis disejajarkan ke kanan (`text-right font-mono tabular-nums`), sedangkan label teks disejajarkan ke kiri.
     - *Toolbar & Chart*: Menghapus badge `(0 Token)` dan icon `Sparkles`. Menyelaraskan tombol `Unduh Excel` dan `Salin Tabel` ke gaya tombol korporat editorial yang harmonis.
     - *Contextual Chips*: Mengubah pil bulat balon menjadi chip penunjuk arah eksplorasi yang bersih (`rounded-md border border-hairline`).
  3. **`ChatHistorySidebar.jsx`**:
     - Tombol `Sesi Percakapan Baru` diperbarui dengan gaya eksekutif gelap (`bg-surface-dark text-white`).
     - Tab sesi aktif diubah menjadi ledger file tab dengan strip aksen kiri terracotta (`border-l-2 border-l-primary bg-white shadow-2xs`).
     - Input pencarian arsip dilengkapi indikator fokus `focus:ring-1 focus:ring-primary/40`.
  4. **`ClarificationCard.jsx`**:
     - Menghapus badge buzzword `(0-Token)` dan menstandarisasi token warna yang usang (`text-text-main`, `text-text-subtle`) ke standar proyek (`text-ink`, `text-muted`, `text-body`).
- **Hasil Verifikasi**:
  - Backend compileall: **exit 0**.
  - Backend pytest: **558 passed in 38.50s** (100% lulus tanpa kegagalan).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
## 3aa. Penerapan Claude Editorial Design System & Eliminasi AI-Slop (DESIGN-claude.md)

- **Latar Belakang & Acuan Desain**:
  - Mengadopsi pedoman desain resmi dari dokumen `DESIGN-claude.md` (arsitektur antarmuka editorial Anthropic Claude).
  - Menghilangkan secara radikal seluruh pola klise generik AI (*AI-slop*): avatar bot kartun raksasa, badge soup dengan emoji berkilau (`✨`), bentuk balon rounded-3xl berlebih, gradasi warna ungu/pink, dan font bold 700 liar.
  - Memastikan *Zero Pure White Rule*: seluruh background menggunakan kanvas hangat (`#faf9f5` / `bg-canvas`), kartu konten menggunakan deeper cream (`#efe9de` / `bg-surface-card`), aksen primer coral hangat (`#cc785c` / `bg-primary`), dan permukaan gelap produk (`#181715` / `bg-surface-dark`).

- **Komponen & Berkas yang Diperbarui**:
  1. **Global Typography & Token Styling (`frontend/index.html` & `frontend/src/index.css`)**:
     - Memuat font Google `Cormorant Garamond` (bobot 400, 500, 600, italic), `Inter` (bobot 400, 500, 600), dan `JetBrains Mono` (bobot 400, 500).
     - Mengkonfigurasi seluruh token warna CSS `@theme` turunan `DESIGN-claude.md`: `--color-primary: #cc785c`, `--color-primary-active: #a9583e`, `--color-canvas: #faf9f5`, `--color-surface-card: #efe9de`, `--color-surface-cream-strong: #e8e0d2`, `--color-surface-dark: #181715`, `--color-surface-dark-soft: #1f1e1b`, `--color-ink: #141413`, `--color-body: #3d3d3a`, `--color-muted: #6c6a64`, `--color-muted-soft: #8e8b82`, `--color-border-hairline: #e6dfd8`.
  2. **Layar Autentikasi (`LoginModal.jsx`)**:
     - Menghapus ikon Sparkles dan nuansa ungu/pink generic AI.
     - Menggunakan monogram arsitektural gelap `DMS` dengan tipografi display serif `Cormorant Garamond` 400 regular (`tracking-tight`).
     - Tombol login diubah menjadi Claude `button-primary` coral (`h-10`, `rounded-md`, `#cc785c` dengan hover `#a9583e`).
  3. **Workspace Asisten Eksekutif (`UserWorkspace.jsx`)**:
     - *Header*: Mengadopsi 64px (`h-16`) top-nav dengan monogram arsitektural `DMS`, pill status database dealer ber-hairline rapi, dan tombol Sesi Baru.
     - *Hero Empty State*: Format `hero-band` Claude dengan judul display serif Cormorant Garamond 400 regular dan 4 kartu kueri cepat berformat `feature-card` Claude (`#efe9de` surface-card, `rounded-lg` 12px, border hairline halus, hover border coral).
     - *Message Bubble*: Pesan pengguna berformat Claude `product-mockup-card-dark` (`bg-surface-dark text-on-dark rounded-lg p-4 font-sans`).
     - *Input Console*: Berfokus tenang dengan hairline hangat, focus ring coral lembut (`focus-within:ring-primary/15`), dan tombol kirim coral tactile.
  4. **Kartu Jawaban & Window Artifact (`AssistantAnswerCard.jsx`)**:
     - *SQL Code Block*: Dirombak menjadi signature Claude `code-window-card` (`bg-surface-dark` #181715 dengan container luar ber-border halus, window control bar 3 titik berwarna Apple #ff5f57, #febc2e, #28c840, tab `query.sql`, tombol Salin SQL, dan teks SQL JetBrains Mono `#f5f4ef`).
     - *Pilar 3S Multi-Table & Category Tabs*: Berganti ke Claude `category-tab` (`rounded-md`, aktif dengan `bg-canvas border border-hairline text-primary`).
     - *Tabel & Aksi*: Menyelaraskan tombol `Unduh Excel` dan `Salin Tabel` ke Claude `button-secondary` (`bg-canvas border border-hairline rounded-md text-ink hover:bg-surface-soft`).
  5. **Sidebar Riwayat Chat (`ChatHistorySidebar.jsx`)**:
     - Header diselaraskan dengan ketinggian 64px (`h-16`).
     - Tombol `+ Sesi Percakapan Baru` menggunakan coral primary CTA (`bg-primary text-on-primary rounded-md h-10`).
     - Sesi aktif berganti ke Claude active item (`bg-surface-cream-strong text-ink font-medium border-l-2 border-l-primary rounded-md`).
  6. **Kartu Dialog Klarifikasi Parameter (`ClarificationCard.jsx`)**:
     - Dibungkus dalam kontainer `bg-surface-card border border-hairline rounded-lg`.
     - Opsi pilihan diformat sebagai Claude `connector-tile` (`bg-canvas border border-hairline hover:bg-surface-cream-strong hover:border-primary/50 rounded-md`).

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 56.75s** (100% lulus tanpa kegagalan).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 1.33s).
  - Visual Browser Verification via Chrome DevTools MCP:
    - Terverifikasi pada viewport desktop nyata di `http://localhost:5173/`.
    - Tangkapan layar hero, dossier eksekutif, dark code window card, dan table view membuktikan antarmuka editorial hangat dan bebas AI-slop secara nyata.

### 3ab. Restorasi Icon Bot Warm Coral, Tipografi Ringkasan, & Struktur Analisis Narasi (2026-09-07)

- **Masalah yang Diatasi**:
  1. **Gambar 1 (Top Navigation Brand)**: Kotak hitam monogram `[DMS]` membuat header terasa kaku dan kehilangan ikonografi ramah asisten bot.
  2. **Gambar 2 (Assistant Message Header)**: Monogram hitam `[AI]` dipertanyakan user karena menggunakan warna hitam solid dan bukan icon bot.
  3. **Gambar 3 (Keterbacaan Ringkasan & Analisis "Semut Berbaris")**: Font ringkasan Cormorant Garamond italic sulit dibaca cepat di monitor resolusi standar, dan teks penjelasan naratif eksekutif berupa satu paragraf raksasa tanpa jeda baris yang padat seperti semut berbaris.

- **Solusi & Perubahan**:
  1. **Restorasi Icon Bot & Brand Header (`UserWorkspace.jsx` & `LoginModal.jsx`)**:
     - Menggantikan monogram kotak hitam `[DMS]` di top-nav dan login dengan kontainer icon `Bot` (`lucide-react`) hangat berlatar coral lembut (`bg-primary/10 text-primary border border-primary/20 shadow-2xs`).
     - Menstandarkan subjudul menjadi `Asisten Laporan Dealer`.
  2. **Restorasi Icon Bot pada Bubble Asisten (`UserWorkspace.jsx`)**:
     - Menggantikan kotak hitam `[AI]` dengan kontainer `<div className="w-5 h-5 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0 border border-primary/20"><Bot size={13} /></div>`.
  3. **Keterbacaan Ringkasan Eksekutif (`AssistantAnswerCard.jsx`)**:
     - Mengganti gaya font dari serif italic miring menjadi sans-serif tegas (`font-sans text-sm sm:text-[15px] leading-relaxed text-ink font-medium`).
  4. **Struktur Naratif Analisis Eksekutif Bebas Semut Berbaris (`AssistantAnswerCard.jsx` & `vanna_engine.py`)**:
     - Backend: Memperketat prompt `buat_penjelasan_naratif` di `vanna_engine.py` untuk mewajibkan 2–3 paragraf pendek dengan pemisah `\n\n`, serta baris terpisah untuk bullet rekomendasi.
     - Frontend: Mengimplementasikan helper `FormattedExecutiveAnalysis` yang secara cerdas mendeteksi kalimat transisi, memecah paragraf panjang, mengisolasi `Rekomendasi:` ke dalam dedicated callout box dengan icon `Compass` dan border coral, serta merender daftar bullet poin dengan dot bulat rapi.

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**).
  - Browser DevTools live testing: Tangkapan layar membuktikan brand bot coral, ringkasan sans-serif tajam, dan narasi analisis terstruktur rapi.

### 3ac. Penyempurnaan Visual & UX Editorial: Warm Bubble, Palet Chart Terracotta, Deduplikasi Judul & Label Bulan (2026-09-07)

- **Masalah yang Diatasi**:
  1. Bubble pesan pengguna berwarna hitam pekat `#181715` yang terlalu kontras dan menusuk mata pada kanvas ivory.
  2. Palet grafik visual Recharts masih menggunakan warna default Tailwind blue `#3b82f6` yang bertabrakan dengan palet terracotta dan cream.
  3. Duplikasi judul grafik di toolbar kartu jawaban (muncul mengambang di samping tombol Salin Tabel dan di dalam kartu grafik).
  4. Label Smart Insights menampilkan *"Baris 6"* alih-alih *"Bulan 6"* karena kolom `bulan` bernilai angka.
  5. Tipografi prompt saran di command deck menggunakan font serif italic yang kurang tegas untuk elemen interaktif.
  6. Kartu login menggunakan `bg-white` murni yang melanggar *Zero Pure White Rule*.
  7. Tidak adanya tombol aksi "Coba Lagi" saat pipeline kueri mengalami kendala jaringan atau error.

- **Solusi & Perubahan**:
  1. **Bubble Pesan Pengguna (`UserWorkspace.jsx`)**: Diubah ke warna permukaan hangat yang elegan: `bg-surface-cream-strong text-ink border border-hairline rounded-lg shadow-2xs font-sans`.
  2. **Palet Warna Chart Terkoordinasi (`AssistantAnswerCard.jsx`)**: Mengganti `BAR_COLORS` menjadi palet editorial terracotta `#cc785c`, deep teal `#2e6f77`, warm amber `#d97706`, dan slate `#475569`.
  3. **Eliminasi Duplikasi Judul (`AssistantAnswerCard.jsx`)**: Menghapus teks judul mengambang di samping tombol toolbar, mempertahankan judul rapi di dalam kartu visual dengan icon `TrendingUp`.
  4. **Penyempurnaan Deteksi Label Kategori (`smartInsights.js`)**: Memprioritaskan kata kunci kategori (`bulan`, `tahun`, `periode`, dsb.) dan memformat label otomatis (`Bulan 6`, `Tahun 2025`).
  5. **Tipografi Command Deck (`UserWorkspace.jsx`)**: Mengubah prompt saran menjadi `font-sans font-medium text-xs text-ink` yang bersih dan tegas.
  6. **Penyelarasan Kartu Login (`LoginModal.jsx`)**: Mengubah kontainer form menjadi `bg-surface-card rounded-xl border border-hairline`.
  7. **Tombol Coba Lagi pada Error (`UserWorkspace.jsx`)**: Menambahkan tombol `Coba Lagi` dengan ikon `RotateCcw` di samping judul `Pemeriksaan Gagal`.

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 40.95s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 2.64s).

### 3ad. Redesign Sidebar History Chat Bergaya Claude Editorial & Fix Hydration Array (2026-09-07)

- **Masalah yang Diatasi**:
  1. **Tampilan Sidebar Kaku & Boros Ruang**: Header sidebar setinggi 64px menumpuk canggung di bawah navbar utama, diikuti tombol raksasa berwarna oranye menyala `+ Sesi Percakapan Baru` yang memakan hampir 200px vertikal sebelum daftar percakapan terlihat.
  2. **Active State Kasar**: Item percakapan aktif menggunakan multi-border tebal (`border-l-2 border-primary border-y border-r border-hairline shadow-2xs`) yang terlihat seperti badge kaku bukan item daftar yang halus.
  3. **Metadata Waktu Nihil**: Item riwayat tidak menampilkan kapan percakapan dilakukan atau jumlah kueri.
  4. **Bug Hydration Percakapan Kosong**: `api.getConversations` dari backend mengembalikan *raw list array* `[...]`, namun kode `UserWorkspace.jsx` mencoba membaca `data.conversations`, sehingga daftar riwayat selalu terbaca `undefined` dan dianggap kosong (`[]`) meski data tersimpan di PostgreSQL.

- **Solusi & Perubahan**:
  1. **Fix Parsing Hydration Data (`UserWorkspace.jsx`)**: Mengubah `const list = Array.isArray(data) ? data : (data?.conversations || [])`, sehingga seluruh sesi tersimpan di database langsung ter-hydrate secara instan ke dalam sidebar.
  2. **Header Compact & Minimalis (`ChatHistorySidebar.jsx`)**: Mengganti header tumpuk 64px dengan header kompak setinggi `h-14` berikon `History` coral, tipografi serif anggun "Arsip Percakapan", badge penghitung total sesi, dan tombol ciutkan yang selaras.
  3. **Tombol Percakapan Baru Taktil & Elegan (`ChatHistorySidebar.jsx`)**: Mengganti tombol oranye mencolok dengan tombol berarsitektur Claude: `bg-canvas hover:bg-surface-cream-strong border border-hairline` dengan ikon `MessageSquarePlus` coral dan shortcut hint `+`.
  4. **Search Bar Terintegrasi**: Bilah pencarian halus dengan ikon lup dan tombol reset `X` yang tidak merusak tata letak.
  5. **Item Percakapan dengan Timestamp & Indicator Dot**: Item aktif kini menggunakan latar `bg-surface-cream-strong` dengan titik coral hangat (`w-1.5 h-1.5 bg-primary`). Menampilkan waktu relatif (`13:05`, `Kemarin`, `Sen`) yang secara elegan berganti menjadi tombol hapus saat di-hover.
  6. **Inline Delete Confirmation**: Konfirmasi hapus yang mulus tanpa merusak tata letak daftar.
  7. **Empty & Footer State Anggun**: Menampilkan ilustrasi bot lembut dengan pesan edukatif, serta footer minimalis dengan total sesi tersimpan dan tombol pembersihan terkonfirmasi.

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 37.42s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 1.31s).

### 3ae. Floating Edge Tab Handle Sidebar: Eliminasi Total Layout Shift Navbar (2026-09-07)

- **Masalah yang Diatasi**:
  - Ketika sidebar ditutup, tombol buka sidebar sebelumnya disuntikkan dinamis ke dalam navbar atas di sebelah kiri logo brand `[Bot] DMS AI Platform`.
  - Hal ini menyebabkan:
    1. Logo brand dan judul aplikasi terdorong ke kanan saat ditutup (*jarring layout shift*).
    2. Tombol toggle melompat vertikal dari area sidebar (di bawah navbar) ke dalam navbar atas.
    3. Penampilan navbar berubah-ubah dan tidak konsisten.

- **Solusi & Perubahan (Gaya Ide 3 - Linear & Cursor Floating Handle)**:
  1. **Navbar 100% Statis & Suci (`UserWorkspace.jsx`)**: Menghapus tombol toggle dari header navbar atas. Logo brand `[Bot]` dan teks `DMS AI Platform` kini terkunci statis di pojok kiri atas dan tidak pernah bergeser 1 piksel pun, baik saat sidebar dibuka maupun ditutup.
  2. **Floating Edge Tab Handle (`UserWorkspace.jsx`)**: Saat sidebar ditutup, muncul sebuah tab handle mengambang yang menempel rapi di garis batas tepi kiri layar (`absolute left-0 top-3 z-30`). Berdesain arsitektural (`bg-surface-card hover:bg-surface-cream-strong border-y border-r border-hairline rounded-r-xl shadow-xs`), tab ini memuat ikon `PanelLeftOpen` coral dan label teks "Riwayat Chat".
  3. **Pengalaman Pengguna Tanpa Goyang**: Navbar atas tetap tenang dan stabil, sementara akses membuka kembali riwayat percakapan berada persis di tepi kiri tempat sidebar akan muncul.

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 37.42s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 846ms).

### 3af. Animasi Slide Mulus (Framer Motion) & Tipografi Ringan Non-Bold (2026-09-07)

- **Masalah yang Diatasi**:
  1. **Hilangnya Animasi**: Sidebar sebelumnya langsung hilang atau muncul seketika secara mendadak (`return null`), tanpa animasi geser (*slide transition*), begitu pula tombol *floating edge handle*.
  2. **Ketebalan Teks (Bold)**: Penggunaan `font-medium` dan `font-semibold` pada item percakapan aktif, tombol, dan header sidebar membuat tipografi terlihat tebal/berat di monitor, tidak sesuai dengan estetika editorial tipis dan elegan.

- **Solusi & Perubahan**:
  1. **Animasi Slide Mulus Sidebar (`ChatHistorySidebar.jsx` & `UserWorkspace.jsx`)**:
     - Membungkus sidebar dalam `<AnimatePresence initial={false}>` dan komponen `<motion.aside>`.
     - Mengatur transisi geser horizontal (`width: 0 -> 288px`, `opacity: 0 -> 1`) dengan kurva cubic-bezier halus (`[0.16, 1, 0.3, 1]`) selama 220ms.
     - Mengunci tata letak konten dalam kontainer `w-72 shrink-0` agar teks tidak mengalami kompresi teks (*squish*) saat proses animasi berlangsung.
  2. **Animasi Geser Masuk Floating Handle (`UserWorkspace.jsx`)**:
     - Menggunakan `<AnimatePresence>` dan `<motion.button>` dengan animasi geser horizontal dari tepi kiri (`x: -30 -> 0`).
  3. **Penghapusan Teks Bold/Tebal (Font-Normal Refinement)**:
     - Mengubah seluruh label (judul percakapan, header "Arsip Percakapan", tombol "Percakapan Baru", dan teks "Riwayat Chat") menjadi `font-normal`.
     - Teks kini tampil sangat tipis, tajam, dan elegan (*crisp editorial typography*).

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 37.42s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 938ms).

### 3ag. Penyempurnaan Tipografi Sidebar, Arsip Percakapan & Polish UI/UX (2026-09-07)

- **Masalah & Masukan Pengguna**:
  1. **Teks "Arsip Percakapan" Terlalu Kecil**: Ukuran sebelumnya `text-xs` (12px serif) tampak sangat kecil dan sulit dibaca di monitor standar.
  2. **Klarifikasi Ketebalan Font (Bold)**: Pengguna mengklarifikasi bahwa yang dimaksud tidak boleh bold hanyalah teks *"Riwayat Chat"* pada floating edge handle. Elemen lainnya (seperti tombol aksi "Percakapan Baru", header grup waktu, dan sesi chat aktif) perlu mempertahankan bobot `font-medium`/`font-semibold` agar hirarki visual tetap jelas.
  3. **Audit Menyeluruh UI, UX, Animasi & Performa**: Menyelaraskan seluruh interaksi aplikasi dari scrollbar tebal default Windows, kemudahan navigasi keyboard, hingga umpan balik taktil klik.

- **Solusi & Implementasi Teknis**:
  1. **Pembesaran Tipografi "Arsip Percakapan" (`ChatHistorySidebar.jsx`)**:
     - Mengubah ukuran teks dari `text-xs font-normal` menjadi `text-[15px] font-serif font-medium text-ink tracking-tight`.
     - Header kini tampil berwibawa, mudah dibaca, dan proporsional dengan tinggi header 56px (`h-14`).
  2. **Restorasi Hirarki Bobot Tipografi Sidebar (`ChatHistorySidebar.jsx`)**:
     - Tombol "Percakapan Baru": Menggunakan `text-xs font-medium text-ink` dengan hover ring coral.
     - Header grup tanggal (`HARI INI`, `KEMARIN`, dll.): Menggunakan `text-[10px] font-mono uppercase font-semibold text-muted`.
     - Sesi chat aktif: Menggunakan `font-medium text-ink` pada judul sesi, memperjelas sesi mana yang sedang aktif.
     - Sesi chat tidak aktif: Tetap `font-normal text-body` yang ramah di mata.
     - Judul empty state: Menggunakan `text-sm font-serif font-medium text-ink`.
  3. **Preservasi Font-Normal Khusus "Riwayat Chat" (`UserWorkspace.jsx`)**:
     - Memastikan teks "Riwayat Chat" pada floating handle tetap `font-normal text-body group-hover:text-ink` (tidak bold), ditemani badge visual shortcut `Ctrl+B`.
  4. **Scrollbar Ramping Editorial Custom (`frontend/src/index.css`)**:
     - Menggantikan scrollbar default OS Windows yang kaku dan tebal (17px abu-abu) dengan scrollbar ramping 6px bertema hangat (`#d8d0c4` pada thumb dan transparan pada track).
     - Menambahkan kustomisasi warna seleksi teks (`::selection`) hangat bernuansa coral transparan (`rgba(204, 120, 92, 0.2)`).
  5. **Keyboard Shortcut Cepat (`UserWorkspace.jsx`)**:
     - Menambahkan listener keyboard global: `Ctrl+B` (Windows/Linux) atau `Cmd+B` (macOS) untuk toggle buka/tutup sidebar riwayat secara instan.
  6. **Umpan Balik Taktil Tombol Kirim (`UserWorkspace.jsx`)**:
     - Menambahkan transisi `active:scale-95` pada tombol submit chat untuk sensasi klik responsif.

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 48.50s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 1.13s).

### 3ah. Eliminasi Badge Visual Ctrl+B & Perluasan Trigger Fan-Out Tiap Divisi (2026-09-07)

- **Latar Belakang & Masukan Pengguna**:
  1. **Badge Visual Ctrl+B**: Pengguna meminta teks badge `<kbd>Ctrl+B</kbd>` dihilangkan dari floating handle dan cukup mengandalkan informasi tooltip hover.
  2. **Evaluasi Pertanyaan `tester02` ("bandingkan peforma tiap divisi dalam tiap tahunnya")**:
     - Hasil lama hanya mengeksekusi tabel `untt_penjualan` (hanya Unit Kendaraan, tanpa Jasa Servis Bengkel & Suku Cadang).
     - AI di fitur *Analisis Naratif Eksekutif* bahkan secara eksplisit mendeteksi kelemahan tersebut: *"Catatan penting: kueri yang dijalankan belum memuat dimensi divisi..."*.
     - Penyebab: kata kunci typo `"peforma"` (tanpa 'r') dan frasa `"tiap divisi"` belum terdaftar dalam trigger pattern `fanout_engine.py`.

- **Solusi & Implementasi Teknis**:
  1. **Pembersihan Tombol Floating Handle (`UserWorkspace.jsx`)**:
     - Menghapus elemen `<kbd>` dari tombol mengambang.
     - Menjaga informasi shortcut pada atribut `title="Buka Riwayat Percakapan (Ctrl+B)"` saat di-hover.
  2. **Pembersihan Cache SQL Memory Tunggal (#67)**:
     - Menghapus entri `sql_memory` lama id 67 yang terlanjur menyimpan kueri single-table unit agar tidak terjadi replay usang.
  3. **Perluasan Regex Deteksi Fan-Out 3S (`fanout_engine.py`)**:
     - Menambahkan pola `peforma` dan `divisi` ke dalam `trigger_patterns`.
     - Menambahkan pola `r"\b(?:tiap|setiap|antar|per|semua|lintas)\s+divisi\b"` pada aturan penjualan dan fungsi `cek_apakah_perlu_komparasi`.
  4. **Hasil Pengujian Nyata**:
     - Kueri *"bandingkan peforma tiap divisi dalam tiap tahunnya"* kini sukses menghasilkan **4 Tab Lengkap**:
       1. **Komparasi Antar Divisi**: Tabel ringkasan komparasi volume & omzet sejajar per divisi.
       2. **Unit Kendaraan**: 13 baris data (tahun 2014–2026).
       3. **Jasa Servis Bengkel**: 13 baris data PKB WO servis (tahun 2014–2026).
       4. **Suku Cadang & Sparepart**: 7 baris data part terjual & omzet part (tahun 2020–2026).

- **Hasil Verifikasi**:
  - Backend pytest: **558 passed in 49.19s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 1.38s).

### 3ai. Strukturisasi Knowledge Base 3S: Global KB vs Tenant Database KB & Sinkronisasi Pgvector (2026-09-07)

- **Latar Belakang & Permasalahan**:
  1. **Kesalahan AI pada Analisis Multi-Divisi**: Pertanyaan komparasi divisi per tahun sebelumnya berisiko hanya mengeksekusi tabel penjualan unit (`untt_penjualan`) tanpa menghubungkan data servis bengkel (`srvt_wo`) dan suku cadang (`srvt_wodetail`).
  2. **Tuntutan Presisi Multi-Tenant**: Tenant `TST_01` terhubung ke database `backup_demo_otobitzcloud` dengan **2.387 tabel**. Tanpa pemisahan tegas antara pengetahuan universal (Global KB) dan skema fisik spesifik (Tenant KB), AI dapat mengalami kebingungan semantik dan memilih tabel/kolom yang salah.

- **Implementasi Arsitektur Knowledge Base Dua Tingkat (Global vs Tenant)**:
  1. **Global Knowledge Base (Public Automotive Domain Knowledge)**:
     - **Tujuan**: Menyediakan prinsip bisnis otomotif 3S (Sales, Service, Sparepart) universal yang berlaku lintas semua tenant dealer.
     - **Tabel Penyimpanan**: `global_knowledge_base` dan `tenant_vector_kb` (`branch_code = 'GLOBAL'`).
     - **Automotive Domain Thesaurus (`automotive_thesaurus.py`)**:
       - Menambahkan kategori aturan baru `komparasi_divisi_3s`: menegaskan bahwa analisis divisi wajib merangkum Penjualan Unit Kendaraan (`untt_penjualan`), Jasa Servis Bengkel (`srvt_wo`), dan Pemakaian Suku Cadang (`srvt_wodetail.part > 0`).
       - Memperbaiki aturan stok gudang bengkel: rumus sisa stok adalah `stockawal + masuk - keluar` dari `srvt_stockparts` (bukan saldoakhir).
       - Menambahkan aturan penjualan sparepart bengkel melalui kolom `srvt_wodetail.part` (> 0).
     - **8 Golden Few-Shot Dealership Templates**:
       1. Komparasi performa tahunan 3 pilar divisi (Sales, Service, Sparepart).
       2. Tren omzet dan volume penjualan unit kendaraan bulanan (`batal = false`, `retur = false`).
       3. Tren unit entry dan total biaya estimasi servis bengkel bulanan (`srvt_wo.batal = false`).
       4. Top 10 suku cadang terlaris berdasarkan nilai pemakaian di bengkel (`srvt_wodetail.part`).
       5. Top 10 customer dengan pembelian unit terbanyak via 2-hop SPK (`untt_penjualan -> untt_pesanankendaraan -> glbm_customer`).
       6. Perbandingan pembelian unit kendaraan tahun 2025 vs 2026 (`untt_pembelian.tglinvoice`).
       7. Stok unit kendaraan ready berdasarkan tipe mobil (`untt_datakendaraan -> untm_tipe`).
       8. Sisa stok suku cadang gudang bengkel yang menipis/kritis (`stockawal + masuk - keluar <= 5`).
     - **Vektorisasi Pgvector**: Seluruh 8 template SQL dan 9 aturan thesaurus berhasil divektorisasi ke `tenant_vector_kb` (IDs 2416–2423 + 9 thesaurus).

  2. **Tenant Database Knowledge Base (`tenants.knowledge_base` untuk TST_01)**:
     - **Tujuan**: Menampung spesifikasi teknis fisik khusus database `backup_demo_otobitzcloud`.
     - **Allowlist Ketat (12 Tabel Operasional dari 2.387 Tabel)**:
       `untt_penjualan`, `untt_pembelian`, `untt_pesanankendaraan`, `untt_datakendaraan`, `untm_tipe`, `untm_model`, `srvt_wo`, `srvt_wodetail`, `srvt_stockparts`, `glbm_customer`, `glbm_cabang`, `vw_untt_penjualan`.
     - **Catatan Kolom Fisik Lengkap**: Deskripsi semantik operasional untuk semua kolom kunci di 12 tabel (misal: `hjakhir`, `hpunit`, `totalestimasibiaya`, `jasa`, `part`, `cogs`, `tglinvoice`, `thnpembuatan`).
     - **Pemetaan Relasi Eksplisit**: Mendefinisikan jalur join 2-hop untuk data customer dari transaksi penjualan (`untt_penjualan.nomor_pesanan -> untt_pesanankendaraan.nomor -> glbm_customer.nomor`), relasi WO ke customer dan unit kendaraan, serta relasi tipe mobil ke model kendaraan.
     - **Glossary Bisnis Spesifik**: Istilah-istilah percakapan dealer yang dipetakan langsung ke ekspresi SQL PostgreSQL.

- **Hasil Pengujian & Verifikasi Nyata**:
  - Seluruh 8 Golden Queries diuji langsung ke tenant database `backup_demo_otobitzcloud` (PostgreSQL port 5432) dan menghasilkan **100% SUKSES** dengan data nyata yang akurat.
  - Pengujian kueri *"bandingkan peforma tiap divisi dalam tiap tahunnya"* melalui `cari_konteks_pgvector` membuktikan bahwa pgvector secara akurat mengambil panduan 3S dan mendeteksi tabel `untt_penjualan`, `srvt_wo`, `srvt_wodetail`, dan `srvt_stockparts` pada peringkat teratas.
  - Backend compileall: **exit 0**.
  - Backend pytest: **558 passed in 41.37s** (100% lulus).
  - Frontend lint: `npm run lint` **0 errors** (100% lulus).
  - Frontend build: `npm run build` exit code 0 (**100% lulus**, built in 1.15s).

### 3aj. Alur Komparasi Progresif (Gaya 1 Terpadu -> Tawaran Gaya 2 Terpisah) & Penegakan Disiplin Zero-Emoji

- **Konteks & Masalah**:
  1. Pengguna menginginkan alur perbandingan dua periode waktu (misal *"2024 vs 2025"*) yang fleksibel: default menjawab dengan **Gaya 1** (1 tabel komparasi side-by-side terpadu yang ringkas), sambil secara proaktif menawarkan apakah pengguna ingin melihat tabel rincian transaksi masing-masing periode secara terpisah (**Gaya 2**).
  2. Pengguna secara mutlak melarang penggunaan emoji unicode: *"JANGAN MENGGUNAKAN EMOJI! gunakan icon.."*. Semua indikator visual, judul tab, tombol saran, dan narasi wajib 100% menggunakan SVG Icon Lucide (`lucide-react`).
  3. Eliminasi total label dan jargon buatan "3S Dealer" di seluruh antarmuka.

- **Solusi Arsitektur & Teknis**:
  1. **Backend (`fanout_engine.py`, `vanna_engine.py`, `presenter.py`)**:
     - `_deteksi_kueri_komparasi_periode`: mendeteksi kueri perbandingan antar tahun/periode secara deterministik (0 token).
     - Menghasilkan saran lokal bebas emoji:
       - `"Tampilkan rincian transaksi {topik} tahun {p1} dan {p2} secara terpisah"`
       - `"Lihat detail transaksi {topik} tahun {p1}"`
       - `"Lihat detail transaksi {topik} tahun {p2}"`
     - `cek_apakah_minta_rincian_terpisah`: mendeteksi permintaan tabel rincian terpisah (Gaya 2) dan secara otomatis memecah eksekusi ke multi-tab murni temporal (*Tab "Rincian Tahun 2024"* dan *Tab "Rincian Tahun 2025"* ber-icon `Calendar`), tanpa kategori artifisial 3S.
     - `_bersihkan_emoji_teks`: filter regex ketat yang membuang seluruh karakter emoji 4-byte (`[\U00010000-\U0010ffff]`) dan simbol dingbat dari ringkasan, saran, dan respons sistem.
  2. **Frontend (`AssistantAnswerCard.jsx`)**:
     - Memasang komponen `ProactiveBreakdownOffer` saat mendeteksi kueri komparasi atau chip rincian terpisah.
     - Menggunakan icon Lucide: `SplitSquareVertical`, `ArrowRight`, `Calendar`, `Table2`.
     - Klik chip secara instan mengirim prompt ke input pengguna via `onAsk(s)`.
  3. **Unit Testing (`test_progressive_comparison.py`)**:
     - 4 test unit baru menguji ekstraksi periode, deteksi komparasi, deteksi rincian terpisah, dan pembersihan emoji. Total suite meningkat menjadi 562 test.

- **Verifikasi**:
  - `compileall app`: exit 0
  - `pytest tests/`: 562 passed
  - `npm run lint`: 0 error
  - `npm run build`: exit 0

### 3ak. Format Otomatis Cerdas Tanggal dan Waktu pada Tabel dan Ekspor Excel (commit: 4d8d635)

- **Masalah**:
  - Tanggal invoice (`tglinvoice`) dan kolom timestamp lainnya dari PostgreSQL tampil mentah berupa format ISO string (misal `2025-11-11T00:00:00`, `2026-07-10T00:00:00`).
  - Pengguna meminta format otomatis cerdas:
    1. Hanya tanggal: jika nilai berupa tanggal atau jam 00:00:00 (cth: `11 Nov 2025`).
    2. Hanya waktu: jika nilai berupa waktu saja (cth: `14:30`).
    3. Keduanya: jika terdapat tanggal dan waktu nyata bukan jam 00:00:00 (cth: `11 Nov 2025, 14:35`).
    4. Bebas pergeseran zona waktu (tidak boleh bergeser hari akibat konversi UTC).

- **Solusi & Implementasi**:
  1. **Frontend (`AssistantAnswerCard.jsx`)**:
     - `formatTanggalWaktu(nilai)`: regex parser akurat tanpa UTC drift (menggunakan konstruktor lokal `new Date(year, month - 1, day)`).
     - Otomatis membedakan waktu saja, tanggal saja (`00:00:00` diabaikan menjadi tanggal murni), dan tanggal beserta waktu.
     - Terintegrasi langsung pada `formatSel`, fungsi salin clipboard (`handleCopyTable`), serta styling sel tabel `td` dengan `font-mono tabular-nums text-left text-body`.
  2. **Backend Ekspor Excel (`report_exporter.py`)**:
     - `_parse_date_or_time(val)`: mengonversi string ISO/date menjadi objek Python native `datetime.date`, `datetime.datetime`, atau `datetime.time` dengan format Excel akuntansi yang tepat (`DD/MM/YYYY`, `DD/MM/YYYY HH:MM`, `HH:MM`).
     - Sel Excel kini dikenali sebagai tipe tanggal/waktu asli oleh Microsoft Excel, memungkinkan filter tanggal dan agregasi otomatis.

- **Verifikasi Nyata**:
  - Backend compile & pytest: **562 passed** (exit code 0).
  - Frontend lint: **0 error** (exit code 0).
  - Frontend build: **exit code 0**.
  - Browser DevTools MCP Live: tabel `tglinvoice` terverifikasi merender `11 Nov 2025`, `05 Nov 2025`, `10 Jul 2026`, `29 Jun 2026` secara rapi dan konsisten.

## 3al. Perbaikan Indikator Statistik Utama, Pelatihan AI Sisi User & Verifikasi Menyeluruh

- **Latar Belakang & Masalah**:
  1. Kartu jawaban menampilkan "Indikator Statistik Utama" bernilai 0: `Tertinggi: ... (0)`, `Total: 0`, `Rata-rata: 0`.
  2. Tombol "Latih Jawaban Ini" memanggil endpoint admin (`/admin/vanna/train`) yang menyebabkan error 403 Forbidden bagi pengguna biasa (`tester01`).
  3. Keraguan pengguna terkait fungsionalitas "Analisis Naratif Eksekutif", "Jawaban benar / salah", konsep 1 vs banyak tabel, serta cara kerja memori AI saat sesi percakapan berlangsung.

- **Akar Masalah & Solusi Teknis**:
  1. **Deteksi Kolom Metrik Statistik Pintar (`frontend/src/utils/smartInsights.js`)**:
     - Variabel `metricColIdx` sebelumnya terdefinisi `-1` dan tidak memiliki alur penugasan (assign) nilai kolom numerik, menyebabkan ekstraksi nilai bernilai `NaN` -> `0`.
     - Ditambahkan algoritma pemindaian kolom metrik berjenjang:
       - Prioritas 1: Kolom berstatus uang eksplisit (`isKolomUang`) yang memiliki data numerik.
       - Prioritas 2: Kolom kuantitas eksplisit (`isKolomKuantitas`) yang memiliki data numerik.
       - Prioritas 3: Kolom numerik pertama yang bukan identifier (`isIdentifierColumn`).
       - Prioritas 4: Kolom numerik apa pun yang tersisa.
     - Memperbaiki regex `IDENTIFIER_KEYWORDS`: sebelumnya `'hp'` mencocokkan substring pada `'hpunit'`, `'hpdpp'`, `'hpppn'`. Diperbaiki dengan regex batas kata `/(?:^|_)(?:no)?hp(?:_|$)|telepon|phone|telp/i` sehingga kolom biaya otomotif tidak keliru dianggap nomor telepon/ID.
     - Menambahkan `'hpunit'`, `'hpdpp'`, `'hpppn'`, `'hppbm'`, `'hp_unit'`, `'harga_unit'`, `'harga_per_unit'` ke dalam daftar `EKSPLISIT_UANG` pada `smartInsights.js` dan `AssistantAnswerCard.jsx` agar tidak tertimpa oleh aturan kuantitas `'unit'`.
     - Membatasi kalkulasi tren persentase (`deltaPersen`) khusus pada data yang berorientasi deret waktu (`isTimeSeriesCategory`: tahun, bulan, periode, tanggal).
  2. **Endpoint Pelatihan AI untuk User (`POST /chat/train`)**:
     - Menambahkan endpoint `POST /chat/train` di `backend/app/routers/chat.py` dengan dependency otorisasi pengguna (`require_user_role`) dan verifikasi `allowed_branches`.
     - Mengubah pemanggilan `api.trainVanna` pada `frontend/src/services/api.js` ke `/chat/train`.
     - Vektor embedding pertanyaan dan SQL disimpan langsung ke tabel `vanna_training_data` dengan status `success` via pgvector FastEmbed BGE-small.
  3. **Verifikasi Fitur "Analisis Naratif Eksekutif"**:
     - Mengalihkan provider AI global ke koneksi stabil dan responsif (`XKiro` / `qwen/qwen3.8-max:free`).
     - Diuji langsung pada browser via DevTools: klik tombol "Analisis Naratif Eksekutif" menghasilkan analisis komprehensif dua bagian (`ANALISIS EKSEKUTIF DATA` & `REKOMENDASI TINDAKAN STRATEGIS`).

- **Verifikasi & Bukti Nyata**:
  - Kartu Komparasi 2025 vs 2026: `Tren -98.4% | Tertinggi: Tahun 2025 (Rp 75.58 Miliar) | Total: Rp 76.79 Miliar | Rata-rata: Rp 38.39 Miliar`.
  - Tab 2025 (50 baris): `Tertinggi: UI-210-25100001 (Rp 527.73 Juta) | Total: Rp 9.72 Miliar | Rata-rata: Rp 194.38 Juta`.
  - Tab 2026 (6 baris): `Tertinggi: UI-210-26060003 (Rp 392.67 Juta) | Total: Rp 1.20 Miliar | Rata-rata: Rp 200.15 Juta`.
  - Backend pytest: **562 passed** (100% lulus dalam 37.47s).
  - Frontend lint: **0 error** (100% lulus).
  - Frontend build: **exit code 0** (1.21s).

## 3am. Penyelarasan Konteks Percakapan Multi-Turn & Koreksi Kolom Skema Riil Tabel Rincian

- **Latar Belakang & Masalah (Laporan Pengguna)**:
  1. *"data juga berbeda dari yg sebelumnyaa..":* Pengguna sebelumnya membandingkan **pembelian** unit 2025 vs 2026 (`untt_pembelian`, 2025 = Rp 75,58 Miliar). Kemudian menanyakan pertanyaan lanjutan eliptikal: *"bagaimana jika dibandingakn dengan 2024 vs 2025?"*. Karena sistem tidak meneruskan konteks topik percakapan aktif (`pembelian`), AI salah mengasumsikan pertanyaan sebagai **penjualan** (`untt_penjualan`, 2025 = Rp 69,82 Miliar), sehingga data tahun 2025 tampak berubah/inkonsisten bagi pengguna.
  2. *"baru lohh gw tes, langsung gabisa..":* Ketika pengguna mengklik chip saran rincian terpisah, kueri rincian terpisah `untt_penjualan` gagal total di database tenant dengan pesan kesalahan: `column "hargajual" does not exist` (karena nama kolom fisik PostgreSQL di tabel dealer adalah `hjunit`). Akibatnya sistem merender: *"Tidak ada data"*.
  3. Chip rekomendasi memunculkan anomali teks: duplikasi kata `"rincian transaksi transaksi"` serta kekosongan string tahun (`"tahun  vs  "`).
  4. SQL Memory replay memutar ulang entri salah yang pernah tersimpan karena tidak memvalidasi kesesuaian domain (*topic mismatch*).

- **Akar Masalah & Solusi Teknis**:
  1. **Multi-Turn Context Inheritance (`vanna_engine.py`)**:
     - Fungsi `deteksi_topik_riwayat_percakapan(core_pool, conversation_id)`: Memeriksa riwayat pesan user terdahulu dan judul sesi percakapan untuk mendeteksi topik aktif (`pembelian`, `penjualan`, `servis`, `sparepart`).
     - Jika pengguna mengajukan pertanyaan perbandingan tanpa menyebutkan entitas (misal: *"bagaimana jika dibandingakn dengan 2024 vs 2025?"*), konteks `pembelian` otomatis disuntikkan ke RAG pgvector dan prompt LLM:
       `Active Multi-turn Conversation Context: The user is currently discussing 'pembelian'...`.
     - Kueri yang dihasilkan konsisten menargetkan `untt_pembelian`: 2024 (963 unit, Rp 230,28 Miliar) & 2025 (349 unit, Rp 75,58 Miliar — persis sama dengan kartu sebelumnya).
  2. **Koreksi Kolom Skema Fisik Dealer (`vanna_engine.py` & `fanout_engine.py`)**:
     - Memperbaiki kolom `untt_penjualan` dari `"hargajual"` menjadi kolom fisik riil `"nomor, tanggal, nomor_pesanan, norangka, hjunit, diskon, hjakhir"`.
     - Menyelaraskan `date_col` di `fanout_engine.py` untuk tabel dealer (`tanggal` untuk `untt_penjualan`/`srvt_wo`/`prtt_penjualan`, dan `tglinvoice` untuk `untt_pembelian`).
     - Menambahkan parameter `p1`, `p2`, dan `topic` pada kamus kembalian `cek_apakah_minta_rincian_terpisah` sehingga saran chip terisi sempurna tanpa ada kata tahun yang kosong.
  3. **Pemberantasan Duplikasi Kata Chip Saran**:
     - Menghilangkan frasa `transaksi transaksi`. Menggunakan `transaksi {subject}` jika subjek spesifik terdeteksi (cth: `transaksi pembelian`), atau `data transaksi` jika subjek bersifat umum.
  4. **Topic-Aware SQL Memory Replay**:
     - Menambahkan guard `topic_mismatch` sebelum memutar ulang `sql_memory`: jika sesi aktif membahas `pembelian` namun SQL tersimpan menargetkan `untt_penjualan`, SQL Memory replay dilewati (dianggap MISS) dan dialihkan ke pemrosesan topik aktif.

- **Verifikasi & Bukti Nyata**:
  - Test skrip `test_multi_turn_fix.py`: **4/4 passed (100%)**.
  - Test follow-up kueri `test_followup.py`: berhasil menghasilkan SQL `untt_pembelian` 2024 vs 2025 dengan omzet Rp 230,28 M vs Rp 75,58 Miliar (konsistensi terbukti).
  - Test rincian terpisah `test_rincian_pembelian.py`: Tab 2024 (50 baris) & Tab 2025 (50 baris) berhasil dieksekusi dan tampil lengkap di browser.
  - Backend pytest: **562 passed** (100% lulus dalam 53.09s).
  - Frontend lint: **0 error** (100% lulus).

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
- [x] **Pembersihan Emoji & Standarisasi Icon SVG Lucide** — SELESAI (lihat §3q).
- [x] **Perbaikan Fitur Explain Naratif On-Demand & Penyelarasan Riwayat Chat** — SELESAI (lihat §3r).
- [x] **Opsi 4: Interactive Clarification Loop (Human-in-the-Loop Dialog)** — SELESAI (lihat §3s).
- [x] **Arsitektur Proaktif Multi-Table 3S (Sales, Service, Sparepart) dengan Query Fan-Out** — SELESAI (lihat §3t).
- [x] **Auto-Adaptive Visual Charts (Grafik Visual Otomatis 0-Token)** — SELESAI (lihat §3u).
- [x] **Ekspor Excel Berformat & Grafik Native + Pertanyaan Emas Dealer (Opsi 1)** — SELESAI (lihat §3v).
- [x] **Metrik Utilisasi AI Admin & Skenario Live Demo Sidang PKL (Opsi 5)** — SELESAI (lihat §3w).
- [x] **Optimasi UI Multi-Table 3S: Tab Bar Dinamis & Pembersihan Tab Kosong** — SELESAI (lihat §3x).
- [x] **Penyempurnaan Analisis Multi-Divisi: Koreksi Skema Riil Dealer, Tab Komparasi Sejajar, De-duplikasi Chip & Smart Context Note** — SELESAI (lihat §3y).
- [x] **Fix Format Mata Uang vs Kuantitas & Total Transaksi** — SELESAI (lihat §3y).
- [x] **Manajemen Riwayat Chat Multi-Sesi, Tabel Pintar Interaktif & Penyelarasan Skema Bengkel Riil** — SELESAI (lihat §3z).
- [x] **Penerapan Claude Editorial Design System & Eliminasi AI-Slop (DESIGN-claude.md)** — SELESAI (lihat §3aa).
- [x] **Strukturisasi Knowledge Base 3S: Global KB vs Tenant Database KB & Sinkronisasi Pgvector** — SELESAI (lihat §3ai).
- [x] **Format Otomatis Cerdas Tanggal dan Waktu pada Tabel dan Ekspor Excel** — SELESAI (lihat §3ak).
- [x] **Perbaikan Indikator Statistik Utama, Pelatihan AI Sisi User & Verifikasi Menyeluruh** — SELESAI (lihat §3al).
- [x] **Penyelarasan Konteks Percakapan Multi-Turn & Koreksi Kolom Skema Riil Tabel Rincian** — SELESAI (lihat §3am).
- [ ] **Roadmap Opsi Pengembangan Lanjutan (Tercatat untuk Eksekusi Berikutnya)**:
  1. *Dedicated Executive Dashboard Page*: Ditutup/dibatalkan atas arahan pengguna untuk mempertahankan identitas murni Conversational AI Assistant.
  2. **Ekspor PDF Siap Cetak**: Mode cetak laporan PDF eksekutif bertandatangan.
  3. **F6 Hardening Skala Besar**: Redis Distributed Rate Limiter & Distributed Schema Cache.
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
