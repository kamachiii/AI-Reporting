-- ============================================================
-- 004: Admin role semantics + AI scope global tunggal
-- Keputusan domain (user, 2026-08-31):
--   - Role admin khusus orang FBS, admin TIDAK punya penugasan cabang
--   - Scope Global pada ai_configs harus TUNGGAL (dijamin index)
--   - Config global kedua yang sudah ada dipindah ke tenant TST_01
-- Sudah diterapkan ke database live pada 2026-08-31.
-- ============================================================

-- 1. Admin tidak punya cabang
DELETE FROM user_branches
WHERE user_id IN (SELECT id FROM users WHERE role = 'admin');

-- 2. Pindahkan config global kedua (ShareLLM bila ada) ke tenant TST_01.
--    Defensif: hanya bila global > 1 DAN TST_01 terdaftar sebagai tenant.
UPDATE ai_configs
SET scope = 'tenant', target_id = 'TST_01'
WHERE id = (
    SELECT id FROM ai_configs
    WHERE scope = 'global' AND provider = 'ShareLLM'
      AND id <> (SELECT MIN(id) FROM ai_configs WHERE scope = 'global')
    LIMIT 1
)
AND (SELECT COUNT(*) FROM ai_configs WHERE scope = 'global') > 1
AND EXISTS (SELECT 1 FROM tenants WHERE branch_code = 'TST_01');

-- 3. Sisa global dobel lainnya (instalasi lain): paling tua tetap global, sisanya
--    dipindah ke tenant TST_01 bila ada, atau ke tenant pertama yang ada
UPDATE ai_configs
SET scope = 'tenant',
    target_id = (SELECT branch_code FROM tenants ORDER BY id LIMIT 1)
WHERE scope = 'global'
  AND id <> (SELECT MIN(id) FROM ai_configs WHERE scope = 'global')
  AND EXISTS (SELECT 1 FROM tenants);

-- 3b. Bila TIDAK ada tenant sama sekali (instalasi fresh), global dobel tidak
--     punya scope valid — dihapus agar unique index dapat dibuat
DELETE FROM ai_configs
WHERE scope = 'global'
  AND id <> (SELECT MIN(id) FROM ai_configs WHERE scope = 'global')
  AND NOT EXISTS (SELECT 1 FROM tenants);

-- 4. Global tunggal dijamin database-level (partial unique index).
--    Urutan penting: statement 2-3 memastikan tersisa 1 global SEBELUM index dibuat.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_configs_global
ON ai_configs (scope) WHERE scope = 'global';
