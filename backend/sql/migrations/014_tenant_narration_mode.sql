-- Migration 014: Tambah kolom auto_narration untuk Mode Eksekutif vs Operasional
-- Idempotent, tidak ada karakter titik koma di dalam komentar

ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS auto_narration BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS auto_narration BOOLEAN DEFAULT NULL;
