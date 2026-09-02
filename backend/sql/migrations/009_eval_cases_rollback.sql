-- 009 rollback manual: membatalkan 009_eval_cases.sql
-- HANYA dokumentasi - tidak dijalankan otomatis oleh init_db.py (guard
-- *_rollback.sql). Menghapus tabel golden-set beserta seluruh pertanyaan
-- emas yang tersimpan per tenant.

DROP TABLE IF EXISTS eval_cases;
