-- Migration: Fix chat schema
-- admin -> chats -> messages

-- 1. Add owner_id to chat_sessions (links to admin)
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES admins(id);

-- 2. Rename user_id to chat_id for clarity (user_id IS the chat identifier)
-- We'll keep user_id column name but understand it means chat_id

-- 3. Clean up: Delete orphan sessions, keep only real chats
-- First, find which user_ids actually have messages
-- DELETE FROM chat_sessions WHERE user_id NOT IN (SELECT DISTINCT user_id FROM conversation_history);

-- 4. Update existing sessions to link to admin (tenant_id 2 = your admin)
UPDATE chat_sessions SET owner_id = (SELECT id FROM admins WHERE tenant_id = 2 LIMIT 1) WHERE owner_id IS NULL;

-- 5. Create proper chats table if we want clean design
-- For now, we'll use conversation_history.user_id as the chat_id
-- and group messages by user_id

-- 6. View to show chats (grouped by user_id from conversation_history)
CREATE OR REPLACE VIEW v_chats AS
SELECT 
    ch.user_id as chat_id,
    ch.tenant_id,
    COUNT(*) as message_count,
    MAX(ch.created_at) as last_activity,
    MIN(ch.created_at) as created_at
FROM conversation_history ch
GROUP BY ch.user_id, ch.tenant_id;

-- 7. Clean up orphan sessions (sessions with no messages)
DELETE FROM chat_sessions 
WHERE id NOT IN (
    SELECT DISTINCT s.id 
    FROM chat_sessions s 
    INNER JOIN conversation_history ch ON ch.user_id = s.user_id
);

-- 8. For remaining sessions, ensure one session per chat_id (user_id)
-- Keep only the most recent session per user_id
DELETE FROM chat_sessions a
USING chat_sessions b
WHERE a.user_id = b.user_id 
  AND a.id < b.id;
