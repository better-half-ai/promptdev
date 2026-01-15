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
    is_halted: bool = False
    halt_reason: Optional[str] = None
    halted_by: Optional[str] = None
    halted_at: Optional[datetime] = None
    personality_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: tenant_id SQL handling
# ═══════════════════════════════════════════════════════════════════════════


def _tenant_clause(tenant_id: Optional[int]) -> tuple[str, list]:
    """
    Return SQL clause and params for tenant filtering.
    NULL tenant_id = system/test data.
    """
    if tenant_id is None:
        return "tenant_id IS NULL", []
    return "tenant_id = %s", [tenant_id]
    return "tenant_id = %s", [tid]


# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════════════════

def add_message(
    user_id: str,
    role: str,
    content: str,
    tenant_id: Optional[int] = None,
    session_id: Optional[int] = None
) -> int:
    """Add a message to conversation history."""
    if role not in ("user", "assistant"):
        raise InvalidRoleError(f"Invalid role '{role}', must be 'user' or 'assistant'")
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_history (tenant_id, user_id, role, content, session_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, user_id, role, content, session_id)
            )
            message_id = cur.fetchone()[0]
            
            # Update session timestamp if session_id provided
            if session_id:
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s",
                    (session_id,)
                )
            
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
    tenant_id: Optional[int] = None,
    session_id: Optional[int] = None
) -> list[ConversationMessage]:
    """Get conversation history for a user (newest first)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            
            # Filter by session if provided
            session_filter = ""
            if session_id is not None:
                session_filter = "AND session_id = %s"
            
            query = f"""
                SELECT id, user_id, role, content, created_at
                FROM conversation_history
                WHERE {tenant_clause} AND user_id = %s {session_filter}
                ORDER BY created_at DESC
            """
            params = tenant_params + [user_id]
            if session_id is not None:
                params.append(session_id)
            
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT id, user_id, role, content, created_at
                FROM conversation_history
                WHERE {tenant_clause} AND user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tenant_params + [user_id, count]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT COUNT(*) FROM conversation_history WHERE {tenant_clause} AND user_id = %s",
                tenant_params + [user_id]
            )
            return cur.fetchone()[0]
    finally:
        put_conn(conn)


def clear_conversation_history(user_id: str, tenant_id: Optional[int] = None) -> int:
    """Clear all conversation history for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"DELETE FROM conversation_history WHERE {tenant_clause} AND user_id = %s",
                tenant_params + [user_id]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"DELETE FROM conversation_history WHERE id = %s AND {tenant_clause}",
                [message_id] + tenant_params
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
    """Set a memory value for a user (upserts)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_memory (tenant_id, user_id, key, value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (COALESCE(tenant_id, 0), user_id, key) 
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                RETURNING id
                """,
                (tenant_id, user_id, key, json.dumps(value))
            )
            memory_id = cur.fetchone()[0]
            conn.commit()
            return memory_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to set memory: {e}")
    finally:
        put_conn(conn)


def get_memory(user_id: str, key: str, tenant_id: Optional[int] = None) -> Optional[Any]:
    """Get a memory value for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT value FROM user_memory
                WHERE {tenant_clause} AND user_id = %s AND key = %s
                """,
                tenant_params + [user_id, key]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT id, user_id, key, value, updated_at
                FROM user_memory
                WHERE {tenant_clause} AND user_id = %s
                ORDER BY key
                """,
                tenant_params + [user_id]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"DELETE FROM user_memory WHERE {tenant_clause} AND user_id = %s AND key = %s",
                tenant_params + [user_id, key]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"DELETE FROM user_memory WHERE {tenant_clause} AND user_id = %s",
                tenant_params + [user_id]
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
                ON CONFLICT (COALESCE(tenant_id, 0), user_id) 
                DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
                """,
                (tenant_id, user_id, mode)
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT user_id, mode, updated_at, is_halted, halt_reason, halted_by, halted_at, personality_id
                FROM user_state WHERE {tenant_clause} AND user_id = %s
                """,
                tenant_params + [user_id]
            )
            row = cur.fetchone()
            if not row:
                return None
            return UserState(
                user_id=row[0], mode=row[1], updated_at=row[2],
                is_halted=row[3] or False, halt_reason=row[4],
                halted_by=row[5], halted_at=row[6], personality_id=row[7]
            )
    finally:
        put_conn(conn)


def delete_user_state(user_id: str, tenant_id: Optional[int] = None) -> None:
    """Delete user state."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"DELETE FROM user_state WHERE {tenant_clause} AND user_id = %s",
                tenant_params + [user_id]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT user_id, COUNT(*) as msg_count, 
                       MIN(created_at) as first_seen,
                       MAX(created_at) as last_seen
                FROM conversation_history
                WHERE {tenant_clause}
                GROUP BY user_id
                ORDER BY last_seen DESC
                """,
                tenant_params
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
                ON CONFLICT (COALESCE(tenant_id, 0), user_id) 
                DO UPDATE SET is_halted = true, halt_reason = EXCLUDED.halt_reason, 
                              halted_by = EXCLUDED.halted_by, halted_at = NOW(), updated_at = NOW()
                """,
                (tenant_id, user_id, reason, halted_by)
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                UPDATE user_state 
                SET is_halted = false, halt_reason = NULL, halted_by = NULL, halted_at = NULL, updated_at = NOW()
                WHERE {tenant_clause} AND user_id = %s
                """,
                tenant_params + [user_id]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"SELECT is_halted FROM user_state WHERE {tenant_clause} AND user_id = %s",
                tenant_params + [user_id]
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
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT user_id, halt_reason, halted_by, halted_at
                FROM user_state
                WHERE {tenant_clause} AND is_halted = true
                """,
                tenant_params
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


# ═══════════════════════════════════════════════════════════════════════════
# CHAT SESSIONS
# ═══════════════════════════════════════════════════════════════════════════

class ChatSession(BaseModel):
    """A chat session."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: str
    tenant_id: Optional[int] = None
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    archived: bool = False
    sentiment_enabled: bool = False
    message_count: int = 0


def create_session(
    user_id: str,
    tenant_id: Optional[int] = None,
    title: Optional[str] = None,
    sentiment_enabled: bool = False
) -> int:
    """Create a new chat session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Auto-generate title if not provided
            if not title:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM chat_sessions 
                    WHERE user_id = %s AND (tenant_id = %s OR (tenant_id IS NULL AND %s IS NULL))
                    """,
                    (user_id, tenant_id, tenant_id)
                )
                count = cur.fetchone()[0]
                title = f"Chat {count + 1}"
            
            cur.execute(
                """
                INSERT INTO chat_sessions (tenant_id, user_id, title, sentiment_enabled)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, user_id, title, sentiment_enabled)
            )
            session_id = cur.fetchone()[0]
            conn.commit()
            return session_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to create session: {e}")
    finally:
        put_conn(conn)


def get_session(session_id: int, tenant_id: Optional[int] = None) -> Optional[ChatSession]:
    """Get a chat session by ID."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT s.id, s.user_id, s.tenant_id, s.title, s.created_at, s.updated_at, 
                       s.is_active, s.sentiment_enabled,
                       (SELECT COUNT(*) FROM conversation_history WHERE session_id = s.id) as message_count
                FROM chat_sessions s
                WHERE s.id = %s AND ({tenant_clause} OR s.tenant_id IS NULL)
                """,
                [session_id] + tenant_params
            )
            row = cur.fetchone()
            if not row:
                return None
            return ChatSession(
                id=row[0], user_id=row[1], tenant_id=row[2], title=row[3],
                created_at=row[4], updated_at=row[5], is_active=row[6],
                sentiment_enabled=row[7], message_count=row[8]
            )
    finally:
        put_conn(conn)


def list_sessions(
    user_id: str,
    tenant_id: Optional[int] = None,
    include_inactive: bool = False
) -> list[ChatSession]:
    """List all chat sessions for a user."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            active_filter = "" if include_inactive else "AND s.is_active = true AND s.archived = false"
            cur.execute(
                f"""
                SELECT s.id, s.user_id, s.tenant_id, s.title, s.created_at, s.updated_at,
                       s.is_active, s.sentiment_enabled, s.archived,
                       (SELECT COUNT(*) FROM conversation_history WHERE session_id = s.id) as message_count
                FROM chat_sessions s
                WHERE s.user_id = %s AND {tenant_clause} {active_filter}
                ORDER BY s.updated_at DESC
                """,
                [user_id] + tenant_params
            )
            return [
                ChatSession(
                    id=row[0], user_id=row[1], tenant_id=row[2], title=row[3],
                    created_at=row[4], updated_at=row[5], is_active=row[6],
                    sentiment_enabled=row[7], archived=row[8], message_count=row[9]
                )
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)


def update_session(
    session_id: int,
    tenant_id: Optional[int] = None,
    title: Optional[str] = None,
    is_active: Optional[bool] = None,
    sentiment_enabled: Optional[bool] = None,
    archived: Optional[bool] = None,
    metadata: Optional[dict] = None
) -> None:
    """Update a chat session."""
    updates = []
    params = []
    
    if title is not None:
        updates.append("title = %s")
        params.append(title)
    if is_active is not None:
        updates.append("is_active = %s")
        params.append(is_active)
    if sentiment_enabled is not None:
        updates.append("sentiment_enabled = %s")
        params.append(sentiment_enabled)
    if archived is not None:
        updates.append("archived = %s")
        params.append(archived)
    if metadata is not None:
        updates.append("metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb")
        params.append(Json(metadata))
    
    if not updates:
        return
    
    updates.append("updated_at = NOW()")
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                UPDATE chat_sessions 
                SET {', '.join(updates)}
                WHERE id = %s AND {tenant_clause}
                """,
                params + [session_id] + tenant_params
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to update session: {e}")
    finally:
        put_conn(conn)


def delete_session(session_id: int, tenant_id: Optional[int] = None, soft: bool = True) -> None:
    """Delete a chat session (soft delete by default)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            if soft:
                cur.execute(
                    f"UPDATE chat_sessions SET is_active = false, updated_at = NOW() WHERE id = %s AND {tenant_clause}",
                    [session_id] + tenant_params
                )
            else:
                cur.execute(
                    f"DELETE FROM chat_sessions WHERE id = %s AND {tenant_clause}",
                    [session_id] + tenant_params
                )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to delete session: {e}")
    finally:
        put_conn(conn)


def get_or_create_session(user_id: str, tenant_id: Optional[int] = None) -> int:
    """Get the most recent active session for a user, or create one."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tenant_clause, tenant_params = _tenant_clause(tenant_id)
            cur.execute(
                f"""
                SELECT id FROM chat_sessions 
                WHERE user_id = %s AND {tenant_clause} AND is_active = true
                ORDER BY updated_at DESC LIMIT 1
                """,
                [user_id] + tenant_params
            )
            row = cur.fetchone()
            if row:
                return row[0]
    finally:
        put_conn(conn)
    
    # No active session, create one
    return create_session(user_id, tenant_id)


# ═══════════════════════════════════════════════════════════════════════════
# CHAT SHARING
# ═══════════════════════════════════════════════════════════════════════════

def share_session(
    session_id: int,
    shared_by: int,
    shared_with: int,
    permission: str = "read"
) -> int:
    """Share a chat session with another admin."""
    if permission not in ("read", "write", "admin"):
        raise MemoryError(f"Invalid permission: {permission}")
    
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_shares (session_id, shared_by, shared_with, permission)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id, shared_with) 
                DO UPDATE SET permission = EXCLUDED.permission
                RETURNING id
                """,
                (session_id, shared_by, shared_with, permission)
            )
            share_id = cur.fetchone()[0]
            conn.commit()
            return share_id
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to share session: {e}")
    finally:
        put_conn(conn)


def unshare_session(session_id: int, shared_with: int) -> None:
    """Remove sharing for a session."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chat_shares WHERE session_id = %s AND shared_with = %s",
                (session_id, shared_with)
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise MemoryError(f"Failed to unshare session: {e}")
    finally:
        put_conn(conn)


def list_shared_sessions(admin_id: int) -> list[ChatSession]:
    """List sessions shared with an admin."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id, s.user_id, s.tenant_id, s.title, s.created_at, s.updated_at,
                       s.is_active, s.sentiment_enabled,
                       (SELECT COUNT(*) FROM conversation_history WHERE session_id = s.id) as message_count
                FROM chat_sessions s
                JOIN chat_shares cs ON cs.session_id = s.id
                WHERE cs.shared_with = %s AND s.is_active = true
                ORDER BY s.updated_at DESC
                """,
                (admin_id,)
            )
            return [
                ChatSession(
                    id=row[0], user_id=row[1], tenant_id=row[2], title=row[3],
                    created_at=row[4], updated_at=row[5], is_active=row[6],
                    sentiment_enabled=row[7], message_count=row[8]
                )
                for row in cur.fetchall()
            ]
    finally:
        put_conn(conn)

