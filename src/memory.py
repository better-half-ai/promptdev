"""
Memory management for conversation history and user context.

This module provides:
- Conversation history storage (user/assistant messages)
- User memory (JSONB key-value storage for preferences, context)
- User state management (mode tracking)
- Retrieval with filtering and limits
- Automatic timestamp management

Example:
    >>> # Store conversation
    >>> add_message("user123", "user", "Hello!")
    >>> add_message("user123", "assistant", "Hi there!")
    >>> 
    >>> # Retrieve history
    >>> history = get_conversation_history("user123", limit=10)
    >>> 
    >>> # Store user preferences
    >>> set_memory("user123", "language", {"preference": "en", "proficiency": "native"})
    >>> 
    >>> # Retrieve memory
    >>> lang = get_memory("user123", "language")
"""

import logging
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import json

from db.db import get_conn, put_conn

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ERRORS
# ═══════════════════════════════════════════════════════════════════════════

class MemoryError(Exception):
    """Base exception for memory operations."""
    pass


class MemoryNotFoundError(MemoryError):
    """Memory key does not exist."""
    pass


class InvalidRoleError(MemoryError):
    """Invalid message role (must be 'user' or 'assistant')."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

class ConversationMessage(BaseModel):
    """A message in conversation history."""
    
    id: int
    user_id: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserMemory(BaseModel):
    """A user memory entry (key-value)."""
    
    id: int
    user_id: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)
    value: dict[str, Any]  # JSONB stored as dict
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserState(BaseModel):
    """User state tracking."""
    
    user_id: str = Field(..., min_length=1)
    mode: str = Field(..., min_length=1)
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════════════════

def add_message(
    user_id: str,
    role: str,
    content: str
) -> int:
    """
    Add a message to conversation history.
    
    Args:
        user_id: User identifier
        role: Message role ('user' or 'assistant')
        content: Message content
    
    Returns:
        Message ID
    
    Raises:
        InvalidRoleError: If role is not 'user' or 'assistant'
        MemoryError: If database operation fails
    
    Example:
        >>> msg_id = add_message("user123", "user", "Hello!")
    """
    if role not in ("user", "assistant"):
        raise InvalidRoleError(f"Invalid role '{role}', must be 'user' or 'assistant'")
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_history (user_id, role, content)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (user_id, role, content)
            )
            message_id = cur.fetchone()[0]
            conn.commit()
            logger.debug(f"Added message {message_id} for user {user_id}")
            return message_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to add message: {e}")
    finally:
        put_conn(conn)


def get_conversation_history(
    user_id: str,
    limit: Optional[int] = None,
    offset: int = 0
) -> list[ConversationMessage]:
    """
    Get conversation history for a user.
    
    Args:
        user_id: User identifier
        limit: Maximum number of messages to return (None = all)
        offset: Number of messages to skip (for pagination)
    
    Returns:
        List of messages (newest first)
    
    Example:
        >>> # Get last 10 messages
        >>> history = get_conversation_history("user123", limit=10)
        >>> for msg in history:
        ...     print(f"{msg.role}: {msg.content}")
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if limit is not None:
                cur.execute(
                    """
                    SELECT id, user_id, role, content, created_at
                    FROM conversation_history
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (user_id, limit, offset)
                )
            else:
                cur.execute(
                    """
                    SELECT id, user_id, role, content, created_at
                    FROM conversation_history
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    OFFSET %s
                    """,
                    (user_id, offset)
                )
            
            rows = cur.fetchall()
            return [
                ConversationMessage(
                    id=row[0],
                    user_id=row[1],
                    role=row[2],
                    content=row[3],
                    created_at=row[4]
                )
                for row in rows
            ]
    finally:
        put_conn(conn)


def get_recent_messages(
    user_id: str,
    count: int = 10
) -> list[ConversationMessage]:
    """
    Get recent messages in chronological order (oldest first).
    
    Convenience function for building context - returns messages
    in the order they should appear in prompts.
    
    Args:
        user_id: User identifier
        count: Number of recent messages to retrieve
    
    Returns:
        List of messages (oldest first, ready for prompt)
    
    Example:
        >>> msgs = get_recent_messages("user123", count=5)
        >>> # [oldest, ..., newest] - ready to append to prompt
    """
    messages = get_conversation_history(user_id, limit=count)
    return list(reversed(messages))  # Reverse to get oldest first


def count_messages(user_id: str) -> int:
    """
    Count total messages for a user.
    
    Args:
        user_id: User identifier
    
    Returns:
        Total message count
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM conversation_history WHERE user_id = %s",
                (user_id,)
            )
            return cur.fetchone()[0]
    finally:
        put_conn(conn)


def clear_conversation_history(user_id: str) -> int:
    """
    Clear all conversation history for a user.
    
    Args:
        user_id: User identifier
    
    Returns:
        Number of messages deleted
    
    Example:
        >>> deleted = clear_conversation_history("user123")
        >>> print(f"Deleted {deleted} messages")
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_history WHERE user_id = %s",
                (user_id,)
            )
            deleted = cur.rowcount
            conn.commit()
            logger.info(f"Cleared {deleted} messages for user {user_id}")
            return deleted
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to clear history: {e}")
    finally:
        put_conn(conn)


def delete_message(message_id: int) -> None:
    """
    Delete a specific message.
    
    Args:
        message_id: Message ID to delete
    
    Raises:
        MemoryNotFoundError: If message doesn't exist
        MemoryError: If database operation fails
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_history WHERE id = %s",
                (message_id,)
            )
            if cur.rowcount == 0:
                raise MemoryNotFoundError(f"Message {message_id} not found")
            conn.commit()
            logger.debug(f"Deleted message {message_id}")
    except MemoryNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to delete message: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# USER MEMORY (KEY-VALUE JSONB)
# ═══════════════════════════════════════════════════════════════════════════

def set_memory(
    user_id: str,
    key: str,
    value: dict[str, Any]
) -> int:
    """
    Set or update a user memory entry.
    
    Args:
        user_id: User identifier
        key: Memory key (e.g., 'preferences', 'context', 'profile')
        value: Memory value as dict (stored as JSONB)
    
    Returns:
        Memory entry ID
    
    Raises:
        MemoryError: If database operation fails
    
    Example:
        >>> # Store user preferences
        >>> set_memory("user123", "preferences", {
        ...     "language": "en",
        ...     "theme": "dark",
        ...     "notifications": True
        ... })
        >>> 
        >>> # Store conversation context
        >>> set_memory("user123", "context", {
        ...     "topic": "Python debugging",
        ...     "expertise_level": "intermediate"
        ... })
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Upsert: insert or update if key exists
            cur.execute(
                """
                INSERT INTO user_memory (user_id, key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, key) 
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                RETURNING id
                """,
                (user_id, key, json.dumps(value))
            )
            memory_id = cur.fetchone()[0]
            conn.commit()
            logger.debug(f"Set memory '{key}' for user {user_id}")
            return memory_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to set memory: {e}")
    finally:
        put_conn(conn)


def get_memory(
    user_id: str,
    key: str
) -> Optional[dict[str, Any]]:
    """
    Get a user memory entry.
    
    Args:
        user_id: User identifier
        key: Memory key
    
    Returns:
        Memory value as dict, or None if not found
    
    Example:
        >>> prefs = get_memory("user123", "preferences")
        >>> if prefs:
        ...     print(f"Language: {prefs['language']}")
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM user_memory WHERE user_id = %s AND key = %s",
                (user_id, key)
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        put_conn(conn)


def get_all_memory(user_id: str) -> list[UserMemory]:
    """
    Get all memory entries for a user.
    
    Args:
        user_id: User identifier
    
    Returns:
        List of all user memory entries
    
    Example:
        >>> memories = get_all_memory("user123")
        >>> for mem in memories:
        ...     print(f"{mem.key}: {mem.value}")
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, key, value, updated_at
                FROM user_memory
                WHERE user_id = %s
                ORDER BY key
                """,
                (user_id,)
            )
            rows = cur.fetchall()
            return [
                UserMemory(
                    id=row[0],
                    user_id=row[1],
                    key=row[2],
                    value=row[3],
                    updated_at=row[4]
                )
                for row in rows
            ]
    finally:
        put_conn(conn)


def delete_memory(
    user_id: str,
    key: str
) -> None:
    """
    Delete a user memory entry.
    
    Args:
        user_id: User identifier
        key: Memory key to delete
    
    Raises:
        MemoryNotFoundError: If memory entry doesn't exist
        MemoryError: If database operation fails
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_memory WHERE user_id = %s AND key = %s",
                (user_id, key)
            )
            if cur.rowcount == 0:
                raise MemoryNotFoundError(f"Memory '{key}' not found for user {user_id}")
            conn.commit()
            logger.debug(f"Deleted memory '{key}' for user {user_id}")
    except MemoryNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to delete memory: {e}")
    finally:
        put_conn(conn)


def clear_all_memory(user_id: str) -> int:
    """
    Clear all memory entries for a user.
    
    Args:
        user_id: User identifier
    
    Returns:
        Number of entries deleted
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_memory WHERE user_id = %s",
                (user_id,)
            )
            deleted = cur.rowcount
            conn.commit()
            logger.info(f"Cleared {deleted} memory entries for user {user_id}")
            return deleted
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to clear memory: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# USER STATE
# ═══════════════════════════════════════════════════════════════════════════

def set_user_state(
    user_id: str,
    mode: str
) -> None:
    """
    Set or update user state.
    
    Args:
        user_id: User identifier
        mode: State mode (e.g., 'active', 'paused', 'completed')
    
    Raises:
        MemoryError: If database operation fails
    
    Example:
        >>> set_user_state("user123", "active")
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_state (user_id, mode)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
                """,
                (user_id, mode)
            )
            conn.commit()
            logger.debug(f"Set state '{mode}' for user {user_id}")
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to set user state: {e}")
    finally:
        put_conn(conn)


def get_user_state(user_id: str) -> Optional[UserState]:
    """
    Get user state.
    
    Args:
        user_id: User identifier
    
    Returns:
        UserState object or None if not found
    
    Example:
        >>> state = get_user_state("user123")
        >>> if state:
        ...     print(f"User is in {state.mode} mode")
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, mode, updated_at FROM user_state WHERE user_id = %s",
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                return UserState(
                    user_id=row[0],
                    mode=row[1],
                    updated_at=row[2]
                )
            return None
    finally:
        put_conn(conn)


def delete_user_state(user_id: str) -> None:
    """
    Delete user state.
    
    Args:
        user_id: User identifier
    
    Raises:
        MemoryNotFoundError: If state doesn't exist
        MemoryError: If database operation fails
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_state WHERE user_id = %s",
                (user_id,)
            )
            if cur.rowcount == 0:
                raise MemoryNotFoundError(f"State not found for user {user_id}")
            conn.commit()
            logger.debug(f"Deleted state for user {user_id}")
    except MemoryNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to delete user state: {e}")
    finally:
        put_conn(conn)