-- ============================================================
-- 015: promosi_kb — antrean promosi pola terkonfirmasi ke KB tenant
-- Idempotent, tidak ada karakter titik koma di dalam komentar
-- ============================================================

CREATE TABLE IF NOT EXISTS promosi_kb (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    memory_id INTEGER NULL REFERENCES sql_memory(id) ON DELETE SET NULL,
    pertanyaan TEXT NOT NULL,
    sql TEXT NOT NULL,
    ringkasan TEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'diusulkan' CHECK (status IN ('diusulkan', 'disetujui', 'ditolak', 'kedaluwarsa')),
    dibuat_oleh INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    diputus_oleh INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    alasan TEXT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, pertanyaan)
);

CREATE INDEX IF NOT EXISTS idx_promosi_kb_tenant_status ON promosi_kb (tenant_id, status);
