-- Migration: Sentiment analysis support
-- Date: 2025-01-14

-- ============================================================
-- 1. ADD SENTIMENT_ENABLED TO CHAT_SESSIONS
-- ============================================================
ALTER TABLE chat_sessions 
    ADD COLUMN IF NOT EXISTS sentiment_enabled BOOLEAN DEFAULT true;

-- ============================================================
-- 2. MESSAGE SENTIMENT TABLE (per-message affect vectors)
-- ============================================================
CREATE TABLE IF NOT EXISTS message_sentiment (
    id SERIAL PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES conversation_history(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES chat_sessions(id) ON DELETE CASCADE,
    
    -- 5-dimensional affect vector (Relational Affect Model)
    valence FLOAT,          -- positive/negative (-1 to 1)
    arousal FLOAT,          -- calm/excited (0 to 1)
    dominance FLOAT,        -- submissive/dominant (0 to 1)
    trust FLOAT,            -- distrust/trust (0 to 1)
    engagement FLOAT,       -- disengaged/engaged (0 to 1)
    
    -- Composite scores
    overall_sentiment FLOAT,  -- weighted composite (-1 to 1)
    confidence FLOAT,         -- model confidence (0 to 1)
    
    -- Raw model output
    raw_output JSONB,
    model_version VARCHAR(50),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(message_id)
);

CREATE INDEX idx_message_sentiment_session ON message_sentiment(session_id);
CREATE INDEX idx_message_sentiment_created ON message_sentiment(created_at DESC);

-- ============================================================
-- 3. SENTIMENT AGGREGATES (per-session trends)
-- ============================================================
CREATE TABLE IF NOT EXISTS sentiment_aggregates (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    window_start TIMESTAMPTZ NOT NULL,
    window_type VARCHAR(20) NOT NULL CHECK (window_type IN ('hourly', 'daily', 'session')),
    
    -- Aggregated vectors
    avg_valence FLOAT,
    avg_arousal FLOAT,
    avg_dominance FLOAT,
    avg_trust FLOAT,
    avg_engagement FLOAT,
    
    -- Trends
    valence_trend FLOAT,    -- slope over window
    engagement_trend FLOAT,
    
    message_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(session_id, window_type, window_start)
);

CREATE INDEX idx_sentiment_agg_session ON sentiment_aggregates(session_id);
