-- Migration 015 Rollback: Hapus tabel antrean promosi KB
-- Idempotent, tidak ada karakter titik koma di dalam komentar

DROP TABLE IF EXISTS promosi_kb;
