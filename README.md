# PromptDev

Prompt engineering workbench for AI companion applications. Manage templates, monitor conversations, and intervene in real-time.

## Documentation

- [Operator Guide](docs/operator_guide.md) — How to use the dashboard
- [Memory Architecture](docs/memory_architecture.md) — How user memory works

---

## Setup

### 1. Install Prerequisites

**Mac:** Install [Homebrew](https://brew.sh), then:
```bash
brew install docker uv git make
```

**Linux (Ubuntu/Debian):** Install [Docker](https://docs.docker.com/engine/install/), then:
```bash
sudo apt install -y docker.io docker-compose-v2 git make curl
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.bashrc
```

### 2. Download and Start

```bash
git clone https://github.com/better-half-ai/promptdev.git
cd promptdev
./setup_env.sh
make dev
```

First run downloads the AI model (~4GB). This takes a few minutes.

### 3. Open Dashboard

http://localhost:8001/

---

## Daily Use

```bash
make dev              # Start (Mac)
make dev-stop         # Stop (Mac)
make prod             # Start (Linux/Cloud)
make prod-stop        # Stop (Linux/Cloud)
make help             # See all commands
```

---

## Dashboard Guide

### Overview

Open http://localhost:8001/ to see the dashboard with three sections in the sidebar:
- **Dashboard** — Statistics (active users, messages, response times)
- **Personalities** — Create and edit AI templates
- **Monitor** — Watch conversations, intervene if needed

---

### Personalities (Templates)

Templates define how the AI behaves. Each template has a name, content, and version number.

#### Create a New Template

1. Click **Personalities** in sidebar
2. Click **+ New Personality**
3. Enter a **Name** (e.g., "companion")
4. Enter **Content** — the instructions for the AI:
   ```
   You are a helpful companion.
   User context: {{user_context}}
   ```
5. Enter your name in **Created By**
6. Click **Create**

#### Edit a Template

1. Find the template in the list
2. Click **Edit**
3. Make changes in the editor
4. Add a note describing your change
5. Click **Save Changes**

Every save creates a new version. Old versions are never lost.

#### View Version History

1. Click **History** on any template
2. See all previous versions with timestamps
3. Click **View Content** to see what changed
4. Click **Rollback** to restore an old version

#### Activate / Deactivate

- **Active** templates (green badge) are used by the AI
- **Inactive** templates (red badge) are saved but not used
- Click **Deactivate** to turn off a template
- Click **Activate** to turn it back on

#### Delete a Template

1. Click **Delete** (requires confirmation)
2. Type the template name to confirm
3. This is permanent — template and all versions are removed

---

### Monitor (Conversations)

Watch user conversations and intervene when needed.

#### View Conversations

1. Click **Monitor** in sidebar
2. See all users with message counts and status:
   - 🟢 **Active** — AI is responding normally
   - 🔴 **Halted** — AI is paused, awaiting review
3. Click a user to see their full conversation

#### Halt a Conversation

Stop the AI from responding (for review or safety):

1. Open a user's conversation
2. Click **Halt**
3. Enter a reason (e.g., "Reviewing content")
4. User sees "Conversation paused" until you resume

#### Resume a Conversation

1. Open the halted conversation
2. Click **Resume**
3. AI begins responding again

#### Inject a Message

Add context or instructions mid-conversation:

1. Open a user's conversation
2. Click **Inject**
3. Type your message (e.g., "User prefers formal tone")
4. Click **Send**

The message appears in the conversation. The AI sees it and adjusts.

#### Export Conversation

1. Open a user's conversation
2. Click **Export**
3. Downloads as JSON file

---

### User Chat

End users access: http://localhost:8001/static/index.html

- Type message, press Enter or click Send
- AI responds based on the active template
- Scroll up to see history
- Each user has their own conversation saved

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "command not found: brew" | Install Homebrew first: https://brew.sh |
| "command not found: make" | Run `brew install make` (Mac) or `sudo apt install make` (Linux) |
| Dashboard won't load | Run `make health` to check if backend is running |
| AI not responding | Check that model finished downloading, restart with `make dev-stop && make dev` |

---

## Future Features

**Data Portability:** Bulk export/import for templates between local and remote. Currently only single-conversation export exists.

**Other planned:** Post-generation filtering, competing objectives, perturbations, wellbeing metrics, A/B testing.

---
---

# Appendix: Technical Reference

*For developers and system administrators.*

---

## Database

### Schema
- `conversation_history` - All messages
- `user_memory` - Key-value storage (JSONB)
- `user_state` - Active/halted status
- `system_prompt` - Templates
- `prompt_version_history` - Version audit
- `guardrail_configs` - Safety rules
- `llm_requests` - Request logs

### Access
```bash
make db-shell         # Open PostgreSQL shell
make db-inspect       # Show tables
make db-migrate       # Run migrations
```

---

## Testing

```bash
make test             # Run all 298 tests
make test-verbose     # Verbose output
```

**Test breakdown:**
- `test_llm_client.py`: 28 tests - HTTP client
- `test_prompts.py`: 71 tests - Templates, versioning
- `test_memory.py`: 45 tests - Conversations
- `test_context.py`: 32 tests - Prompt assembly
- `test_guardrails.py`: 38 tests - Safety rules
- `test_main.py`: 52 tests - API endpoints
- `test_telemetry.py`: 18 tests - Metrics
- `test_integration_e2e.py`: 14 tests - Full flows

All tests use real PostgreSQL via testcontainers (no mocks).

---

## API Examples

### Create Template
```bash
curl -X POST http://localhost:8001/admin/templates \
  -H "Content-Type: application/json" \
  -d '{"name": "companion", "content": "You are a helpful companion.", "created_by": "admin"}'
```

### Send Chat Message
```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user123", "message": "Hello!"}'
```

### Halt Conversation
```bash
curl -X POST http://localhost:8001/admin/interventions/user123/halt \
  -H "Content-Type: application/json" \
  -d '{"operator": "admin", "reason": "Review needed"}'
```

Full API reference: http://localhost:8001/docs

---

## Configuration

**config.toml:**
```toml
[llm]
base_url = "http://mistral:8080"
timeout = 120.0
max_retries = 3

[database]
host = "postgres"
port = 5432
database = "promptdev"
user = "promptdev"
password = "promptdev"
pool_size = 10
```

---

## Project Structure

```
promptdev/
├── src/
│   ├── main.py           # FastAPI app
│   ├── prompts.py        # Template management
│   ├── memory.py         # Conversation storage
│   ├── context.py        # Prompt assembly
│   ├── guardrails.py     # Safety rules
│   ├── llm_client.py     # LLM client
│   ├── telemetry.py      # Metrics
│   └── config.py         # Config loader
├── static/               # Dashboard HTML
├── docs/                 # Documentation
├── tests/                # 298 tests
├── migrations/           # Database schema
└── Makefile              # Commands
```

---

## Production Checklist

**Required before production:**
- [ ] Add authentication (JWT/API keys)
- [ ] Add rate limiting
- [ ] Enable HTTPS
- [ ] Set up database backups
- [ ] Configure monitoring
- [ ] Secure environment variables
- [ ] Set CORS to specific origins

---

## Contributing

1. All code changes require tests
2. Tests must use real databases (no mocks)
3. Run `make test` before committing