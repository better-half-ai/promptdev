# memory.py Architecture Documentation

## Overview

The memory module provides conversation history storage, user context management, and state tracking for the PromptDev system. It manages three independent storage areas in PostgreSQL, all keyed by `user_id` and isolated by `tenant_id`.

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
│  ALL FUNCTIONS REQUIRE tenant_id FOR ISOLATION              │
│                                                              │
└──────────────┬────────────────────┬──────────────────┬──────┘
               │                    │                  │
               ▼                    ▼                  ▼
         ┌──────────┐         ┌──────────┐      ┌──────────┐
         │ conv_    │         │ user_    │      │ user_    │
         │ history  │         │ memory   │      │ state    │
         │          │         │          │      │          │
         │ id       │         │ id       │      │ user_id  │
         │ tenant_id│         │ tenant_id│      │ tenant_id│
         │ user_id  │         │ user_id  │      │ mode     │
         │ role     │         │ key      │      │ updated  │
         │ content  │         │ value    │      └──────────┘
         │ created  │         │ updated  │
         └──────────┘         └──────────┘
              ↓                     ↓                  ↓
         PostgreSQL          PostgreSQL           PostgreSQL
```

---

## Multi-Tenant Isolation

All memory operations are isolated by `tenant_id`. Each admin (tenant) can only access their own users' data.

### The `_tenant_clause()` Helper

All database queries use `_tenant_clause()` to handle tenant isolation:

```python
def _tenant_clause(tenant_id: Optional[int]) -> tuple[str, list]:
    """Generate SQL clause for tenant filtering.
    
    Returns (sql_clause, params) tuple.
    - tenant_id=None: Returns "tenant_id IS NULL" (system/global data)
    - tenant_id=int: Returns "tenant_id = %s" with param
    """
    if tenant_id is None:
        return "tenant_id IS NULL", []
    return "tenant_id = %s", [tenant_id]
```

**Why this matters:** PostgreSQL treats `NULL != NULL`, so `WHERE tenant_id = NULL` returns nothing. The helper ensures correct NULL handling for system-level data.

---

## Component Details

### 1. Conversation History

**Purpose:** Store chronological message exchanges between user and assistant.

**Functions:**
- `add_message(user_id, role, content, tenant_id)` → message_id
- `get_conversation_history(user_id, tenant_id, limit, offset)` → List[ConversationMessage]
- `get_recent_messages(user_id, tenant_id, count)` → List[ConversationMessage]
- `count_messages(user_id, tenant_id)` → int
- `clear_conversation_history(user_id, tenant_id)` → deleted_count
- `delete_message(message_id, tenant_id)` → None

**Features:**
- Role validation: Only `"user"` or `"assistant"` allowed
- Pagination support via limit/offset
- Two retrieval modes:
  - `get_conversation_history()`: Newest first (for display)
  - `get_recent_messages()`: Oldest first (for prompt context)
- Tenant isolation: Each tenant's users are separate

**Database Schema:**
```sql
conversation_history (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER,  -- NULL for system, FK to admins for tenants
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

**Example Usage:**
```python
from src.memory import add_message, get_recent_messages

# Store conversation (tenant_id from authenticated admin)
add_message("user123", "user", "What is Python?", tenant_id=1)
add_message("user123", "assistant", "Python is a programming language...", tenant_id=1)

# Get last 10 messages for prompt (oldest first)
history = get_recent_messages("user123", tenant_id=1, count=10)
for msg in history:
    print(f"{msg.role}: {msg.content}")
```

---

### 2. User Memory (JSONB Key-Value)

**Purpose:** Store flexible user context, preferences, and metadata.

**Functions:**
- `set_memory(user_id, key, value: dict, tenant_id)` → memory_id
- `get_memory(user_id, key, tenant_id)` → dict | None
- `get_all_memory(user_id, tenant_id)` → List[UserMemory]
- `delete_memory(user_id, key, tenant_id)` → None
- `clear_all_memory(user_id, tenant_id)` → deleted_count

**Features:**
- JSONB storage: Supports complex nested data structures
- Automatic upsert: `ON CONFLICT (tenant_id, user_id, key) DO UPDATE`
- No schema required: Store any dict structure
- Unique constraint: (tenant_id, user_id, key) must be unique

**Database Schema:**
```sql
user_memory (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER,
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, key)
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
}, tenant_id=1)

# Store conversation context
set_memory("user123", "context", {
    "current_topic": "async/await",
    "questions_asked": 3,
    "depth": "advanced"
}, tenant_id=1)

# Retrieve for prompt building
prefs = get_memory("user123", "preferences", tenant_id=1)
print(prefs["expertise_level"])  # → "intermediate"

# Update (automatic upsert)
set_memory("user123", "preferences", {
    "language": "en",
    "expertise_level": "advanced"  # Updated
}, tenant_id=1)
```

---

### 3. User State

**Purpose:** Track simple user mode/status (e.g., active, halted).

**Functions:**
- `set_user_state(user_id, mode, tenant_id)` → None
- `get_user_state(user_id, tenant_id)` → UserState | None
- `delete_user_state(user_id, tenant_id)` → None

**Features:**
- Single mode string per user
- Automatic upsert: `ON CONFLICT (tenant_id, user_id) DO UPDATE`
- Timestamp tracking

**Database Schema:**
```sql
user_state (
    tenant_id INTEGER,
    user_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, user_id)
)
```

**Example Usage:**
```python
from src.memory import set_user_state, get_user_state

# Halt a user
set_user_state("user123", "halted", tenant_id=1)

# Check state
state = get_user_state("user123", tenant_id=1)
if state and state.mode == "halted":
    print("User is halted")

# Resume
set_user_state("user123", "active", tenant_id=1)
```

---

## Data Flow

### Typical Chat Flow

```
1. User sends message (tenant_id from admin session)
   └─→ add_message("user123", "user", "Hello", tenant_id=1)

2. Retrieve context
   ├─→ history = get_recent_messages("user123", tenant_id=1, count=10)
   ├─→ prefs = get_memory("user123", "preferences", tenant_id=1)
   └─→ context = get_memory("user123", "context", tenant_id=1)

3. Build prompt (prompts.py uses this data)
   └─→ render_template(template_id, {
           "history": history,
           "user_prefs": prefs,
           "context": context
       }, tenant_id=1)

4. Get LLM response (llm_client.py)
   └─→ response = call_llm(prompt)

5. Store assistant response
   └─→ add_message("user123", "assistant", response, tenant_id=1)
```

---

## Key Design Decisions

### 1. Tenant Isolation First

**Every function requires tenant_id** to ensure:
- Complete data isolation between admins
- No cross-tenant data leakage
- Security by design

### 2. NULL Tenant for System Data

- `tenant_id = NULL` represents system-level data (e.g., default templates)
- `_tenant_clause()` handles NULL correctly with `IS NULL` instead of `= NULL`

### 3. Dual History Retrieval Modes

**Why two functions?**
- `get_conversation_history()`: Newest first → for UI display
- `get_recent_messages()`: Oldest first → for prompt assembly

**Rationale:** Prompts need chronological order (oldest→newest), but UIs typically show newest first.

### 4. JSONB for User Memory

**Why JSONB instead of columns?**
- Flexible schema: No migrations needed for new fields
- Nested data: Store complex preferences/context
- PostgreSQL native: Fast queries and indexing
- Type preservation: Booleans, numbers, arrays preserved

### 5. Upsert Pattern

**Why ON CONFLICT instead of SELECT then INSERT/UPDATE?**
- Atomic operation: No race conditions
- Fewer queries: Single statement
- Simpler code: No existence checking
- Better performance: One round-trip to DB

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
history = get_conversation_history("user123", tenant_id=1, limit=10)

# Bad: Fetch everything
history = get_conversation_history("user123", tenant_id=1)  # Could be 10,000+ messages
```

### Indexing
Ensure these indexes exist:
```sql
CREATE INDEX idx_conv_tenant_user_created ON conversation_history(tenant_id, user_id, created_at DESC);
CREATE INDEX idx_memory_tenant_user_key ON user_memory(tenant_id, user_id, key);
CREATE INDEX idx_state_tenant_user ON user_state(tenant_id, user_id);
```

### Memory Cleanup
```python
# Periodically clear old history
from src.memory import count_messages, clear_conversation_history

if count_messages("user123", tenant_id=1) > 1000:
    # Archive or truncate old messages
    clear_conversation_history("user123", tenant_id=1)
```

---

## Testing

### Core Test Coverage

```python
# Conversation tests (all with tenant_id)
test_add_message_user()
test_get_conversation_history()
test_get_recent_messages()
test_count_messages()
test_clear_conversation_history()
test_tenant_isolation()  # Verify cross-tenant blocked

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
    tenant_id: Optional[int]
    user_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime

class UserMemory(BaseModel):
    id: int
    tenant_id: Optional[int]
    user_id: str
    key: str
    value: dict[str, Any]  # JSONB
    updated_at: datetime

class UserState(BaseModel):
    tenant_id: Optional[int]
    user_id: str
    mode: str
    updated_at: datetime
```
