-- 008 rollback manual: membatalkan 008_tenant_tier2.sql
-- HANYA dokumentasi - tidak dijalankan otomatis oleh init_db.py (guard
-- *_rollback.sql). Menghapus kolom flag Tier 2; status per-tenant hilang.

ALTER TABLE tenants DROP COLUMN IF EXISTS chat_tier2;
