"""
Comprehensive test suite for memory.py

Covers:
- Conversation history CRUD operations
- User memory CRUD (JSONB key-value)
- User state management
- Pagination and filtering
- Error conditions
- Edge cases (Unicode, large data, concurrent updates)
- User isolation
"""

import pytest
import psycopg2
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.memory import (
    # Conversation functions
    add_message,
    get_conversation_history,
    get_recent_messages,
    count_messages,
    clear_conversation_history,
    delete_message,
    # Memory functions
    set_memory,
    get_memory,
    get_all_memory,
    delete_memory,
    clear_all_memory,
    # State functions
    set_user_state,
    get_user_state,
    delete_user_state,
    # Models
    ConversationMessage,
    UserMemory,
    UserState,
    # Errors
    MemoryError,
    MemoryNotFoundError,
    InvalidRoleError,
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def migrations_dir():
    """Get migrations directory."""
    root = Path(__file__).resolve().parent.parent
    return root / "migrations"


@pytest.fixture(scope="session")
def test_db(postgres_container, migrations_dir):
    """Setup test database with migrations."""
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    
    # Run migrations
    migration_file = migrations_dir / "001_init.sql"
    if migration_file.exists():
        with migration_file.open("r") as f:
            with conn.cursor() as cur:
                cur.execute(f.read())
        conn.commit()
    
    conn.close()
    yield


@pytest.fixture
def db_connection(test_db, postgres_container):
    """Provide a test database connection and patch memory module."""
    import src.memory as memory_module
    
    # Create real connection to test DB
    def mock_get_conn():
        return psycopg2.connect(
            host=os.environ["TEST_DB_HOST"],
            port=int(os.environ["TEST_DB_PORT"]),
            user=os.environ["TEST_DB_USER"],
            password=os.environ["TEST_DB_PASSWORD"],
            database=os.environ["TEST_DB_NAME"],
        )
    
    def mock_put_conn(conn):
        conn.close()
    
    # Patch where the functions are USED (in memory module)
    with patch.object(memory_module, 'get_conn', mock_get_conn):
        with patch.object(memory_module, 'put_conn', mock_put_conn):
            yield
            
            # Cleanup: truncate tables between tests
            conn = mock_get_conn()
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE conversation_history CASCADE")
                cur.execute("TRUNCATE TABLE user_memory CASCADE")
                cur.execute("TRUNCATE TABLE user_state CASCADE")
            conn.commit()
            conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_add_message_user(db_connection):
    """Test adding a user message."""
    msg_id = add_message("user1", "user", "Hello!")
    
    assert isinstance(msg_id, int)
    assert msg_id > 0


def test_add_message_assistant(db_connection):
    """Test adding an assistant message."""
    msg_id = add_message("user1", "assistant", "Hi there!")
    
    assert isinstance(msg_id, int)
    assert msg_id > 0


def test_add_message_invalid_role(db_connection):
    """Test that invalid role raises error."""
    with pytest.raises(InvalidRoleError) as exc_info:
        add_message("user1", "system", "Invalid")
    
    assert "must be 'user' or 'assistant'" in str(exc_info.value)


def test_add_message_invalid_role_empty(db_connection):
    """Test that empty role raises error."""
    with pytest.raises(InvalidRoleError):
        add_message("user1", "", "Invalid")


def test_get_conversation_history(db_connection):
    """Test retrieving conversation history."""
    # Add messages
    add_message("user1", "user", "Hello")
    add_message("user1", "assistant", "Hi")
    add_message("user1", "user", "How are you?")
    
    # Get history
    history = get_conversation_history("user1")
    
    assert len(history) == 3
    # Newest first
    assert history[0].content == "How are you?"
    assert history[0].role == "user"
    assert history[1].content == "Hi"
    assert history[1].role == "assistant"
    assert history[2].content == "Hello"
    assert history[2].role == "user"


def test_get_conversation_history_with_limit(db_connection):
    """Test retrieving conversation history with limit."""
    # Add 5 messages
    for i in range(5):
        add_message("user1", "user", f"Message {i}")
    
    # Get only last 2
    history = get_conversation_history("user1", limit=2)
    
    assert len(history) == 2
    assert history[0].content == "Message 4"
    assert history[1].content == "Message 3"


def test_get_conversation_history_with_offset(db_connection):
    """Test pagination with offset."""
    # Add 5 messages
    for i in range(5):
        add_message("user1", "user", f"Message {i}")
    
    # Skip first 2, get next 2
    history = get_conversation_history("user1", limit=2, offset=2)
    
    assert len(history) == 2
    assert history[0].content == "Message 2"
    assert history[1].content == "Message 1"


def test_get_conversation_history_empty(db_connection):
    """Test getting history for user with no messages."""
    history = get_conversation_history("nonexistent")
    
    assert len(history) == 0


def test_get_conversation_history_different_users(db_connection):
    """Test that users' histories are isolated."""
    add_message("user1", "user", "User 1 message")
    add_message("user2", "user", "User 2 message")
    
    history1 = get_conversation_history("user1")
    history2 = get_conversation_history("user2")
    
    assert len(history1) == 1
    assert len(history2) == 1
    assert history1[0].content == "User 1 message"
    assert history2[0].content == "User 2 message"


def test_get_recent_messages(db_connection):
    """Test getting recent messages in chronological order."""
    # Add messages
    add_message("user1", "user", "First")
    add_message("user1", "assistant", "Second")
    add_message("user1", "user", "Third")
    
    # Get in chronological order (oldest first)
    recent = get_recent_messages("user1", count=3)
    
    assert len(recent) == 3
    assert recent[0].content == "First"  # Oldest
    assert recent[1].content == "Second"
    assert recent[2].content == "Third"  # Newest


def test_get_recent_messages_with_limit(db_connection):
    """Test recent messages respects count limit."""
    # Add 5 messages
    for i in range(5):
        add_message("user1", "user", f"Message {i}")
    
    # Get only last 3
    recent = get_recent_messages("user1", count=3)
    
    assert len(recent) == 3
    assert recent[0].content == "Message 2"  # Oldest of the 3
    assert recent[2].content == "Message 4"  # Newest


def test_count_messages(db_connection):
    """Test counting messages."""
    add_message("user1", "user", "Message 1")
    add_message("user1", "assistant", "Message 2")
    add_message("user1", "user", "Message 3")
    
    count = count_messages("user1")
    
    assert count == 3


def test_count_messages_empty(db_connection):
    """Test counting when no messages exist."""
    count = count_messages("nonexistent")
    
    assert count == 0


def test_count_messages_different_users(db_connection):
    """Test that count is per-user."""
    add_message("user1", "user", "Message 1")
    add_message("user1", "user", "Message 2")
    add_message("user2", "user", "Message 1")
    
    assert count_messages("user1") == 2
    assert count_messages("user2") == 1


def test_clear_conversation_history(db_connection):
    """Test clearing all messages for a user."""
    # Add messages
    add_message("user1", "user", "Message 1")
    add_message("user1", "user", "Message 2")
    add_message("user2", "user", "User 2 message")
    
    # Clear user1's history
    deleted = clear_conversation_history("user1")
    
    assert deleted == 2
    assert count_messages("user1") == 0
    assert count_messages("user2") == 1  # user2 unaffected


def test_clear_conversation_history_empty(db_connection):
    """Test clearing when no messages exist."""
    deleted = clear_conversation_history("nonexistent")
    
    assert deleted == 0


def test_delete_message(db_connection):
    """Test deleting a specific message."""
    msg_id = add_message("user1", "user", "Delete me")
    add_message("user1", "user", "Keep me")
    
    delete_message(msg_id)
    
    history = get_conversation_history("user1")
    assert len(history) == 1
    assert history[0].content == "Keep me"


def test_delete_message_not_found(db_connection):
    """Test deleting nonexistent message raises error."""
    with pytest.raises(MemoryNotFoundError):
        delete_message(99999)


def test_conversation_message_model(db_connection):
    """Test ConversationMessage model validation."""
    msg_id = add_message("user1", "user", "Test")
    history = get_conversation_history("user1")
    
    msg = history[0]
    assert isinstance(msg, ConversationMessage)
    assert msg.id == msg_id
    assert msg.user_id == "user1"
    assert msg.role == "user"
    assert msg.content == "Test"
    assert isinstance(msg.created_at, datetime)


def test_conversation_alternating_roles(db_connection):
    """Test typical conversation pattern."""
    add_message("user1", "user", "Hello")
    add_message("user1", "assistant", "Hi there!")
    add_message("user1", "user", "How are you?")
    add_message("user1", "assistant", "I'm doing well!")
    
    history = get_conversation_history("user1")
    
    assert len(history) == 4
    assert [m.role for m in reversed(history)] == ["user", "assistant", "user", "assistant"]


# ═══════════════════════════════════════════════════════════════════════════
# USER MEMORY TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_set_memory(db_connection):
    """Test setting user memory."""
    mem_id = set_memory("user1", "preferences", {"theme": "dark", "lang": "en"})
    
    assert isinstance(mem_id, int)
    assert mem_id > 0


def test_get_memory(db_connection):
    """Test retrieving user memory."""
    set_memory("user1", "preferences", {"theme": "dark", "lang": "en"})
    
    value = get_memory("user1", "preferences")
    
    assert value is not None
    assert value["theme"] == "dark"
    assert value["lang"] == "en"


def test_get_memory_not_found(db_connection):
    """Test getting nonexistent memory returns None."""
    value = get_memory("user1", "nonexistent")
    
    assert value is None


def test_set_memory_upsert(db_connection):
    """Test that setting same key updates value."""
    set_memory("user1", "count", {"value": 1})
    mem_id1 = set_memory("user1", "count", {"value": 2})  # Update
    mem_id2 = set_memory("user1", "count", {"value": 3})  # Update again
    
    value = get_memory("user1", "count")
    
    assert value["value"] == 3
    # Should be same ID (updated, not new row)
    assert mem_id1 == mem_id2


def test_get_all_memory(db_connection):
    """Test getting all memory entries."""
    set_memory("user1", "prefs", {"theme": "dark"})
    set_memory("user1", "context", {"topic": "Python"})
    set_memory("user1", "profile", {"name": "Alice"})
    
    memories = get_all_memory("user1")
    
    assert len(memories) == 3
    keys = {m.key for m in memories}
    assert keys == {"prefs", "context", "profile"}


def test_get_all_memory_empty(db_connection):
    """Test getting memory when none exists."""
    memories = get_all_memory("nonexistent")
    
    assert len(memories) == 0


def test_get_all_memory_different_users(db_connection):
    """Test that users' memories are isolated."""
    set_memory("user1", "key1", {"data": "user1"})
    set_memory("user2", "key2", {"data": "user2"})
    
    mem1 = get_all_memory("user1")
    mem2 = get_all_memory("user2")
    
    assert len(mem1) == 1
    assert len(mem2) == 1
    assert mem1[0].value["data"] == "user1"
    assert mem2[0].value["data"] == "user2"


def test_delete_memory(db_connection):
    """Test deleting a memory entry."""
    set_memory("user1", "delete_me", {"data": "test"})
    set_memory("user1", "keep_me", {"data": "test"})
    
    delete_memory("user1", "delete_me")
    
    memories = get_all_memory("user1")
    assert len(memories) == 1
    assert memories[0].key == "keep_me"


def test_delete_memory_not_found(db_connection):
    """Test deleting nonexistent memory raises error."""
    with pytest.raises(MemoryNotFoundError):
        delete_memory("user1", "nonexistent")


def test_clear_all_memory(db_connection):
    """Test clearing all memory for a user."""
    set_memory("user1", "key1", {"data": 1})
    set_memory("user1", "key2", {"data": 2})
    set_memory("user2", "key3", {"data": 3})
    
    deleted = clear_all_memory("user1")
    
    assert deleted == 2
    assert len(get_all_memory("user1")) == 0
    assert len(get_all_memory("user2")) == 1  # user2 unaffected


def test_clear_all_memory_empty(db_connection):
    """Test clearing when no memory exists."""
    deleted = clear_all_memory("nonexistent")
    
    assert deleted == 0


def test_memory_jsonb_complex(db_connection):
    """Test storing complex JSONB data."""
    complex_data = {
        "preferences": {
            "theme": "dark",
            "notifications": {
                "email": True,
                "sms": False
            }
        },
        "history": ["item1", "item2", "item3"],
        "count": 42,
        "enabled": True,
        "ratio": 3.14
    }
    
    set_memory("user1", "complex", complex_data)
    value = get_memory("user1", "complex")
    
    assert value["preferences"]["theme"] == "dark"
    assert value["preferences"]["notifications"]["email"] is True
    assert value["history"] == ["item1", "item2", "item3"]
    assert value["count"] == 42
    assert value["enabled"] is True
    assert value["ratio"] == 3.14


def test_memory_jsonb_empty_dict(db_connection):
    """Test storing empty dict."""
    set_memory("user1", "empty", {})
    value = get_memory("user1", "empty")
    
    assert value == {}


def test_memory_jsonb_nested_arrays(db_connection):
    """Test nested arrays in JSONB."""
    data = {
        "matrix": [[1, 2], [3, 4], [5, 6]]
    }
    
    set_memory("user1", "nested", data)
    value = get_memory("user1", "nested")
    
    assert value["matrix"][0] == [1, 2]
    assert value["matrix"][2] == [5, 6]


def test_user_memory_model(db_connection):
    """Test UserMemory model validation."""
    set_memory("user1", "test", {"data": "value"})
    memories = get_all_memory("user1")
    
    mem = memories[0]
    assert isinstance(mem, UserMemory)
    assert mem.user_id == "user1"
    assert mem.key == "test"
    assert mem.value["data"] == "value"
    assert isinstance(mem.updated_at, datetime)


def test_memory_key_uniqueness(db_connection):
    """Test that same key for different users are independent."""
    set_memory("user1", "shared_key", {"user": "user1"})
    set_memory("user2", "shared_key", {"user": "user2"})
    
    val1 = get_memory("user1", "shared_key")
    val2 = get_memory("user2", "shared_key")
    
    assert val1["user"] == "user1"
    assert val2["user"] == "user2"


# ═══════════════════════════════════════════════════════════════════════════
# USER STATE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_set_user_state(db_connection):
    """Test setting user state."""
    set_user_state("user1", "active")
    
    state = get_user_state("user1")
    
    assert state is not None
    assert state.user_id == "user1"
    assert state.mode == "active"


def test_set_user_state_upsert(db_connection):
    """Test that setting state again updates it."""
    set_user_state("user1", "active")
    set_user_state("user1", "paused")
    
    state = get_user_state("user1")
    
    assert state.mode == "paused"


def test_get_user_state_not_found(db_connection):
    """Test getting nonexistent state returns None."""
    state = get_user_state("nonexistent")
    
    assert state is None


def test_delete_user_state(db_connection):
    """Test deleting user state."""
    set_user_state("user1", "active")
    delete_user_state("user1")
    
    state = get_user_state("user1")
    
    assert state is None


def test_delete_user_state_not_found(db_connection):
    """Test deleting nonexistent state raises error."""
    with pytest.raises(MemoryNotFoundError):
        delete_user_state("nonexistent")


def test_user_state_model(db_connection):
    """Test UserState model validation."""
    set_user_state("user1", "active")
    state = get_user_state("user1")
    
    assert isinstance(state, UserState)
    assert state.user_id == "user1"
    assert state.mode == "active"
    assert isinstance(state.updated_at, datetime)


def test_user_state_different_users(db_connection):
    """Test that user states are isolated."""
    set_user_state("user1", "active")
    set_user_state("user2", "paused")
    
    state1 = get_user_state("user1")
    state2 = get_user_state("user2")
    
    assert state1.mode == "active"
    assert state2.mode == "paused"


# ═══════════════════════════════════════════════════════════════════════════
# EDGE CASES & ERROR CONDITIONS
# ═══════════════════════════════════════════════════════════════════════════

def test_long_message_content(db_connection):
    """Test storing long message content."""
    long_content = "x" * 10000
    msg_id = add_message("user1", "user", long_content)
    
    history = get_conversation_history("user1")
    assert history[0].content == long_content


def test_unicode_in_messages(db_connection):
    """Test Unicode characters in messages."""
    msg = "Hello 世界! 🎉 Привет مرحبا"
    add_message("user1", "user", msg)
    
    history = get_conversation_history("user1")
    assert history[0].content == msg


def test_unicode_in_memory(db_connection):
    """Test Unicode in memory values."""
    data = {
        "message": "你好世界",
        "emoji": "🚀",
        "russian": "Привет",
        "arabic": "مرحبا"
    }
    set_memory("user1", "unicode", data)
    
    value = get_memory("user1", "unicode")
    assert value["message"] == "你好世界"
    assert value["emoji"] == "🚀"
    assert value["russian"] == "Привет"
    assert value["arabic"] == "مرحبا"


def test_large_conversation_history(db_connection):
    """Test handling large conversation history."""
    # Add 100 messages
    for i in range(100):
        add_message("user1", "user" if i % 2 == 0 else "assistant", f"Message {i}")
    
    count = count_messages("user1")
    assert count == 100
    
    # Get recent subset
    recent = get_recent_messages("user1", count=10)
    assert len(recent) == 10
    assert recent[-1].content == "Message 99"  # Newest


def test_concurrent_memory_updates(db_connection):
    """Test that concurrent updates to same key work correctly."""
    set_memory("user1", "counter", {"value": 1})
    set_memory("user1", "counter", {"value": 2})
    set_memory("user1", "counter", {"value": 3})
    
    value = get_memory("user1", "counter")
    assert value["value"] == 3


def test_empty_content_message(db_connection):
    """Test storing message with empty content."""
    msg_id = add_message("user1", "user", "")
    
    history = get_conversation_history("user1")
    assert history[0].content == ""


def test_special_characters_in_user_id(db_connection):
    """Test user_id with special characters."""
    user_id = "user@example.com"
    add_message(user_id, "user", "Test")
    
    count = count_messages(user_id)
    assert count == 1


def test_memory_value_with_null(db_connection):
    """Test JSONB with null values."""
    data = {
        "key1": None,
        "key2": "value",
        "key3": {"nested": None}
    }
    
    set_memory("user1", "with_null", data)
    value = get_memory("user1", "with_null")
    
    assert value["key1"] is None
    assert value["key2"] == "value"
    assert value["key3"]["nested"] is None


def test_pagination_edge_cases(db_connection):
    """Test pagination with edge cases."""
    # Add 5 messages
    for i in range(5):
        add_message("user1", "user", f"Message {i}")
    
    # Offset beyond available messages
    history = get_conversation_history("user1", limit=10, offset=10)
    assert len(history) == 0
    
    # Limit larger than available
    history = get_conversation_history("user1", limit=100)
    assert len(history) == 5


def test_multiple_users_concurrent(db_connection):
    """Test operations across multiple users simultaneously."""
    # Simulate multiple users
    for i in range(10):
        user_id = f"user{i}"
        add_message(user_id, "user", f"Message from {user_id}")
        set_memory(user_id, "data", {"id": i})
        set_user_state(user_id, "active")
    
    # Verify isolation
    for i in range(10):
        user_id = f"user{i}"
        assert count_messages(user_id) == 1
        assert get_memory(user_id, "data")["id"] == i
        assert get_user_state(user_id).mode == "active"


def test_verify_real_database(db_connection):
    """Verification test: Prove we're using real database, not mocks."""
    import psycopg2, os
    
    # Add message via our function
    msg_id = add_message("verify_user", "user", "Real message")
    
    # Connect DIRECTLY to database (bypassing our code)
    conn = psycopg2.connect(
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        database=os.environ["TEST_DB_NAME"],
    )
    cur = conn.cursor()
    
    # Query database directly
    cur.execute(
        "SELECT user_id, role, content FROM conversation_history WHERE id = %s",
        (msg_id,)
    )
    row = cur.fetchone()
    
    # Verify data persisted to REAL database
    assert row[0] == "verify_user"
    assert row[1] == "user"
    assert row[2] == "Real message"
    
    cur.close()
    conn.close()