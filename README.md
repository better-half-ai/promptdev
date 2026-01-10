# PromptDev

Prompt engineering workbench for developing and operating AI companion personas. Provides template versioning, real-time conversation monitoring, and operator intervention capabilities.

## Why PromptDev?

When building AI companions, you need to:
- Iterate on prompts rapidly
- Monitor live conversations for safety/quality
- Intervene when things go wrong

PromptDev provides the infrastructure for this workflow.

## Architecture

**Two modes of operation:**

| Mode | Database | LLM | Use Case |
|------|----------|-----|----------|
| Local Dev | PostgreSQL in Docker (`db=local`) | Mistral via llama.cpp (`llm=local`) | Offline development, no API costs |
| Production | Supabase cloud (`db=remote`) | Venice.ai API (`llm=venice`) | Live deployment, real users |

**Why two databases?** Local Docker PostgreSQL for development (fast, free, disposable). Supabase for production (managed, backed up, accessible from anywhere).

**Why two LLMs?** Local Mistral for development (no API costs, works offline, ~4GB download). Venice.ai for production (faster, no GPU needed, pay-per-use).

**No defaults:** Every command requires explicit `db=local|remote` and `llm=local|venice`. This prevents accidentally running production commands against local DB or vice versa.

## Documentation

- [Operator Guide](docs/operator_guide.md) — How to use the dashboard
- [Memory Architecture](docs/memory_architecture.md) — How user memory works

---

## Quick Start

### Prerequisites

**Mac:**
```bash
brew install docker uv git make
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install -y docker.io docker-compose-v2 git make curl
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.bashrc
```

### Setup

```bash
git clone https://github.com/better-half-ai/promptdev.git
cd promptdev
cp .env.example .env
# Edit .env with your credentials (see Configuration below)
uv sync
```

### Run

```bash
# Local development (local Postgres + local LLM)
make run db=local llm=local

# Production (Supabase + Venice.ai)
make run db=remote llm=venice
```

### Access

- **Dashboard:** http://localhost:8001/dashboard
- **Chat UI:** http://localhost:8001/chat-ui
- **API Docs:** http://localhost:8001/docs

---

## Configuration

### Environment Variables (.env)

```bash
# Database - Local
PROMPTDEV_USER_PASS=your_local_db_password

# Database - Remote (Supabase)
SUPABASE_PASSWORD=your_supabase_password

# LLM - Venice.ai
VENICE_API_KEY=your_venice_api_key
VENICE_API_URL=https://api.venice.ai/api/v1
VENICE_MODEL=mistral-31-24b

# Admin Auth
SESSION_SECRET_KEY=random_32_char_hex_string
```

### Database Options

| Option | Description |
|--------|-------------|
| `db=local` | Local PostgreSQL in Docker |
| `db=remote` | Supabase cloud PostgreSQL |

### LLM Options

| Option | Description |
|--------|-------------|
| `llm=local` | Local Mistral via llama.cpp (requires `make llm` first) |
| `llm=venice` | Venice.ai API (requires `VENICE_API_KEY`) |

---

## Commands

All commands require explicit `db=` and/or `llm=` parameters. No defaults.

### Run

```bash
make run db=local llm=local      # Local dev
make run db=local llm=venice     # Local DB + Venice API
make run db=remote llm=venice    # Production (Supabase + Venice)
make stop                        # Stop all services
```

### Database

```bash
make db-up                       # Start local PostgreSQL
make db-reset                    # Nuke local DB and start fresh
make db-migrate db=local         # Run migrations (local)
make db-migrate db=remote        # Run migrations (Supabase)
make db-shell db=local           # Open psql shell (local)
make db-shell db=remote          # Open psql shell (Supabase)
make db-inspect db=local llm=local   # Show tables
```

### Testing

```bash
make test llm=local              # Run tests with local LLM
make test llm=venice             # Run tests with Venice API
```

### Admin

```bash
make admin-create db=remote user=admin   # Create admin user
make health                              # Check backend health
```

---

## Admin Authentication

All `/admin/*` endpoints require authentication.

### Setup Admin User

```bash
# Run migration first
make db-migrate db=remote

# Create admin user (will prompt for password)
make admin-create db=remote user=admin
```

### Login

1. Visit http://localhost:8001/login
2. Enter username and password
3. Session valid for 24 hours

### API Authentication

```bash
# Login (sets cookie)
curl -X POST http://localhost:8001/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "yourpassword"}' \
  -c cookies.txt

# Use cookie for admin requests
curl http://localhost:8001/admin/users -b cookies.txt

# Logout
curl -X POST http://localhost:8001/admin/logout -b cookies.txt
```

---

## Dashboard Guide

### Overview

Open http://localhost:8001/dashboard (requires login)

Sections:
- **Dashboard** — Statistics (active users, messages, response times)
- **Personalities** — Create and edit AI templates
- **Monitor** — Watch conversations, intervene if needed

### Personalities (Templates)

Templates define how the AI behaves.

**Create:**
1. Click **Personalities** → **+ New Personality**
2. Enter name, content, and your name
3. Click **Create**

**Edit:**
1. Click **Edit** on any template
2. Make changes, add a note
3. Click **Save Changes** (creates new version)

**Version History:**
- Click **History** to see all versions
- Click **Rollback** to restore old version

### Monitor (Conversations)

**View:** Click **Monitor** to see all users and conversations

**Halt:** Stop AI from responding (for review)
- Click **Halt**, enter reason
- User sees "Conversation paused"

**Resume:** Click **Resume** to restart AI responses

**Inject:** Add context mid-conversation
- Click **Inject**, type message, click **Send**

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Browser       │     │   Venice.ai     │
│   Dashboard     │     │   (LLM API)     │
└────────┬────────┘     └────────▲────────┘
         │                       │
    ┌────▼────────────────────────────┐
    │         FastAPI Backend         │
    │         localhost:8001          │
    └────┬───────────────────────┬────┘
         │                       │
    ┌────▼────────┐        ┌────▼────────┐
    │  Local      │   OR   │  Supabase   │
    │  PostgreSQL │        │  PostgreSQL │
    └─────────────┘        └─────────────┘
```

### Database Schema

| Table | Purpose |
|-------|---------|
| `conversation_history` | All messages (user_id isolated) |
| `user_memory` | Key-value storage (JSONB) |
| `user_state` | Active/halted status, personality |
| `system_prompt` | Templates (personas) |
| `prompt_version_history` | Version audit trail |
| `guardrail_configs` | Safety rules |
| `llm_requests` | Request logs for telemetry |
| `admin_users` | Dashboard authentication |

---

## API Examples

### Chat

```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user123", "message": "Hello!"}'
```

### Templates (requires auth)

```bash
# Create
curl -X POST http://localhost:8001/admin/templates \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"name": "companion", "content": "You are helpful.", "created_by": "admin"}'

# List
curl http://localhost:8001/admin/templates -b cookies.txt
```

### Interventions (requires auth)

```bash
# Halt
curl -X POST http://localhost:8001/admin/interventions/user123/halt \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"operator": "admin", "reason": "Review needed"}'

# Resume
curl -X POST "http://localhost:8001/admin/interventions/user123/resume?operator=admin" \
  -b cookies.txt
```

Full API: http://localhost:8001/docs

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `db= is required` | All commands need explicit `db=local` or `db=remote` |
| `llm= is required` | Test/run commands need `llm=local` or `llm=venice` |
| 401 on admin routes | Login first at `/login` or via API |
| Connection refused (Supabase) | Check `SUPABASE_PASSWORD` in `.env` |
| Venice API errors | Check `VENICE_API_KEY` in `.env` |
| Port 8001 in use | Run `make stop` or `lsof -ti :8001 \| xargs kill` |

---

## Development

### Local LLM Setup

```bash
# Download and start Mistral (first time takes ~10 min)
make llm

# Then in another terminal
make run db=local llm=local
```

### Running Tests

Tests use testcontainers (real PostgreSQL, no mocks).

```bash
# Requires Docker running
make test llm=local
make test llm=venice
```
