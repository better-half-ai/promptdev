"""
Memory management for conversation history and user context.

This module provides:
- Conversation history storage (user/assistant messages)
- User memory (JSONB key-value storage for preferences, context)
- User state management (mode tracking)
- Retrieval with filtering and limits
- Multi-tenant isolation
"""

import logging
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
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
    
    model_config = ConfigDict(from_attributes=True)


class UserMemory(BaseModel):
    """A user memory entry (key-value)."""
    
    id: int
    user_id: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)
    value: dict[str, Any]
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class UserState(BaseModel):
    """User state tracking."""
    
    user_id: str = Field(..., min_length=1)
    mode: str = Field(..., min_length=1)
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: Default tenant_id for SQL
# ═══════════════════════════════════════════════════════════════════════════

def _tid(tenant_id: Optional[int]) -> int:
    """Convert None tenant_id to 0 for SQL operations."""
    return tenant_id if tenant_id is not None else 0


# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════════════════

def add_message(
    user_id: str,
    role: str,
    content: str,
    tenant_id: Optional[int] = None
) -> int:
    """Add a message to conversation history."""
    if role not in ("user", "assistant"):
        raise InvalidRoleError(f"Invalid role '{role}', must be 'user' or 'assistant'")
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_history (tenant_id, user_id, role, content)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (_tid(tenant_id), user_id, role, content)
            )
            message_id = cur.fetchone()[0]
            conn.commit()
            return message_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to add message: {e}")
    finally:
        put_conn(conn)


def get_conversation_history(
    user_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    tenant_id: Optional[int] = None
) -> list[ConversationMessage]:
    """Get conversation history for a user (newest first)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, user_id, role, content, created_at
                FROM conversation_history
                WHERE tenant_id = %s AND user_id = %s
                ORDER BY created_at DESC
            """
            params = [_tid(tenant_id), user_id]
            
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            
            if offset > 0:
                query += " OFFSET %s"
                params.append(offset)
            
            cur.execute(query, params)
            
            return [
                ConversationMessage(
                    id=row[0], user_id=row[1], role=row[2],
                    content=row[3], created_at=row[4]
                )
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def get_recent_messages(
    user_id: str,
    count: int = 10,
    tenant_id: Optional[int] = None
) -> list[ConversationMessage]:
    """Get recent messages in chronological order (oldest first)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, role, content, created_at
                FROM conversation_history
                WHERE tenant_id = %s AND user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (_tid(tenant_id), user_id, count)
            )
            
            messages = [
                ConversationMessage(
                    id=row[0], user_id=row[1], role=row[2],
                    content=row[3], created_at=row[4]
                )
                for row in cur.fetchall()
            ]
            return list(reversed(messages))
    finally:
        put_conn(conn)


def count_messages(user_id: str, tenant_id: Optional[int] = None) -> int:
    """Count messages for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM conversation_history WHERE tenant_id = %s AND user_id = %s",
                (_tid(tenant_id), user_id)
            )
            return cur.fetchone()[0]
    finally:
        put_conn(conn)


def clear_conversation_history(user_id: str, tenant_id: Optional[int] = None) -> int:
    """Clear all conversation history for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_history WHERE tenant_id = %s AND user_id = %s",
                (_tid(tenant_id), user_id)
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to clear history: {e}")
    finally:
        put_conn(conn)


def delete_message(message_id: int, tenant_id: Optional[int] = None) -> None:
    """Delete a specific message."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_history WHERE id = %s AND tenant_id = %s",
                (message_id, _tid(tenant_id))
            )
            if cur.rowcount == 0:
                raise MemoryNotFoundError(f"Message {message_id} not found")
            conn.commit()
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
    value: Any,
    tenant_id: Optional[int] = None
) -> int:
    """Set or update a user memory entry."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_memory (tenant_id, user_id, key, value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, user_id, key) 
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                RETURNING id
                """,
                (_tid(tenant_id), user_id, key, json.dumps(value))
            )
            memory_id = cur.fetchone()[0]
            conn.commit()
            return memory_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to set memory: {e}")
    finally:
        put_conn(conn)


def get_memory(
    user_id: str,
    key: str,
    tenant_id: Optional[int] = None
) -> Optional[Any]:
    """Get a user memory entry."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM user_memory WHERE tenant_id = %s AND user_id = %s AND key = %s",
                (_tid(tenant_id), user_id, key)
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        put_conn(conn)


def get_all_memory(user_id: str, tenant_id: Optional[int] = None) -> list[UserMemory]:
    """Get all memory entries for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, key, value, updated_at
                FROM user_memory
                WHERE tenant_id = %s AND user_id = %s
                ORDER BY key
                """,
                (_tid(tenant_id), user_id)
            )
            return [
                UserMemory(
                    id=row[0], user_id=row[1], key=row[2],
                    value=row[3], updated_at=row[4]
                )
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def delete_memory(user_id: str, key: str, tenant_id: Optional[int] = None) -> None:
    """Delete a user memory entry."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_memory WHERE tenant_id = %s AND user_id = %s AND key = %s",
                (_tid(tenant_id), user_id, key)
            )
            if cur.rowcount == 0:
                raise MemoryNotFoundError(f"Memory '{key}' not found for user {user_id}")
            conn.commit()
    except MemoryNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to delete memory: {e}")
    finally:
        put_conn(conn)


def clear_all_memory(user_id: str, tenant_id: Optional[int] = None) -> int:
    """Clear all memory entries for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_memory WHERE tenant_id = %s AND user_id = %s",
                (_tid(tenant_id), user_id)
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to clear memory: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# USER STATE
# ═══════════════════════════════════════════════════════════════════════════

def set_user_state(user_id: str, mode: str, tenant_id: Optional[int] = None) -> None:
    """Set user state (upserts)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_state (tenant_id, user_id, mode)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id, user_id) 
                DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
                """,
                (_tid(tenant_id), user_id, mode)
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to set state: {e}")
    finally:
        put_conn(conn)


def get_user_state(user_id: str, tenant_id: Optional[int] = None) -> Optional[UserState]:
    """Get user state."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, mode, updated_at FROM user_state WHERE tenant_id = %s AND user_id = %s",
                (_tid(tenant_id), user_id)
            )
            row = cur.fetchone()
            if not row:
                return None
            return UserState(user_id=row[0], mode=row[1], updated_at=row[2])
    finally:
        put_conn(conn)


def delete_user_state(user_id: str, tenant_id: Optional[int] = None) -> None:
    """Delete user state."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_state WHERE tenant_id = %s AND user_id = %s",
                (_tid(tenant_id), user_id)
            )
            if cur.rowcount == 0:
                raise MemoryNotFoundError(f"State for user {user_id} not found")
            conn.commit()
    except MemoryNotFoundError:
        raise
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to delete state: {e}")
    finally:
        put_conn(conn)


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-TENANT EXTENSIONS
# ═══════════════════════════════════════════════════════════════════════════

def list_users(tenant_id: Optional[int] = None) -> list[dict]:
    """List all users with conversation activity."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, COUNT(*) as msg_count, 
                       MIN(created_at) as first_seen,
                       MAX(created_at) as last_seen
                FROM conversation_history
                WHERE tenant_id = %s
                GROUP BY user_id
                ORDER BY last_seen DESC
                """,
                (_tid(tenant_id),)
            )
            
            return [
                {
                    "user_id": row[0],
                    "message_count": row[1],
                    "first_seen": row[2].isoformat() if row[2] else None,
                    "last_seen": row[3].isoformat() if row[3] else None
                }
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def halt_user(user_id: str, reason: str, halted_by: str, tenant_id: Optional[int] = None) -> None:
    """Halt a user's conversation."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_state (tenant_id, user_id, mode, is_halted, halt_reason, halted_by, halted_at)
                VALUES (%s, %s, 'halted', true, %s, %s, NOW())
                ON CONFLICT (tenant_id, user_id) 
                DO UPDATE SET is_halted = true, halt_reason = EXCLUDED.halt_reason, 
                              halted_by = EXCLUDED.halted_by, halted_at = NOW(), updated_at = NOW()
                """,
                (_tid(tenant_id), user_id, reason, halted_by)
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to halt user: {e}")
    finally:
        put_conn(conn)


def resume_user(user_id: str, tenant_id: Optional[int] = None) -> None:
    """Resume a halted user's conversation."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_state 
                SET is_halted = false, halt_reason = NULL, halted_by = NULL, halted_at = NULL, updated_at = NOW()
                WHERE tenant_id = %s AND user_id = %s
                """,
                (_tid(tenant_id), user_id)
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to resume user: {e}")
    finally:
        put_conn(conn)


def is_user_halted(user_id: str, tenant_id: Optional[int] = None) -> bool:
    """Check if user is halted."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_halted FROM user_state WHERE tenant_id = %s AND user_id = %s",
                (_tid(tenant_id), user_id)
            )
            row = cur.fetchone()
            return row[0] if row else False
    finally:
        put_conn(conn)


def list_halted_users(tenant_id: Optional[int] = None) -> list[dict]:
    """List all halted users."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, halt_reason, halted_by, halted_at
                FROM user_state
                WHERE tenant_id = %s AND is_halted = true
                """,
                (_tid(tenant_id),)
            )
            
            return [
                {
                    "user_id": row[0],
                    "halt_reason": row[1],
                    "halted_by": row[2],
                    "halted_at": row[3].isoformat() if row[3] else None
                }
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)
