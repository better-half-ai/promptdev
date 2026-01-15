-- Add archived column to chat_sessions
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT false;

-- Fix sentiment_enabled default
ALTER TABLE chat_sessions ALTER COLUMN sentiment_enabled SET DEFAULT true;
