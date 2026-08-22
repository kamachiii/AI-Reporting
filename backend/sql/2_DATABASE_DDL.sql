-- 1. HAPUS SEMUA TABEL (CASCADE akan menghapus relasi FK)
DROP TABLE IF EXISTS 
    companies,
    users,
    branches,
    user_branches,
    tenants,
    audit_logs,
    conversations,
    messages,
    ai_configs
CASCADE;

-- 2. BUAT ULANG TABEL DARI AWAL (9 Tabel Sesuai 2_DATABASE_DDL.sql + kolom baru)
CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_role CHECK (role IN ('admin', 'user'))
);

CREATE TABLE branches (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    company_code VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_branches_company FOREIGN KEY (company_code) REFERENCES companies(code) ON DELETE RESTRICT
);

CREATE TABLE user_branches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    branches_code VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ub_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ub_branches FOREIGN KEY (branches_code) REFERENCES branches(code) ON DELETE CASCADE,
    CONSTRAINT unique_user_branch UNIQUE (user_id, branches_code)
);

CREATE TABLE tenants (
    id SERIAL PRIMARY KEY,
    branch_code VARCHAR(50) UNIQUE NOT NULL,
    db_host VARCHAR(255) NOT NULL,
    db_port INTEGER NOT NULL DEFAULT 5432,
    db_name VARCHAR(100) NOT NULL,
    db_username VARCHAR(100) NOT NULL,
    db_password TEXT NOT NULL,
    schema_config_json JSONB,
    daily_token_quota INTEGER DEFAULT 50000,
    tokens_used_today INTEGER DEFAULT 0,
    last_quota_reset DATE DEFAULT CURRENT_DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tenants_branches FOREIGN KEY (branch_code) REFERENCES branches(code) ON DELETE RESTRICT
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    branch_code VARCHAR(50) NOT NULL,
    prompt_text TEXT,
    ai_json_filter JSONB,
    generated_sql TEXT,
    execution_time_ms INTEGER,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    branch_code VARCHAR(50) NOT NULL,
    title VARCHAR(255),
    summary_json JSONB,
    summary_generated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_conv_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_msgs_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE ai_configs (
    id SERIAL PRIMARY KEY,
    scope VARCHAR(20) NOT NULL DEFAULT 'global',
    target_id VARCHAR(100),
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    api_key TEXT,
    temperature FLOAT DEFAULT 0.7,
    api_type VARCHAR(20) DEFAULT 'openai',
    base_url VARCHAR(255) NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_scope_target UNIQUE (scope, target_id)
);

-- 3. KELUAR DARI PSQL
\q