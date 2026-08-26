-- 003: Registry Database (db_connections). Satu cabang = satu database,
-- satu database boleh dipakai banyak cabang. Data lama dimigrasi otomatis.

CREATE TABLE IF NOT EXISTS db_connections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    db_host VARCHAR(255) NOT NULL,
    db_port INTEGER NOT NULL DEFAULT 5432,
    db_name VARCHAR(100) NOT NULL,
    db_username VARCHAR(100) NOT NULL,
    db_password TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 1. Registrasi kombinasi kredensial unik yang sudah ada di tenants
INSERT INTO db_connections (name, db_host, db_port, db_name, db_username, db_password)
SELECT DISTINCT ON (db_host, db_port, db_name, db_username, db_password)
       COALESCE(db_name, 'koneksi-' || ROW_NUMBER() OVER ()) AS name,
       db_host, db_port, db_name, db_username, db_password
FROM tenants
ON CONFLICT (name) DO NOTHING;

-- 2. Tambah kolom penunjuk ke registry
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS db_connection_id INTEGER;

-- 3. Hubungkan baris lama ke entri registry yang cocok
UPDATE tenants t
SET db_connection_id = dc.id
FROM db_connections dc
WHERE dc.db_host = t.db_host
  AND dc.db_port = t.db_port
  AND dc.db_name = t.db_name
  AND dc.db_username = t.db_username
  AND dc.db_password = t.db_password;

-- 4. Wajib punya penunjuk (semua baris lama harus sudah terpetakan)
ALTER TABLE tenants ALTER COLUMN db_connection_id SET NOT NULL;

-- 5. Kredensial tidak lagi tersimpan duplikat per-cabang
ALTER TABLE tenants DROP COLUMN IF EXISTS db_host;
ALTER TABLE tenants DROP COLUMN IF EXISTS db_port;
ALTER TABLE tenants DROP COLUMN IF EXISTS db_name;
ALTER TABLE tenants DROP COLUMN IF EXISTS db_username;
ALTER TABLE tenants DROP COLUMN IF EXISTS db_password;
