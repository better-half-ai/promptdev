-- Note: schema_migrations table is created by migrate.py, not in this file

CREATE TABLE IF NOT EXISTS system_prompt (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS prompt_version_history (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, key)
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_hist_user
    ON conversation_history (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_state (
    user_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
