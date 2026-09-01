-- 006: SQL Memory (docs/PERANCANGAN-PIPELINE-AI-v2.md §3)
--
-- Menyimpan SQL terverifikasi per tenant agar pertanyaan berulang dijawab
-- TANPA panggilan LLM (replay, level keyakinan A). SQL baru yang lolos
-- verifier disimpan berstatus 'pending', konfirmasi user / tinjauan admin
-- menaikkan ke 'approved', skema berubah menandai entri 'stale'.
--
-- Catatan migrasi (konvensi repo):
--   - komentar TIDAK memakai titik-koma di tengah kalimat (init_db
--     memecah file SQL per karakter titik-koma)
--   - idempotent: CREATE ... IF NOT EXISTS, aman dijalankan berulang
--   - rollback manual tersedia di 006_sql_memory_rollback.sql

CREATE TABLE IF NOT EXISTS sql_memory (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    pertanyaan_ternormalisasi TEXT NOT NULL,
    sql TEXT NOT NULL,
    plan_json JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    sumber VARCHAR(30) NOT NULL DEFAULT 'tier1',
    times_used INTEGER NOT NULL DEFAULT 0,
    last_used TIMESTAMP WITH TIME ZONE,
    fingerprint_tabel TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sql_memory_tenants FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT check_sql_memory_status CHECK (status IN ('approved', 'pending', 'rejected', 'stale'))
);

-- Pencarian replay per tenant berdasarkan pertanyaan ternormalisasi
CREATE INDEX IF NOT EXISTS idx_sql_memory_lookup
    ON sql_memory (tenant_id, pertanyaan_ternormalisasi);

-- Index partial untuk jalur replay cepat: hanya entri approved
CREATE INDEX IF NOT EXISTS idx_sql_memory_approved
    ON sql_memory (tenant_id, pertanyaan_ternormalisasi)
    WHERE status = 'approved';
