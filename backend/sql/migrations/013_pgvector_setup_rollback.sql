-- Migration 013 Rollback: Hapus tabel tenant_vector_kb
-- Idempotent, tidak ada karakter titik koma di dalam komentar

DROP TABLE IF EXISTS tenant_vector_kb CASCADE;
