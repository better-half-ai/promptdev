# PromptDev

Prompt engineering workbench with self-hosted Mistral CPU LLM.

## Status

**Infrastructure:** ✅ Complete  
**Implementation:** ❌ Empty modules (need implementation)  
**Tests:** ✅ 13 passing (infrastructure only)

## Quick Start

```bash
# Mac
cp .env.example .env
make local-start
make db-migrate
make test

# Cloud
cp .env.example .env
# Edit: MISTRAL_URL=http://mistral:8080
make cloud-start
make db-migrate
make test
```

## Structure

```
promptdev/
├── src/            # Application code
│   ├── config.py      ✅ Complete
│   ├── main.py        ⚠️  Health endpoint only
│   ├── llm_client.py  ❌ Empty - needs implementation
│   ├── prompts.py     ❌ Empty - needs implementation
│   ├── memory.py      ❌ Empty - needs implementation
│   ├── context.py     ❌ Empty - needs implementation
│   └── telemetry.py   ❌ Empty - needs implementation
├── tests/          # Test suite (13 passing)
├── db/             # Database connection
├── scripts/        # Utilities
├── migrations/     # Database schema
├── config.toml     # Configuration
├── .env.example    # Environment template
└── Makefile        # Commands
```

## What Works

- Database schema (5 tables)
- Migrations system
- Docker orchestration
- Test infrastructure
- Health endpoint

## What Needs Implementation

- LLM client (call Mistral API)
- Prompt management (CRUD + versions)
- Memory system (JSONB operations)
- Context builder (format prompts)
- Telemetry (metrics)
- API endpoints (chat, etc.)

## Key Fixes Applied

- ✅ Schema uses JSONB key-value for user_memory
- ✅ Dependencies include python-dotenv, pydantic
- ✅ No nested directories
- ✅ No template pollution

## Commands

```bash
make test           # Run tests (should pass 13)
make health         # Test health endpoint
make local-start    # Start backend (Mac)
make cloud-start    # Start all (Linux)
make db-migrate     # Run migrations
```

## Next Steps

1. Implement empty modules in src/
2. Add API endpoints to main.py
3. Write tests for implementations
4. Deploy

## Important

This package contains **infrastructure only**. The 5 empty module files need real implementations before the application will function beyond the health check.
