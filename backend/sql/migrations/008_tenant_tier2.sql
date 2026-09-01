-- 008: Feature flag Tier 2 per tenant (docs/PERANCANGAN-PIPELINE-AI-v2.md §1)
--
-- chat_tier2 mengaktifkan jalur Verified Text2SQL untuk tenant terkait:
-- router+generator satu panggilan LLM (tier 1 laporan standar / tier 2 SQL
-- utuh), self-repair maks 2x dengan umpan balik verifier, fallback Tier 1.
-- Default FALSE — alur chat lama (planner -> composer) berjalan selama flag
-- mati. Flag hanya dinaikkan admin lewat endpoint
-- POST /admin/tenants/{branch_code}/tier2 setelah eval lolos (docs v2 §8).
--
-- Catatan migrasi (konvensi repo):
--   - komentar TIDAK memakai titik-koma di tengah kalimat (init_db
--     memecah file SQL per karakter titik-koma)
--   - idempotent: ADD COLUMN IF NOT EXISTS, aman dijalankan berulang
--   - rollback manual tersedia di 008_tenant_tier2_rollback.sql

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS chat_tier2 BOOLEAN NOT NULL DEFAULT FALSE;
