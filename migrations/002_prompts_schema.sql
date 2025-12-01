-- Migration for prompts.py module
-- Drops old tables and creates new schema

-- Drop old tables if they exist
DROP TABLE IF EXISTS prompt_version_history CASCADE;
DROP TABLE IF EXISTS system_prompt CASCADE;

-- Create system_prompt table
CREATE TABLE system_prompt (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    content TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT true
);

-- Create prompt_version_history table
CREATE TABLE prompt_version_history (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES system_prompt(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),
    change_description TEXT,
    UNIQUE(template_id, version)
);

-- Create indexes
CREATE INDEX idx_system_prompt_name ON system_prompt(name);
CREATE INDEX idx_system_prompt_active ON system_prompt(is_active);
CREATE INDEX idx_prompt_version_template ON prompt_version_history(template_id, version DESC);
