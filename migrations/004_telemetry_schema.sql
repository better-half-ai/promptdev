-- Telemetry schema for metrics collection and aggregation

-- Raw LLM request events (append-only log)
CREATE TABLE IF NOT EXISTS llm_requests (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    template_name TEXT,
    response_time_ms INTEGER NOT NULL,
    request_tokens INTEGER,
    response_tokens INTEGER,
    total_tokens INTEGER,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_requests_created 
    ON llm_requests (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_requests_user 
    ON llm_requests (user_id, created_at DESC);

-- Aggregated metrics cache (updated periodically)
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id SERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    time_window TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(metric_name, time_window, window_start)
);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_lookup
    ON metric_snapshots (metric_name, time_window, window_start DESC);

-- User activity tracking (lightweight)
CREATE TABLE IF NOT EXISTS user_activity (
    user_id TEXT PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_messages INTEGER NOT NULL DEFAULT 0,
    total_errors INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_user_activity_last_seen
    ON user_activity (last_seen DESC);
