-- Migration 012: Tambah kolom chat_mode di tabel tenants
--
-- Menyimpan mode AI per tenant (cabang):
-- 'vanna' = Mode Vanna murni
-- 'tier2' = Mode Standar Tier 2 (Verified Text2SQL)
-- 'tier1' = Mode Standar Tier 1 (Deterministik)

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS chat_mode VARCHAR(20) NOT NULL DEFAULT 'vanna';

UPDATE tenants
SET chat_mode = CASE
    WHEN chat_tier2 = TRUE THEN 'tier2'
    ELSE 'vanna'
END
WHERE chat_mode IS NULL OR chat_mode = 'vanna';
