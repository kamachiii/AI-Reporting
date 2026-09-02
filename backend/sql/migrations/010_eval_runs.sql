-- 010: Snapshot hasil eval (docs/PERANCANGAN-PIPELINE-AI-v2.md §8)
--
-- eval_runs menyimpan satu baris snapshot per kali eval dijalankan
-- (POST /admin/tenants/{branch_code}/eval-run): jumlah kasus, lulus,
-- pelanggaran verifier, pass_rate, dan detail per kasus (JSONB).
-- Baris TERBARU per tenant adalah dasar gate aktivasi Tier 2 (docs v2 §8):
-- pass_rate >= 0.95 DAN 0 pelanggaran verifier. Metrik ini juga yang
-- dipublikasikan sebagai metrik mingguan ke admin.
--
-- Catatan migrasi (konvensi repo):
--   - komentar TIDAK memakai titik-koma di tengah kalimat (init_db
--     memecah file SQL per karakter titik-koma)
--   - idempotent: CREATE ... IF NOT EXISTS, aman dijalankan berulang
--   - rollback manual tersedia di 010_eval_runs_rollback.sql

CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    total INTEGER NOT NULL,
    lulus INTEGER NOT NULL,
    pelanggaran_verifier INTEGER NOT NULL,
    pass_rate REAL NOT NULL,
    detail JSONB,
    dijalankan_oleh VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_eval_runs_tenants FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- Riwayat snapshot per tenant, terbaru dulu (sumber gate + metrik mingguan)
CREATE INDEX IF NOT EXISTS idx_eval_runs_tenant_created
    ON eval_runs (tenant_id, created_at DESC);
