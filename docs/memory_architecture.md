# memory.py Architecture Documentation

## Overview

The memory module provides conversation history storage, user context management, and state tracking for the PromptDev system. It manages three independent storage areas in PostgreSQL, all keyed by `user_id`.

---

## System Architecture

```
memory.py Architecture
======================

┌─────────────────────────────────────────────────────────────┐
│                         memory.py                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  CONVERSATION HISTORY          USER MEMORY          STATE   │
│  ────────────────────         ───────────────       ─────   │
│                                                              │
│  add_message()                 set_memory()         set_    │
│  get_history()                 get_memory()         get_    │
│  get_recent()                  get_all()            delete_ │
│  count/clear/delete            delete/clear                 │
│                                                              │
│  Role: user|assistant          Key-Value JSONB      Mode    │
│  Pagination support            Nested data OK       String  │
│  Newest-first / Oldest-first   Auto-upsert          Upsert  │
│                                                              │
└──────────────┬────────────────────┬──────────────────┬──────┘
               │                    │                  │
               ▼                    ▼                  ▼
         ┌──────────┐         ┌──────────┐      ┌──────────┐
         │ conv_    │         │ user_    │      │ user_    │
         │ history  │         │ memory   │      │ state    │
         │          │         │          │      │          │
         │ id       │         │ id       │      │ user_id  │
         │ user_id  │         │ user_id  │      │ mode     │
         │ role     │         │ key      │      │ updated  │
         │ content  │         │ value    │      └──────────┘
         │ created  │         │ updated  │
         └──────────┘         └──────────┘
              ↓                     ↓                  ↓
         PostgreSQL          PostgreSQL           PostgreSQL
```

---

## Component Details

### 1. Conversation History

**Purpose:** Store chronological message exchanges between user and assistant.

**Functions:**
- `add_message(user_id, role, content)` → message_id
- `get_conversation_history(user_id, limit, offset)` → List[ConversationMessage]
- `get_recent_messages(user_id, count)` → List[ConversationMessage]
- `count_messages(user_id)` → int
- `clear_conversation_history(user_id)` → deleted_count
- `delete_message(message_id)` → None

**Features:**
- Role validation: Only `"user"` or `"assistant"` allowed
- Pagination support via limit/offset
- Two retrieval modes:
  - `get_conversation_history()`: Newest first (for display)
  - `get_recent_messages()`: Oldest first (for prompt context)
- User isolation: Each user's history is separate

**Database Schema:**
```sql
conversation_history (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

**Example Usage:**
```python
from src.memory import add_message, get_recent_messages

# Store conversation
add_message("user123", "user", "What is Python?")
add_message("user123", "assistant", "Python is a programming language...")

# Get last 10 messages for prompt (oldest first)
history = get_recent_messages("user123", count=10)
for msg in history:
    print(f"{msg.role}: {msg.content}")
```

---

### 2. User Memory (JSONB Key-Value)

**Purpose:** Store flexible user context, preferences, and metadata.

**Functions:**
- `set_memory(user_id, key, value: dict)` → memory_id
- `get_memory(user_id, key)` → dict | None
- `get_all_memory(user_id)` → List[UserMemory]
- `delete_memory(user_id, key)` → None
- `clear_all_memory(user_id)` → deleted_count

**Features:**
- JSONB storage: Supports complex nested data structures
- Automatic upsert: `ON CONFLICT (user_id, key) DO UPDATE`
- No schema required: Store any dict structure
- Unique constraint: (user_id, key) pair must be unique

**Database Schema:**
```sql
user_memory (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, key)
)
```

**Example Usage:**
```python
from src.memory import set_memory, get_memory

# Store user preferences
set_memory("user123", "preferences", {
    "language": "en",
    "expertise_level": "intermediate",
    "topic_interest": "Python debugging"
})

# Store conversation context
set_memory("user123", "context", {
    "current_topic": "async/await",
    "questions_asked": 3,
    "depth": "advanced"
})

# Retrieve for prompt building
prefs = get_memory("user123", "preferences")
print(prefs["expertise_level"])  # → "intermediate"

# Update (automatic upsert)
set_memory("user123", "preferences", {
    "language": "en",
    "expertise_level": "advanced"  # Updated
})
```

---

### 3. User State

**Purpose:** Track simple user mode/status.

**Functions:**
- `set_user_state(user_id, mode)` → None
- `get_user_state(user_id)` → UserState | None
- `delete_user_state(user_id)` → None

**Features:**
- Single mode string per user
- Automatic upsert: `ON CONFLICT (user_id) DO UPDATE`
- Timestamp tracking

**Database Schema:**
```sql
user_state (
    user_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

**Example Usage:**
```python
from src.memory import set_user_state, get_user_state

# Set user state
set_user_state("user123", "active")

# Check state
state = get_user_state("user123")
if state and state.mode == "active":
    print("User is active")
```

---

## Data Flow

### Typical Chat Flow

```
1. User sends message
   └─→ add_message("user123", "user", "Hello")

2. Retrieve context
   ├─→ history = get_recent_messages("user123", 10)
   ├─→ prefs = get_memory("user123", "preferences")
   └─→ context = get_memory("user123", "context")

3. Build prompt (context.py uses this data)
   └─→ render_template(template_id, {
           "history": history,
           "user_prefs": prefs,
           "context": context
       })

4. Get LLM response (llm_client.py)
   └─→ response = call_mistral(prompt)

5. Store assistant response
   └─→ add_message("user123", "assistant", response)
```

---

## Key Design Decisions

### 1. Dual History Retrieval Modes

**Why two functions?**
- `get_conversation_history()`: Newest first → for UI display
- `get_recent_messages()`: Oldest first → for prompt assembly

**Rationale:** Prompts need chronological order (oldest→newest), but UIs typically show newest first.

### 2. JSONB for User Memory

**Why JSONB instead of columns?**
- Flexible schema: No migrations needed for new fields
- Nested data: Store complex preferences/context
- PostgreSQL native: Fast queries and indexing
- Type preservation: Booleans, numbers, arrays preserved

### 3. Upsert Pattern

**Why ON CONFLICT instead of SELECT then INSERT/UPDATE?**
- Atomic operation: No race conditions
- Fewer queries: Single statement
- Simpler code: No existence checking
- Better performance: One round-trip to DB

### 4. User Isolation by Design

**Every function requires user_id** to prevent:
- Cross-user data leakage
- Accidental global operations
- Security vulnerabilities

---

## Error Handling

### Custom Exceptions

```python
class MemoryError(Exception):
    """Base exception for memory operations."""
    
class MemoryNotFoundError(MemoryError):
    """Resource doesn't exist."""
    
class InvalidRoleError(MemoryError):
    """Role must be 'user' or 'assistant'."""
```

### Transaction Safety

All write operations use:
```python
try:
    # Database operation
    conn.commit()
except Exception as e:
    conn.rollback()
    raise MemoryError(f"Operation failed: {e}")
finally:
    put_conn(conn)  # Always return to pool
```

---

## Performance Considerations

### Pagination
```python
# Good: Fetch only what you need
history = get_conversation_history("user123", limit=10)

# Bad: Fetch everything
history = get_conversation_history("user123")  # Could be 10,000+ messages
```

### Indexing
Ensure these indexes exist:
```sql
CREATE INDEX idx_conv_user_created ON conversation_history(user_id, created_at DESC);
CREATE INDEX idx_memory_user_key ON user_memory(user_id, key);
CREATE INDEX idx_state_user ON user_state(user_id);
```

### Memory Cleanup
```python
# Periodically clear old history
from src.memory import count_messages, clear_conversation_history

if count_messages("user123") > 1000:
    # Keep only recent 100 messages
    history = get_conversation_history("user123", limit=100)
    clear_conversation_history("user123")
    # Re-insert recent 100
    for msg in reversed(history):
        add_message("user123", msg.role, msg.content)
```

---

## Integration Points

### Used By

**context.py** (next to implement):
```python
from src.memory import get_recent_messages, get_all_memory

def build_prompt_context(user_id):
    history = get_recent_messages(user_id, count=10)
    memories = get_all_memory(user_id)
    return {"history": history, "memories": memories}
```

**main.py** (chat endpoint):
```python
from src.memory import add_message

@app.post("/chat")
async def chat(user_id: str, message: str):
    # Store user message
    add_message(user_id, "user", message)
    
    # Build context and get response
    # ...
    
    # Store assistant response
    add_message(user_id, "assistant", response)
```

---

## Testing

### Core Test Coverage

```python
# Conversation tests
test_add_message_user()
test_get_conversation_history()
test_get_recent_messages()
test_count_messages()
test_clear_conversation_history()

# Memory tests
test_set_memory()
test_get_memory()
test_memory_upsert()
test_delete_memory()

# State tests
test_set_user_state()
test_get_user_state()
test_state_upsert()

# Error tests
test_invalid_role_error()
test_memory_not_found()
test_delete_nonexistent()
```

### Test Database

Uses testcontainers for real PostgreSQL:
```python
@pytest.fixture
def db_connection(test_db, postgres_container):
    # Real PostgreSQL container
    # Clean tables between tests
    # No mocks - actual database operations
```

---

## API Reference

### Models

```python
class ConversationMessage(BaseModel):
    id: int
    user_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime

class UserMemory(BaseModel):
    id: int
    user_id: str
    key: str
    value: dict[str, Any]  # JSONB
    updated_at: datetime

class UserState(BaseModel):
    user_id: str
    mode: str
    updated_at: datetime
```

