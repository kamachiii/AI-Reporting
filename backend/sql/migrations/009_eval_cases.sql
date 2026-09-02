-- 009: Eval harness golden-set (docs/PERANCANGAN-PIPELINE-AI-v2.md §6/§8)
--
-- eval_cases menyimpan "pertanyaan emas" per tenant beserta SQL yang
-- diharapkan (golden set). Regresi dijalankan otomatis oleh eval_runner
-- (F2.7) pada tiap perubahan prompt/profil — tanpa eval terkurasi,
-- perubahan prompt sama dengan judi (docs v2 §6). Hasil run disimpan di
-- eval_runs (migration 010) dan menjadi gate aktivasi Tier 2 (docs v2 §8):
-- pass_rate >= 0.95 DAN 0 pelanggaran verifier.
--
-- sql_harapan WAJIB lolos verifier (sql_guard.verify_sql) terhadap skema
-- efektif tenant saat dibuat/diubah lewat endpoint admin — golden set yang
-- salah tidak boleh masuk (verifikasi ulang tetap jalan saat eval).
--
-- Catatan migrasi (konvensi repo):
--   - komentar TIDAK memakai titik-koma di tengah kalimat (init_db
--     memecah file SQL per karakter titik-koma)
--   - idempotent: CREATE ... IF NOT EXISTS, aman dijalankan berulang
--   - rollback manual tersedia di 009_eval_cases_rollback.sql

CREATE TABLE IF NOT EXISTS eval_cases (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    pertanyaan TEXT NOT NULL,
    sql_harapan TEXT NOT NULL,
    catatan TEXT,
    aktif BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_eval_cases_tenants FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT uq_eval_cases_tenant_pertanyaan UNIQUE (tenant_id, pertanyaan)
);
