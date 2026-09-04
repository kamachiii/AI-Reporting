-- Rollback migration 012: Hapus kolom chat_mode dari tabel tenants

ALTER TABLE tenants DROP COLUMN IF EXISTS chat_mode;
