-- Migration: Chat sessions for multi-conversation support
-- Date: 2025-01-14

-- ============================================================
-- 1. CHAT SESSIONS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER REFERENCES admins(id),
    user_id VARCHAR(255) NOT NULL,
    title VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_chat_sessions_tenant_user ON chat_sessions(tenant_id, user_id);
CREATE INDEX idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
CREATE UNIQUE INDEX idx_chat_sessions_tenant_user_unique 
    ON chat_sessions(COALESCE(tenant_id, 0), user_id, id);

-- ============================================================
-- 2. ADD SESSION_ID TO CONVERSATION_HISTORY
-- ============================================================
ALTER TABLE conversation_history 
    ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES chat_sessions(id) ON DELETE CASCADE;

CREATE INDEX idx_conv_hist_session ON conversation_history(session_id);

-- ============================================================
-- 3. CHAT SHARES TABLE (admin collaboration)
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_shares (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    shared_by INTEGER NOT NULL REFERENCES admins(id),
    shared_with INTEGER NOT NULL REFERENCES admins(id),
    permission VARCHAR(20) DEFAULT 'read' CHECK (permission IN ('read', 'write', 'admin')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, shared_with)
);

CREATE INDEX idx_chat_shares_session ON chat_shares(session_id);
CREATE INDEX idx_chat_shares_shared_with ON chat_shares(shared_with);
