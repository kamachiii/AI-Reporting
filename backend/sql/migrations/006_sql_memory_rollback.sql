-- 006 rollback manual: membatalkan 006_sql_memory.sql
-- HANYA dokumentasi — tidak dijalankan otomatis oleh init_db.py (guard
-- *_rollback.sql). Menghapus tabel & index SQL Memory beserta datanya.

DROP TABLE IF EXISTS sql_memory;
