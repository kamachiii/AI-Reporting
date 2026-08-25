-- ============================================================
-- 001: users.is_active
-- Menambahkan kemampuan menonaktifkan user tanpa menghapusnya.
-- Sudah diterapkan ke database live pada 2026-08-24.
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
