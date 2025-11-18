# PromptDev

Prompt engineering workbench with self-hosted Mistral CPU LLM and template versioning.

## Status

**Infrastructure:** ✅ Complete  
**Prompts Module:** ✅ Complete (549 lines, 48 tests passing)  
**LLM Client:** ✅ Complete (async Mistral integration)  
**Implementation:** ⚠️ In progress  
**Tests:** ✅ 89 passing

## Quick Start

```bash
# 1. Setup
cp .env.example .env
tar -xzf prompts_files.tar.gz  # If installing prompts module

# 2. Deploy (builds backend, starts services, runs migrations)
make deploy

# 3. Start Mistral locally (Mac only)
make local-mistral

# 4. Test
make test
```

## Usage

### Create and Use Templates

```bash
# Create a template
uv run python scripts/manage_templates.py create \
  chatbot \
  "You are {{role}}. Help with {{topic}}." \
  --created-by=admin

# List templates
uv run python scripts/manage_templates.py list

# Use template with Mistral
uv run python scripts/run_prompt.py chatbot \
  "Explain Docker networking" \
  role="DevOps expert" \
  topic="containerization"
```

### Template Management

```bash
# View template
uv run python scripts/manage_templates.py get chatbot

# Update template (creates v2)
uv run python scripts/manage_templates.py update chatbot \
  "You are {{role}}. Expert in {{topic}}."

# View version history
uv run python scripts/manage_templates.py history chatbot

# Rollback to v1
uv run python scripts/manage_templates.py rollback chatbot 1
```

## Structure

```
promptdev/
├── src/                # Application code
│   ├── config.py       ✅ Complete
│   ├── main.py         ✅ Health endpoint + FastAPI
│   ├── llm_client.py   ✅ Complete - async Mistral client
│   ├── prompts.py      ✅ Complete - Jinja2 templates + versioning
│   ├── memory.py       ❌ TODO - user context storage
│   ├── context.py      ❌ TODO - prompt assembly
│   └── telemetry.py    ❌ TODO - metrics
├── scripts/            # Management scripts
│   ├── run_prompt.py          # Execute templates with Mistral
│   └── manage_templates.py    # CRUD for templates
├── tests/              # Test suite (89 tests)
│   ├── test_prompts.py        # 48 template tests
│   ├── test_llm_client.py     # 28 LLM tests
│   └── test_db.py             # 8 database tests
├── db/                 # Database connection pool
├── migrations/         # SQL migrations
│   ├── 001_init.sql           # Base schema
│   └── 002_prompts_schema.sql # Prompts tables
├── config.toml         # Configuration
├── .env                # Secrets (DB password)
└── Makefile            # Commands
```

## Features

### ✅ Template Management (prompts.py)
- **Jinja2 templating** - Variables, loops, conditionals, filters
- **Immutable versioning** - Every change creates new version
- **Rollback support** - Restore any previous version
- **Version history** - Full audit trail with metadata
- **Syntax validation** - Catch Jinja2 errors at creation
- **Sandboxed execution** - Secure rendering

### ✅ LLM Client (llm_client.py)
- **Async Mistral API** - Non-blocking requests
- **Automatic retries** - Exponential backoff
- **Error handling** - Connection, timeout, malformed responses
- **Configurable** - Max tokens, temperature, stop sequences

### ❌ TODO
- **memory.py** - Store user context (JSONB key-value)
- **context.py** - Assemble prompts from templates + memory
- **telemetry.py** - Prometheus metrics
- **API endpoints** - REST API for templates & chat

## Database Schema

**system_prompt** - Template definitions
- id, name (unique), content, current_version, is_active
- created_at, updated_at

**prompt_version_history** - Version tracking
- id, template_id, version, content
- created_at, created_by, change_description

**user_memory** - User context (TODO)
- id, user_id, key, value (JSONB), updated_at

**conversation_history** - Chat history (TODO)
- id, user_id, role, content, created_at

## Configuration

**config.toml:**
```toml
[mistral]
url = "http://host.docker.internal:8080"  # Mac: local Mistral
# url = "http://mistral:8080"             # Docker: Mistral container

[database]
host = "postgres"
port = 5432
user = "promptdev_user"
database = "promptdev_db"
max_connections = 10
```

**.env:**
```bash
PROMPTDEV_USER_PASS=your_secure_password
```

## Commands

```bash
# Deployment
make deploy         # Full deployment (build + start + migrate)
make rebuild        # Rebuild containers with new dependencies
make local-start    # Start postgres and backend
make local-stop     # Stop all services

# Database
make db-migrate     # Run migrations
make db-shell       # Open PostgreSQL shell
make db-inspect     # List tables

# Development
make test           # Run all 89 tests
make test-verbose   # Verbose test output
make health         # Check backend status
make logs           # Tail container logs

# Mistral (Mac only)
make local-mistral  # Start Mistral on port 8080
```

## Python API

```python
from src.prompts import (
    create_template,
    update_template,
    get_template,
    get_template_by_name,
    list_templates,
    render_template,
    render_template_by_name,
    get_version_history,
    rollback_to_version,
)

# Create
tid = create_template("greeting", "Hello {{name}}!", created_by="admin")

# Render
result = render_template(tid, {"name": "World"})
# → "Hello World!"

# Update (creates v2)
update_template(tid, "Hi {{name}}!")

# Rollback (creates v3 with v1 content)
rollback_to_version(tid, 1)

# Use with Mistral
from src.llm_client import call_mistral_simple
import asyncio

async def chat():
    prompt = render_template_by_name("chatbot", {"role": "assistant"})
    response = await call_mistral_simple(prompt=prompt)
    return response

asyncio.run(chat())
```

## Testing

```bash
# All tests (89 total)
make test

# Specific modules
uv run pytest tests/test_prompts.py -v      # 48 template tests
uv run pytest tests/test_llm_client.py -v   # 28 LLM tests
uv run pytest tests/test_db.py -v           # 8 database tests

# Single test
uv run pytest tests/test_prompts.py::test_create_simple_template -v
```

## Architecture

```
┌─────────────┐
│   Scripts   │ manage_templates.py, run_prompt.py
└──────┬──────┘
       │
┌──────▼──────────────────────────────────────┐
│  Python Application (FastAPI)               │
│  ┌──────────────┐  ┌────────────────────┐  │
│  │  prompts.py  │  │  llm_client.py     │  │
│  │  (Jinja2)    │  │  (Async Mistral)   │  │
│  └──────┬───────┘  └─────────┬──────────┘  │
│         │                    │              │
│  ┌──────▼──────────┐  ┌──────▼──────────┐  │
│  │   PostgreSQL    │  │  Mistral LLM    │  │
│  │  (Templates +   │  │  (localhost:    │  │
│  │   Versions)     │  │   8080)         │  │
│  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────┘
```

## Production Deployment

1. **Update config.toml** for production:
   ```toml
   [mistral]
   url = "http://mistral-service:8080"
   ```

2. **Add Mistral to docker-compose.yml** (if containerized)

3. **Run migrations:**
   ```bash
   make deploy
   ```

4. **Verify:**
   ```bash
   make health
   make test
   ```

## Important Notes

- **Mac users:** Mistral runs locally via `make local-mistral` (not in Docker)
- **Config:** Use `host.docker.internal:8080` for Mac, `mistral:8080` for Docker
- **Dependencies:** jinja2, pytest-asyncio required (in pyproject.toml)
- **Versioning:** Templates are immutable - updates create new versions
- **LLM agnostic:** prompts.py is LLM-independent, llm_client.py is Mistral-specific

## Next Steps

1. ✅ ~~Implement prompts.py~~
2. ✅ ~~Implement llm_client.py~~
3. ❌ Implement memory.py (user context storage)
4. ❌ Implement context.py (prompt assembly)
5. ❌ Add REST API endpoints to main.py
6. ❌ Add telemetry.py (Prometheus metrics)
7. ❌ Build web UI for template management

## Troubleshooting

**Tests fail with Docker error:**
→ Start Docker Desktop

**Backend can't connect to Mistral:**
→ Check config.toml uses `host.docker.internal:8080` (Mac)
→ Verify Mistral is running: `curl http://localhost:8080/health`

**Template not found:**
→ List templates: `uv run python scripts/manage_templates.py list`

**Database migration fails:**
→ Check postgres is running: `docker compose ps`
→ Verify .env has PROMPTDEV_USER_PASS set

## License

Private project - All rights reserved