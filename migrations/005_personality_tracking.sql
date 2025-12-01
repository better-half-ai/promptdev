-- Migration: Add personality tracking to user_state table
-- Date: 2025-11-22
-- Purpose: Track which personality template each user is using

-- Add personality_id column to user_state table
ALTER TABLE user_state 
ADD COLUMN personality_id INTEGER REFERENCES system_prompt(id);

-- Create index for faster lookups
CREATE INDEX idx_user_state_personality ON user_state(personality_id);

-- Optional: Add comment for documentation
COMMENT ON COLUMN user_state.personality_id IS 'References the active system prompt template for this user';
