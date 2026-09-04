-- Migration 011: Tabel global_knowledge_base untuk KB global (F3)
--
-- Menyimpan data KB yang di-sync dari sumber eksternal (Vanna API) agar
-- bisa di-merge dengan KB per-tenant saat pipeline chat berjalan.
-- Dua jenis data: 'text' (deskripsi tabel, business rules, glossary)
-- dan 'example' (pasangan pertanyaan -> SQL).

CREATE TABLE IF NOT EXISTS global_knowledge_base (
    id SERIAL PRIMARY KEY,
    external_id TEXT UNIQUE,
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('text', 'example')),
    content TEXT NOT NULL,
    question TEXT,
    sql_example TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_global_kb_kind
    ON global_knowledge_base (kind);

CREATE INDEX IF NOT EXISTS idx_global_kb_external_id
    ON global_knowledge_base (external_id);
