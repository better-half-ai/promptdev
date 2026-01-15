# PromptDev Admin Guide

## What is PromptDev?

PromptDev is a prompt engineering workbench for developing, testing, and analyzing AI conversations. It connects to LLM backends (local Mistral via llama.cpp or Venice.ai API) and provides tools to:

- Create and iterate on system prompt templates
- Run test conversations with different prompts
- Analyze conversation quality via sentiment scoring
- Monitor and intervene in live chats

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Admin Dashboard                     │
│  /dashboard - Stats, Templates, Chats, Settings          │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    FastAPI Backend                       │
│  - Chat endpoint: /chat                                  │
│  - Admin API: /admin/*                                   │
│  - Template CRUD: /templates/*                           │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐    ┌─────▼─────┐   ┌─────▼─────┐
    │ LLM     │    │ PostgreSQL │   │ Sentiment │
    │ Backend │    │ (Supabase) │   │ Analyzer  │
    └─────────┘    └───────────┘   └───────────┘
```

### LLM Configuration

Set via `LLM_BACKEND` environment variable:

| Backend | Endpoint | Config |
|---------|----------|--------|
| `local` | `http://127.0.0.1:8080/completion` | Local llama.cpp server |
| `venice` | `https://api.venice.ai/api/v1/chat/completions` | Venice.ai API (needs `VENICE_API_KEY`) |

---

## Workflow: Developing and Testing Prompts

### 1. Create a Template

**Dashboard → Personalities Tab**

Templates use Jinja2 syntax with variables:

```
You are {{ personality_name }}, a {{ description }}.

{% if context %}
User context: {{ context }}
{% endif %}

Respond helpfully while staying in character.
```

Each save creates a new version. You can rollback to any previous version.

### 2. Create a Test Chat

**Dashboard → Chats Tab → View any chat → "New Chat" dropdown**

- **Chat ID**: Identifier for the test user (e.g., `test_empathy_v2`)
- **Chat Name**: Human-readable label
- **Enable Sentiment**: Toggle on for analysis

### 3. Send Test Messages

**Chat Interface** (`/static/index.html`)

Select your chat from dropdown and send messages. The LLM responds using the active template.

### 4. Review Results

**Monitor View** (`/static/monitor.html?user=<chat_id>`)

Access via "View" button on any chat in dashboard.

---

## Sentiment Analysis

When enabled, each user message is analyzed for:

| Metric | Range | Meaning |
|--------|-------|---------|
| **Valence** | -1 to +1 | Negative ↔ Positive emotional tone |
| **Trust** | 0 to 1 | How open/trusting the user seems |
| **Engagement** | 0 to 1 | Investment level in conversation |

### How It Works

1. User sends message
2. Backend calls sentiment analyzer (RoBERTa-based)
3. Scores stored in `message_sentiment` table
4. Context injected into LLM prompt: `"User seems [frustrated/engaged/etc], respond [empathetically/etc]"`

### Viewing Sentiment

- **Per-message**: Monitor view shows badges (V: valence score)
- **Aggregates**: `GET /admin/sessions/{id}/sentiment/aggregate` returns averages
- **Trends**: Coming soon - line chart of scores over conversation

---

## Comparing Prompts

### A/B Testing Workflow

1. **Create two templates** with different approaches
2. **Create separate chats** for each (e.g., `test_prompt_A`, `test_prompt_B`)
3. **Assign templates** (via template selector in dashboard or API)
4. **Run same test scenarios** through both
5. **Compare sentiment scores** and message quality

### What to Look For

- Higher average valence = better emotional response
- Higher engagement = user stays invested
- Trust trends upward = building rapport

---

## Template Variables

Templates can use these runtime variables:

| Variable | Source | Example |
|----------|--------|---------|
| `user_id` | Chat session | `chat_test_123` |
| `history` | Recent messages | Last N turns |
| `sentiment_context` | Analysis result | `"User appears frustrated"` |
| `custom.*` | Admin-defined | Per-tenant config |

---

## Key Pages

| URL | Purpose |
|-----|---------|
| `/login` | Admin authentication |
| `/dashboard` | Main control panel |
| `/static/index.html` | Chat interface |
| `/static/monitor.html?user=X` | Monitor specific chat |
| `/static/template-manager.html` | Advanced template editing |

---

## API Reference (Key Endpoints)

### Chat Operations

```
POST /chat                          # Send message
POST /chat/sessions?user_id=X       # Create session
PUT  /chat/sessions/{id}            # Update title/notes
POST /chat/sessions/{id}/archive    # Hide from list
POST /chat/sessions/{id}/deactivate # Stop accepting messages
```

### Templates

```
GET  /admin/templates               # List all
POST /admin/templates               # Create new
PUT  /admin/templates/{id}          # Update (creates version)
GET  /admin/templates/{id}/versions # Version history
POST /admin/templates/{id}/rollback?version=N
```

### Analytics

```
GET /admin/stats/overview                      # Aggregate stats
GET /admin/sessions/{id}/sentiment             # Per-message scores
GET /admin/sessions/{id}/sentiment/aggregate   # Session averages
GET /admin/sessions                            # List all chats
GET /admin/sessions?include_archived=true      # Include archived
```

---

## Monitor View Actions

| Button | Effect |
|--------|--------|
| **Refresh** | Reload conversation |
| **Inject Message** | Insert admin message (appears as assistant) |
| **Halt Conversation** | User gets error, can't continue |
| **Export** | Download chat as JSON |
| **Sentiment Toggle** | Enable/disable per-message analysis |

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| 401 on all requests | Session expired | Re-login at `/login` |
| Sentiment shows "-" | Analysis not enabled | Toggle sentiment on, send new messages |
| LLM timeout | Backend unreachable | Check `LLM_BACKEND` env, verify server running |
| Template not rendering | Jinja2 error | Check syntax in template editor |
| Chat not appearing | Archived | Add `?include_archived=true` to API call |

---

## Environment Variables

```bash
DATABASE_URL=postgresql://...       # Supabase connection
LLM_BACKEND=venice                  # or 'local'
VENICE_API_KEY=sk-...               # If using Venice
SESSION_SECRET=...                  # For admin auth
```

---

## Database Migrations

Run in order for fresh setup:

```sql
-- Core schema
migrations/001_init.sql
migrations/002_prompts_schema.sql
...
migrations/011_fix_null_tenant_constraints.sql
migrations/012_chat_sessions.sql
migrations/013_sentiment.sql

-- Required columns (run manually if missing)
ALTER TABLE message_sentiment ADD COLUMN IF NOT EXISTS injection_context TEXT;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE;
```