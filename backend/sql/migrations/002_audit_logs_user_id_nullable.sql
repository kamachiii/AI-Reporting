-- ============================================================
-- 002: audit_logs.user_id nullable
-- Kolom user_id TIDAK boleh NOT NULL karena FK memakai
-- ON DELETE SET NULL (log harus selamat meski user dihapus).
-- Sudah diterapkan ke database live pada 2026-08-24.
-- ============================================================

ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL;
