-- 007 rollback manual: membatalkan 007_sql_memory_ringkasan.sql
-- HANYA dokumentasi - tidak dijalankan otomatis oleh init_db.py (guard
-- *_rollback.sql). Menghapus kolom ringkasan & saran beserta datanya.

ALTER TABLE sql_memory DROP COLUMN IF EXISTS saran;

ALTER TABLE sql_memory DROP COLUMN IF EXISTS ringkasan;
