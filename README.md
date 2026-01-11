# PromptDev

Prompt engineering workbench for developing and operating AI companion personas. Provides template versioning, real-time conversation monitoring, and operator intervention capabilities.

## Why PromptDev?

When building AI companions, you need to:
- Iterate on prompts rapidly
- Monitor live conversations for safety/quality
- Intervene when things go wrong

PromptDev provides the infrastructure for this workflow.

## Multi-Tenant Architecture

Each admin (tenant) has completely isolated:
- Templates (personas)
- Users and conversations
- Guardrails
- Activity logs

Admins can optionally share templates with others via the shared library.

```
┌─────────────────────────────────────────────────────────┐
│                    PromptDev SaaS                       │
├─────────────────────────────────────────────────────────┤
│  Super Admin (from .env)                                │
│  └── Can CRUD all admins                                │
├─────────────────────────────────────────────────────────┤
│  Admin A (tenant)          Admin B (tenant)             │
│  ├── templates             ├── templates                │
│  ├── shared templates ◄────┼── shared templates         │
│  ├── users                 ├── users                    │
│  │   └── conversations     │   └── conversations        │
│  ├── guardrails            ├── guardrails               │
│  └── audit_log             └── audit_log                │
└─────────────────────────────────────────────────────────┘
```

## Two Modes of Operation

| Mode | Database | LLM | Use Case |
|------|----------|-----|----------|
| Local Dev | PostgreSQL in Docker (`db=local`) | Mistral via llama.cpp (`llm=local`) | Offline development, no API costs |
| Production | Supabase cloud (`db=remote`) | Venice.ai API (`llm=venice`) | Live deployment, real users |

**Why two databases?** Local Docker PostgreSQL for development (fast, free, disposable). Supabase for production (managed, backed up, accessible from anywhere).

**Why two LLMs?** Local Mistral for development (no API costs, works offline, ~4GB download). Venice.ai for production (faster, no GPU needed, pay-per-use).

**No defaults:** Every command requires explicit `db=local|remote` and `llm=local|venice`. This prevents accidentally running production commands against local DB or vice versa.

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

### Run Migrations

```bash
# Local development
make db-migrate db=local

# Production
make db-migrate db=remote
```

### Create Admin

```bash
# Create first admin
make admin-create db=remote email=admin@example.com password=secretpass123
```

### Run

```bash
# Local development
make run db=local llm=local

# Production
make run db=remote llm=venice
```

### Access

- **Dashboard:** http://localhost:8001/dashboard
- **Login:** http://localhost:8001/login
- **Chat UI:** http://localhost:8001/chat-ui
- **API Docs:** http://localhost:8001/docs

---

## Configuration

### Environment Variables (.env)

```bash
# Super Admin (not in database, checked at runtime)
SUPER_ADMIN_EMAIL=super@yourdomain.com
SUPER_ADMIN_PASSWORD=very_secure_super_admin_password

# Session Security
SESSION_SECRET_KEY=random_32_char_hex_string

# Database - Local
PROMPTDEV_USER_PASS=your_local_db_password

# Database - Remote (Supabase)
SUPABASE_PASSWORD=your_supabase_password

# LLM - Venice.ai
VENICE_API_KEY=your_venice_api_key
VENICE_API_URL=https://api.venice.ai/api/v1
VENICE_MODEL=mistral-31-24b
```

### Super Admin

The super admin is defined in `.env`, not in the database. Super admin can:
- Create, list, deactivate, delete other admins
- View all tenants (for support purposes)

Super admin cannot access tenant data without explicit audit logging.

---

## Admin Management

```bash
# Create admin
make admin-create db=remote email=newadmin@example.com password=secretpass123

# List all admins
make admin-list db=remote

# Deactivate admin (can't login, data preserved)
make admin-deactivate db=remote email=badactor@example.com
```

---

## Commands

All commands require explicit `db=` and/or `llm=` parameters.

### Run

```bash
make run db=local llm=local      # Local dev
make run db=remote llm=venice    # Production
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
```

### Testing

```bash
make test llm=local              # Run tests with local LLM
make test llm=venice             # Run tests with Venice API
```

Tests use testcontainers (isolated PostgreSQL), not your local/remote DB.

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `admins` | Admin users (tenants) |
| `admin_audit_log` | All admin actions |
| `system_prompt` | Templates (tenant isolated) |
| `prompt_version_history` | Version audit trail |
| `conversation_history` | All messages (tenant isolated) |
| `user_memory` | Key-value storage per user |
| `user_state` | Active/halted status |
| `guardrail_configs` | Safety rules (tenant isolated) |
| `llm_requests` | Request logs for telemetry |

All tables have `tenant_id` for complete isolation.

---

## Template Sharing

1. Admin A creates template, marks `is_shareable = true`
2. Template appears in shared library
3. Admin B browses shared library, clicks "Clone"
4. Independent copy created in Admin B's space
5. Original and clone are completely independent

Lineage tracked via `cloned_from_id` and `cloned_from_tenant`.

---

## Documentation

- [Operator Guide](docs/operator_guide.md) — How to use the dashboard
- [Memory Architecture](docs/memory_architecture.md) — How user memory works
