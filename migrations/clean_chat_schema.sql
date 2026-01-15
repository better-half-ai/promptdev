-- Migration: Simplify to admin -> chats -> messages
-- Run this to clean up the database

-- Step 1: See current state
-- SELECT user_id, COUNT(*) as msgs FROM conversation_history GROUP BY user_id;
-- SELECT id, user_id, title FROM chat_sessions;

-- Step 2: Delete all chat_sessions (we'll recreate from actual messages)
DELETE FROM chat_sessions;

-- Step 3: Create one session per actual chat (user_id in conversation_history)
INSERT INTO chat_sessions (tenant_id, user_id, title, created_at, updated_at, is_active)
SELECT 
    tenant_id,
    user_id,
    'Chat ' || ROW_NUMBER() OVER (ORDER BY MIN(created_at)),
    MIN(created_at),
    MAX(created_at),
    true
FROM conversation_history
GROUP BY tenant_id, user_id;

-- Step 4: Link messages to their sessions
UPDATE conversation_history ch
SET session_id = (
    SELECT s.id FROM chat_sessions s 
    WHERE s.user_id = ch.user_id 
    LIMIT 1
)
WHERE session_id IS NULL;

-- Step 5: Verify
-- SELECT * FROM chat_sessions;
-- SELECT session_id, COUNT(*) FROM conversation_history GROUP BY session_id;
