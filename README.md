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
cp config.toml.example config.toml  # If needed
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
# Interactive - prompts for email and password
make admin-create db=local
make admin-create db=remote
```

### Run

```bash
# Local development
make run db=local llm=local

# Production
make run db=remote llm=venice

# Stop
make stop
```

### Access

- **Dashboard:** http://localhost:8001/
- **API Docs:** http://localhost:8001/docs

---

## Configuration

### Environment Variables (.env)

Only secrets go in `.env`:

```bash
# Session Security
SESSION_SECRET_KEY=random_32_char_hex_string

# Database - Local
PROMPTDEV_USER_PASS=postgres

# Database - Remote (Supabase)
SUPABASE_PASSWORD=your_supabase_password

# LLM - Venice.ai
VENICE_API_KEY=your_venice_api_key
```

### Config File (config.toml)

All non-secret config goes in `config.toml`:

```toml
mode = "standalone"

[mistral]
url = "http://host.docker.internal:8080"

[venice]
url = "https://api.venice.ai/api/v1"
model = "mistral-31-24b"

[database]
host = "postgres"
port = 5432
user = "promptdev_user"
database = "promptdev_db"

[remote_database]
host = "your-project.pooler.supabase.com"
port = 5432
user = "postgres.your-project-id"
database = "postgres"
```

---

## Admin Management

```bash
# Create admin (interactive prompts for email/password)
make admin-create db=local
make admin-create db=remote

# List all admins
make admin-list db=local
make admin-list db=remote

# Reset password (interactive)
make admin-reset-password db=remote email=admin@example.com

# Activate/deactivate admin
make admin-activate db=remote email=admin@example.com
make admin-deactivate db=remote email=admin@example.com
```

---

## Commands

All commands require explicit `db=` and/or `llm=` parameters. Run `make` or `make help` to see all available commands.

### Run

```bash
make run db=local llm=local      # Local dev (Docker PostgreSQL + local Mistral)
make run db=remote llm=venice    # Production (Supabase + Venice API)
make stop                        # Stop all services
make llm                         # Start local LLM server only
```

### Database

```bash
make db-up                       # Start local PostgreSQL container
make db-reset                    # Nuke local DB volumes and start fresh
make db-drop-remote              # Drop remote schema (destructive!)
make db-migrate db=local         # Run migrations (local)
make db-migrate db=remote        # Run migrations (remote)
make db-inspect db=local         # Show tables
make db-shell db=local           # Open psql shell (local)
make db-shell db=remote          # Open psql shell (remote)
```

### Connection Tests

```bash
make test-db-local               # Test local PostgreSQL connection
make test-db-remote              # Test Supabase connection
```

### Admin Management

```bash
make admin-create db=local                           # Create admin (interactive)
make admin-create db=remote
make admin-list db=local                             # List all admins
make admin-list db=remote
make admin-reset-password db=remote email=...        # Reset password (interactive)
make admin-activate db=remote email=...              # Re-enable admin
make admin-deactivate db=remote email=...            # Disable admin
```

### Testing

```bash
make test llm=local              # Run tests with local LLM
make test llm=venice             # Run tests with Venice API
```

Tests use testcontainers (isolated PostgreSQL), not your local/remote DB.

### Utilities

```bash
make health                      # Check backend health
make clean                       # Clean Python cache files
```

---

## Authentication

Login at `http://localhost:8001/` with your admin credentials. Session cookie is set automatically.

### API Authentication

```bash
# Login and save session cookie
curl -X POST http://localhost:8001/admin/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"yourpassword"}' \
  -c cookies.txt

# Use authenticated endpoints
curl http://localhost:8001/admin/templates -b cookies.txt

# Logout
curl -X POST http://localhost:8001/admin/logout -b cookies.txt
```

Session duration: 24 hours.

---

## Default Template

When a new admin logs in with no templates, the system automatically clones the default template for them.

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
