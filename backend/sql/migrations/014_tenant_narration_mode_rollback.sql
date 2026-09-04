-- Migration 014 Rollback: Hapus kolom auto_narration
-- Idempotent, tidak ada karakter titik koma di dalam komentar

ALTER TABLE tenants DROP COLUMN IF EXISTS auto_narration;
ALTER TABLE users DROP COLUMN IF EXISTS auto_narration;
