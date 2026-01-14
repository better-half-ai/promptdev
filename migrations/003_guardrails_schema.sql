CREATE TABLE IF NOT EXISTS guardrail_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    rules JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    is_active BOOLEAN DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_guardrail_configs_name ON guardrail_configs(name);
CREATE INDEX IF NOT EXISTS idx_guardrail_configs_active ON guardrail_configs(is_active);

INSERT INTO guardrail_configs (name, description, rules, created_by, is_active) VALUES
('unrestricted', 'No content filtering - full model capabilities', '[]', 'system', true),
('research_safe', 'Academic research mode with source citation requirements', '[{"type": "system_instruction", "content": "Always cite sources and maintain academic rigor."}]', 'system', true),
('clinical', 'Healthcare-appropriate responses with medical disclaimers', '[{"type": "system_instruction", "content": "Include appropriate medical disclaimers and recommend professional consultation."}]', 'system', true)
ON CONFLICT (name) DO NOTHING;
