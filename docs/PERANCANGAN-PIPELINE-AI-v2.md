# Perancangan Pipeline AI v2 — Dua Tier: Constrained + Verified Text2SQL

> Status: DRAFT v2 untuk dibahas (2026-08-31). Jika disetujui, dokumen ini
> menggantikan `PERANCANGAN-PIPELINE-AI.md` (v1). Bagian yang tidak diubah dari
> v1 (model deployment, knowledge base, skalabilitas dasar) tetap berlaku
> sebagaimana tertulis di v1.

## 0. Inti perubahan dari v1

v1 aman karena membatasi penulis SQL (LLM hanya boleh membuat rencana JSON).
v2 memindahkan sumber keamanan: **siapa pun boleh menulis SQL — termasuk LLM —
asalkan setiap SQL lolos verifikasi mekanis lengkap sebelum dieksekusi.**

| Faktor | vs v1 | Sumber perbaikan |
|---|---|---|
| Keamanan | ≥ v1 | Verifier 6 gerbang + eksekusi terkurung; tidak bergantung pada kecerdasan LLM |
| Fleksibilitas | ↑ besar | Tier 2 (verified text2sql): subquery/CTE/window function bisa dijawab |
| Kecepatan | ≥ v1 | SQL Memory (0 panggilan LLM untuk pertanyaan berulang), router 1 panggilan, verifier milidetik |
| Kegunaan | ↑ | SQL selalu bisa dilihat, level keyakinan per jawaban, fallback rapi, loop feedback |

Prinsip dasar: **keamanan tidak bergantung pada kecerdasan LLM, dan
fleksibilitas tidak bergantung pada kelemahan verifier.**

## 1. Arsitektur dua tier

```
Pertanyaan user
   │
   ▼
CONTEXT BUILDER (skema tenant + knowledge base + memori chat + few-shot)
   │
   ▼
ROUTER + PLANNER (LLM, panggilan #1 tunggal)
   │  satu panggilan sekaligus: memahami pertanyaan, memilih jalur,
   │  dan menghasilkan output sesuai jalur
   │
   ├─ TIER 1 — Standar (mayoritas laporan harian)
   │    Rencana JSON → SQL COMPOSER deterministik (desain v1, tetap ada)
   │
   └─ TIER 2 — Verified Text2SQL (long-tail: subquery, CTE, window function)
        LLM menulis SQL utuh → VERIFIER PIPELINE (§2) → EXECUTOR
        Gagal verifikasi → self-repair maks 2x (error verifier diumpankan balik)
                        → tetap gagal → fallback Tier 1, atau jawaban jujur
                          "tidak bisa dijawab otomatis" + saran pertanyaan ulang
   │
   ▼
PRESENTER (LLM #2, opsional — dilewati untuk jawaban tabel sederhana)
   angka HANYA dari hasil query + NUMBER CHECK mekanis (§4)
```

Tier dikontrol feature flag per tenant: `chat_tier2` (default mati; aktif hanya
setelah eval lolos, §8) dan `chat_new_sql_policy` (§7).

## 2. Verifier Pipeline — gerbang keamanan, semua default-deny

| # | Gerbang | Yang diblokir | Mekanisme | Biaya |
|---|---|---|---|---|
| 1 | Parser & bentuk | Multi-statement, non-SELECT, INTO/COPY, lock clause, SET | sqlglot AST; parse gagal = tolak | ms |
| 2 | Whitelist objek menyeluruh | Tabel/kolom di SEMUA bagian AST (subquery & CTE termasuk), identifier tak dikenal | Cocokkan ke `schema_config_json` minus `tabel_dilarang`; menangkap halusinasi skema | ms |
| 3 | Profil fitur SQL (versioned) | Fungsi/konstruksi di luar whitelist (pg_sleep, dblink, pg_read_file, DDL/DML, RECURSIVE tanpa batas) | Lihat §9 | ms |
| 4 | Budget kompleksitas | Cross-join explosion, nesting tak wajar (nalar-DoS) | Batas kedalaman AST, jumlah join, jumlah CTE | ms |
| 5 | EXPLAIN pre-flight | Query legal tapi mahal (cartesian, seq scan raksasa) | Estimasi cost/rows dibaca SEBELUM eksekusi; di atas budget = tolak | ~50 ms |
| 6 | Eksekusi terkurung | Sisa risiko runtime apa pun | Transaksi READ ONLY, statement_timeout 10 dtk, cap baris hasil, user DB khusus read-only (syarat onboarding klien) | — |

Isolasi antar tenant TIDAK berasal dari SQL, melainkan dari koneksi: SQL apa
pun hanya pernah menyentuh DB tenant milik cabang user tersebut.
Setiap keputusan verifier (lolos/ditolak, gerbang mana) tercatat di audit log.

## 3. SQL Memory — fleksibilitas yang menumpuk

Tabel `sql_memory`: `tenant, pertanyaan_ternormalisasi, sql, rencana_json,
status (approved|pending|rejected|stale), sumber, times_used, last_used,
fingerprint_tabel`.

- **Replay**: pertanyaan serupa dengan entri `approved` dijalankan TANPA
  panggilan LLM — deterministik, tercepat, level keyakinan A (§4).
- **Isi memory**: SQL baru yang lolos verifier disimpan berstatus `pending`;
  konfirmasi user ("jawaban benar") atau tinjauan admin → `approved`.
- **Invalidasi otomatis**: skema tenant berubah dan SQL memakai objek yang
  berubah → status `stale` sampai diverifikasi ulang.
- Efek jangka panjang: pertanyaan berulang makin dominan dijalankan via replay,
  sehingga sistem makin cepat, makin murah, dan makin deterministik.

## 4. Kejujuran tentang "99,9% benar" — taxonomy kegagalan & jaminan nyata

Tidak ada sistem NL-to-data yang dapat menjamin 99,9% benar untuk pertanyaan
apa pun; yang dapat direkayasa adalah: **setiap mode kegagalan punya penangkal
konkret, dan kegagalan tidak pernah senyap** (SQL selalu bisa dilihat, semua
tercatat di audit).

| Mode kegagalan | Contoh | Penangkal | Kualitas jaminan |
|---|---|---|---|
| Fabrikasi angka (halusinasi presenter) | Ringkasan menyebut angka yang tak ada di hasil | Presenter hanya boleh memakai angka hasil query + NUMBER CHECK mekanis: setiap angka di ringkasan dicocokkan ke sel hasil; tak cocok → 1x retry → fallback template tanpa narasi | ≈ 0, by construction (bukan statistik) |
| Halusinasi skema | Kolom/tabel yang tidak ada | Gerbang #2 (whitelist AST menyeluruh) | ≈ 0 — ditolak, tak pernah dieksekusi |
| SQL berbahaya | pg_sleep, akses lintas tabel, penulisan data | Gerbang #1–#6 berlapis; terakhir user DB read-only | ≈ 0 (default-deny) |
| Salah semantik (SQL jalan & aman, tapi menjawab pertanyaan lain) | "omzet" dimaknai `harga_jual` padahal `harga_deal` | KB + few-shot + eval terkurasi (§8) + SQL Memory + tampilan SQL + tombol "Jawaban ini salah" | TIDAK dapat dijamin absolut — dikelola: target terukur < 1% pada eval; selalu terdeteksi dan dapat diperbaiki |
| Data sumber salah | DB dealer memang berisi data keliru | Di luar cakupan AI — proses data klien | — |

Definisi operasional "99,9%": satu jawaban salah per 1.000 pertanyaan, dan
setiap kekeliruan terlihat serta dapat dilaporkan. Komitmen yang realistis:

- Fabrikasi angka & halusinasi skema: ditangkal mekanis, mendekati nol.
- Salah semantik: dibatasi lewat eval gate + memory + feedback; metrik mingguan
  dipublikasikan ke admin; tidak pernah senyap.
- UI menampilkan **Level Keyakinan** per jawaban:
  - **A** — replay SQL Memory `approved` (sudah pernah dikonfirmasi benar);
  - **B** — Tier 1 composer (deterministik, diuji eval);
  - **C** — SQL baru (ditandai "jawaban baru", SQL ditampilkan untuk
    verifikasi mandiri sebelum dipakai keputusan besar).

## 5. Kecepatan — anggaran latensi per jalur

| Jalur | Panggilan LLM | Mekanis tambahan | Perkiraan |
|---|---|---|---|
| Replay SQL Memory | 0 | eksekusi saja | < 1–2 dtk; dominan untuk pertanyaan berulang |
| Tier 1 | 1 | compose (µs) + verify (ms) + exec | p95 < 8 dtk (target v1 dipertahankan) |
| Tier 2 baru | 1 (router+generator satu panggilan) | verify (ms) + EXPLAIN (~50 ms) + exec | self-repair menambah maks 2 panggilan, hanya saat gagal |
| Presenter | 0–1 | number check (ms) | dilewati untuk jawaban tabel sederhana (template ringkas) |

Persepsi cepat: indikator tahap di UI (streaming), cache skema (Redis TTL 1
jam), cache knowledge base.

## 6. Kegunaan — kontrak UI

- Setiap jawaban: ringkasan + tabel/chart + chip "Lihat SQL" + Level Keyakinan
  (A/B/C) + tombol "Jawaban ini salah".
- Chip saran lanjutan; pertanyaan tak-bisa-dijawab diberi alasan jelas +
  saran cara bertanya ulang.
- Admin: dashboard eval & metrik mingguan; antrean tinjauan memory (hanya di
  mode strict).

## 7. Kebijakan SQL baru — default TANPA antrean admin

Keamanan TIDAK pernah berasal dari persetujuan admin (ia berasal dari
verifier + executor terkurung). Persetujuan hanya mempercepat keyakinan akan
kebenaran semantik. Karena itu:

- **Mode `auto` (default)**: SQL baru yang lolos verifier langsung dieksekusi,
  ditandai Level C + SQL tampil, disimpan ke memory berstatus `pending`;
  konfirmasi user → `approved` (Level A di replay berikutnya). Tanpa jeda,
  tanpa bottleneck admin.
- **Mode `strict` (opsional per tenant)**: SQL baru menunggu tinjauan admin
  sebelum dieksekusi — untuk tenant yang ingin ekstra konservatif.
- Kedua mode memiliki keamanan identik; perbedaannya hanya proses membangun
  keyakinan semantik.

## 8. Eval harness — gate aktivasi Tier 2

- Golden set per tenant: pertanyaan emas + SQL/hasil yang diharapkan (di KB);
  regresi otomatis dijalankan setiap perubahan prompt/profil.
- Tier 2 diaktifkan hanya bila pass ≥ ambang (usulan 95%) DAN 0 pelanggaran
  verifier pada eval.
- Metrik mingguan: flag rate "Jawaban ini salah", memory hit rate, p95 per
  tier, jumlah self-repair.

## 9. Profil fitur SQL — penjelasan sederhana

Analogi: whitelist "kosakata" yang boleh dipakai SQL. Mulai dari kosakata
laporan harian; kosakata baru hanya ditambah lewat revisi profil yang
versioned, diuji, dan didokumentasikan — tidak pernah dibuka diam-diam.

- Awal diizinkan: SELECT, WHERE, JOIN (via peta FK), GROUP BY, ORDER BY,
  LIMIT, CTE non-rekursif, agregasi (SUM/COUNT/AVG/MIN/MAX), fungsi string &
  tanggal umum, CASE, DISTINCT, UNION ALL (kolom hasil sama).
- Awal dilarang: fungsi administrasi/file/jaringan (pg_sleep, dblink,
  pg_read_file, …), DDL/DML apa pun, RECURSIVE tanpa batas kedalaman, fungsi
  di luar daftar.
- Butuh fungsi tambahan? Masuk revisi profil + uji katalog serangan + catatan
  changelog.

## 10. Urutan kerja revisi

```
F2.0  Knowledge base (tetap dari v1)
F2.3' Verifier v2: gerbang #1–#5 (TDD, katalog serangan diperluas)
F2.2  SQL Composer Tier 1
F3    Chat API (Tier 1 + SQL Memory replay) — rilis awal
F2.5  Generator Tier 2 + SQL Memory (tulis) + eval harness
F4    UI lengkap: level keyakinan, lihat SQL, feedback
F5    Mode laporan + export
F6    Hardening (kuota, Redis rate limit, cache, metrik)
```

Verifier dibangun SEBELUM generator — saat Tier 2 datang, gerbangnya sudah
teruji.

## 11. Keputusan terbuka

| # | Keputusan | Usulan awal |
|---|---|---|
| 1 | Ambang eval aktivasi Tier 2 | ≥ 95% pass, 0 pelanggaran verifier |
| 2 | Normalisasi pertanyaan untuk replay | lowercase + strip tanda baca; kecocokan longgar → jawaban pertama tetap Level C |
| 3 | Retensi sql_memory & audit | audit 12 bulan (mengikuti v1); memory dipertahankan selama fingerprint skema cocok |
| 4 | NUMBER CHECK: string-match atau numerik | numerik dengan toleransi format |
