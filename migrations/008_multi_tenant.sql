-- Migration: Multi-tenant support with admin isolation
-- Date: 2025-01-10
-- Purpose: Add tenant isolation, admin management, and audit logging

-- ============================================================
-- 1. CREATE ADMINS TABLE (tenants)
-- ============================================================
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by INTEGER REFERENCES admins(id),  -- NULL = created by super admin
    last_login TIMESTAMPTZ
);

CREATE INDEX idx_admins_email ON admins(email);
CREATE INDEX idx_admins_active ON admins(is_active) WHERE is_active = true;

-- ============================================================
-- 2. CREATE AUDIT LOG TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id SERIAL PRIMARY KEY,
    admin_id INTEGER REFERENCES admins(id),    -- NULL = super admin action
    admin_email VARCHAR(255) NOT NULL,         -- denormalized for history
    action VARCHAR(50) NOT NULL,               -- login, logout, template_create, user_halt, etc.
    resource_type VARCHAR(50),                 -- template, user, guardrail, admin, file
    resource_id VARCHAR(255),
    details JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_admin ON admin_audit_log(admin_id);
CREATE INDEX idx_audit_action ON admin_audit_log(action);
CREATE INDEX idx_audit_resource ON admin_audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_created ON admin_audit_log(created_at DESC);

-- ============================================================
-- 3. ADD TENANT_ID TO ALL TABLES
-- ============================================================

-- system_prompt: add tenant_id, sharing columns
ALTER TABLE system_prompt 
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id),
    ADD COLUMN IF NOT EXISTS is_shareable BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS cloned_from_id INTEGER REFERENCES system_prompt(id),
    ADD COLUMN IF NOT EXISTS cloned_from_tenant INTEGER REFERENCES admins(id);

-- prompt_version_history: add tenant_id
ALTER TABLE prompt_version_history
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- conversation_history: add tenant_id
ALTER TABLE conversation_history
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- user_memory: add tenant_id
ALTER TABLE user_memory
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- user_state: needs restructure (currently user_id is PK)
-- Drop old primary key and add tenant_id
ALTER TABLE user_state DROP CONSTRAINT IF EXISTS user_state_pkey;
ALTER TABLE user_state
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id),
    ADD COLUMN IF NOT EXISTS is_halted BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS halt_reason TEXT,
    ADD COLUMN IF NOT EXISTS halted_by VARCHAR(255),
    ADD COLUMN IF NOT EXISTS halted_at TIMESTAMPTZ;

-- Add composite primary key (will fail gracefully if constraint exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_state_tenant_user_pk') THEN
        ALTER TABLE user_state ADD CONSTRAINT user_state_tenant_user_pk PRIMARY KEY (tenant_id, user_id);
    END IF;
EXCEPTION WHEN others THEN
    NULL;
END $$;

-- guardrail_configs: add tenant_id
ALTER TABLE guardrail_configs
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- llm_requests: add tenant_id
ALTER TABLE llm_requests
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- user_activity: add tenant_id
ALTER TABLE user_activity
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- metric_snapshots: add tenant_id
ALTER TABLE metric_snapshots
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES admins(id);

-- ============================================================
-- 4. UPDATE UNIQUE CONSTRAINTS TO INCLUDE TENANT_ID
-- ============================================================

-- Drop old unique constraints and recreate with tenant_id
-- system_prompt: name unique per tenant
ALTER TABLE system_prompt DROP CONSTRAINT IF EXISTS system_prompt_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_prompt_tenant_name 
    ON system_prompt(tenant_id, name) WHERE tenant_id IS NOT NULL;

-- guardrail_configs: name unique per tenant
ALTER TABLE guardrail_configs DROP CONSTRAINT IF EXISTS guardrail_configs_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_guardrail_tenant_name 
    ON guardrail_configs(tenant_id, name) WHERE tenant_id IS NOT NULL;

-- user_memory: user_id + key unique per tenant
ALTER TABLE user_memory DROP CONSTRAINT IF EXISTS user_memory_user_id_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_memory_tenant_user_key 
    ON user_memory(tenant_id, user_id, key) WHERE tenant_id IS NOT NULL;

-- user_activity: user_id unique per tenant
ALTER TABLE user_activity DROP CONSTRAINT IF EXISTS user_activity_user_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_activity_tenant_user 
    ON user_activity(tenant_id, user_id) WHERE tenant_id IS NOT NULL;

-- ============================================================
-- 5. CREATE TENANT ISOLATION INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_system_prompt_tenant ON system_prompt(tenant_id);
CREATE INDEX IF NOT EXISTS idx_system_prompt_shareable ON system_prompt(is_shareable) WHERE is_shareable = true;
CREATE INDEX IF NOT EXISTS idx_prompt_version_tenant ON prompt_version_history(tenant_id);
CREATE INDEX IF NOT EXISTS idx_conversation_tenant_user ON conversation_history(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_memory_tenant ON user_memory(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_state_tenant ON user_state(tenant_id);
CREATE INDEX IF NOT EXISTS idx_guardrail_tenant ON guardrail_configs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_llm_requests_tenant ON llm_requests(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_activity_tenant ON user_activity(tenant_id);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_tenant ON metric_snapshots(tenant_id);

-- ============================================================
-- 6. MARK EXISTING SYSTEM GUARDRAILS AS SHARED (no tenant)
-- ============================================================
-- System-level presets remain tenant_id = NULL
-- They are available to all tenants as read-only presets

COMMENT ON TABLE admins IS 'Admin users (tenants) - each admin has isolated data space';
COMMENT ON TABLE admin_audit_log IS 'Audit trail for all admin actions';
COMMENT ON COLUMN system_prompt.tenant_id IS 'Owner tenant - NULL for system templates';
COMMENT ON COLUMN system_prompt.is_shareable IS 'If true, visible in shared template library';
COMMENT ON COLUMN system_prompt.cloned_from_id IS 'Source template if cloned from shared library';
