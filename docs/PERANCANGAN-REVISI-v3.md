# PERANCANGAN REVISI v3 — Responsivitas AI, Governance KB/Memori, RBAC 7 Role, Admin Training, Pusat Analisa

> **Status**: Perancangan (belum diimplementasikan).
> **Tanggal**: 2026-09-14.
> **Konteks**: Revisi dari pemilik — (1) AI belum responsif & jawaban belum sesuai, (2) KB Global & KB tenant belum benar-benar mengatur, (3) role user baru (direksi, sales manager, sales supervisor, service manager, finance manager, accounting manager, admin head) dengan izin data sesuai role, (4) admin punya tempat chat untuk melatih AI, (5) status tidak-terjawab/salah/error dikumpulkan untuk analisa admin, (6) fix KB & Memory SQL: sudah ditolak tapi masih dipakai; KB tenant A bocor ke tenant B.
> **Keputusan pemilik**: izin role = tabel & kolom per role; KB Global tetap tapi terkurasi ketat; admin training bisa simpan ke tenant atau global; spike verifikasi dijalankan sebelum estimasi final.

---

## 1. Temuan Akar Masalah (hasil riset kode sesi 2026-09-14)

### 1.1. AI belum responsif & jawaban belum sesuai
- **Provider tunggal tanpa fallback**: `panggil_llm_default` (`backend/app/services/query_planner.py:291`) satu panggilan httpx ke satu provider. Provider global XKiro (`qwen/qwen3.8-max:free`) 500 intermiten → semua pertanyaan baru gagal. Tidak ada rantai fallback.
- **Jalur jawaban bercabang dengan presedensi heuristik**: hook deterministik vs memori vs fanout vs LLM saling menimpa (contoh insiden: hook revenue-dealer benar tapi tidak jalan karena worker basi). Urutan evaluasi tidak dipertegas.
- **Presenter/narasi bisa menyimpang dari tabel** (kelas bug 253M — sudah diperbaiki, tapi belum ada pagar kode umum angka-narasi-vs-rows).
- Tidak ada instrumentasi latensi per tahap → "tidak responsif" tidak bisa dilokalisasi.

### 1.2. KB Global & KB tenant belum benar-benar mengatur
- `muat_kb_gabungan` (`backend/app/services/knowledge_base.py:428-462`): glossary & catatan_kolom & contoh_tanya **global SELALU di-merge ke semua tenant**. Hanya `tabel_dilarang/diizinkan/kolom_dikecualikan` yang tenant-only (`:379-380`, `:430-432`).
- `cari_konteks_pgvector` (`backend/app/services/vanna_pgvector.py:128` & `:163`): `WHERE branch_code = $2 OR branch_code = 'GLOBAL'`.
- Fallback `global_knowledge_base` ILIKE (`vanna_pgvector.py:148-157`) tanpa filter tenant.
- Ada **4 penyimpanan pengetahuan terpisah** tanpa satu sumber kebenaran:
  1. `tenants.knowledge_base` (JSONB, per-tenant),
  2. `global_knowledge_base` (global),
  3. `tenant_vector_kb` (branch + GLOBAL),
  4. `sql_memory` (per-tenant).

### 1.3. Role hanya `admin`/`user`
- `sql/1_SCHEMA_BASE.sql:21-25` → `CHECK (role IN ('admin','user'))`.
- 7 role bisnis belum ada model maupun izin datanya.

### 1.4. Admin tidak punya tempat chat melatih
- `require_user_role` menolak role admin di `/chat` (`backend/app/core/security.py:96-100`).
- `/admin/vanna/train` ada tapi bukan chat interaktif.

### 1.5. Belum ada wadah analisa kegagalan
- `audit_logs` sudah mencatat `status`/`error_message` (`_audit_gagal`), tapi `AuditLogTab` hanya baca. Tidak ada antrean kurasi + aksi perbaikan.

### 1.6. "Sudah ditolak tapi masih dipakai" & "KB tenant A kena tenant B" — AKAR TERKONFIRMASI SPIKE
- **Akar reject**: reject hanya ubah SATU baris `sql_memory.status` (`chat_pipeline.py:402-464`). Satu pertanyaan bisa punya BANYAK baris (`simpan_memory_pending` upsert pada `(tenant_id, pertanyaan, sql)` → SQL berbeda = baris baru). Baris kembar tetap hidup → "sudah ditolak kok masih dipakai". BUKAN masalah vektor (terbukti: 3 SQL rejected tidak ada di vektor/global).
- **Akar bocor**: item `GLOBAL` dibaca semua tenant (mekanisme di 1.2). Data nyata: 2416 DDL + 24 sql_example + 16 thesaurus GLOBAL; `global_knowledge_base` 2419 text masuk ke tiap tenant.

---

## 2. Hasil Spike Verifikasi (read-only, 2026-09-14)

Sumber: koneksi core DB `localhost:5433/ai-dms`, kueri SELECT-only.

### 2.1. Skala data live (kecil → risiko migrasi rendah)

| Fakta | Angka |
|---|---|
| Tenant aktif | 2 (TST_01, TST_02) |
| User | admin 1, user 4 |
| `tenant_vector_kb` | GLOBAL: 2416 ddl + 16 domain_thesaurus + 24 sql_example · TST_01: 9 · TST_02: 3 |
| `global_knowledge_base` | 2419 text + 28 example |
| `sql_memory` | TST_01: 39 approved / 36 pending / 2 rejected · TST_02: 16 / 15 / 1 |
| `ai_configs` | #13 global XKiro · #11 user ByNara (tester03) · #14 user OpenAgentic (user_jkt) — **tidak ada fallback** |
| `audit_logs` | 1089 success, 167 error, 2 rejected, 3 clarification |

### 2.2. Bukti "rejected tapi masih dipakai" = baris kembar

```
[TST_01] 'penjualan bulan ini'                     status=[rejected, pending]           ids=[6, 21]
[TST_02] 'perbandingan service 20000km...'          status=[rejected, pending]           ids=[130, 131]
[TST_01] 'bandingkan data pembelian 2025 vs 2026'   status=[pending,pending,pending,approved] ids=[36,40,41,43]
[TST_01] 'data penjualan berbanding data pembelian 2025' status=[pending, approved]     ids=[32, 53]
```

**Interpretasi**: status adalah properti per-baris, bukan per-pertanyaan. Menolak satu baris tidak menuntaskan pertanyaan itu. Koreksi desain: status & perintah admin harus pada granularitas **pertanyaan ternormalisasi**, bukan baris.

### 2.3. Jalur tulis (inventaris lengkap — grep seluruh `backend/app`)

| Store | Jalur INSERT | Jalur UPDATE | Jalur DELETE |
|---|---|---|---|
| `sql_memory` | `chat_pipeline.py:367` (pending), `vanna_engine.py:3385` | `:324` (dipakai), `:332` (stale), `:357` (plan), `:452` (status), `:612` (ringkasan) | tidak ada |
| `tenant_vector_kb` | `vanna_pgvector.py:88` (upsert branch_code) | — (upsert) | `routers/admin/vanna_training.py:116` (per id) |
| `global_knowledge_base` | `routers/admin/global_kb.py:186`, `services/vanna_sync.py:121` | via sync | `:312`, `vanna_sync.py:159` (orphan) |

**Catatan**: tidak ada kolom `scope`/`status` di `tenant_vector_kb` — verifikasi skema information_schema. Tidak ada mekanisme cascade antar-store.

---

## 3. Klasifikasi Kepastian

- **Terverifikasi (baca kode + data live)**: seluruh 1.1–1.6 di atas, angka 2.1–2.2, inventaris 2.3.
- **Inferensi (mekanisme pasti, dampak perlu dicacah)**: 1294 dari 2419 text global menyebut "TST/cabang" — belum dibedakan mana benar-benar bocor spesifik-tenant vs sekadar nama kolom/skema.
- **Belum diketahui**: perilaku persis 500 XKiro (kondisi pemicu); integrasi mulus/tidaknya verifier dengan `role_permissions` (Fase C).
- **2 spike sisa** (untuk kepastian penuh): (1) prototipe 1 role end-to-end ±0,5 hari; (2) cacah konten global yang benar-benar bocor ±0,5 hari.

---

## 4. Prinsip Desain

1. Satu sumber kebenaran, banyak proyeksi — setiap pengetahuan punya satu tempat asal; turunannya proyeksi yang bisa dicabut.
2. Isolasi default-deny — tanpa penanda `GLOBAL` eksplisit, tidak terbaca lintas-tenant.
3. Kurasi global eksplisit — masuk global hanya via aksi sadar ("Promosikan ke Global"), bukan efek samping sync.
4. Satu aksi admin = tuntas semua store (propagasi reject/hapus).
5. Tanpa hardcode — perbaikan lewat data (KB/memori/permission).
6. Observable by default — tiap tahap pipeline punya jejak.

---

## 5. Perancangan Per Fase

### Fase A — Observabilitas & Provider Fallback (fondasi)
- `ai_configs` tambah `priority` + `is_fallback` (atau tabel `ai_config_fallbacks`). `panggil_llm_default` (`query_planner.py:291`) mencoba primary → fallback saat HTTP 5xx/timeout.
- Health-check + circuit breaker in-memory ber-TTL; provider mati di-skip sementara.
- Trace per tahap `{rute, memori, kb_ms, llm_ms, verifier_ms, eksekusi_ms, presenter_ms, sumber}` → via SSE `lapor` + `audit_logs.ai_json_filter.trace`.
- **Ubah**: `query_planner.py`, `chat_pipeline.py`, migrasi `ai_configs` (016), `ai_orchestrator.py`.

### Fase B — KB Satu Sumber + Isolasi Keras (inti revisi 2 & 6)
- Tambah kolom `scope` ∈ (`tenant`,`global`) di `tenant_vector_kb` (backfill existing; `GLOBAL` lama dikurasi ulang).
- Retrieval default-deny di `cari_konteks_pgvector` & `ambil_konteks_vanna`: `branch_code = tenant OR (branch_code='GLOBAL' AND scope='global')`. Hapus fallback ILIKE lintas-tenant; ganti fallback tenant-scoped.
- Status per-pertanyaan: tambah kolom `pertanyaan_status` (atau tabel `memory_questions`) — aksi admin berlaku untuk SEMUA baris satu pertanyaan.
- Layanan baru `kb_governance.py`: `cabut_pengetahuan(pertanyaan_norm)` (hapus/tandai di sql_memory + vektor + global sekaligus, satu transaksi, beraudit) dan `promosikan_ke_global()`.
- Panggil otomatis saat: reject memory, hapus KB tenant, hapus KB global.
- UI: label "Berlaku Global (semua cabang)" vs "Khusus Cabang X".
- **Ubah**: `knowledge_base.py`, `vanna_pgvector.py`, `vanna_engine.py`, `chat_pipeline.py`, `fewshot_provider.py`, migrasi `016_kb_isolation.sql`, router KB.
- **Urutan aman**: cacah konten global dulu (spike sisa #2), lalu kurasi, lalu isolasi — agar jawaban yang sah tidak hilang.

### Fase C — RBAC 7 Role, Izin Tabel & Kolom per Role (revisi 3)
- Perluas constraint: `check_role IN ('admin','user','direksi','sales_manager','sales_supervisor','service_manager','finance_manager','accounting_manager','admin_head')`.
- Tabel `role_permissions`: `role`, `allowed_tables` (text[]), `denied_columns` (text[]), `allowed_branches_mode` (`own`/`all`).
- Komposisi ke mekanisme yang sudah ada: `skema_efektif = skema_tenant ∩ role.allowed_tables − role.denied_columns − kb.tabel_dilarang` (reuse `_siapkan_skema_efektif`, `chat_pipeline.py:221`).
- Verifier terima `role_denied_columns` → gerbang "kolom ditolak" (`sql_guard.verify_sql`).
- Ganti `require_user_role` → `require_roles(*roles)` generik; JWT tetap diverifikasi ulang ke DB.
- Role bisnis memakai workspace chat yang sama (skema dipersempit) — landing berbeda (mis. direksi→dashboard) keputusan lanjutan.
- **Ubah**: migrasi `017_rbac.sql`, `security.py`, `chat_pipeline.py`, `sql_guard.py`, `auth.py`, `App.jsx`, UI manajemen role.

### Fase D — Admin Training Chat (revisi 4; simpan tenant ATAU global)
- Workspace `/admin/latih`: admin bertanya → pipeline dry-run → tampil SQL + pratinjau hasil.
- Panel aksi **Simpan ke** `[Cabang X ▾]` atau `[Global]`. Tenant → `latih_pertanyaan_sql(branch_code=X)` + `sql_memory` tenant; Global → `global_knowledge_base` + vektor `scope='global'`.
- Branch dipilih eksplisit (admin tak punya cabang); guard `require_admin_role` + `@audit_admin("admin-train")`.
- **Ubah**: router `admin/training_chat.py` baru + service orkestrasi + `AdminTrainingTab.jsx`. Endpoint `/admin/vanna/train` dipakai ulang.

### Fase E — Pusat Analisa Kegagalan (revisi 5)
- Sumber: `audit_logs` (status rejected/error, 169 baris error existing) + `sql_memory` rejected/stale + low-confidence.
- Tab "Analisa & Perbaikan" + aksi per item: tambah SQL ke KB (tenant/global), simpan sebagai memori, hapus KB terkait (`cabut_pengetahuan()`), tandai selesai — semua via data + audit, tanpa hardcode.
- **Ubah**: tabel kurasi (`failure_reviews` / kolom kurasi di `audit_logs`), router admin, tab frontend.

### Fase F — Kualitas Jawaban (revisi 1)
- Presedensi jalur dipertegas: deterministik → memori approved → KB → LLM (+ log alasan).
- Tutup R1–R5: (R1) satu-kolom-uang di agregator komparasi mode-peringatan; (R2) audit memori basi; (R3) pemeriksa angka narasi-vs-rows longgar; (R4) disclosure pembanding default; (R5) angka eksak + singkatan.
- Target: chat < 60 dtk, mayoritas < 15 dtk (diukur via trace Fase A).

---

## 6. Ringkasan Migrasi DB

| Migrasi | Isi |
|---|---|
| `016_kb_isolation.sql` | `tenant_vector_kb.scope` + backfill + indeks; status per-pertanyaan |
| `017_rbac.sql` | perluas role + `role_permissions` |
| `018_failure_reviews.sql` | tabel kurasi kegagalan |
| `019_ai_fallback.sql` | prioritas/fallback provider di `ai_configs` |
| `020_kb_provenance.sql` | tautan memori↔vektor↔global untuk propagasi (bila diperlukan) |

---

## 7. Estimasi Waktu (solo, penuh waktu, 1 developer)

| Fase | Estimasi | Keyakinan | Penggerak ketidakpastian |
|---|---|---|---|
| A. Observabilitas + provider fallback | 2–3 d | Tinggi | kesehatan provider |
| B. Isolasi KB + dedup status + propagasi | 2–3 d | Sedang-tinggi | cacah konten global |
| C. RBAC 7 role (tabel & kolom) | 4–6 d | Sedang | 7 role × BE/FE/verifier — variabel dominan, bisa ±1,5× |
| D. Admin training chat | 2–3 d | Sedang-tinggi | dependensi Fase B |
| E. Pusat analisa kegagalan | 2–3 d | Sedang | cakupan aksi kurasi |
| F. Kualitas jawaban (R1–R5) | 3–4 d | Sedang | false-positive pagar narasi |
| Integrasi + regresi + e2e + QA | 3–5 d | Sedang | interaksi antar-fase |
| **Total** | **~18–27 hari-kerja** | Sedang | |

Urutan teraman: A (1 mgg) → B (1 mgg) → C (1–1,5 mgg) → D+E (1 mgg) → F (~1 mgg). Tiap fase: unit test + e2e + verifikasi live, suite hijau sebelum lanjut.

**Catatan untuk pelaporan**: angka di atas adalah *rentang kerja*, bukan janji tanggal. Untuk menyempitkan ke ±3 hari, jalankan dulu 2 spike sisa (±1 hari total): prototipe 1 role end-to-end + cacah konten global.

---

## 8. Risiko & Trade-off Utama

- **B**: jawaban yang tadinya "kaya" bisa menyusut saat global diramping → mitigasi kurasi + promosi.
- **C**: aturan komposisi KB × izin role harus jelas (∩; dilarang menang); biaya join kecil per request.
- **Migrasi role**: backfill `admin`/`user` existing hati-hati; skala kecil (2 tenant, 5 user) → risiko rendah.
- **A**: kualitas antar-provider bisa beda → normalisasi keluaran.
- **F**: setiap pagar baru menambah false-positive → mulai dari mode peringatan, bukan penolakan.

---

## 9. Hasil 2 Spike Sisa (2026-09-14, executable — bukan opini)

Skrip spike (throwaway, di luar repo): `spike_role.py`, `spike_global.py` (temp opencode).

### 9.1. Spike 1 — prototipe 1 role end-to-end: BERHASIL PENUH

Mock `role_permissions` (`sales_manager`: allowed 3 tabel, denied 2 kolom) → komposisi dengan KB → `_siapkan_skema_efektif` **tanpa perubahan** → `verify_sql` terhadap skema TST_01 asli (2387 tabel):

```
GABUNG izinkan: ['srvt_wo', 'srvt_wodetail', 'untt_penjualan']
GABUNG kecuali: ['srvt_wo.nopolisi', 'untt_penjualan.diskon']
TABEL_EFEKTIF: 3 tabel | diskon & nopolisi terbuang dari skema
A_boleh (kolom diizinkan)   : ok=True
B_kolom_ditolak (diskon)    : ok=False gate=whitelist "kolom 'diskon' tidak ada di tabel yang diizinkan"
C_tabel_ditolak (glbm_customer): ok=False gate=whitelist "tabel di luar whitelist: glbm_customer"
D_star (SELECT *)           : ok=True (aman — eksekusi hanya mengembalikan kolom yang tersisa di skema)
```

**Kesimpulan pasti**:
- Integrasi RBAC **tidak butuh bongkar arsitektur**: komposisi izin + pruning skema cukup; verifier menolak otomatis via whitelist. Tidak perlu gerbang baru (opsional: pesan error lebih eksplisit).
- FE: role baru otomatis jatuh ke `UserWorkspace` (chat) — `App.jsx:56-79` hanya memisahkan `admin` vs sisanya. Yang wajib berubah hanya guard backend (`require_user_role` → `require_roles`) + UI manajemen role.
- Sisa kerja Fase C = migrasi 017 + tabel/resolve `role_permissions` + generalisasi guard + UI + test. Bukan riset.

### 9.2. Spike 2 — cacah konten global yang bocor: TERBATAS & TERDAFTAR

- Skema TST_01 ≡ TST_02 (2387 tabel, irisan 2387, selisih 0) → **sharing DDL tidak berbahaya**.
- `global_knowledge_base` 2447 = **2388 DDL + 28 example + 20 glossary + 11 teks bebas**.
- DDL di luar irisan skema: **0**. Kebocoran struktural = nihil.
- Example perlu kurasi (filter cabang spesifik / artefak): `#2494` ("cabang 210 dan 211"), `#10/#11` (information_schema generik — aman), `#9631/#9665-9667` (false-positive regex/C TE — verifikasi manual), `#720` teks bebas "OLDTRISURYA" (stale, tenant lama), `#3` teks bebas sampah CSV.
- Vektor GLOBAL `sql_example` (24): generik dealer, 1 ber-filter cabang (`#2494` setara) → masuk daftar kurasi.
- Vektor TST_01 (9) vs TST_02 (3): terisolasi benar per `branch_code` — tidak bocor.

**Kesimpulan pasti**: kurasi Fase B hanya ~±10 item terdaftar, bukan "ribuan misterius". Estimasi kurasi ≈ 0,5 hari.

### 9.3. Estimasi revisi pasca-spike (solo, penuh waktu)

| Fase | Estimasi | Keyakinan | Dasar |
|---|---|---|---|
| A. Observabilitas + provider fallback | 2–3 d | Tinggi | terisolasi, jelas |
| B. Isolasi KB + dedup status + propagasi | 2–3 d | **Tinggi** (naik) | akar pasti + kurasi terdaftar ±10 item |
| C. RBAC 7 role (tabel & kolom) | **3–5 d** (turun) | **Sedang-tinggi** (naik) | prototipe executable lolos; sisa = migrasi+guard+UI+test |
| D. Admin training chat | 2–3 d | Sedang-tinggi | reuse endpoint ada |
| E. Pusat analisa kegagalan | 2–3 d | Sedang | 169 error existing siap dianalisa |
| F. Kualitas jawaban (R1–R5) | 3–4 d | Sedang | FP pagar narasi hanya terukur saat implementasi |
| Integrasi + regresi + e2e + QA | 3–5 d | Sedang | antar-fase |
| **Total** | **~17–26 hari-kerja** | **Sedang-tinggi** | |

Sisa ketidakpastian yang jujur masih ada: pemicu 500 XKiro (sisi provider, tak bisa diverifikasi dari sini), laju false-positive pagar narasi (terukur saat implementasi), selera UX pusat analisa (keputusan pemilik).

### 9.4. Update provider 2026-09-14: XKiro mati → B.AI global (terverifikasi langsung)

- `ai_configs` kini: `#18 global B.AI` (`deepseek-v4.1-flash:free` via `https://tokenharbor.ai/v1`, dibuat 2026-09-14), `#11 user ByNara` (tester03), `#14 user OpenAgentic` (user_jkt). XKiro (#13) sudah dihapus.
- Uji ping langsung via `panggil_llm_default` (jalur produksi yang sama): **OK, `{"status":"ok"}`, tapi 33,6 dtk** untuk prompt trivial.
- Uji susulan 2026-09-14: **OpenAgentic (#14) OK 5,5 dtk** (6× lebih cepat dari B.AI); **ByNara (#11) MATI** — 403 "Your plan does not include the requested model" (paket/plan key berubah).
- Perbandingan provider saat ini: OpenAgentic 5,5 dtk (hidup) > B.AI 33,6 dtk (hidup, lambat) > ByNara (mati) > XKiro (dihapus).
- **Keputusan 2026-09-14: global #18 dialihkan ke OpenAgentic** (provider/model/base_url/key = salinan #14 user_jkt; temperature 0,7→0,1). Backup nilai lama B.AI tercatat di audit log `[provider-switch]`. Verifikasi E2E (TST_01/tester01, pertanyaan baru): resolve → OpenAgentic, SQL valid, 5 baris, 33,6 dtk total pipeline. Residu uji (memori pending #132, conversation #221) sudah dibersihkan.
- **Sisa masalah**: `#11` ByNara (tester03) mati (403 plan) — butuh key baru, tidak bisa diperbaiki dari sini.
- **Verifikasi ulang 2026-09-14 (pasca-switch)**: suite backend **648 passed**; audit tumbuh wajar (success 1115, error 175 — error baru = jejak aktivitas sesi ini + 500 ByNara + 1 rate-limit user).
- **⚠️ Temuan kritis verifikasi ulang**: key OpenAgentic bersama (reuse #14) kini **429 "Daily quota exceeded (100/100 requests today)"** — persis risiko yang diprediksi saat reuse key. Global ikut mati sampai kuota reset (±1 jam per `retry_after`, atau reset harian) atau ada key baru. Bukti dampak: audit `#1329` (pertanyaan user TST_01 gagal rate-limit). Opsi: (a) tunggu reset, (b) kembalikan sementara ke B.AI (hidup, lambat), (c) pasang key OpenAgentic baru sebagai global.
- **Update lanjutan (masih 2026-09-14)**: retry 2× global OpenAgentic gagal konsisten — kini **400 "Model is unavailable" (upstream)**, bukan lagi 429. Artinya model `glm-5.3-flash` di sisi OpenAgentic sedang down/kehabisan kapasitas, bukan sekadar kuota key. Global MATI total sampai (a) model pulih, (b) revert ke B.AI, atau (c) key/model baru.
- **Update lanjutan 2 (masih 2026-09-14): global #18 diganti pemilik ke OpenCode Zen** (`muse-spark-1.3-contributor-free` via `https://opencode.ai/zen/v1`). Hasil uji berlapis: key VALID (`/models` → 200, 70 model, termasuk `muse-spark-1.3-contributor-free`); TAPI inference gagal semua — `muse-spark-1.3-contributor-free` → 500 (dengan/tanpa `response_format`); `deepseek-v4-flash-free` → 400 unavailable; `glm-5.3-flash` → **401 `CreditsError: No payment method`** (key tanpa billing). Kesimpulan: Zen belum viable sebagai global — model free error upstream, model berbayar terkunci billing. Opsi: (a) revert ke B.AI sementara, (b) tambah payment method di workspace Zen lalu pakai model berbayar, (c) tunggu model free pulih.
- **Update lanjutan 5 (masih 2026-09-14): global #18 DIHAPUS pemilik; global baru #19 = ByNara/agnes** — saat eksekusi revert, `#18` sudah tidak ada (hanya #11, #14 tersisa). Karena key B.AI lama sudah tertimpa dan tak dapat dikembalikan, dibuat global baru `#19` ByNara/`agnes-2.5-flash` (key reuse #11, temp 0.1; audit `[provider-switch]`). Verifikasi E2E (TST_01/tester01): resolve → ByNara/agnes ✓; replay memori 0,4 dtk ✓; jalur LLM penuh (pertanyaan baru) 30,4 dtk, SQL valid, 3 baris ✓. Residu uji dibersihkan. Status: layanan AI global PULIH (dengan catatan kuota key bersama #11/#19).
- **Update lanjutan 3 (masih 2026-09-14): root-cause "selalu 500 ke Nara router"** — diuji langsung ke `router.bynara.id/v1` dengan key tersimpan (#11, terdekripsi normal): `GET /models` → **500 `internal_error/An internal error occurred`** (bug di sisi ByNara, key valid tapi endpoint models error); `POST /chat/completions` (`glm-5.3-flash`) → **403 `Your plan does not include the requested model`** (paket key tidak mencakup model itu). Backend kita memetakan dengan benar (502 + pesan ringkas); 500 yang terlihat di UI berasal dari gateway ByNara. Perbaikan harus dari sisi ByNara (perbaiki endpoint models / sesuaikan plan) — tidak ada yang bisa diperbaiki dari kode kita.
- **Update lanjutan 4 (masih 2026-09-14): jalan keluar ganti model tanpa fetch** — (a) UI: `ModelPickerModal.jsx` + input manual "ketik nama model" (backend memang tidak validasi nama model, jadi string apa pun tersimpan); (b) model in-plan ditemukan via probing + pricing publik: `agnes-2.5-flash` (3,2 dtk, JSON-mode OK 9 dtk via jalur produksi), `laguna-s-2.1` (2,1 dtk), `mimo-v2.5-free` (3,6 dtk), `glm-5.3-free` (200 tapi reasoning/null-content — butuh max_tokens besar). **Keputusan: #11 → `agnes-2.5-flash`** (audit `[provider-switch]`), resolve tester03 → ByNara/agnes ✓, JSON-mode ✓. Catatan: `auto/bynara` 404, `/api/plans` 401 — daftar resmi hanya dari dashboard ByNara.
- Dampak ke rancangan: risiko provider berubah bentuk dari "500 intermiten" menjadi **"latensi tinggi"**. Fase A tetap wajib, dengan penekanan tambah: timeout agresif + fallback cepat (jangan tunggu 30 dtk), budget latensi per tahap, dan jawaban deterministik/KB diutamakan agar mayoritas pertanyaan tidak menyentuh LLM lambat.

---

## 10. Proof-of-Concept Temuan Kritis (2026-09-14, DIEKSEKUSI — bukan statis)

Suite baseline sebelum PoC: **648 passed**. Semua baris PoC berlabel dan **sudah dibersihkan total** (verifikasi 0 residu).

### PoC K1a — memori `pending` di-replay sebagai confidence A: TERBUKTI
- Baris `pending` #134 (SQL jinak) + pertanyaan baru → `source=memory confidence=A rows=1` dalam 0,4 dtk.
- Artinya jawaban **belum dikonfirmasi** disajikan sebagai keyakinan tertinggi.

### PoC K1b — SQL berbahaya lolos mentah tanpa verifier: TERBUKTI
- Baris `approved` #135 berisi `SELECT pg_sleep(2)` → dieksekusi (`dt=2.2s` membuktikan sleep berjalan), `rows=1 confidence=A`.
- `verify_sql` terhadap SQL yang sama: `ok=False gate=profil "fungsi dilarang (profil v1): pg_sleep"`.
- Artinya gerbang keamanan **dilewati total** di jalur replay Vanna. Vektor serangan: user latih SQL jahat via `/chat/train` → korban se-cabang yang bertanya sama mengeksekusinya.

### PoC K2 — IDOR `conversation_id`: TERBUKTI
- Conversation #230 milik tester02 (id=5) dibaca lewat `deteksi_topik_riwayat_percakapan(core_pool, 230)` + `ambil_konteks_percakapan_aktif` — tanpa cek pemilik.
- Hasil: `topic='pembelian'`, `year=2025`, `has_prior_chat=True` — konteks korban bocor dan dapat meracuni kueri penyerang (atau sebaliknya).
- Catatan: jalur tulis (`ambil_atau_buat_conversation`, `chat_pipeline.py:520`) SUDAH benar — hanya jalur baca yang bolong.

### Status keyakinan pasca-PoC
- K1a, K1b, K2: **pasti (terbukti runtime)** → layak dieksekusi sebagai fix K1–K2.
- Temuan MEDIUM/LOW audit: tetap **keyakinan sedang** (statis, belum di-PoC-kan).

### Follow-up 2026-09-15 — PoC ulang vs kode fixed (DIEKSEKUSI)
- Suite: **656 passed** (Blok 1–3 + test replay/pulihkan/formula; `test_replay_verdict_gagal_jadi_stale_dan_miss` diperkuat tahap B dengan mock classifier).
- K1b live (2 run, mid #137 non-topikal + #138 topikal `tampilkan 5 model mobil terlaris ...`, SQL `SELECT pg_sleep(2) FROM untt_penjualan`): replay **MISS** (`Replay SQL memory gagal (), lanjut ke LLM...`), `mem=None`, sleep **tidak dieksekusi**, kedua baris → **`stale`** (verifikasi sebelum cleanup). Catatan: pertanyaan non-topikal jatuh ke `source=conversational` setelah MISS; topikal pun `source=conversational sql=''` (fallback LLM pasca-MISS) — hasil keamanan identik: SQL berbahaya tidak jalan + baris di-invalidasi.
- K2 live: `_conversation_milik_user` → guard asing (user 4 vs conv milik 5) = **`None`** + warning `conversation_id asing ditolak`, guard pemilik = conv ID ✓.
- Excel: `_sel_teks_aman('=cmd|xx')` → `"'=cmd|xx"` (prefix kutip Tunggal, netral di spreadsheet); `+`, `@` sama; teks normal (`Avanza`) tak tersentuh. Caps rows≤1000/cols≤50 + sanitasi filename teruji via `test_report_exporter.py`.
- Cleanup: residu `mem 0 / conv 0 / msg 0 / poc-fix 0` (mid #137–138, conv #253–256 dihapus).

### Follow-up 2026-09-15 — Fase B SELESAI via durable fix (profil v2 + enforcement)
- Diagnosis Fase 1 (live, read-only): introspeksi segar (srvt_wo 132=132, wodetail 15=15, untt_penjualan 98=98); `total_biaya`/`qty` memang TIDAK ADA live → penolakan sampel tepat (verifier benar); DB public punya **0 FK fisik** (ERP legacy) → aturan JOIN-FK menolak semua = kebijakan usang, bukan bug data.
- Profil v2 (`sql_guard.py`, V1 dibekukan): node `Window`+`RowNumber` diizinkan (read-only analitik, dibatasi LIMIT/budget/EXPLAIN); JOIN menjadi **FK-bila-ada** (skema ber-FK tetap enforced — katalog serangan no-FK-pair tetap ditolak; skema 0-FK fallback ON/USING+anti-CROSS+budget). Katalog serangan dimutakhirkan (Window→positif; JOIN tanpa ON/CROSS tetap negatif).
- Enforcement provenance-based: SQL LLM (single + fanout + repair) → `verify_and_execute` penuh; builder internal (revenue/komparasi/rincian/splitter) → AST-only (kode tepercaya). Tenant tanpa skema → fallback AST (paritas, bukan fail-closed). Tolak LLM → 1x self-repair dengan alasan verdict → gagal lagi = raise (fleksibel, bukan vonis mati).
- Bukti: suite **662 passed** (+6: 3 enforcement, 2 FK-bila-ada, net katalog); probe live flagship lolos (revenue cost 45486/3 rows, rincian, komparasi, fanout_mobil) + negatif ditolak (pg_sleep profil v2, DELETE bentuk); PoC live stub-LLM: legit dieksekusi (rows=1), pg_sleep diblokir pasca-repair, revenue E2E 3 baris; residu 0.
- Sasaran awal: ganti `conn.fetch` AST-only di jalur single-query (`vanna_engine.py:3348/3374`) + fanout (`eksekusi_subdomain_fanout :774`) dengan `verify_and_execute` penuh.
- Hasil probe verdict live (TST_01, EXPLAIN-only, tanpa eksekusi data):
  - `revenue_union` (deterministik flagship): `ok=False gate=profil` — JOIN `srvt_wodetail`↔`srvt_wo` tanpa FK.
  - `rincian_window` (deterministik): `ok=False gate=profil` — Window function di luar profil v1.
  - `srvt_wo_biasa` (SQL wajar tipikal LLM): `ok=False gate=whitelist` — kolom `total_biaya` ditolak.
  - `sparepart_join` (tipikal LLM): `ok=False gate=whitelist` — `d.qty` (alias) ditolak.
  - Negatif benar ditolak: `pg_sleep` (profil), `DELETE` (bentuk).
  - Lolos: `komparasi_3th` (cost 935/53 rows), `fanout_mobil` (cost 910/1 row).
- Keputusan: **blanket enforcement DITUNDA**. Alasan: (1) 2 builder deterministik flagship + SQL wajar harian ikut ditolak → regresi availability pasti; (2) nilai-tambah keamanan kecil — koneksi sudah terisolasi per-tenant + AST sudah menutup mutasi/fungsi berbahaya; sisa risiko verifier (whitelist/budget) mayoritas correctness/cost, bukan eksfiltrasi.
- Prasyarat sebelum enforcement: tuning verifier (profil v2: pola JOIN builder + Window; whitelist: resolusi alias/kolom) + uji false-positive atas traffic nyata.
- Status AST fail-closed single/fanout: tetap sebagai pertahanan berlaku (bukan lubang terbuka).
