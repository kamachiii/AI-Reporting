# Perancangan Pipeline AI (NL → Data) — Draft Diskusi

> Status: DRAFT untuk dibahas. Belum disetujui, belum diimplementasikan.
> Target: platform AI laporan untuk **perusahaan besar** — keamanan, isolasi, dan
> kepercayaan lebih diutamakan daripada kecanggihan fitur.

---

## 1. Apa yang sebenarnya dibangun

Bukan text2sql klasik (AI menulis SQL mentah), melainkan **constrained NL-to-data**:

```
Pertanyaan user (bahasa natural)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ 1. CONTEXT BUILDER                                        │
│    • Ringkasan skema tenant (dari schema_config_json)     │
│    • Knowledge base: glossary + catatan kolom + nilai map │
│    • Memori percakapan (8 pesan terakhir)                 │
│    • 2-3 contoh few-shot khas tenant                      │
└──────────────────────┬────────────────────────────────────┘
                       ▼
┌───────────────────────────────────────────────────────────┐
│ 2. QUERY PLANNER (LLM, panggilan #1)                      │
│    Output WAJIB JSON ketat (divalidasi schema):           │
│    { intent, tables[], columns[], filters[], time_range,  │
│      group_by, order_by, limit, chart_hint, answer_style }│
│    JSON rusak → 1x retry dengan umpan balik error         │
└──────────────────────┬────────────────────────────────────┘
                       ▼
┌───────────────────────────────────────────────────────────┐
│ 3. SQL COMPOSER (deterministik, TANPA LLM)                │
│    Rencana → SQL parameterized; JOIN dari peta FK         │
└──────────────────────┬────────────────────────────────────┘
                       ▼
┌───────────────────────────────────────────────────────────┐
│ 4. SQL GUARD (sqlglot — gerbang keamanan)                 │
│    ✗ multi-statement  ✗ non-read-only  ✗ tabel/kolom      │
│    di luar whitelist  ✗ fungsi berbahaya  ✓ LIMIT ≤ 500   │
└──────────────────────┬────────────────────────────────────┘
                       ▼
┌───────────────────────────────────────────────────────────┐
│ 5. EXECUTOR (tenant DB)                                   │
│    Koneksi read-only, statement_timeout 10 dtk,           │
│    pool per tenant, konversi tipe (Decimal/date/UUID)     │
└──────────────────────┬────────────────────────────────────┘
                       ▼
┌───────────────────────────────────────────────────────────┐
│ 6. PRESENTER (LLM, panggilan #2 — opsional/ringkas)       │
│    1 kalimat ringkasan + saran pertanyaan lanjutan        │
│    ATURAN: angka HANYA dari hasil query, dilarang mengarang│
└──────────────────────┬────────────────────────────────────┘
                       ▼
        Frontend: SummaryCard / Chart (Recharts) / DataTable
                   │
                   ▼
        AUDIT LOG: user, cabang, pertanyaan, rencana, SQL,
        durasi, jumlah baris, status, error — setiap tahap
```

**Kenapa bukan text2sql murni:** injeksi praktis mustahil (filter selalu
parameterized, identifier di-whitelist dari skema), hasil deterministik antar
gaya user (ahli vs pemula), dan jejak audit rencana→SQL lengkap. Konsekuensi:
subquery/window-function eksotis tidak bisa — jalur "advanced mode" disiapkan
sebagai fase lanjutan bila benar-benar dibutuhkan.

---

## 2. Model deployment (keputusan terbesar)

| Opsi | Deskripsi | Cocok untuk |
|---|---|---|
| **A. On-premise per klien** | Seluruh stack (backend + frontend + core DB) dipasang di jaringan klien; backend menembak DB DMS mereka via LAN | Perusahaan besar yang melarang data keluar |
| **B. SaaS + agent outbound** | Stack di cloud kita; agent kecil di jaringan klien membuka koneksi KELUAR (reverse tunnel); tak perlu buka port masuk | Banyak klien, operasi terpusat |
| **C. SaaS + buka firewall** | Klien allowlist IP cloud kita + serah kredensial | Sering ditolak departemen keamanan |

**Rekomendasi: A sekarang, disiapkan untuk B.** Arsitektur yang sudah ada
(registry kredensial + koneksi keluar) cocok untuk A. Supaya B mungkin nanti,
`query_executor` harus berada di balik **interface tunggal**
(`execute(branch, sql, params)`) sejak hari pertama — bukan tersebar.

Konsekuensi A: satu instalasi = satu perusahaan (multi-cabang). Lihat §7.

---

## 3. Knowledge base (lapisan semantik)

Masalah: user bilang "omzet", kolom bernama `harga_deal`; bilang "unit laku",
artinya `COUNT(penjualan)`. Tanpa pemetaan, AI menebak.

**Usulan struktur** — satu kolom JSONB di `tenants` (cukup untuk F2; migrasi ke
tabel terpisah bila kelola per-kolom jadi rumit):

```jsonc
{
  "glossary": [
    { "istilah": "omzet",       "arti": "SUM(penjualan.harga_deal)" },
    { "istilah": "unit laku",   "arti": "COUNT(*) dari penjualan" },
    { "istilah": "prospek",     "arti": "pelanggan belum beli (tanpa penjualan)" }
  ],
  "catatan_kolom": {
    "penjualan.harga_deal": "Harga final setelah negosiasi — beda dengan kendaraan.harga_jual (harga pasaran)",
    "penjualan.uang_muka":  "0 artinya tunai"
  },
  "nilai_map": {
    "penjualan.metode_pembayaran": { "cash": "tunai", "credit": "kredit" }
  },
  "contoh_tanya": [
    { "tanya": "omzet bulan ini", "tabel": ["penjualan"], "agg": "sum(harga_deal)", "time_range": "this_month" }
  ],
  "tabel_dilarang": ["log_audit_internal"]
}
```

- CRUD: `GET/PUT /admin/tenants/{branch}/knowledge-base` + form admin
  (mulai dari form sederhana; validasi JSON ketat).
- Dipakai Context Builder; `tabel_dilarang` ikut mempersempit whitelist guard.
- **Prompt injection**: isi glossary/sample rows adalah DATA — di-escape sebagai
  data, output planner tetap divalidasi skema JSON, tidak pernah dieksekusi.

RAG/embedding **tidak diperlukan** selama skema < ~100 tabel (semua muat di
prompt). Skema raksasa → baru shortlisting via embedding (fase jauh).

---

## 4. Keamanan berlapis (defense in depth — 5 gerbang)

1. **AuthN/AuthZ** — JWT + role + `allowed_branches` di token; chat API wajib
   menolak branch di luar izin user (isolasi antar cabang/perusahaan).
2. **Whitelist dari skema** — planner hanya boleh menyebut tabel/kolom yang ada
   di `schema_config_json` (+ `tabel_dilarang` dikecualikan).
3. **SQL Guard (sqlglot)** — parse AST: single statement, read-only, whitelist,
   blokir fungsi berbahaya (`pg_sleep`, dll), paksa LIMIT ≤ 500. Unit test
   katalog serangan sudah ada (TDD) dan wajib hijau.
4. **Eksekusi terkendali** — transaksi `READ ONLY`, `statement_timeout` 10 dtk,
   **disarankan klien membuat user DB khusus read-only** untuk tenant
   (jadi walau semua gerbang di atas bocor, DB tetap tak bisa diubah).
5. **Audit penuh** — setiap pertanyaan tercatat: user, cabang, pertanyaan,
   rencana JSON, SQL final, durasi, jumlah baris, status/error. Basis
   kepercayaan & kepatuhan (compliance) perusahaan besar.

Tambahan enterprise: retensi audit log (mis. 12 bulan), PII masking per kolom
(tandai di knowledge base → presenter menyamarkan), kuota token harian per
tenant (kolom `daily_token_quota` sudah ada), batas query konkuren per tenant.

---

## 5. Skalabilitas & reliabilitas

| Aspek | Keputusan usulan |
|---|---|
| State in-memory (rate limit login) | Pindah ke Redis saat multi-instance (Redis sudah tersedia, belum terpakai) |
| Koneksi tenant | **Pool per tenant** (LRU, maks N koneksi, idle timeout) — bukan connect-per-query |
| Query berat | Tetap sinkron dengan timeout; laporan multi-bagian (F5) via pekerjaan async |
| Respons chat | Sinkron dulu (JSON lengkap); streaming SSE = peningkatan di F4+ |
| Ketahanan AI provider | Timeout 30 dtk, 1x retry planner, circuit breaker sederhana, opsional fallback provider, **metering token per query** |
| Cache | Skema di-cache (Redis, TTL 1 jam); cache hasil query TIDAK diaktifkan default (data harus segar) |

Target non-fungsional usulan: p95 pertanyaan sederhana < 8 detik; satu pertanyaan
gagal TIDAK boleh mempengaruhi tenant lain (isolasi kegagalan).

---

## 6. Mutu & kepercayaan (yang membuat perusahaan besar berani pakai)

1. **Evaluasi terkurasi**: per tenant, kumpulan pertanyaan emas + SQL/hasil yang
   diharapkan (disimpan di knowledge base); script uji regresi tiap kali prompt
   berubah. Tanpa ini, perubahan prompt = judi.
2. **Tombol "Jawaban ini salah"** di frontend → menandai baris audit → admin
   meninjau; metrik akurasi per minggu.
3. **Transparansi**: UI selalu menampilkan SQL yang dijalankan (sudah ada di
   desain detail audit) — userenterprise percaya pada yang bisa diperiksa.
4. **Presenter anti-halusinasi**: ringkasan hanya boleh memakai angka dari hasil.

---

## 7. Pertanyaan perancangan yang belum terjawab (perlu keputusan)

| # | Keputusan | Rekomendasi |
|---|---|---|
| 1 | Model deployment: A/B/C (§2) | A (on-prem) sekarang, interface untuk B |
| 2 | Satu deployment = satu perusahaan? Atau multi-perusahaan (SaaS) dalam satu core DB? | Satu perusahaan dulu; `companies` tetap dipakai untuk struktur internal |
| 3 | Knowledge base: JSONB di `tenants` vs tabel terpisah | JSONB dulu (YAGNI), migrasi bila perlu |
| 4 | Streaming jawaban (SSE) sekarang atau nanti | Nanti (F4+) — sederhanakan F2/F3 |
| 5 | User DB read-only per tenant diwajibkan ke klien? | Ya — jadi syarat onboarding (dokumen) |
| 6 | Bahasa hasil: nama kolom asli vs alias Indonesia dari AI | AI boleh memberi `display_name` di rencana; fallback nama asli |

---

### Keputusan yang sudah dijawab (2026-08-31)

> **Siapa boleh chat AI:** hanya role `user`. Admin tidak memiliki akses chat —
> perannya mengatur sistem & memantau lewat Audit Log. Ini keputusan domain dari
> pemilik proyek (admin = orang FBS; dealer = user). Isolasi `allowed_branches`
> di token tetap berlaku untuk user; admin tidak butuh karena tidak chat.

## 8. Urutan kerja Fase 2 (usulan revisi)

```
F2.0  Knowledge base: kolom + endpoint + form admin ringkas
F2.1  query_planner.py   (LLM → JSON rencana, validasi + 1x retry)
F2.2  sql_composer.py    (rencana → SQL parameterized deterministik)
F2.3  sql_guard.py       (sqlglot; katalog serangan test hijau)
F2.4  query_executor.py  (pool per tenant, read-only, timeout) — DI BALIK INTERFACE
F3    Chat API (/chat/query, conversations, isolasi cabang)
F4    UserWorkspace frontend (chat, kartu/grafik/tabel, feedback)
F5    Mode laporan + export PDF
F6    Hardening (kuota, Redis rate limit, cache skema, metrik)
```

Setiap komponen F2.x punya unit test sendiri; integrasi end-to-end diuji
terhadap `dealer_dummy` (terhubung ke JKT_01, skema sudah ter-introspeksi).
