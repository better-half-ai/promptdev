-- End users: belong to a tenant, can chat within that tenant's data
CREATE TABLE IF NOT EXISTS end_users (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    external_id VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    display_name VARCHAR(255),
    password_hash VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    UNIQUE(tenant_id, external_id),
    UNIQUE(tenant_id, email)
);

-- Indexes for end_users
CREATE INDEX IF NOT EXISTS idx_end_users_tenant ON end_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_end_users_email ON end_users(tenant_id, email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_end_users_active ON end_users(tenant_id, is_active) WHERE is_active = true;

-- Record migration
INSERT INTO schema_migrations (version) VALUES ('010') ON CONFLICT DO NOTHING;
