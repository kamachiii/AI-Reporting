-- ============================================================
-- 005 ROLLBACK: hapus kolom knowledge_base dari tenants (F2.0).
--
-- PENTING: file ini TIDAK PERNAH dijalankan oleh loop migrasi init_db.py —
-- run_migrations melewatkan semua file *_rollback.sql (rollback hanya
-- dokumentasi manual). Menjalankannya otomatis justru membatalkan
-- migration induknya setiap kali init_db dipanggil.
--
-- Jalankan manual SAJA bila perlu membatalkan fitur Knowledge Base:
--   docker exec -i dms_pg psql -U postgres -d ai-dms < backend/sql/migrations/005_knowledge_base_rollback.sql
-- lalu hapus record tracking agar tidak dianggap applied:
--   DELETE FROM _migrations WHERE filename = '005_knowledge_base.sql';
-- ============================================================

ALTER TABLE tenants DROP COLUMN IF EXISTS knowledge_base;
