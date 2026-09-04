-- Migration 013: Setup ekstensi pgvector dan tabel tenant_vector_kb
-- Idempotent, tidak ada karakter titik koma di dalam komentar

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenant_vector_kb (
    id SERIAL PRIMARY KEY,
    branch_code VARCHAR(50) NOT NULL,
    item_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_vector_kb_branch_type_content 
ON tenant_vector_kb(branch_code, item_type, md5(content));

CREATE INDEX IF NOT EXISTS idx_tenant_vector_branch 
ON tenant_vector_kb(branch_code);

CREATE INDEX IF NOT EXISTS idx_tenant_vector_embedding_hnsw 
ON tenant_vector_kb USING hnsw (embedding vector_cosine_ops);
