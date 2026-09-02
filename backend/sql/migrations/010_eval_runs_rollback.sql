-- 010 rollback manual: membatalkan 010_eval_runs.sql
-- HANYA dokumentasi - tidak dijalankan otomatis oleh init_db.py (guard
-- *_rollback.sql). Menghapus tabel snapshot eval; riwayat pass_rate
-- hilang sehingga gate Tier 2 kembali terkunci (belum pernah eval).

DROP TABLE IF EXISTS eval_runs;
