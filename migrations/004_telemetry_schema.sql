CREATE TABLE IF NOT EXISTS llm_requests (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    template_name VARCHAR(255),
    response_time_ms INTEGER,
    request_tokens INTEGER,
    response_tokens INTEGER,
    total_tokens INTEGER,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_activity (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) UNIQUE NOT NULL,
    total_messages INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(255) NOT NULL,
    time_window VARCHAR(50),
    window_start TIMESTAMPTZ,
    value JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(metric_name, time_window, window_start)
);

CREATE INDEX IF NOT EXISTS idx_llm_requests_user_id ON llm_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_llm_requests_created_at ON llm_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_requests_template ON llm_requests(template_name);
CREATE INDEX IF NOT EXISTS idx_llm_requests_user_time ON llm_requests(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_requests_template_time ON llm_requests(template_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_activity_user_id ON user_activity(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activity_last_seen ON user_activity(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_name ON metric_snapshots(metric_name);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_name_window ON metric_snapshots(metric_name, time_window, window_start DESC);
