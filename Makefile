SHELL := /bin/bash

.DEFAULT_GOAL := help

# Validate db= is set and valid
check-db:
ifndef db
	$(error db= is required. Use db=local or db=remote)
endif
ifneq ($(db),local)
ifneq ($(db),remote)
	$(error Invalid db=$(db). Use db=local or db=remote)
endif
endif

# Validate llm= is set and valid
check-llm:
ifndef llm
	$(error llm= is required. Use llm=local or llm=venice)
endif
ifneq ($(llm),local)
ifneq ($(llm),venice)
	$(error Invalid llm=$(llm). Use llm=local or llm=venice)
endif
endif

help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║                    PromptDev Commands                      ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🚀 RUN (requires db=local|remote llm=local|venice)"
	@echo "  make run db=... llm=...   Run backend"
	@echo "  make stop                 Stop all services"
	@echo ""
	@echo "🔌 LLM"
	@echo "  make llm              Start local LLM server"
	@echo ""
	@echo "🐳 DOCKER"
	@echo "  make db-up            Start local PostgreSQL container"
	@echo "  make db-reset         Nuke local volumes and start fresh"
	@echo ""
	@echo "🗄️  DATABASE (auto-starts containers if needed)"
	@echo "  make db-migrate db=... [llm=...]  Run migrations (llm required for local)"
	@echo "  make db-inspect db=... [llm=...]  Show tables (llm required for local)"
	@echo "  make db-shell db=...              Open psql shell"
	@echo "  make db-drop-remote               Drop remote schema (destructive!)"
	@echo ""
	@echo "🔌 CONNECTION TESTS"
	@echo "  make test-db-local    Test local PostgreSQL connection"
	@echo "  make test-db-remote   Test remote Supabase connection"
	@echo ""
	@echo "🧪 TESTING (requires llm=local|venice)"
	@echo "  make test llm=...    Run tests with specified LLM"
	@echo ""
	@echo "👤 ADMIN MANAGEMENT"
	@echo "  make admin-create db=... email=... password=...  Create admin"
	@echo "  make admin-list db=...                           List all admins"
	@echo "  make admin-deactivate db=... email=...           Deactivate admin"
	@echo ""
	@echo "🔧 UTILITIES"
	@echo "  make health                       Check backend health"
	@echo "  make clean                        Clean Python cache files"
	@echo ""

# ============================================================================
# RUN
# ============================================================================

llm:
	@./scripts/run_mistral_local.sh

run: check-db check-llm
	@# Stop any existing services first
	@LLM_BACKEND=x docker compose --profile local down 2>/dev/null || true
	@lsof -ti :8001 | xargs kill -9 2>/dev/null || true
ifeq ($(db),local)
	@LLM_BACKEND=$(llm) docker compose --profile local up -d
	@sleep 3
	@$(MAKE) db-migrate db=$(db) llm=$(llm)
	@echo "✅ Backend running at http://localhost:8001 (db=$(db), llm=$(llm))"
else ifeq ($(db),remote)
	DB_TARGET=remote LLM_BACKEND=$(llm) uv run uvicorn src.main:app --host 0.0.0.0 --port 8001
endif

stop:
	@LLM_BACKEND=x docker compose --profile local down 2>/dev/null || true
	@lsof -ti :8001 | xargs kill -9 2>/dev/null || true
	@echo "✅ Stopped"

# ============================================================================
# DOCKER
# ============================================================================

db-up:
	@LLM_BACKEND=x docker compose --profile local up -d postgres

db-reset:
	@echo "🗑️  Nuking local database..."
	@LLM_BACKEND=x docker compose --profile local down -v --remove-orphans
	@echo "🚀 Starting fresh..."
	@LLM_BACKEND=x docker compose --profile local up -d postgres
	@sleep 3
	@echo "✅ Local database reset complete"

db-drop-remote:
	@echo "🗑️  Dropping remote schema..."
	@source .env && psql "postgresql://postgres.hykoamfsyttvteipvsbw:$$SUPABASE_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	@echo "✅ Remote database schema dropped"

# ============================================================================
# DATABASE
# ============================================================================

db-migrate: check-db
ifeq ($(db),local)
	@set -a && source .env && set +a && docker compose up -d postgres 2>/dev/null || true
	@sleep 2
	@uv run python -m scripts.migrate
else ifeq ($(db),remote)
	@DB_TARGET=$(db) uv run python -m scripts.migrate
endif

db-inspect: check-db
ifeq ($(db),local)
	@set -a && source .env && set +a && docker compose up -d postgres 2>/dev/null || true
	@sleep 2
	@uv run python -c "from scripts.inspect_db import list_tables; print(list_tables())"
else ifeq ($(db),remote)
	@DB_TARGET=$(db) uv run python -c "from scripts.inspect_db import list_tables; print(list_tables())"
endif

db-shell: check-db
ifeq ($(db),local)
	@LLM_BACKEND=x docker compose --profile local up -d postgres 2>/dev/null || true
	@sleep 2
	@LLM_BACKEND=x docker compose --profile local exec postgres psql -U promptdev_user -d promptdev_db
else ifeq ($(db),remote)
	@source .env && psql "postgresql://postgres.hykoamfsyttvteipvsbw:$$SUPABASE_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
endif

# ============================================================================
# CONNECTION TESTS
# ============================================================================

test-db-local:
	@LLM_BACKEND=x docker compose --profile local up -d postgres 2>/dev/null || true
	@sleep 2
	@LLM_BACKEND=x docker compose --profile local exec postgres psql -U promptdev_user -d promptdev_db -c "SELECT 1;" && echo "✅ Local connection OK" || echo "❌ Local connection failed"

test-db-remote:
	@source .env && psql "postgresql://postgres.hykoamfsyttvteipvsbw:$$SUPABASE_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres" -c "SELECT 1;" && echo "✅ Remote connection OK" || echo "❌ Remote connection failed"

# ============================================================================
# TESTING
# ============================================================================

test: check-llm
	@uv run pytest -s --llm=$(llm)

# ============================================================================
# UTILITIES
# ============================================================================

health:
	@curl -sf http://localhost:8001/health && echo "✅ Backend healthy" || echo "❌ Backend not responding"

admin-create: check-db
ifndef email
	$(error email= is required. Usage: make admin-create db=... email=... password=...)
endif
ifndef password
	$(error password= is required. Usage: make admin-create db=... email=... password=...)
endif
ifeq ($(db),local)
	@LLM_BACKEND=x docker compose --profile local up -d postgres 2>/dev/null || true
	@sleep 2
endif
	@uv run python -m scripts.create_admin --db=$(db) --email=$(email) --password=$(password)

admin-list: check-db
ifeq ($(db),local)
	@LLM_BACKEND=x docker compose --profile local up -d postgres 2>/dev/null || true
	@sleep 2
endif
	@uv run python -m scripts.create_admin --db=$(db) --list

admin-deactivate: check-db
ifndef email
	$(error email= is required. Usage: make admin-deactivate db=... email=...)
endif
ifeq ($(db),local)
	@LLM_BACKEND=x docker compose --profile local up -d postgres 2>/dev/null || true
	@sleep 2
endif
	@uv run python -m scripts.create_admin --db=$(db) --email=$(email) --deactivate

clean:
	@find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleaned"

.PHONY: help llm run stop db-up db-reset db-drop-remote db-migrate db-inspect db-shell test-db-local test-db-remote test health admin-create admin-list admin-deactivate clean check-db check-llm
