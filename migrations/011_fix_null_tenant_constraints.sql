-- Migration: Fix constraints to allow NULL tenant_id for system/test data
-- Date: 2025-01-14
--
-- NULL tenant_id = system/test data (FK allows NULL)
-- Only fix: constraints and is_super column

-- ============================================================
-- 1. ADD is_super COLUMN TO ADMINS
-- ============================================================
ALTER TABLE admins ADD COLUMN IF NOT EXISTS is_super BOOLEAN DEFAULT false;

-- ============================================================
-- 2. FIX user_state TABLE
-- ============================================================
-- Drop composite PK from migration 008 (it forces tenant_id NOT NULL)
ALTER TABLE user_state DROP CONSTRAINT IF EXISTS user_state_tenant_user_pk;
ALTER TABLE user_state DROP CONSTRAINT IF EXISTS user_state_pkey;

-- Explicitly allow NULL
DO $$
BEGIN
    ALTER TABLE user_state ALTER COLUMN tenant_id DROP NOT NULL;
EXCEPTION WHEN others THEN NULL;
END $$;

-- Add surrogate primary key
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'user_state' AND column_name = 'id') THEN
        ALTER TABLE user_state ADD COLUMN id SERIAL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint 
                   WHERE conname = 'user_state_pkey' AND conrelid = 'user_state'::regclass) THEN
        ALTER TABLE user_state ADD PRIMARY KEY (id);
    END IF;
EXCEPTION WHEN others THEN NULL;
END $$;

-- Unique index using COALESCE to handle NULL
DROP INDEX IF EXISTS idx_user_state_tenant_user_key;
CREATE UNIQUE INDEX idx_user_state_tenant_user_key 
    ON user_state(COALESCE(tenant_id, 0), user_id);

-- ============================================================
-- 3. FIX user_memory TABLE
-- ============================================================
DROP INDEX IF EXISTS idx_user_memory_tenant_user_key;
ALTER TABLE user_memory DROP CONSTRAINT IF EXISTS user_memory_user_id_key_key;
CREATE UNIQUE INDEX idx_user_memory_tenant_user_key 
    ON user_memory(COALESCE(tenant_id, 0), user_id, key);

-- ============================================================
-- 4. FIX guardrail_configs TABLE
-- ============================================================
DROP INDEX IF EXISTS idx_guardrail_tenant_name;
ALTER TABLE guardrail_configs DROP CONSTRAINT IF EXISTS guardrail_configs_name_key;
CREATE UNIQUE INDEX idx_guardrail_tenant_name 
    ON guardrail_configs(COALESCE(tenant_id, 0), name);
